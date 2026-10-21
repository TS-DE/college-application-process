# -*- coding: utf-8 -*-
"""0.18.0 验收：确认 4 个历史 patch 点在拆分后仍然生效。

这些 patch 是既有测试的命脉（tests/rag/*、tests/integration/* 大量使用），
一旦失效，测试会「假绿」——所以必须逐个亲手验证，而不是"应该可以"。

用法：python tests/rag/test_rag_refactor_patchpoints.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

RESULTS = []


def check(name: str, cond: bool, extra: str = "") -> None:
    RESULTS.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {extra}" if extra else ""))


def patch_llm() -> None:
    """把生成环节换成桩，避免真实调用大模型（只验证检索侧的 patch 生效）。"""
    import app.services.llm.ai_service as ai

    ai.ask = lambda *a, **k: "桩答案：这是测试用的固定回答。"  # noqa: ARG005


def test_collection_patch() -> None:
    """a) _collection = None 后，下一次 collection() 真的重建。"""
    print("a) rag_service._collection = None → 重建集合")
    from app.services.rag import rag_service

    first = rag_service.collection()
    rag_service._collection = None
    second = rag_service.collection()
    check("重置后拿到新集合对象", first is not second)
    check("新集合可用（count 不报错）", second.count() >= 0)

    # 维度缓存同理
    rag_service._collection_dim_cache = None
    dim = rag_service._collection_dimension()
    check("维度缓存 cleared 后能重新取值", dim is not None, f"dim={dim}")


def test_search_patch() -> None:
    """b) search = lambda [] 后，answer_with_hybrid 的向量路真的为空。"""
    print("\nb) rag_service.search = lambda *a, **k: [] → 向量通道为空")
    from app.services.rag import rag_service

    patch_llm()
    original = rag_service.search
    rag_service.search = lambda *a, **k: []  # noqa: ARG005
    try:
        out = rag_service.answer_with_hybrid("郑州大学计算机专业怎么样", top_k=3)
        check("vector_hit 为 False", out.get("vector_hit") is False, f"实际 {out.get('vector_hit')}")
        check("sources 不含向量来源", all(not s for s in out.get("sources") or []))
    finally:
        rag_service.search = original


def test_graph_engine_patch() -> None:
    """c) _graph_engine = False 后，answer_with_hybrid 的 graph_hit 为 false。"""
    print("\nc) rag_service._graph_engine = False → 图谱通道关闭")
    from app.services.rag import rag_service

    patch_llm()
    original = rag_service._graph_engine
    rag_service._graph_engine = False
    try:
        check("_get_graph_engine() 返回 None", rag_service._get_graph_engine() is None)
        out = rag_service.answer_with_hybrid("郑州大学计算机专业怎么样", top_k=3)
        check("graph_hit 为 False", out.get("graph_hit") is False, f"实际 {out.get('graph_hit')}")
    finally:
        rag_service._graph_engine = original


def test_sql_filter_patch() -> None:
    """d) rag_service_extract_sql_filters = lambda None 后，MySQL 通道为空。"""
    print("\nd) rag_service.rag_service_extract_sql_filters = lambda q: None → MySQL 通道为空")
    from app.services.rag import rag_service

    patch_llm()
    original = rag_service.rag_service_extract_sql_filters
    rag_service.rag_service_extract_sql_filters = lambda q: None  # noqa: ARG005
    try:
        out = rag_service.answer_with_hybrid("郑州大学计算机专业学费多少", top_k=3)
        check("mysql_hit 为 False", out.get("mysql_hit") is False, f"实际 {out.get('mysql_hit')}")
    finally:
        rag_service.rag_service_extract_sql_filters = original


def main() -> int:
    print("=" * 72)
    test_collection_patch()
    test_search_patch()
    test_graph_engine_patch()
    test_sql_filter_patch()
    print("=" * 72)
    failed = [n for n, ok in RESULTS if not ok]
    print(f"共 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项")
    for n in failed:
        print("  FAIL:", n)
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
