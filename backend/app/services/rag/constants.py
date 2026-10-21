"""RAG 检索共用常量（0.18.0）。

收敛前，同一组数值散落在 `rag_service.py` 与 `retrieval.py` 两处
（例如 RRF 常数 60 各写一份、默认 top_k 各写一份），改一处容易漏另一处。
本模块是这些数值的**唯一来源**，原位置改为 re-import，数值一个未改。
"""

#: RRF（倒数排名融合）常数。用来压平前几名的分数差：
#: 没有 k 时 rank=1 得 1.0、rank=2 得 0.5，第一名权重过大；
#: 加 60 后 rank=1 → 1/61、rank=2 → 1/62，"两路都还行"的文档能压过"一路第一、另一路垫底"。
RRF_K = 60

#: 子查询长度上限。Prompt 要求 ≤20 字，但小模型常写到 22-25 字，
#: 解析时放宽到 30 字，超过的丢弃（避免把整段问题当子查询用）。
MAX_SUB_QUERY_LEN = 30

#: 检索默认返回条数（未显式传 top_k 时使用）。
DEFAULT_TOP_K = 5

#: 单路召回默认候选数量（融合前的初筛规模）。
DEFAULT_CANDIDATE_N = 20

__all__ = [
    "RRF_K",
    "MAX_SUB_QUERY_LEN",
    "DEFAULT_TOP_K",
    "DEFAULT_CANDIDATE_N",
]
