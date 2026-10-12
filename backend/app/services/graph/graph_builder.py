"""图谱离线构建：MySQL → Neo4j（0.9.0）。

## 单一职责
本类只负责「抽数 + 写图」，不参与在线问答。

## 幂等性（★ 关键）
所有写入都用 `MERGE`，重复运行不会产生重复节点 / 重复关系，
可以放心地按年份多次构建。

## 运行方式
    python -m app.services.graph.graph_builder --year 2025 --batch 本科批

## 数据来源（表名由 app.models.dataset.table_name 动态拼装）
    major_admission_{year}_henan  → 院校 / 专业 / 专业组 / OPENS / RANKS 关系
    enrollment_plan_{year}_henan  → TUITION / ENROLLS / REQUIRES 关系
    school_province 列            → 省份节点 + LOCATED_IN 关系
"""
from __future__ import annotations

import argparse
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.models.dataset import (
    KIND_MAJOR,
    KIND_PLAN,
    KIND_SCHOOL,
    normalize_code,
    normalize_duration,
    normalize_score,
    resolve_batch,
    table_name,
)
from app.services.graph import ontology as onto
from app.services.graph.graph_store import GraphStore

logger = logging.getLogger(__name__)

# 一次 MERGE 提交的批量大小（过大容易触发事务超时）
BATCH_SIZE = 500


def _s(value: Any) -> str:
    """安全字符串化：None / int / float 都不会炸。

    必须有的原因：`major_group`（专业组号）在 enrollment_plan 表里是 **int**，
    在 major_admission 表里是 **str**，直接 `.strip()` 会 AttributeError。
    """
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


