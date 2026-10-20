"""图谱查询引擎：图谱通道对外唯一入口（0.9.0）。

## 合成复用（而非继承）
本类**组合** EntityExtractor + CypherGenerator + GraphStore 三个单一职责类，
自己只负责编排流程：

    用户问题 ──▶ EntityExtractor.extract()     实体（双路混合，词典优先）
             ──▶ GraphStore.get_schema()      Schema 文本
             ──▶ CypherGenerator.generate()   Cypher 语句
             ──▶ GraphStore.execute_cypher()  记录列表
             ──▶ _format_records()            自然语言上下文

## 与向量通道的关系
`GraphQueryEngine` 与向量检索（`rag_service.search()`）在 `rag_service.search_with_graph()`
里**并行**调用，二者是平级的两个通道；融合策略（优先级 + Token 配额）在 rag_service 层，
本类不感知，符合迪米特法则。

## 降级契约
任何一步失败都返回 `GraphResult(hit=False, error=...)`，**绝不抛异常**，
保证「Neo4j 没启动」时问答链路自动退化成纯向量 RAG。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.graph.cypher_generator import CypherGenerator
from app.services.graph.entity_extractor import EntityExtractor
from app.services.graph.graph_store import GraphConnectionError, GraphStore

logger = logging.getLogger(__name__)


@dataclass
class GraphResult:
    """图谱通道的统一返回（与向量通道的 list[dict] 平级）。"""

    context: str = ""                                  # 自然语言上下文（喂给融合层）
    entities: List[Dict[str, str]] = field(default_factory=list)  # 识别到的实体
    cypher: str = ""                                   # 实际执行的 Cypher（前端调试用）
    hit: bool = False                                  # 是否查到有效结果
    error: Optional[str] = None                        # 失败原因（降级时非空）


def graph_llm(prompt: str, temperature: float = 0.0, num_predict: int = 800) -> str:
    """图谱专用 LLM 通道（0.12.1）。

    与 `entity_extractor.default_llm` 的区别只有一点：**超时更短**
    （`settings.GRAPH_LLM_TIMEOUT`，默认 20 秒）。
    图谱链路要串「实体识别 + Cypher 生成」两次调用，若沿用默认 30 秒，
    最坏 60 秒会挤占最终生成的预算，把整条问答拖过 100 秒上限。
    图谱只是增强项，快速失败回落到 MySQL/向量通道比拖死链路更合理。
    """
    from app.config import settings
    from app.services.ai_service import ask

    return ask(
        prompt,
        temperature=temperature,
        top_p=1.0,
        num_predict=num_predict,
        timeout=settings.GRAPH_LLM_TIMEOUT,
    ) or ""


class GraphQueryEngine:
    """图谱通道门面：实体识别 → Cypher 生成 → 执行 → 格式化。"""

    def __init__(
        self,
        store: Optional[GraphStore] = None,
        extractor: Optional[EntityExtractor] = None,
        generator: Optional[CypherGenerator] = None,
    ) -> None:
        self.store = store or GraphStore()
        # 0.12.1：默认装配时注入图谱专用 LLM 通道（短超时）
        self.extractor = extractor or EntityExtractor(llm_chat=graph_llm)
        self.generator = generator or CypherGenerator(llm_chat=graph_llm)

    # ---------------- 对外入口 ----------------

    def query(self, question: str) -> GraphResult:
        """完整图谱查询流程；任一步失败都降级返回 hit=False。"""
        question = (question or "").strip()
        if not question:
            return GraphResult(hit=False, error="问题为空")

        # ① 实体识别（双路混合）
        try:
            entities = self.extractor.extract(question)
        except Exception as exc:  # noqa: BLE001
            logger.info("[GRAPH] 实体识别异常，降级：%s", exc.__class__.__name__)
            return GraphResult(hit=False, error=f"实体识别失败：{exc.__class__.__name__}")

        if not entities:
            return GraphResult(hit=False, error="未识别到图谱实体")

        # ② Schema（Neo4j 不可用在这一步抛 GraphConnectionError）
        try:
            schema = self.store.get_schema()
        except GraphConnectionError as exc:
            logger.info("[GRAPH] Neo4j 不可用，图谱通道降级：%s", str(exc)[:120])
            return GraphResult(entities=entities, hit=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            return GraphResult(entities=entities, hit=False, error=f"读取 Schema 失败：{exc.__class__.__name__}")

        # ③ 生成 Cypher
        cypher = self.generator.generate(question, entities, schema)
        if not cypher:
            return GraphResult(entities=entities, hit=False, error="Cypher 生成失败")

        # ④ 执行（把实体绑定成 Cypher 参数：Prompt 里约定用 $类型_序号 占位，
        #    不绑定的话 Neo4j 会报 "Expected parameter(s) 院校_0"）
        try:
            records = self.store.execute_cypher(cypher, self.generator.build_params(entities))
        except GraphConnectionError as exc:
            return GraphResult(entities=entities, cypher=cypher, hit=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 Cypher 语法错 / 执行错 → 空结果，不抛
            logger.info("[GRAPH] Cypher 执行失败，降级：%s | %s", exc.__class__.__name__, str(exc)[:150])
            return GraphResult(entities=entities, cypher=cypher, hit=False, error=f"Cypher 执行失败：{exc.__class__.__name__}")

        if not records:
            return GraphResult(entities=entities, cypher=cypher, hit=False, error="图谱无匹配结果")

        context = self._format_records(records)
        if not context:
            return GraphResult(entities=entities, cypher=cypher, hit=False, error="图谱结果为空")

        return GraphResult(context=context, entities=entities, cypher=cypher, hit=True, error=None)

    # ---------------- 结果格式化 ----------------

    @staticmethod
    def _format_records(records: List[Dict[str, Any]]) -> str:
        """把 Cypher 记录格式化为自然语言上下文（参考课堂案例 enriched_context 逻辑）。

        规则：
          · 值是 dict → 展开成多行 "键: 值"
          · 值是 list → 逗号拼接
          · 其余     → "键: 值"
        每条记录之间用换行分隔，值里的 None 统一显示为「未知」。
        """
        blocks: List[str] = []
        for rec in records:
            lines: List[str] = []
            for key, value in rec.items():
                if isinstance(value, dict):
                    for k2, v2 in value.items():
                        lines.append(f"{k2}: {_display(v2)}")
                elif isinstance(value, (list, tuple)):
                    lines.append(f"{key}: {', '.join(str(_display(v)) for v in value)}")
                else:
                    lines.append(f"{key}: {_display(value)}")
            if lines:
                blocks.append("；".join(lines))
        return "\n".join(blocks)


def _display(value: Any) -> str:
    """值的人类可读化：None → 未知，浮点整数化（5000.0 → 5000）。"""
    if value is None:
        return "未知"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def build_default_engine() -> GraphQueryEngine:
    """生产环境默认引擎装配（词典路从 MySQL 加载 + LLM 路走阿里云通道）。

    为什么要一个工厂：`rag_service` 的在线链路和离线测试需要**同一套**装配逻辑
    （词典必须加载，否则 LLM 抽到的简称无法消歧成图谱里的全称），
    抽成函数后两边都不会漏，也避免重复代码（合成复用而非复制）。
    """
    from app.config import settings

    extractor = EntityExtractor(llm_chat=graph_llm, use_llm=settings.GRAPH_LLM_EXTRACT_ENABLED)
    if settings.GRAPH_DICT_EXTRACT_ENABLED:
        try:
            extractor.load_entity_dict_from_mysql()
        except Exception as exc:  # noqa: BLE001 词典加载失败 → 只剩 LLM 抽取路
            logger.info("[GRAPH] 实体词典加载失败，仅用 LLM 抽取路：%s", exc.__class__.__name__)
    return GraphQueryEngine(extractor=extractor, generator=CypherGenerator(llm_chat=graph_llm))
