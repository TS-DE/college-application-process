"""混合检索最小验证用例：对比「纯向量检索」与「向量 + BM25 + RRF 混合检索」。

运行：
    cd backend
    python test_hybrid_search.py

用例设计：
    知识库里有两段都和"计算机"有关，但只有一段含精确的"专业代码 080901"。
    纯向量检索容易把"泛泛介绍计算机"的块排第一；
    混合检索里 BM25 会精确命中"080901"，RRF 融合后把它顶到第一位。
"""
import sys

sys.path.insert(0, ".")

from app.services import rag_service

TEST_COLLECTION = "test_hybrid_demo"

DOCS = [
    # 0：泛泛介绍，语义上和"计算机"很近，但没有专业代码
    "计算机类专业是工科热门方向，主要学习程序设计、数据结构、操作系统、计算机网络等课程，"
    "就业面广，毕业生可从事软件开发、系统运维、人工智能等工作。",
    # 1：含精确专业代码（BM25 的强项）
    "普通高等学校本科专业目录中，计算机科学与技术专业代码为 080901，"
    "软件工程专业代码为 080902，网络工程专业代码为 080903。",
    # 2：另一段含代码
    "河南省 2025 年本科批招生计划中，计算机科学与技术（专业代码 080901）在物理类投放较多，"
    "要求首选物理，再选化学。",
    # 3：语义相关但讲的是别的专业
    "电子信息工程专业主要研究电子设备与信息系统的设计、开发与应用，与计算机专业有交叉课程。",
    # 4：完全无关
    "学校教职工婚假为 10 天，需在休假前 5 个工作日提交申请，由所在院系负责人审批。",
]

QUERY = "计算机专业代码"


def main() -> None:
    # 使用临时 collection，跑完即删，不影响正式知识库
    rag_service.settings.CHROMA_COLLECTION = TEST_COLLECTION
    rag_service._collection = None

    col = rag_service.collection()
    if col is None:
        print("Chroma 不可用，无法运行用例")
        return

    try:
        # ---- 建库 ----
        for i, text in enumerate(DOCS):
            rag_service.add_document(f"t_{i}", text, {"filename": "demo.txt", "chunk_index": i})
        print(f"已写入 {len(DOCS)} 个测试块\n")

        # ---- 1. 纯向量检索（改造前的方式）----
        print("=" * 72)
        print("【1】纯向量检索（稠密，改造前）")
        print("=" * 72)
        vec = rag_service.get_embedding(QUERY)
        if vec is None:
            print("embedding 不可用（Ollama 未启动？），跳过稠密路对比")
            dense_top = []
        else:
            res = col.query(query_embeddings=[vec], n_results=3, include=["documents", "distances"])
            dense_top = res["documents"][0]
            for rank, (doc, dist) in enumerate(zip(res["documents"][0], res["distances"][0]), 1):
                print(f"  {rank}. [距离 {dist:.4f}] {doc[:46]}...")

        # ---- 2. BM25 稀疏检索 ----
        print()
        print("=" * 72)
        print("【2】BM25 稀疏检索（关键词精确匹配）")
        print("=" * 72)
        retriever = rag_service.HybridRetrieval(col, k=60, top_k=3)
        bm25_hits = retriever.bm25_search(QUERY)
        for rank, h in enumerate(bm25_hits[:3], 1):
            print(f"  {rank}. [BM25 {h['score']:.4f}] {DOCS[h['index']][:46]}...")

        # ---- 3. 混合检索（RRF k=60）----
        print()
        print("=" * 72)
        print("【3】混合检索（稠密 + BM25 → RRF 融合，k=60）")
        print("=" * 72)
        fused = retriever.search(QUERY, top_k=3)
        for rank, h in enumerate(fused, 1):
            flag = "  ← 含专业代码" if "080901" in h["text"] else ""
            print(
                f"  {rank}. [RRF {h['rrf_score']:.5f}] "
                f"[稠密第{h['dense_rank'] or '-'}名, BM25第{h['bm25_rank'] or '-'}名]{flag}"
            )
            print(f"      {h['text'][:46]}...")

        # ---- 结论 ----
        print()
        print("=" * 72)
        hit_dense = dense_top and "080901" in dense_top[0]
        hit_hybrid = bool(fused) and "080901" in fused[0]["text"]
        print(f"查询：{QUERY}")
        print(f"  纯向量 Top1 命中含专业代码的块：{'是' if hit_dense else '否'}")
        print(f"  混合检索 Top1 命中含专业代码的块：{'是' if hit_hybrid else '否'}")
        print("结论：BM25 精确命中「080901」，RRF 融合后把精确答案顶到第一位" if hit_hybrid else "结论：见上方排序对比")
        print("=" * 72)
    finally:
        try:
            rag_service._client.delete_collection(TEST_COLLECTION)
            print("\n已清理临时集合", TEST_COLLECTION)
        except Exception:
            pass
        rag_service._collection = None


if __name__ == "__main__":
    main()