class GraphBuilder:
    """把 MySQL 里的录取 / 计划数据写进 Neo4j。"""

    def __init__(self, store: Optional[GraphStore] = None, year: int = 2025,
                 province: str = "河南", batch: str = "本科批") -> None:
        self.store = store or GraphStore()
        self.year = year
        self.province = province
        self.batch = batch or ""
        self.stats: Dict[str, int] = {}

    # ---------------- 全量入口 ----------------

    def run_all(self, batch: str = "本科批") -> Dict[str, int]:
        """按依赖顺序构建：先节点后关系，返回各类写入条数统计。"""
        self.stats = {"school": 0, "major": 0, "major_group": 0, "province": 0,
                      "batch": 0, "subject_req": 0, "score_segment": 0,
                      "opens": 0, "tuition": 0, "enrolls": 0, "ranks": 0,
                      "admits": 0, "located_in": 0, "belongs_to": 0, "requires": 0}

        logger.info("[GRAPH] 开始构建图谱：year=%s province=%s batch=%s", self.year, self.province, self.batch)
        self.build_school_nodes()
        self.build_major_nodes()
        self.build_major_group_nodes()
        self.build_province_nodes()
        self.build_batch_nodes()
        self.build_subject_req_nodes()
        self.build_score_segment_nodes()
        self.build_relations(batch)
        logger.info("[GRAPH] 图谱构建完成：%s", self.stats)
        return self.stats

    # ---------------- 节点 ----------------

    def build_school_nodes(self) -> int:
        """院校节点：院校代码 + 名称 + 办学性质 + 985/211 标签。"""
        table = table_name("major_admission", self.year, self.province)
        rows = self._fetch_distinct(table, ["university_code", "university_name", "school_province",
                                            "school_nature", "is_985", "is_211"])
        data = []
        for r in rows:
            name = _s(r.get("university_name"))
            if not name:
                continue
            data.append({
                "name": name,
                "code": normalize_code(r.get("university_code")) or "",
                "nature": _s(r.get("school_nature")),
                "is_985": int(r.get("is_985") or 0) == 1,
                "is_211": int(r.get("is_211") or 0) == 1,
                "province": _s(r.get("school_province")),
            })
        self._merge_nodes(onto.SCHOOL, data, "name")
        self.stats["school"] = len(data)
        return len(data)

    def build_major_nodes(self) -> int:
        """专业节点：专业代码 + 名称。"""
        table = table_name("major_admission", self.year, self.province)
        rows = self._fetch_distinct(table, ["major_code", "major_name"])
        data = []
        for r in rows:
            name = _s(r.get("major_name"))
            if not name:
                continue
            data.append({"name": name, "code": normalize_code(r.get("major_code")) or ""})
        self._merge_nodes(onto.MAJOR, data, "name")
        self.stats["major"] = len(data)
        return len(data)

    def build_major_group_nodes(self) -> int:
        """专业组节点：院校 + 专业组名（同一院校下专业组名唯一）。"""
        table = table_name("major_admission", self.year, self.province)
        rows = self._fetch_distinct(table, ["university_name", "major_group", "major_code"])
        data = []
        for r in rows:
            group = _s(r.get("major_group"))
            if not group:
                continue
            data.append({
                "name": f"{r.get('university_name', '').strip()}-{group}",
                "group": group,
                "school": _s(r.get("university_name")),
            })
        self._merge_nodes(onto.MAJOR_GROUP, data, "name")
        self.stats["major_group"] = len(data)
        return len(data)

    def build_province_nodes(self) -> int:
        """省份节点：来自 school_province 列（院校所在省份）。"""
        table = table_name("major_admission", self.year, self.province)
        rows = self._fetch_distinct(table, ["school_province"])
        data = [{"name": _s(r.get("school_province"))} for r in rows]
        data = [d for d in data if d["name"]]
        self._merge_nodes(onto.PROVINCE, data, "name")
        self.stats["province"] = len(data)
        return len(data)

    def build_batch_nodes(self) -> int:
        """批次节点：来自 batch 列。"""
        table = table_name("major_admission", self.year, self.province)
        rows = self._fetch_distinct(table, ["batch"])
        data = [{"name": _s(r.get("batch"))} for r in rows]
        data = [d for d in data if d["name"]]
        self._merge_nodes(onto.BATCH, data, "name")
        self.stats["batch"] = len(data)
        return len(data)

    def build_subject_req_nodes(self) -> int:
        """选科要求节点：来自招生计划表的 subject_req 列。"""
        table = table_name("enrollment_plan", self.year, self.province)
        rows = self._fetch_distinct(table, ["subject_req"])
        data = [{"name": _s(r.get("subject_req"))} for r in rows]
        data = [d for d in data if d["name"]]
        self._merge_nodes(onto.SUBJECT_REQ, data, "name")
        self.stats["subject_req"] = len(data)
        return len(data)

    def build_score_segment_nodes(self) -> int:
        """分数段节点：按「年份-省份-批次-科类」聚合的投档事实载体。"""
        table = table_name("major_admission", self.year, self.province)
        rows = self._fetch_distinct(table, ["year", "batch", "category"])
        data = []
        for r in rows:
            year = r.get("year") or self.year
            batch = _s(r.get("batch"))
            category = _s(r.get("category"))
            data.append({
                "name": f"{year}-{self.province}-{batch}-{category}",
                "year": int(year),
                "province": self.province,
                "batch": batch,
                "category": category,
            })
        self._merge_nodes(onto.SCORE_SEGMENT, data, "name")
        self.stats["score_segment"] = len(data)
        return len(data)

    # ---------------- 关系 ----------------

    def build_relations(self, batch: str = "本科批") -> None:
        """写入 8 类关系（依赖上面的节点已存在）。"""
        self._build_opens_and_admits()
        self._build_tuition_and_enrolls()
        self._build_ranks()
        self._build_located_in()
        self._build_belongs_to()
        self._build_requires()

    def _build_opens_and_admits(self) -> None:
        """OPENS（院校→专业，携带分数事实）+ ADMITS（专业→分数段）。"""
        table = table_name("major_admission", self.year, self.province)
        rows = self._fetch_distinct(table, [
            "university_name", "major_name", "major_group",
            "year", "batch", "category",
            "min_score", "min_rank", "max_score", "avg_score", "admit_count",
        ], kind=KIND_MAJOR, batch=self.batch)
        opens, admits = [], []
        for r in rows:
            school = _s(r.get("university_name"))
            major = _s(r.get("major_name"))
            if not school or not major:
                continue
            year = int(r.get("year") or self.year)
            props = {
                "year": year,
                "province": self.province,
                "batch": _s(r.get("batch")),
                "category": _s(r.get("category")),
                "min_score": normalize_score(r.get("min_score")),
                "min_rank": normalize_score(r.get("min_rank")),
                "max_score": normalize_score(r.get("max_score")),
                "avg_score": normalize_score(r.get("avg_score")),
                "admit_count": normalize_score(r.get("admit_count")),
                "major_group": _s(r.get("major_group")),
            }
            opens.append({"school": school, "major": major, "props": props})
            admits.append({
                "major": major,
                "segment": f"{year}-{self.province}-{props['batch']}-{props['category']}",
                "props": {"year": year, "min_score": props["min_score"], "min_rank": props["min_rank"]},
            })
        self._merge_edges(onto.SCHOOL, onto.MAJOR, onto.OPENS, opens)
        self._merge_edges(onto.MAJOR, onto.SCORE_SEGMENT, onto.ADMITS, admits)
        self.stats["opens"] = len(opens)
        self.stats["admits"] = len(admits)

    def _build_tuition_and_enrolls(self) -> None:
        """TUITION（学费）+ ENROLLS（招生人数）：院校→专业。"""
        table = table_name("enrollment_plan", self.year, self.province)
        rows = self._fetch_distinct(table, [
            "university_name", "major_name", "major_group",
            "tuition", "plan_count", "duration", "subject_req", "batch",
        ], kind=KIND_PLAN, batch=self.batch)
        tuitions, enrolls = [], []
        for r in rows:
            school = _s(r.get("university_name"))
            major = _s(r.get("major_name"))
            if not school or not major:
                continue
            tuitions.append({
                "school": school, "major": major,
                "props": {
                    "year": self.year, "province": self.province,
                    "tuition": normalize_score(r.get("tuition")),
                    "duration": normalize_duration(r.get("duration")),
                },
            })
            enrolls.append({
                "school": school, "major": major,
                "props": {
                    "year": self.year, "province": self.province,
                    "batch": _s(r.get("batch")),
                    "plan_count": normalize_score(r.get("plan_count")),
                    "subject_req": _s(r.get("subject_req")),
                },
            })
        self._merge_edges(onto.SCHOOL, onto.MAJOR, onto.TUITION, tuitions)
        self._merge_edges(onto.SCHOOL, onto.MAJOR, onto.ENROLLS, enrolls)
        self.stats["tuition"] = len(tuitions)
        self.stats["enrolls"] = len(enrolls)

    def _build_ranks(self) -> None:
        """RANKS（院校→分数段）：学校维度投档线。"""
        table = table_name("school_admission", self.year, self.province)
        rows = self._fetch_distinct(table, [
            "university_name", "year", "batch", "category", "min_score", "min_rank",
        ], kind=KIND_SCHOOL, batch=self.batch)
        edges = []
        for r in rows:
            school = _s(r.get("university_name"))
            if not school:
                continue
            year = int(r.get("year") or self.year)
            batch = _s(r.get("batch"))
            category = _s(r.get("category"))
            edges.append({
                "school": school,
                "segment": f"{year}-{self.province}-{batch}-{category}",
                "props": {"year": year, "min_score": normalize_score(r.get("min_score")),
                          "min_rank": normalize_score(r.get("min_rank"))},
            })
        self._merge_edges(onto.SCHOOL, onto.SCORE_SEGMENT, onto.RANKS, edges)
        self.stats["ranks"] = len(edges)

    def _build_located_in(self) -> None:
        """LOCATED_IN（院校→省份）。"""
        table = table_name("major_admission", self.year, self.province)
        rows = self._fetch_distinct(table, ["university_name", "school_province"])
        edges = [
            {"school": _s(r.get("university_name")),
             "province": _s(r.get("school_province"))}
            for r in rows
        ]
        edges = [e for e in edges if e["school"] and e["province"]]
        self._merge_edges(onto.SCHOOL, onto.PROVINCE, onto.LOCATED_IN, edges)
        self.stats["located_in"] = len(edges)

    def _build_belongs_to(self) -> None:
        """BELONGS_TO（专业→专业组）。"""
        table = table_name("major_admission", self.year, self.province)
        rows = self._fetch_distinct(table, ["university_name", "major_name", "major_group"])
        edges = []
        for r in rows:
            major = _s(r.get("major_name"))
            group = _s(r.get("major_group"))
            if not major or not group:
                continue
            edges.append({"major": major,
                          "group": f"{(r.get('university_name') or '').strip()}-{group}"})
        self._merge_edges(onto.MAJOR, onto.MAJOR_GROUP, onto.BELONGS_TO, edges)
        self.stats["belongs_to"] = len(edges)

    def _build_requires(self) -> None:
        """REQUIRES（专业组→选科要求）。"""
        table = table_name("enrollment_plan", self.year, self.province)
        rows = self._fetch_distinct(table, ["university_name", "major_group", "subject_req"])
        edges = []
        for r in rows:
            group = _s(r.get("major_group"))
            req = _s(r.get("subject_req"))
            if not group or not req:
                continue
            edges.append({"group": f"{(r.get('university_name') or '').strip()}-{group}",
                          "req": req})
        self._merge_edges(onto.MAJOR_GROUP, onto.SUBJECT_REQ, onto.REQUIRES, edges)
        self.stats["requires"] = len(edges)

    # ---------------- 底层工具 ----------------

    def _fetch_distinct(self, table: str, columns: List[str],
                        kind: str = "", batch: str = "") -> List[Dict[str, Any]]:
        """SELECT DISTINCT 指定列；表不存在 / 列不存在时返回空列表（不中断构建）。

        :param kind:   数据集类型（major_admission / school_admission / enrollment_plan），
                       用于把规范批次翻译成该表里的真实写法（2024 老高考是「本一/本二」）。
        :param batch:  规范批次（如「本科批」），为空表示不过滤。
        """
        from app.database import fetch_all_params, table_exists

        if not table_exists(table):
            logger.info("[GRAPH] 跳过不存在的表：%s", table)
            return []
        cols = ", ".join(f"`{c}`" for c in columns)
        where, params = self._batch_where(kind, batch)
        try:
            return fetch_all_params(f"SELECT DISTINCT {cols} FROM `{table}`{where}", params)
        except Exception as exc:  # noqa: BLE001 缺列时退化为不带该列
            logger.info("[GRAPH] 查询 %s 失败（%s），尝试逐列降级", table, exc.__class__.__name__)
            return self._fetch_columns_fallback(table, columns, kind, batch)

    def _batch_where(self, kind: str, batch: str) -> Tuple[str, Dict[str, Any]]:
        """把规范批次翻译成 WHERE 子句（复用 dataset 模块的新老高考映射）。"""
        if not batch or not kind:
            return "", {}
        values = resolve_batch(batch, self.year, kind)
        if not values:
            return "", {}
        return " WHERE `batch` IN :batches", {"batches": list(values)}

    def _fetch_columns_fallback(self, table: str, columns: List[str],
                                kind: str = "", batch: str = "") -> List[Dict[str, Any]]:
        """列级降级：只查实际存在的列（不同年份数据集列不完全一致）。"""
        from sqlalchemy import text

        from app.database import engine

        try:
            with engine.connect() as conn:
                existing = {
                    row[0] for row in conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = DATABASE() AND table_name = :t"
                        ),
                        {"t": table},
                    )
                }
        except Exception:  # noqa: BLE001
            return []

        usable = [c for c in columns if c in existing]
        if not usable:
            return []
        cols = ", ".join(f"`{c}`" for c in usable)
        where, params = self._batch_where(kind, batch)
        try:
            return fetch_all_params(f"SELECT DISTINCT {cols} FROM `{table}`{where}", params)
        except Exception:  # noqa: BLE001
            return []

    def _merge_nodes(self, label: str, data: List[Dict[str, Any]], key: str = "name") -> int:
        """MERGE 节点（幂等）：属性统一走参数绑定，避免注入。

        注意：匹配键（如 name）必须保留在 row 里，否则 `MERGE (n:Label {name: row.name})` 取不到值。
        """
        if not data:
            return 0
        cypher = (
            f"UNWIND $rows AS row "
            f"MERGE (n:{onto.label(label)} {{{key}: row.{key}}}) "
            f"SET n += row"
        )
        self._run_in_batches(cypher, data)
        return len(data)

    def _merge_edges(self, from_label: str, to_label: str, rel: str,
                     edges: List[Dict[str, Any]]) -> int:
        """MERGE 关系（幂等）：edges 形如 {"school":..., "major":..., "props": {...}}。

        端点按 name 匹配；关系属性一次性 SET，重复执行不会叠加。
        纯结构关系（如 LOCATED_IN）可以不带 props，此时不生成 SET 子句。
        """
        if not edges:
            return 0
        keys = [k for k in edges[0] if k != "props"]
        from_key = keys[0]
        to_key = keys[1] if len(keys) > 1 else keys[0]
        props = edges[0].get("props") or {}
        set_clause = " SET r += row.props" if props else ""
        cypher = (
            f"UNWIND $rows AS row "
            f"MATCH (a:{onto.label(from_label)} {{name: row.{from_key}}}), "
            f"(b:{onto.label(to_label)} {{name: row.{to_key}}}) "
            f"MERGE (a)-[r:{rel}]->(b){set_clause}"
        )
        self._run_in_batches(cypher, edges)
        return len(edges)

    def _run_in_batches(self, cypher: str, rows: List[Dict[str, Any]], drop_key: str = "") -> None:
        """分批执行，避免单条 UNWIND 列表过长导致事务超时。"""
        for i in range(0, len(rows), BATCH_SIZE):
            chunk = rows[i:i + BATCH_SIZE]
            params = {"rows": [_strip_none(r, drop_key) for r in chunk]}
            try:
                self.store.execute_cypher(cypher, params)
            except Exception as exc:  # noqa: BLE001 单批失败不影响后续批次
                logger.warning("[GRAPH] 写入批次失败（%s~%s）：%s", i, i + len(chunk), exc.__class__.__name__)


