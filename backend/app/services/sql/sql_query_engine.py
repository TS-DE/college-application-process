"""MySQL 结构化查询引擎（0.9.1 三路融合的「数据库精确值」通道）。

## 定位（单一职责）
本模块**只**负责「按结构化条件查 MySQL 并把结果转成自然语言」，
不做意图识别（那是 rag_service.detect_structured_intent 的活）、
不做向量检索、不调大模型。

## 为什么需要它
0.9.0 的 answer_with_graph() 只有「图谱 + 向量」两路，学费 / 分数线 / 位次 /
选科 / 招生人数这些字段的精确值明明在 MySQL 里，系统却绕道去 Chroma 翻 PDF，
翻不到就拒答。本模块把这条路补上。

## 表结构说明（与任务书假设不同，按真实 schema 实现）
本项目把字段拆在两张表里，**不是**单表：
  · `major_admission_{year}_all` ：投档事实，含 province / category / university_name /
    major_name / subject_req / min_score / min_rank
  · `enrollment_plan_{year}_all`  ：招生计划，含 province / category / university_name /
    major_name / tuition / plan_count
因此本引擎按 intents 分成两组分别查询后合并，而不是做一张大 JOIN
（录取行与计划行数量级不同，JOKIN 会产生笛卡尔积噪声）。
对外 filters 仍沿用 extract_sql_filters() 的 school_name / major_name 契约，
内部适配成真实的 university_name 列名。

## ★ 0.11.0 全国多省自适应
原先按 `table_name(KIND_MAJOR, year, province)` 拼**分省表**（`major_admission_2025_henan`），
数据合并后这些表已全部删除，只剩 `_all` 总表，因此改为：
  · 表名固定 `{kind}_{year}_all`，不再按省份拼；
  · WHERE 必须带 `province = :prov AND category = :cat`，防止跨省数据串联污染。
province 入参可传中文名或拼音，由 `region_mapper` 归一。

## 安全设计
1. 表名由 app.models.dataset.table_name() 的固定模板生成，年份只接受 4 位数字；
2. 查询条件一律参数化绑定（:school / :major），不字符串拼接，防 SQL 注入；
3. 数据库异常一律返回 hit=False，不向上抛，避免拖垮整个问答链路。

## 线程安全
rag_service.answer_with_hybrid() 通过 ThreadPoolExecutor 并行调用本模块，
因此这里每次 query_structured() 都新建自己的 Session，不共享可变状态。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Tuple

from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal, table_exists
from app.utils.region_mapper import (
    get_categories_by_province,
    normalize_province,
)

logger = logging.getLogger(__name__)

# 默认参考年份：config 里没有 YEAR 配置项，项目各处（schemas、前端表单）统一用 2025，
# 这里抽成常量避免散落；用户问题里带年份时以 extract_sql_filters() 提取到的为准。
DEFAULT_YEAR = 2025

# 院校名 / 专业名在数据库里的真实列名（对外 filters 用 school_name / major_name，
# 这里做一层适配，避免把 schema 细节泄漏给调用方）
COL_SCHOOL = "university_name"
COL_MAJOR = "major_name"

# 0.11.0 全国总表名模板（不再按省份拼表名）
_TABLE_MAJOR = "major_admission_{year}_all"   # 投档事实表
_TABLE_PLAN = "enrollment_plan_{year}_all"    # 招生计划表

# 意图名 -> 数据库列名（只允许这些列被查询，避免整表回传）
INTENT_COLUMNS: Dict[str, str] = {
    "tuition": "tuition",
    "subject_req": "subject_req",
    "min_score": "min_score",
    "min_rank": "min_rank",
    "plan_count": "plan_count",
}

# 意图名 -> 所属数据表（决定查投档表还是招生计划表）
INTENT_TABLE: Dict[str, str] = {
    "tuition": _TABLE_PLAN,
    "plan_count": _TABLE_PLAN,
    "subject_req": _TABLE_MAJOR,
    "min_score": _TABLE_MAJOR,
    "min_rank": _TABLE_MAJOR,
}

# 意图名 -> 自然语言行模板
INTENT_TEMPLATES: Dict[str, str] = {
    "tuition": "{school}{major}专业{year}年学费为{value}元/年。",
    "subject_req": "{school}{major}专业选科要求：{value}。",
    "min_score": "{school}{major}专业{year}年最低录取分{value}分。",
    "min_rank": "{school}{major}专业{year}年最低位次{value}。",
    "plan_count": "{school}{major}专业{year}年招生计划{value}人。",
}

# year 只接受 4 位数字，防止拼接出奇怪的表名
_YEAR_RE = re.compile(r"^\d{4}$")


def _display(value: Any) -> str:
    """值的人类可读化：DECIMAL 列常返回 Decimal('23000.00')，
    浮点整数化后输出 23000 而不是 23000.0 / 23000.00。"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value)
    if text.endswith(".00"):
        text = text[:-3]
    elif text.endswith(".0"):
        text = text[:-2]
    return text


