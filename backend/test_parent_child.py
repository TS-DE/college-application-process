"""父子块最小验证用例：v2.1.0（500 字大块直接检索） vs v2.2.0（120 字子块命中 → 回填父块）。

运行：
    cd backend
    python test_parent_child.py

对比点：查询「婚假几天」
  - v2.1.0：向量库里是 500 字的父块，短查询被大块里的大量无关词稀释，召回不稳，
            且返回的上下文就是那 500 字（里面混着别的话题）
  - v2.2.0：向量库里是 120 字的子块，"婚假"语义聚焦 → 命中更准；
            命中后回填父块，交给 LLM 的上下文仍然是完整的 500 字（含审批条件等细节）
"""
import sys

sys.path.insert(0, ".")

from app.services import rag_service

V21_COLLECTION = "test_pc_v21"   # v2.1.0 基线：只索引 500 字父块
V22_COLLECTION = "test_pc_v22"   # v2.2.0：只索引 120 字子块 + docstore 存父块

QUERY = "婚假几天"

# 三段约 480 字的长文本（都小于 500，所以各自就是一个「父块」）：
#   P1：招生政策（完全无关）
#   P2：假期制度（语义上和"婚假几天"很近，但只讲年休假/探亲假 —— 干扰项）
#   P3：考勤办法（正确答案「婚假 10 天」被埋在大量考勤内容中间）
# v2.1.0 用 480 字整块做向量 → P3 的向量被"打卡/迟到"稀释，容易被 P2 抢走第一；
# v2.2.0 用 120 字子块做向量 → 命中"婚假"那一小子块，再回填父块拿到完整上下文。
PARAGRAPHS = [
    "河南省2025年普通高校招生工作规定，本科批实行平行志愿，考生可填报四十八个院校专业组志愿，"
    "每个院校专业组志愿包含若干个专业以及是否服从专业调剂选项。投档规则为分数优先、遵循志愿、"
    "一轮投档，投档后由高校按招生章程分配专业。考生位次是志愿填报最重要的参考指标，"
    "建议结合近三年录取位次与招生计划变化综合判断，避免只看分数。",

    "学校假期管理制度节选：年休假根据工龄分为5天、10天、15天三档，年假期间工资福利待遇不变；"
    "探亲假用于探望异地配偶或父母，路程另计；病假需提供医院证明，事假按日扣发绩效。"
    "各类假期均须提前在系统提交申请，由所在部门审批，未经批准擅自离岗按旷工处理。",

    "学校教职工考勤管理办法：全体教职工实行人脸识别打卡，上午八点半前打卡视为正常出勤，"
    "迟到三十分钟以内记为迟到，超过三十分钟记为旷工半天，月度累计迟到三次扣发当月绩效。"
    "其中，教职工婚假为10天，再婚者同样享受10天婚假，婚假期间工资照发。"
    "婚假申请流程：需在休假前5个工作日提交书面申请，由所在院系负责人审批后报人事处备案。",
]


def build_v21():
    """v2.1.0：递归分块得到 500 字块，块直接进向量库（无父子结构）。"""
    rag_service.settings.CHROMA_COLLECTION = V21_COLLECTION
    rag_service._collection = None
    col = rag_service.collection()

    chunks = []
    for p in PARAGRAPHS:
        chunks.extend(rag_service.split_text(p, rag_service.settings.CHUNK_SIZE, rag_service.settings.CHUNK_OVERLAP))

    for i, c in enumerate(chunks):
        rag_service.add_document(f"v21_{i}", c, {"file_id": 9001, "filename": "制度汇编.txt", "chunk_index": i})
    return col, chunks


def build_v22():
    """v2.2.0：500 字父块存 docstore，120 字子块进向量库。"""
    rag_service.settings.CHROMA_COLLECTION = V22_COLLECTION
    rag_service._collection = None
    col = rag_service.collection()

    parents = []
    for p in PARAGRAPHS:
        parents.extend(rag_service.split_text(p, rag_service.settings.CHUNK_SIZE, rag_service.settings.CHUNK_OVERLAP))

    # add_documents 内部完成：父块写 docstore + 子块写向量库
    child_count = rag_service.add_documents(
        parents, {"file_id": 9002, "filename": "制度汇编.txt"}, key_fmt="file_9002_chunk_{idx}"
    )
    return col, parents, child_count


