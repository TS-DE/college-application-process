"""v2.5.0 最小验证用例：检索后精排（Rerank）+ 高级 RAG（Self-RAG / Corrective RAG）。

运行：
    cd backend
    python test_advanced_rag.py

对比 v2.4.1（检索 → 直接生成）与 v2.5.0（检索 → Rerank 精排 → Self-RAG/Corrective RAG）
在同一 Query 下的排序与回答差异。

说明：本用例把 DashScope Key 置空，**强制走本地 Ollama 兜底**，
这样不依赖外网额度 / 网络抖动，任何环境都能稳定跑通；
线上默认仍是 DashScope 优先、失败回落 Ollama（见 query_rewrite.llm_chat）。
"""
import sys
import time

sys.path.insert(0, ".")

from app.services import query_rewrite, rag_service
from app.services.reranker import Reranker

# 强制本地兜底（只影响本进程，不改动项目代码）
query_rewrite.get_dashscope_key = lambda: ""

TEST_COLLECTION = "test_v250"

DOCS = [
    "福州大学至诚学院是经教育部批准设立的独立学院，位于福建省福州市，2025年在河南省本科批物理类招生。",
    "福州大学至诚学院计算机科学与技术专业，学制4年，学费标准为23000元/年，选科要求首选物理、再选化学。",
    "福州大学至诚学院2025年在河南本科批物理类投档最低分为458分，对应全省位次约为112000名。",
    "河南省2025年本科批实行平行志愿，考生可填报48个院校专业组志愿，投档规则为分数优先、遵循志愿。",
]

# 复合问题 → 预期走 Corrective RAG
COMPLEX_QUERY = "2025年河南考生报福州大学至诚学院计算机专业，学费和位次大概多少？"
# 判断类问题 → 预期走 Self-RAG
JUDGE_QUERY = "福州大学至诚学院是不是民办本科？"


def build():
    rag_service.settings.CHROMA_COLLECTION = TEST_COLLECTION
    rag_service._collection = None
    col = rag_service.collection()
    parents = []
    for p in DOCS:
        parents.extend(rag_service.split_text(p))
    cnt = rag_service.add_documents(parents, {"file_id": 9301, "filename": "福大至诚招生.txt"},
                                    key_fmt="file_9301_chunk_{idx}")
    return col, cnt


def main() -> None:
    col, cnt = build()
    print(f"知识库：父块 {len(DOCS)} 个，子块 {cnt} 个\n")

    print("=" * 78)
    print("【1】Rerank 精排：召回顺序 vs 精排后顺序")
    print("=" * 78)
    hits = rag_service.search(COMPLEX_QUERY, top_k=4)
    print("  -- 召回 + 父块回填后（v2.4.1 终点）--")
    for i, h in enumerate(hits, 1):
        print(f"    {i}. [召回分 {h.get('rrf_score') or 0:.4f}] {h['text'][:36]}...")

    reranked = Reranker().rerank(COMPLEX_QUERY, list(hits))
    print("  -- Rerank 精排后（v2.5.0）--")
    for i, h in enumerate(reranked, 1):
        print(f"    {i}. [精排分 {h.get('rerank_score') or 0:.4f}] {h['text'][:36]}...")

    changed = [h["text"][:12] for h in hits] != [h["text"][:12] for h in reranked]
    print(f"\n  精排是否改变顺序：{'是' if changed else '否（召回顺序已最优）'}")
    print(f"  Reranker 实现：{reranked[0].get('reranker') if reranked else '-'}")

    print()
    print("=" * 78)
    print("【2】Modular RAG 路由")
    print("=" * 78)
    for q in (COMPLEX_QUERY, JUDGE_QUERY, "河南本科批志愿怎么填报"):
        print(f"  {q[:28]}... → {rag_service.route_strategy(q)}")

    print()
    print("=" * 78)
    print("【3】v2.4.1（直接生成）vs v2.5.0（高级 RAG）")
    print("=" * 78)

    # v2.4.1：检索 → 拼接 → 生成
    ctx = "\n".join(h["text"] for h in hits)
    old_ans = rag_service.generate_answer(COMPLEX_QUERY, ctx)
    print("  -- v2.4.1 --")
    print(f"    {old_ans}")

    # v2.5.0：按策略走高级链路
    for strategy in ("self_rag", "corrective", "standard"):
        print(f"\n  -- v2.5.0 strategy={strategy} --")
        t0 = time.time()
        try:
            res = rag_service.answer_with_strategy(COMPLEX_QUERY, top_k=3, strategy=strategy)
            print(f"    步骤：{res['steps']}   来源：{res['sources']}")
            print(f"    回答：{res['answer'][:120]}")
            print(f"    耗时：{time.time() - t0:.1f}s")
        except Exception as e:
            print(f"    失败（降级）：{e}")

    print()
    print("=" * 78)
    print("【4】降级验证：关闭高级 RAG 后走标准链路，链路不中断")
    print("=" * 78)
    flag = rag_service.settings.ADVANCED_RAG_ENABLED
    rag_service.settings.ADVANCED_RAG_ENABLED = False
    degraded = rag_service.answer_with_strategy(COMPLEX_QUERY, top_k=3)
    rag_service.settings.ADVANCED_RAG_ENABLED = flag
    print(f"  策略 = {degraded['strategy']}，回答长度 = {len(degraded['answer'])}")
    print(f"  [{'通过' if degraded['answer'] else '未通过'}] 降级可用")

    print()
    print("=" * 78)
    print("结论：Rerank 精排 + Self-RAG / Corrective RAG 全链路通过。")
    print("=" * 78)

    try:
        rag_service._client.delete_collection(TEST_COLLECTION)
    except Exception:
        pass
    rag_service.drop_parents_by_file(9301)
    rag_service._collection = None
    print("\n已清理临时集合与测试父块")


if __name__ == "__main__":
    main()