class MySQLQueryEngine:
    """按结构化条件查 MySQL，返回自然语言上下文。"""

    def __init__(self, session_factory=None) -> None:
        """
        :param session_factory: 可调用对象，返回 SQLAlchemy Session。
                                依赖倒置：默认用 app.database.SessionLocal，
                                测试时可注入桩工厂（无需真实数据库）。
        """
        self._session_factory = session_factory or SessionLocal

    # ---------------- 对外唯一入口 ----------------

    def query_structured(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """按结构化条件查询，返回 {"hit", "context", "raw", "error"}。

        :param filters: {
                "school_name": str,   # 可选，院校名（LIKE 模糊匹配）
                "major_name":  str,   # 可选，专业名（LIKE 模糊匹配）
                "year":        int,   # 可选，默认 DEFAULT_YEAR
                "province":    str,   # 可选，默认 settings.DEFAULT_PROVINCE（中文名或拼音）
                "category":    str,   # 可选，默认该省第一个科类
                "intents":     list,  # 要输出哪些字段，见 INTENT_COLUMNS
             }
        :return: hit=True 时 context 为按 intents 逐行生成的中文句子；
                 无结果或异常时 hit=False，context 为空。
        """
        intents = [i for i in (filters.get("intents") or []) if i in INTENT_COLUMNS]
        if not intents:
            # 没有意图就不查库：调用方应该先走 detect_structured_intent()
            return {"hit": False, "context": "", "raw": [], "error": "未指定结构化意图"}

        year = self._resolve_year(filters.get("year"))
        school = (filters.get("school_name") or "").strip()
        major = (filters.get("major_name") or "").strip()

        # 院校与专业都为空时不做全表扫描（总表单表 43 万行）
        if not school and not major:
            return {"hit": False, "context": "", "raw": [], "error": "缺少院校或专业条件"}

        # 0.11.0 省份 / 科类归一（必传，防跨省污染）
        prov = normalize_province(filters.get("province") or settings.DEFAULT_PROVINCE)
        cats = get_categories_by_province(prov)
        cat = (filters.get("category") or "").strip() or (cats[0] if cats else "")
        if not prov or not cat:
            return {"hit": False, "context": "", "raw": [],
                    "error": f"无法确定省份/科类：{filters.get('province')}"}

        # 按意图拆成两组，分别查投档表与招生计划表
        by_table: Dict[str, List[str]] = {}
        for intent in intents:
            by_table.setdefault(INTENT_TABLE[intent], []).append(intent)

        lines: List[str] = []
        raw: List[Dict[str, Any]] = []
        errors: List[str] = []
        for tpl, tbl_intents in by_table.items():
            tbl = tpl.format(year=year)
            if not table_exists(tbl):
                errors.append(f"数据表不存在：{tbl}")
                continue
            try:
                rows = self._fetch(tbl, tbl_intents, school, major, prov, cat)
            except Exception as exc:  # noqa: BLE001 单表异常不影响另一张表
                logger.info("[MYSQL] 结构化查询失败 %s：%s", tbl, exc.__class__.__name__)
                errors.append(f"查询异常：{exc.__class__.__name__}")
                continue
            if not rows:
                continue
            raw.extend(rows)
            lines.extend(self._format_rows(rows, tbl_intents, year))

        if not lines:
            return {
                "hit": False,
                "context": "",
                "raw": raw,
                "error": "；".join(errors) if errors else "",
            }
        return {
            "hit": True,
            "context": "\n".join(lines),
            "raw": raw,
            "error": "；".join(errors),
        }

    # ---------------- 内部工具 ----------------

    def _fetch(
        self, tbl: str, intents: List[str], school: str, major: str,
        prov: str, cat: str,
    ) -> List[Dict[str, Any]]:
        """单表查询：只 SELECT 需要的列，条件全部参数化。

        0.11.0：WHERE 必须带 province + category，避免跨省数据串联污染。
        """
        columns = [COL_SCHOOL, COL_MAJOR] + [INTENT_COLUMNS[i] for i in intents]
        # min_rank 只在投档表存在；计划表没有该列时退化为按院校名排序
        order = "min_rank IS NULL, min_rank ASC" if "min_rank" in columns else f"{COL_SCHOOL} ASC"
        sql = (
            f"SELECT {', '.join(columns)} FROM `{tbl}` "
            f"WHERE {COL_SCHOOL} LIKE :school AND {COL_MAJOR} LIKE :major "
            f"AND `province` = :prov AND `category` = :cat "
            f"ORDER BY {order} LIMIT :limit"
        )
        params = {
            "school": f"%{school}%" if school else "%",
            "major": f"%{major}%" if major else "%",
            "prov": prov,
            "cat": cat,
            "limit": int(settings.MYSQL_MAX_ROWS),
        }
        with self._session_factory() as session:
            return [dict(r) for r in session.execute(text(sql), params).mappings()]

    @staticmethod
    def _resolve_year(raw: Any) -> int:
        """年份归一：只接受 4 位数字，否则回落到默认年份。"""
        candidate = str(raw or "").strip()
        if _YEAR_RE.match(candidate):
            return int(candidate)
        return DEFAULT_YEAR

    @staticmethod
    def _format_rows(rows: List[Dict[str, Any]], intents: List[str], year: int) -> List[str]:
        """把查询结果按 intents 逐行转成中文句子（只输出用户问到的字段）。

        例：intents=["tuition", "subject_req"] 时输出
            福州大学至诚学院计算机科学与技术专业2025年学费为23000元/年。
            福州大学至诚学院计算机科学与技术专业选科要求：首选物理再选化学。
        """
        lines: List[str] = []
        for row in rows:
            school = row.get(COL_SCHOOL) or "未知院校"
            major = row.get(COL_MAJOR) or "未知专业"
            for intent in intents:
                value = row.get(INTENT_COLUMNS[intent])
                if value is None or str(value).strip() == "":
                    continue  # 该行这个字段为空：跳过而不是输出「未知」，避免噪声
                lines.append(INTENT_TEMPLATES[intent].format(
                    school=school, major=major, year=year, value=_display(value),
                ))
        # 去重（同院校同专业多行时常出现重复句子）
        seen, unique = set(), []
        for line in lines:
            if line not in seen:
                seen.add(line)
                unique.append(line)
        return unique