def main() -> None:
    print("=" * 78)
    print(f"查询：{QUERY}")
    print("=" * 78)

    # ---------- v2.1.0 ----------
    col21, chunks21 = build_v21()
    print(f"\n【v2.1.0】向量库 = {len(chunks21)} 个 500 字大块（无父子结构）")
    r21 = rag_service.HybridRetrieval(col21, k=60, top_k=3)
    hits21 = r21.search(QUERY, 3)
    for i, h in enumerate(hits21, 1):
        print(f"  {i}. [RRF {h['rrf_score']:.5f}] 上下文 {len(h['text'])} 字 | {h['text'][:34]}...")
    top21 = hits21[0]["text"] if hits21 else ""

    # ---------- v2.2.0 ----------
    col22, parents22, child_cnt = build_v22()
    print(f"\n【v2.2.0】向量库 = {child_cnt} 个 120 字子块，docstore = {len(parents22)} 个父块")
    r22 = rag_service.HybridRetrieval(col22, k=60, top_k=3)
    child_hits = r22.search(QUERY, 3)
    print("  -- 命中的子块（仅用于检索）--")
    for i, h in enumerate(child_hits, 1):
        print(f"    {i}. {len(h['text'])} 字 | {h['text'][:34]}...")

    # 子块 → 父块回填
    final22 = rag_service._expand_to_parents(child_hits)
    print("  -- 回填父块后交给 LLM 的上下文 --")
    for i, h in enumerate(final22, 1):
        print(f"    {i}. [{h['context_level']}] {h['parent_chunk_id']} "
              f"上下文 {len(h['text'])} 字 | {h['text'][:34]}...")
    top22 = final22[0]["text"] if final22 else ""

    # ---------- 对比 ----------
    child_top = child_hits[0]["text"] if child_hits else ""
    print("\n" + "=" * 78)
    print("对比结果（查询「婚假几天」）")
    print("=" * 78)
    print(f"  A) v2.1.0 直接用大块检索    → Top1 {len(top21)} 字，命中「婚假」={'是' if '婚假' in top21 else '否'}")
    print(f"  B) v2.2.0 命中的子块（检索用）→ Top1 {len(child_top)} 字，"
          f"命中「婚假」={'是' if '婚假' in child_top else '否'}，"
          f"含审批条件「5个工作日」={'是' if '5个工作日' in child_top else '否'}")
    print(f"  C) v2.2.0 回填父块（交给LLM）→ Top1 {len(top22)} 字，粒度={final22[0]['context_level'] if final22 else '-'}，"
          f"命中「婚假」={'是' if '婚假' in top22 else '否'}，"
          f"含审批条件「5个工作日」={'是' if '5个工作日' in top22 else '否'}")
    print()
    print("  关键差异：B 只看到「婚假10天」这 116 字，C 通过父块拿回了同一段落里的")
    print("           「5个工作日提交申请」等完整条件 —— 即『小块命中、大块生成』。")
    if len(final22) < len(child_hits):
        print(f"  去重收益：{len(child_hits)} 个命中子块中有多个属于同一父块，"
              f"回填后合并为 {len(final22)} 条，避免上下文重复。")

    # ---------- 降级验证：删掉 docstore 里的父块 ----------
    print("\n" + "-" * 78)
    print("降级验证：清空 docstore 后，应直接返回子块且不报错")
    rag_service._parent_store = {}
    rag_service._parent_store_loaded = True
    degraded = rag_service._expand_to_parents(child_hits)
    for i, h in enumerate(degraded, 1):
        print(f"  {i}. [{h['context_level']}] {len(h['text'])} 字 | {h['text'][:26]}...")
    print(f"  降级后仍返回 {len(degraded)} 条，链路未中断 ✅" if degraded else "  降级失败 ❌")
    print("-" * 78)

    # ---------- 清理 ----------
    for name in (V21_COLLECTION, V22_COLLECTION):
        try:
            rag_service._client.delete_collection(name)
        except Exception:
            pass
    rag_service._collection = None
    rag_service.drop_parents_by_file(9002)
    print("\n已清理临时集合与测试父块")


if __name__ == "__main__":
    main()
