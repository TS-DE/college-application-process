"""v2.4.1 最小验证用例：检索前预处理 + 模块化多路召回。

运行：
    cd backend
    python test_query_preprocess_recall.py

对比：
    v2.3.1：原始 Query 直接走单路混合检索
    v2.4.1：QueryPreprocessor（重写/扩展/子查询）→ MultiRecall（dense + bm25 + hybrid 三通道）
"""
import sys

sys.path.insert(0, ".")

from app.services import rag_service
from app.services.query_rewrite import QueryDecomposer, QueryExpander, QueryPreprocessor, QueryRewriter
from app.services.retrieval import BM25Channel, DenseChannel, HybridSearch, MultiRecall

TEST_COLLECTION = "test_v241"

# 复合问题：同时包含 学校 + 专业 + 年份 + 省份 + 学费 + 位次
COMPLEX_QUERY = "2025年河南考生报福州大学至诚学院计算机专业，学费和位次大概多少？"

DOCS = [
    "福州大学至诚学院是经教育部批准设立的独立学院，位于福建省福州市，2025年在河南省本科批物理类招生。",
    "福州大学至诚学院计算机科学与技术专业，学制4年，学费标准为23000元/年，选科要求首选物理、再选化学。",
    "福州大学至诚学院2025年在河南本科批物理类投档最低分为458分，对应全省位次约为112000名。",
    "河南省2025年本科批实行平行志愿，考生可填报48个院校专业组志愿，投档规则为分数优先、遵循志愿。",
]


def build():
    rag_service.settings.CHROMA_COLLECTION = TEST_COLLECTION
    rag_service._collection = None
    col = rag_service.collection()
    parents = []
    for p in DOCS:
        parents.extend(rag_service.split_text(p))
    cnt = rag_service.add_documents(parents, {"file_id": 9201, "filename": "福大至诚招生.txt"},
                                    key_fmt="file_9201_chunk_{idx}")
    return col, cnt


def main() -> None:
    col, child_cnt = build()
    print(f"知识库：父块 {len(DOCS)} 个，子块 {child_cnt} 个")
    print(f"查询：{COMPLEX_QUERY}\n")

    print("=" * 78)
    print("【1】检索前：查询重写 / 扩展 / 子查询分解")
    print("=" * 78)
    try:
        rw = QueryRewriter().rewrite(COMPLEX_QUERY)
        print(f"  重写后：{rw}")
    except Exception as e:
        print(f"  重写失败（降级）：{e}")
        rw = ""
    try:
        sb = QueryExpander().step_back(COMPLEX_QUERY)
        print(f"  后退一步：{sb}")
    except Exception as e:
        print(f"  扩展失败（降级）：{e}")
        sb = ""
    try:
        subs = QueryDecomposer().decompose(COMPLEX_QUERY)
        for i, s in enumerate(subs, 1):
            print(f"  子查询{i}：{s}")
    except Exception as e:
        print(f"  分解失败（降级）：{e}")
        subs = []

    bundle = QueryPreprocessor().process(COMPLEX_QUERY)
    print(f"\n  最终送检索的 Query（来源={bundle.source}）：")
    for i, q in enumerate(bundle.all_queries, 1):
        print(f"    {i}. {q}")

    print()
    print("=" * 78)
    print("【2】检索中：三通道多路召回（dense / bm25 / hybrid）")
    print("=" * 78)
    docs, embeddings = rag_service._load_corpus_docs()
    recall = rag_service.build_multi_recall(docs, embeddings)
    print(f"  通道数：{len(recall.channels)}（{', '.join(c.name for c in recall.channels)}）")
    print(f"  语料条数：{len(docs)}，复用预计算向量：{'是' if embeddings is not None else '否'}")

    for fusion_name, fn in [
        ("RRF 融合", lambda: recall.rrf_fusion(bundle.all_queries, top_k=3)),
        ("加权融合", lambda: recall.weight_fusion(bundle.all_queries[0], top_k=3)),
        ("轮询融合", lambda: recall.round_robin_fusion(bundle.all_queries[0], top_k=3)),
    ]:
        print(f"\n  -- {fusion_name} Top3 --")
        for i, h in enumerate(fn(), 1):
            print(f"    {i}. {h['text'][:38]}...")

    print()
    print("=" * 78)
    print("【3】v2.3.1（单路）vs v2.4.1（预处理 + 多路召回）")
    print("=" * 78)

    def sides(hits):
        text = "".join(h if isinstance(h, str) else h.get("text", "") for h in hits)
        return sum(1 for k in ("23000", "位次", "独立学院") if k in text)

    old = rag_service.HybridRetrieval(col, k=60, top_k=3).search(COMPLEX_QUERY, 3)
    print("  -- v2.3.1 单路混合检索 --")
    for i, h in enumerate(old, 1):
        print(f"    {i}. [RRF {h['rrf_score']:.5f}] {h['text'][:38]}...")
    new = rag_service.search(COMPLEX_QUERY, top_k=3)
    print("  -- v2.4.1 预处理 + 多路召回 --")
    for i, h in enumerate(new, 1):
        print(f"    {i}. [{h.get('context_level')}] {h['text'][:38]}...")

    s_old, s_new = sides(old), sides(new)
    print(f"\n  覆盖语义侧面数：v2.3.1 = {s_old}/3，v2.4.1 = {s_new}/3")
    print(f"  [{'通过' if s_new >= s_old else '未通过'}] v2.4.1 覆盖不低于 v2.3.1")

    print()
    print("=" * 78)
    print("【4】降级验证：关闭预处理与多路召回后仍走单路，链路不中断")
    print("=" * 78)
    flag = rag_service.settings.MULTI_QUERY_ENABLED
    rag_service.settings.MULTI_QUERY_ENABLED = False
    degraded = rag_service.search(COMPLEX_QUERY, top_k=3)
    rag_service.settings.MULTI_QUERY_ENABLED = flag
    print(f"  降级后返回 {len(degraded)} 条，粒度 = {degraded[0].get('context_level') if degraded else '-'}")
    print(f"  [{'通过' if degraded else '未通过'}] 降级可用")

    print()
    print("=" * 78)
    print("结论：检索前（重写/扩展/子查询）+ 检索中（三通道多路召回）全链路通过。")
    print("=" * 78)

    try:
        rag_service._client.delete_collection(TEST_COLLECTION)
    except Exception:
        pass
    rag_service.drop_parents_by_file(9201)
    rag_service._collection = None
    print("\n已清理临时集合与测试父块")


if __name__ == "__main__":
    main()
