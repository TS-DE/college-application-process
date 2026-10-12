# -*- coding: utf-8 -*-
"""0.9.0 知识图谱双通道测试：实体识别 / Cypher 生成 / 图谱查询 / 融合层 / 双通道对比。

## 设计（依赖倒置的收益）
`EntityExtractor` / `CypherGenerator` / `GraphStore` 都是构造注入，
所以本文件**默认不连 Neo4j、不调真实 LLM**，用桩对象（stub）即可跑通全流程；
只有加 `--real` 时才打真实阿里云接口 + 真实 Neo4j。

## 运行方式
    python test_graph_rag.py             # 桩版：秒级，CI / 无网环境可跑
    python test_graph_rag.py --real      # 真实版：需要 Neo4j 已启动 + 图谱已构建
    python test_graph_rag.py --compare   # 双通道对比：use_graph=false vs true 的回答差异
"""
from __future__ import annotations

import argparse
import sys
import time

QUESTION = "福州大学至诚学院计算机专业学费多少"


# ============================================================ 桩对象
class StubLLM:
    """桩 LLM：根据 Prompt 内容返回预置响应，不发任何网络请求。

    这里刻意模拟「模型爱输出废话和代码块包裹」的真实情况，用来验证解析鲁棒性。
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, prompt: str, temperature: float = 0.0, max_tokens: int = 400) -> str:
        self.calls.append(prompt[:40])
        if "实体识别专家" in prompt:
            return '好的，下面是结果：\n```json\n{"entities": [{"type": "院校", "name": "福州大学至诚学院"}, {"type": "专业", "name": "计算机科学与技术"}]}\n```'
        if "Cypher 查询生成专家" in prompt:
            return (
                "```cypher\n"
                "MATCH (s:`院校` {name: $院校_0})-[r:TUITION]->(m:`专业` {name: $专业_0})\n"
                "WHERE r.year = 2025\n"
                "RETURN s.name AS 院校, m.name AS 专业, r.tuition AS 学费, r.duration AS 学制\n"
                "```"
            )
        return ""


class StubGraphStore:
    """桩 Neo4j：不连数据库，直接返回预置记录。"""

    def get_schema(self) -> str:
        return (
            "节点标签及属性：\n  (`院校` {is_211, is_985, name, nature, code})\n"
            "  (`专业` {code, name})\n关系类型：\n  [:TUITION]\n  [:OPENS]\n  [:LOCATED_IN]"
        )

    def execute_cypher(self, cypher: str, params=None) -> list[dict]:
        assert "MATCH" in cypher and "CREATE" not in cypher.upper()
        return [
            {"院校": "福州大学至诚学院", "专业": "计算机科学与技术", "学费": 18000, "学制": "4年"},
            {"院校": "福州大学至诚学院", "专业": "计算机科学与技术", "学费": 18000, "学制": "4年"},
        ]


class StubVectorSearch:
    """桩向量检索：返回固定 hits（结构与 rag_service.search() 一致）。"""

    def __call__(self, query: str, top_k: int = 5) -> list[dict]:
        return [
            {"text": "福州大学至诚学院位于福州市鼓楼区，是全日制本科独立学院。",
             "metadata": {"filename": "至诚学院简介.txt"}, "context_level": "parent"},
            {"text": "该校计算机类专业学费为每学年 18000 元。",
             "metadata": {"filename": "招生简章.txt"}, "context_level": "parent"},
        ]


# ============================================================ 用例
def test_entity_extractor_hybrid() -> None:
    """用例 1：双路实体识别合并去重，词典路优先。"""
    from app.services.graph import EntityExtractor

    extractor = EntityExtractor(
        llm_chat=StubLLM(),
        entity_dict={"院校": ["福州大学至诚学院", "郑州大学"], "专业": ["计算机科学与技术"]},
    )
    entities = extractor.extract(QUESTION)
    names = {(e["type"], e["name"]) for e in entities}
    assert ("院校", "福州大学至诚学院") in names, names
    assert ("专业", "计算机科学与技术") in names, names
    # 去重：词典路与 LLM 路都命中同一个实体，结果里只应出现一次
    assert len([e for e in entities if e["name"] == "福州大学至诚学院"]) == 1
    # 词典路优先：第一个实体应来自词典
    assert entities[0]["name"] == "福州大学至诚学院"
    print(f"  实体识别结果：{entities}")


def test_cypher_generator_guard() -> None:
    """用例 2：Cypher 生成 + 只读保护（写操作关键字一律丢弃）。"""
    from app.services.graph import CypherGenerator

    gen = CypherGenerator(llm_chat=StubLLM())
    cypher = gen.generate(QUESTION, [{"type": "院校", "name": "福州大学至诚学院"}], "（Schema）")
    assert cypher.startswith("MATCH"), cypher
    assert "```" not in cypher, cypher
    assert "TUITION" in cypher, cypher

    # 危险语句必须被拦下
    class EvilLLM(StubLLM):
        def __call__(self, prompt, temperature=0.0, max_tokens=400):
            return "MATCH (n) DETACH DELETE n"

    evil = CypherGenerator(llm_chat=EvilLLM())
    assert evil.generate(QUESTION, [{"type": "院校", "name": "x"}], "s") == ""
    print(f"  生成 Cypher：{cypher.splitlines()[0]} ...")
    print("  只读保护：DETACH DELETE 已被拦截")


def test_graph_query_engine() -> None:
    """用例 3：图谱通道全流程 + 记录格式化。"""
    from app.services.graph import CypherGenerator, EntityExtractor, GraphQueryEngine, GraphStore

    engine = GraphQueryEngine(
        store=GraphStore.__new__(GraphStore),  # 不调 __init__，避免读配置
        extractor=EntityExtractor(llm_chat=StubLLM(), entity_dict={"院校": ["福州大学至诚学院"]}),
        generator=CypherGenerator(llm_chat=StubLLM()),
    )
    engine.store = StubGraphStore()  # 合成复用：运行时替换 store，GraphQueryEngine 无需改

    res = engine.query(QUESTION)
    assert res.hit is True, res
    assert res.error is None, res.error
    assert "福州大学至诚学院" in res.context
    assert "18000" in res.context, res.context
    assert "4年" in res.context, res.context
    assert res.cypher.startswith("MATCH")
    print(f"  hit={res.hit} entities={len(res.entities)}")
    print(f"  格式化上下文：\n{res.context}")


def test_graph_channel_degrade() -> None:
    """用例 4：图谱不可用时必须降级为 hit=False，不能抛异常。"""
    from app.services.graph import CypherGenerator, EntityExtractor, GraphQueryEngine
    from app.services.graph.graph_store import GraphConnectionError

    class DeadStore:
        def get_schema(self):
            raise GraphConnectionError("无法连接 Neo4j")

        def execute_cypher(self, cypher, params=None):
            raise GraphConnectionError("无法连接 Neo4j")

    engine = GraphQueryEngine(
        store=DeadStore(),
        extractor=EntityExtractor(llm_chat=StubLLM(), entity_dict={"院校": ["福州大学至诚学院"]}),
        generator=CypherGenerator(llm_chat=StubLLM()),
    )
    res = engine.query(QUESTION)
    assert res.hit is False and res.error, res
    print(f"  降级正常：hit={res.hit} error={res.error}")


def test_fusion_layer() -> None:
    """用例 5：双通道并行 + Level 1 优先级 + Level 2 Token 配额。"""
    from app.services import rag_service as rs

    # 用桩替换两个通道（依赖倒置：不碰真实 Neo4j / Chroma）
    rs._graph_engine = type(
        "E", (), {"query": staticmethod(lambda q: _fake_graph_result(q))}
    )()
    original_search = rs.search
    rs.search = StubVectorSearch()
    try:
        hybrid = rs.search_with_graph(QUESTION, top_k=2)
    finally:
        rs.search = original_search
        rs._graph_engine = None

    assert hybrid.graph_hit and hybrid.vector_hit, hybrid
    assert hybrid.fusion_strategy == "priority_quota"
    assert "以图谱为准" in hybrid.priority_hint, hybrid.priority_hint
    # 配额：图谱 60% = 2400 token ≈ 3600 字符；向量 40% = 1600 token ≈ 2400 字符
    assert len(hybrid.graph_context) <= 3600 + 30
    assert len(hybrid.vector_context) <= 2400 + 30
    # sources 在 rag_service 里已 sorted()，按 Unicode 码点「招(U+62DB) < 至(U+81F3)」排序
    assert hybrid.sources == ["招生简章.txt", "至诚学院简介.txt"], hybrid.sources
    print(f"  graph_hit={hybrid.graph_hit} vector_hit={hybrid.vector_hit}")
    print(f"  图谱上下文 {len(hybrid.graph_context)} 字符 / 向量上下文 {len(hybrid.vector_context)} 字符")
    print(f"  priority_hint：{hybrid.priority_hint}")

    # 只有图谱命中 / 只有向量命中 / 都没命中 三种提示语
    assert "仅检索到【图谱事实】" in rs._build_priority_hint(True, False)
    assert "仅检索到【向量背景】" in rs._build_priority_hint(False, True)
    assert "预设拒答" in rs._build_priority_hint(False, False)


def _fake_graph_result(question: str):
    from app.services.graph import GraphResult

    return GraphResult(
        context="福州大学至诚学院计算机科学与技术专业：学费 18000 元/年，学制 4 年。",
        entities=[{"type": "院校", "name": "福州大学至诚学院"}],
        cypher="MATCH (s:`院校` {name: $院校_0})-[r:TUITION]->(m:`专业` {name: $专业_0}) RETURN r.tuition",
        hit=True,
    )


def test_token_quota_handover() -> None:
    """用例 6：图谱没用满时，剩余额度让给向量通道。"""
    from app.services import rag_service as rs

    long_vector = "招生政策补充说明。" * 800   # 约 6400 字符
    got = rs._truncate_by_tokens(long_vector, 4000)   # 4000 token ≈ 6000 字符
    assert got.endswith("（上下文已按 Token 配额截断）"), got[-30:]
    assert len(got) <= 6000 + 30
    print(f"  截断生效：{len(long_vector)} → {len(got)} 字符")


# ============================================================ 真实链路
def test_real() -> None:
    """真实链路：需要 Neo4j 已启动 + 已运行 graph_builder 构建图谱。

    用 `build_default_engine()`（与生产同一套装配：词典从 MySQL 加载 + LLM 走阿里云），
    这样测出来的实体消歧效果就是线上效果。
    """
    from app.services.graph import build_default_engine

    engine = build_default_engine()
    if not engine.store.available():
        print("  [SKIP] Neo4j 不可用，跳过真实用例（桩版已覆盖逻辑）")
        return
    print(f"  词典规模：院校 {len(engine.extractor.entity_dict.get('院校', []))} / "
          f"专业 {len(engine.extractor.entity_dict.get('专业', []))}")

    t0 = time.time()
    res = engine.query(QUESTION)
    print(f"  耗时 {time.time() - t0:.2f}s hit={res.hit}")
    print(f"  实体：{res.entities}")
    print(f"  Cypher：\n{res.cypher}")
    print(f"  上下文：\n{res.context}")
    if res.error:
        print(f"  error：{res.error}")


def test_compare() -> None:
    """双通道对比：同一问题 use_graph=false vs use_graph=true。"""
    from app.services import rag_service as rs

    q = QUESTION
    print("  --- use_graph=false（纯向量 RAG）---")
    t0 = time.time()
    try:
        plain = rs.answer_with_strategy(q, top_k=5, strategy="standard")
        print(f"  耗时 {time.time() - t0:.2f}s")
        print(f"  回答：{plain['answer'][:300]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  纯向量链路失败：{exc.__class__.__name__} {exc}")

    print("  --- use_graph=true（图谱 + 向量融合）---")
    t0 = time.time()
    try:
        hybrid = rs.answer_with_graph(q, top_k=5)
        print(f"  耗时 {time.time() - t0:.2f}s")
        print(f"  graph_hit={hybrid['graph_hit']} vector_hit={hybrid['vector_hit']} "
              f"strategy={hybrid['fusion_strategy']}")
        print(f"  回答：{hybrid['answer'][:300]}")
        if hybrid.get("graph_error"):
            print(f"  graph_error：{hybrid['graph_error']}")
    except Exception as exc:  # noqa: BLE001
        print(f"  双通道链路失败：{exc.__class__.__name__} {exc}")


# ============================================================ 入口
def main() -> int:
    parser = argparse.ArgumentParser(description="0.9.0 知识图谱双通道测试")
    parser.add_argument("--real", action="store_true", help="打真实 Neo4j / 阿里云接口")
    parser.add_argument("--compare", action="store_true", help="双通道回答对比")
    args = parser.parse_args()

    print("=" * 70)
    print("用例 1：实体识别双路混合（词典优先 + 去重）")
    test_entity_extractor_hybrid()
    print("用例 2：Cypher 生成与只读保护")
    test_cypher_generator_guard()
    print("用例 3：图谱通道全流程")
    test_graph_query_engine()
    print("用例 4：图谱不可用时的降级")
    test_graph_channel_degrade()
    print("用例 5：双通道融合（优先级 + Token 配额）")
    test_fusion_layer()
    print("用例 6：Token 配额截断")
    test_token_quota_handover()

    if args.real:
        print("=" * 70)
        print("真实链路：GraphQueryEngine.query()")
        test_real()

    if args.compare:
        print("=" * 70)
        print("双通道对比：use_graph=false vs true")
        test_compare()

    print("=" * 70)
    print("桩版用例全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
