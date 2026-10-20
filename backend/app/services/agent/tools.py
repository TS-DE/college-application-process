"""三个本地工具的实现（0.13.0）。

对应任务书要求的三路本地知识：
    `tool_search_vector`  查 Chroma 政策库（知识库文档）
    `tool_search_mysql`   查分数线 / 学费 / 位次 / 选科
    `tool_search_graph`   查 Neo4j 知识图谱（未启动则自动不可用）

## 关键设计
每个工具都**只负责「执行 + 把结果转成人话」**，不做调度、不判断先后顺序——
顺序由模型通过 Function Calling 决定（这是 0.13.0 与 0.12.x 最本质的区别）。

工具内部全部复用 0.9.x ~ 0.12.x 已经验证过的检索实现（合成复用原则）：
    · 向量：`rag_service.search()`
    · MySQL：`detect_structured_intent()` + `extract_sql_filters()` + `MySQLQueryEngine`
    · 图谱：`rag_service._get_graph_engine()` + `search_with_graph` 的引擎
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.agent.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# 实体词典全局复用（2729 院校 + 1651 专业，加载一次约 0.3s）
_SHARED_EXTRACTOR = None


# ---------------------------------------------------------------- 向量库


class VectorSearchTool(BaseTool):
    """政策 / 院校介绍类文档检索（Chroma 公共知识库）。"""

    name = "tool_search_vector"
    description = (
        "查询公共知识库中的政策文件、填报规则、院校与专业介绍等文字资料。"
        "适用于：平行志愿规则、批次设置、投档比例、体检要求、专业学什么、"
        "某校的办学特色等「说明性」问题。不适用于查询具体分数、位次、学费金额。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索关键词，保留用户原问题的核心名词即可，例如「平行志愿 投档规则」",
            },
            "top_k": {
                "type": "integer",
                "description": "返回条数，默认 5，最多 8",
            },
        },
        "required": ["query"],
    }

    def __init__(self, searcher=None) -> None:
        # 依赖注入：默认懒加载真实实现，测试可传桩函数
        self._searcher = searcher

    def _get_searcher(self):
        if self._searcher is None:
            from app.services.rag.rag_service import search

            self._searcher = search
        return self._searcher

    def run(self, query: str, top_k: int = 5, **kwargs: Any) -> ToolResult:
        def _do() -> ToolResult:
            q = (query or kwargs.get("question") or "").strip()
            if not q:
                return ToolResult.empty("缺少检索词", skipped=True)
            k = max(1, min(8, int(top_k or 5)))
            try:
                hits = self._get_searcher()(q, k) or []
            except Exception as exc:  # noqa: BLE001
                return ToolResult.empty(f"知识库检索失败：{exc.__class__.__name__}")

            lines: List[str] = []
            sources: List[str] = []
            for h in hits:
                meta = h.get("metadata") or {}
                name = meta.get("filename") or meta.get("source") or "知识库"
                if name not in sources:
                    sources.append(name)
                text = (h.get("text") or "").strip().replace("\n", " ")
                if text:
                    lines.append(f"[{name}] {text[:400]}")
            if not lines:
                return ToolResult.empty("知识库中未检索到相关内容")
            return ToolResult(
                ok=True,
                summary="\n".join(lines),
                data=hits,
                sources=sources,
            )

        return self._timed(_do)


# ---------------------------------------------------------------- MySQL


class MySQLSearchTool(BaseTool):
    """结构化数据检索（分数线 / 位次 / 学费 / 计划数 / 选科要求）。"""

    name = "tool_search_mysql"
    description = (
        "查询数据库中的**精确数值**：某校某专业的最低分、最低位次、学费、招生计划数、"
        "选科要求。适用于含具体院校或专业名称的问题，例如"
        "「郑州大学计算机专业多少分」「XX学院学费多少」。"
        "问题里没有院校或专业名称时不要调用本工具。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "包含院校名 / 专业名的原始问题，例如「郑州大学 计算机 分数线」",
            },
            "intents": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["tuition", "min_score", "min_rank", "plan_count", "subject_req"],
                },
                "description": "想查哪些字段；不确定就全部传上",
            },
        },
        "required": ["query"],
    }

    def __init__(self, engine_factory=None, filter_extractor=None, intent_detector=None) -> None:
        self._engine_factory = engine_factory
        self._filter_extractor = filter_extractor
        self._intent_detector = intent_detector

    def _get_engine(self):
        if self._engine_factory is None:
            from app.services.sql.sql_query_engine import MySQLQueryEngine

            self._engine_factory = MySQLQueryEngine
        return self._engine_factory()

    def _detect_intents(self, query: str) -> List[str]:
        if self._intent_detector is not None:
            return list(self._intent_detector(query) or [])
        from app.services.rag.rag_service import detect_structured_intent

        return list(detect_structured_intent(query) or [])

    def _extract_filters(self, query: str) -> Optional[Dict[str, Any]]:
        """抽取院校 / 专业名（0.13.0 改为**词典匹配**，不走 LLM）。

        ## 为什么不用 rag_service.extract_sql_filters
        那个函数内部要调一次大模型（`num_predict=120`，timeout=20s），
        在 Agent 链路里等于给每次查询**额外加 20-40 秒**，
        而我们已经有 2729 个院校 / 1651 个专业的实体词典，
        纯字符串匹配就能覆盖绝大多数问法（实测「郑州大学计算机专业多少分」
        → 院校=郑州大学）。

        词典没匹配到就返回 None，由调用方判定为 skipped——
        让模型改用向量工具，而不是去跑一次全表扫描。
        """
        if self._filter_extractor is not None:
            return self._filter_extractor(query)

        try:
            from app.services.graph.entity_extractor import EntityExtractor

            extractor = _SHARED_EXTRACTOR
            if extractor is None:
                extractor = EntityExtractor()
                extractor.load_entity_dict_from_mysql()
                globals()["_SHARED_EXTRACTOR"] = extractor
            entities = extractor.extract_by_dict(query) or []
        except Exception as exc:  # noqa: BLE001 词典不可用时退化为「无结构化条件」
            logger.info("[AGENT] 实体词典不可用：%s", exc.__class__.__name__)
            return None

        school = ""
        major = ""
        for e in entities:
            etype = str(e.get("type") or "")
            name = str(e.get("name") or "").strip()
            if not name:
                continue
            if etype == "院校" and not school:
                school = name
            elif etype == "专业" and not major:
                major = name
        if not school and not major:
            return None
        out: Dict[str, Any] = {}
        if school:
            out["school_name"] = school
        if major:
            out["major_name"] = major
        return out

    def run(
        self,
        query: str,
        intents: Optional[List[str]] = None,
        province: str = "",
        category: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        def _do() -> ToolResult:
            q = (query or kwargs.get("question") or "").strip()
            if not q:
                return ToolResult.empty("缺少查询词", skipped=True)

            # 模型可能只给了部分 intents，缺的用规则补齐（两者取并集）
            picked = [i for i in (intents or []) if isinstance(i, str)]
            picked += [i for i in self._detect_intents(q) if i not in picked]
            # 问题里既没有院校名也没有专业名时，MySQL 查不了（避免全表扫描）
            filters = self._extract_filters(q)
            if not filters:
                return ToolResult.empty(
                    "问题中未识别到院校名或专业名，跳过数据库精确查询", skipped=True
                )
            filters["intents"] = picked or ["min_score", "min_rank", "tuition"]
            filters["province"] = province or kwargs.get("province") or ""
            if category:
                filters["category"] = category

            try:
                res = self._get_engine().query_structured(filters)
            except Exception as exc:  # noqa: BLE001
                return ToolResult.empty(f"数据库查询失败：{exc.__class__.__name__}")

            if not res.get("hit"):
                return ToolResult.empty(res.get("error") or "数据库中未找到匹配记录")
            return ToolResult(
                ok=True,
                summary=res.get("context") or "",
                data=res.get("raw") or [],
                sources=["数据库"],
            )

        return self._timed(_do)


# ---------------------------------------------------------------- 图谱


class GraphSearchTool(BaseTool):
    """Neo4j 知识图谱检索（院校—专业—地区等关系）。"""

    name = "tool_search_graph"
    description = (
        "查询知识图谱中的**关系信息**：某省有哪些 985/211 院校、"
        "某院校开设的专业、院校与地区的关联等。"
        "适用于「关系型」问题，例如「河南有哪些 211」「北京有哪些计算机强校」。"
        "注意：本工具只返回关系，不含分数与学费。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "自然语言问题，例如「河南省有哪些 985 院校」",
            },
        },
        "required": ["query"],
    }

    def __init__(self, engine_factory=None) -> None:
        self._engine_factory = engine_factory

    def _get_engine(self):
        if self._engine_factory is None:
            from app.services.rag.rag_service import _get_graph_engine

            self._engine_factory = _get_graph_engine
        return self._engine_factory()

    def is_available(self) -> bool:
        """Neo4j 未启动时该工具直接不出现在候选列表里（避免模型选了才发现不可用）。"""
        try:
            from app.config import settings

            if not settings.GRAPH_ENABLED:
                return False
            return self._get_engine() is not None
        except Exception:  # noqa: BLE001
            return False

    def run(self, query: str, **kwargs: Any) -> ToolResult:
        def _do() -> ToolResult:
            q = (query or kwargs.get("question") or "").strip()
            if not q:
                return ToolResult.empty("缺少查询词", skipped=True)
            engine = self._get_engine()
            if engine is None:
                return ToolResult.empty("知识图谱未启用或 Neo4j 未启动")
            try:
                res = engine.query(q)
            except Exception as exc:  # noqa: BLE001
                return ToolResult.empty(f"图谱查询失败：{exc.__class__.__name__}")

            # GraphResult 是 dataclass：hit / context / error / cypher
            hit = bool(getattr(res, "hit", False))
            context = (getattr(res, "context", "") or "").strip()
            if not hit or not context:
                return ToolResult.empty(getattr(res, "error", "") or "图谱中没有匹配的关系")
            return ToolResult(
                ok=True,
                summary=context,
                data={"cypher": getattr(res, "cypher", ""), "context": context},
                sources=["知识图谱"],
            )

        return self._timed(_do)


__all__ = ["VectorSearchTool", "MySQLSearchTool", "GraphSearchTool"]
