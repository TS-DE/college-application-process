"""知识图谱模块（0.9.0）：向量 + 图谱双通道中的「图谱通道」。

对外只暴露这几个类/数据类，调用方（rag_service）不需要关心内部文件划分：

    GraphStore        Neo4j 连接 + Cypher 执行 + Schema（单一职责）
    EntityExtractor   实体识别双路混合：LLM 抽取 + 词典匹配（词典优先）
    CypherGenerator   实体 + 问题 → Cypher（Schema 动态注入 + Few-shot）
    GraphQueryEngine  图谱通道唯一入口（合成复用上面三个类）
    GraphBuilder      离线构建：MySQL → Neo4j（MERGE 幂等）

    GraphResult       图谱通道返回（context / entities / cypher / hit / error）

## 与向量通道的融合位置
融合不在本模块内，而在 `rag_service.search_with_graph()`：
Level 1 优先级（图谱在前）+ Level 2 Token 配额（图谱 60% / 向量 40%）。
本模块保持「只查图谱、不感知融合」，符合单一职责与迪米特法则。

## 依赖倒置
`GraphQueryEngine` 的 store / extractor / generator 都是构造注入，
测试时可整体替换为桩对象，无需真实 Neo4j 与 LLM。

## 为什么 GraphBuilder 用懒加载导出
`GraphBuilder` 只在离线构建时用到，在线问答链路不需要它。
用模块级 `__getattr__`（PEP 562）延迟导入，可以避免
`python -m app.services.graph.graph_builder` 时的重复导入警告，
也省掉一次无关模块的加载。
"""
from app.services.graph.cypher_generator import CypherGenerator
from app.services.graph.entity_extractor import EntityExtractor, default_llm_chat
from app.services.graph.graph_query_engine import GraphQueryEngine, GraphResult, build_default_engine
from app.services.graph.graph_store import GraphConnectionError, GraphStore

__all__ = [
    "GraphStore",
    "GraphConnectionError",
    "EntityExtractor",
    "CypherGenerator",
    "GraphQueryEngine",
    "GraphResult",
    "GraphBuilder",
    "build_default_engine",
    "default_llm_chat",
]


def __getattr__(name: str):
    """懒加载离线构建器（在线问答链路用不到，不该在 import 时就加载）。"""
    if name == "GraphBuilder":
        from app.services.graph.graph_builder import GraphBuilder

        return GraphBuilder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
