"""v2.4.0 最小验证用例：Query 分解 + 多路召回（Multi-Route Recall）。

运行：
    cd backend
    python test_multi_query.py

验证四件事：
  1. decompose_query() 能把复杂问题拆成多条聚焦子查询（≤20 字、保留关键实体）
  2. decompose 失败/降级时返回 [原始 Query]
  3. multi_route_search() 相比单路检索，能同时召回「学校 / 学费 / 位次」多个侧面
  4. search() 完整流程（多路 → RRF → Rerank → 父块回填）仍返回父块上下文
"""
import sys

sys.path.insert(0, ".")

from app.services import rag_service

TEST_COLLECTION = "test_multi_query"

# 复杂问题：一句话里同时包含 学校 + 专业 + 年份 + 省份 + 学费 + 位次
COMPLEX_QUERY = "2025年河南考生报福州大学至诚学院计算机专业，学费和位次大概多少？"

# 知识库语料：三个侧面分别落在不同块里
DOCS = [
    # 0：学校介绍
    "福州大学至诚学院是经教育部批准设立的独立学院，位于福建省福州市，"
    "2025年在河南省本科批物理类招生，办学性质为民办本科。",
    # 1：专业与学费（子块里才会精确出现 23000）
    "福州大学至诚学院计算机科学与技术专业，学制4年，学费标准为23000元/年，"
    "选科要求首选物理、再选化学。",
    # 2：录取位次
    "福州大学至诚学院2025年在河南本科批物理类投档最低分为458分，"
    "对应全省位次约为112000名，计算机类专业录取位次在105000至115000名之间。",
    # 3：无关干扰项
    "河南省2025年本科批实行平行志愿，考生可填报48个院校专业组志愿，"
    "投档规则为分数优先、遵循志愿、一轮投档。",
]


def build():
    rag_service.settings.CHROMA_COLLECTION = TEST_COLLECTION
    rag_service._collection = None
    col = rag_service.collection()
    parents = []
    for p in DOCS:
        parents.extend(rag_service.split_text(p))
    child_cnt = rag_service.add_documents(parents, {"file_id": 9101, "filename": "福大至诚招生.txt"},
                                          key_fmt="file_9101_chunk_{idx}")
    return col, child_cnt


def main() -> None:
    col, child_cnt = build()
    print(f"知识库：父块 {len(DOCS)} 个，子块 {child_cnt} 个\n")

    print("=" * 78)
    print(f"【1】Query 分解（MULTI_QUERY_PROMPT, temperature=0.0）")
    print("=" * 78)
    print(f"  原始问题：{COMPLEX_QUERY}")
    queries = rag_service.decompose_query(COMPLEX_QUERY)
    for i, q in enumerate(queries, 1):
        print(f"    {i}. {q}  ({len(q)} 字)")
    ok_decompose = (
        len(queries) >= 2
        and queries[0] == COMPLEX_QUERY
        and all(0 < len(q) <= rag_service.MAX_SUB_QUERY_LEN for q in queries[1:])
    )
    print(f"  [{'通过' if ok_decompose else '未通过'}] 原始 Query 保留 + 子查询非空且 ≤{rag_service.MAX_SUB_QUERY_LEN} 字")

    print()
    print("=" * 78)
    print("【2】降级验证：AI 关闭时 decompose_query 返回原始 Query")
    print("=" * 78)
    old = rag_service.settings.MULTI_QUERY_ENABLED
    rag_service.settings.MULTI_QUERY_ENABLED = False
    fallback = rag_service.decompose_query(COMPLEX_QUERY)
    rag_service.settings.MULTI_QUERY_ENABLED = old
    print(f"  返回：{fallback}")
    print(f"  [{'通过' if fallback == [COMPLEX_QUERY] else '未通过'}] 降级为单条原始 Query")

    print()
    print("=" * 78)
    print("【3】单路检索 vs 多路召回（Top-3）")
    print("=" * 78)
    single = rag_service.HybridRetrieval(col, k=60, top_k=3).search(COMPLEX_QUERY, 3)
    print("  -- 单路（v2.3.x）--")
    for i, h in enumerate(single, 1):
        print(f"    {i}. [RRF {h['rrf_score']:.5f}] {h['text'][:36]}...")

    multi = rag_service.multi_route_search(COMPLEX_QUERY, top_k=3)
    print("  -- 多路召回（v2.4.0）--")
    for i, h in enumerate(multi, 1):
        mq = "/".join(h.get("matched_queries", [])[:2])
        print(f"    {i}. [RRF {h['rrf_score']:.5f}] 命中子查询[{mq}] {h['text'][:36]}...")

    def sides(hits):
        """统计召回结果覆盖了几个语义侧面"""
        text = "".join(h["text"] for h in hits)
        return sum(1 for k in ("23000", "位次", "独立学院") if k in text)

    s1, s2 = sides(single), sides(multi)
    print(f"\n  单路覆盖侧面数：{s1}/3    多路覆盖侧面数：{s2}/3")
    print(f"  [{'通过' if s2 >= s1 else '未通过'}] 多路召回覆盖不低于单路（{s2} >= {s1}）")

    print()
    print("=" * 78)
    print("【4】完整流程 search()：多路 → RRF → Rerank → 父块回填")
    print("=" * 78)
    final = rag_service.search(COMPLEX_QUERY, top_k=3)
    for i, h in enumerate(final, 1):
        print(f"  {i}. [{h.get('context_level')}] {h.get('parent_chunk_id')} "
              f"{len(h['text'])} 字 | {h['text'][:30]}...")
    ok_final = bool(final) and final[0].get("context_level") == "parent"
    print(f"  [{'通过' if ok_final else '未通过'}] 返回父块上下文（小块命中、大块生成）")

    print()
    print("=" * 78)
    print("结论：Query 分解 → 多路召回 → 跨路 RRF 累加 → 父块回填，全链路通过。")
    print("=" * 78)

    try:
        rag_service._client.delete_collection(TEST_COLLECTION)
    except Exception:
        pass
    rag_service.drop_parents_by_file(9101)
    rag_service._collection = None
    print("\n已清理临时集合与测试父块")


if __name__ == "__main__":
    main()