def _strip_none(row: Dict[str, Any], drop_key: str = "") -> Dict[str, Any]:
    """Neo4j 不接受 None 属性值，统一剔除；同时移除冗余的匹配键。"""
    cleaned: Dict[str, Any] = {}
    for k, v in row.items():
        if k == drop_key:
            continue
        if isinstance(v, dict):
            cleaned[k] = {k2: v2 for k2, v2 in v.items() if v2 is not None}
        elif v is not None:
            cleaned[k] = v
    return cleaned


def main() -> None:
    """命令行入口：python -m app.services.graph.graph_builder --year 2025 --batch 本科批"""
    parser = argparse.ArgumentParser(description="从 MySQL 构建高考志愿知识图谱到 Neo4j")
    parser.add_argument("--year", type=int, default=2025, help="数据年份，默认 2025")
    parser.add_argument("--province", type=str, default="河南", help="省份，默认河南")
    parser.add_argument("--batch", type=str, default="本科批", help="批次，默认本科批")
    parser.add_argument("--uri", type=str, default="", help="Neo4j URI，默认读配置")
    args = parser.parse_args()

    store = GraphStore(uri=args.uri or "")
    builder = GraphBuilder(store=store, year=args.year, province=args.province, batch=args.batch)
    stats = builder.run_all(batch=args.batch)
    print(f"[GRAPH] 构建完成：{stats}")


if __name__ == "__main__":
    main()
