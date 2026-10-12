"""Neo4j 连接封装 + Cypher 执行 + Schema 获取（0.9.0）。

## 单一职责
本类**只**负责「怎么连 Neo4j、怎么执行 Cypher、怎么拿 Schema」，
不持有任何 Prompt、不识别实体、不生成 Cypher（那些分别在 entity_extractor / cypher_generator）。

## 依赖倒置 + 接口隔离
GraphQueryEngine 只依赖本类暴露的 4 个方法（get_schema / execute_cypher /
get_node_properties / close），不需要知道背后是 py2neo 还是别的驱动；
换驱动只改本文件。

## 降级契约
- py2neo 未安装 / Neo4j 未启动 → 抛 `GraphConnectionError`，**绝不静默返回空**；
- 上层（GraphQueryEngine）捕获后返回 `GraphResult(hit=False, error=...)`，问答链路不中断。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.graph import ontology as onto

logger = logging.getLogger(__name__)


class GraphConnectionError(RuntimeError):
    """Neo4j 不可用（驱动缺失 / 连接失败 / 认证失败）。

    上层捕获后走「图谱通道降级」，不影响向量通道与整体问答。
    """


class GraphStore:
    """Neo4j 门面：连接 + Cypher 执行 + Schema 读取。"""

    def __init__(self, uri: str = "", user: str = "", password: str = "") -> None:
        self.uri = uri or settings.NEO4J_URI
        self.user = user or settings.NEO4J_USER
        self.password = password or settings.NEO4J_PASSWORD
        self._graph = None
        self._connect_error: Optional[str] = None

    # ---------------- 连接（懒加载 + 失败记忆） ----------------

    @property
    def graph(self):
        """获取 py2neo Graph；不可用时抛 GraphConnectionError。

        懒加载的原因：import 本模块时不能去连数据库（会让 FastAPI 启动失败），
        必须等到真正要查图谱的那一刻才建连接。
        """
        if self._graph is not None:
            return self._graph
        if self._connect_error is not None:
            raise GraphConnectionError(self._connect_error)

        try:
            from py2neo import Graph  # 局部导入：没装 py2neo 不影响其他模块导入
        except Exception as exc:  # noqa: BLE001
            self._connect_error = f"py2neo 未安装（{exc.__class__.__name__}）：请执行 pip install py2neo"
            raise GraphConnectionError(self._connect_error) from exc

        try:
            self._graph = Graph(self.uri, auth=(self.user, self.password))
            self._run("RETURN 1 AS ok")  # 连通性验证，连不上立刻抛
        except Exception as exc:  # noqa: BLE001
            self._graph = None
            self._connect_error = (
                f"无法连接 Neo4j（uri={self.uri} user={self.user}）："
                f"{exc.__class__.__name__} {str(exc)[:200]}"
            )
            raise GraphConnectionError(self._connect_error) from exc
        logger.info("[GRAPH] Neo4j 连接就绪 uri=%s", self.uri)
        return self._graph

    def available(self) -> bool:
        """探测图谱是否可用（供上层决定是否要走图谱通道，不抛异常）。"""
        try:
            self.graph
            return True
        except GraphConnectionError:
            return False

    def close(self) -> None:
        """释放连接（py2neo 的 Graph 无需显式关闭，这里只重置缓存状态）。"""
        self._graph = None
        self._connect_error = None

    # ---------------- Cypher 执行 ----------------

    def execute_cypher(self, cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """执行 Cypher 并返回 dict 记录列表。

        兼容两种 py2neo API：
          · 经典版（2021.x）：`graph.run(cypher).data()`
          · v5+：`graph.execute_query(cypher)` 返回 EagerResult
        用 try/except AttributeError 兜住版本差异，避免因驱动版本不同而崩。
        """
        if not cypher or not cypher.strip():
            return []
        return self._run(cypher, params)

    def _run(self, cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """统一执行入口：兼容经典 py2neo 与 v5+ 两套 API。"""
        graph = self.graph
        try:
            cursor = graph.run(cypher, params or {})
            return [dict(row) for row in cursor.data()]
        except AttributeError:
            result = graph.execute_query(cypher, parameters_=params or {})
            records = getattr(result, "records", None) or []
            return [dict(rec) for rec in records]

    # ---------------- Schema ----------------

    def get_schema(self) -> str:
        """返回「节点标签 + 属性 + 关系类型」的 Schema 文本，喂给 Cypher 生成 Prompt。

        实现思路（对应课堂案例 `Neo4jGraphStore.get_schema`）：
          · `CALL db.labels()` 拿全部节点标签
          · `CALL db.relationshipTypes()` 拿全部关系类型
          · 每个标签抽样一条节点，`keys(n)` 拿属性名
        Neo4j 未启动时抛 GraphConnectionError，由上层降级。
        """
        labels = [r.get("label") for r in self._run("CALL db.labels() YIELD label RETURN label")]
        rel_types = [r.get("relationshipType") for r in self._run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")]

        lines: List[str] = ["节点标签及属性："]
        for lb in labels:
            if not lb:
                continue
            props = self._label_properties(lb)
            lines.append(f"  ({onto.label(lb)} {{{', '.join(props)}}})" if props else f"  ({onto.label(lb)})")

        lines.append("关系类型：")
        for rt in rel_types:
            if rt:
                lines.append(f"  [:{rt}]")

        if len(lines) == 2:  # 库里还没有数据
            lines.append("  （图谱为空，请先运行 graph_builder 构建）")
        return "\n".join(lines)

    def _label_properties(self, label_name: str) -> List[str]:
        """抽样读取某个标签出现过的属性名（上限 1 条节点）。"""
        try:
            rows = self._run(
                f"MATCH (n:{onto.label(label_name)}) "
                "UNWIND keys(n) AS key RETURN collect(DISTINCT key) AS props LIMIT 1"
            )
        except Exception:  # noqa: BLE001 某些标签属性异常不应阻断整体 Schema
            return []
        if not rows:
            return []
        return sorted(rows[0].get("props") or [])

    # ---------------- 单节点查询 ----------------

    def get_node_properties(self, label_name: str, name: str) -> Dict[str, Any]:
        """按 (标签, name) 取单节点全部属性；不存在返回空 dict。"""
        rows = self.execute_cypher(
            f"MATCH (n:{onto.label(label_name)} {{{onto.NAME}: $name}}) RETURN properties(n) AS props LIMIT 1",
            {"name": name},
        )
        if not rows:
            return {}
        props = rows[0].get("props") or {}
        return dict(props) if hasattr(props, "items") else {}
