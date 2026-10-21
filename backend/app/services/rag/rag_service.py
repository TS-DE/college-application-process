"""RAG 服务：Chroma 向量库 + embedding 通道 + 递归分块 + 混合检索。

设计要点：
- 所有向量库操作都封装在本文件，将来换 Milvus 只需替换这几个函数
- 分块：RecursiveCharacterTextSplitter（递归分块），失败时退化为定长切分
- 检索：稠密（Chroma 向量）+ 稀疏（BM25 关键词）→ RRF 融合（k=60）
- 0.7.1：embedding 与 LLM 统一走 `llm_client`（Ali OpenAI 兼容 → Ollama 兜底），
  维度自动对齐已存在的集合，避免历史 768 维数据报错
- 若 Ali / Ollama / Chroma 全不可用，退化为「关键词打分」的本地检索，保证链路不中断
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import requests

from app.config import settings
# 0.17.0：分块与父块存储拆到 services/knowledge/，此处保留同名引用，
# 历史调用方（含 test_*.py 里的 rag_service.split_text 等）无需改动。
from app.services.knowledge.parent_store import (  # noqa: F401
    drop_parents_by_file,
    get_parent,
    put_parents,
)
from app.services.knowledge.splitter import (  # noqa: F401
    CHILD_CHUNK_OVERLAP,
    CHILD_CHUNK_SIZE,
    SEPARATORS,
    _split_text_fixed,
    split_child_text,
    split_text,
)
from app.services.llm import llm_client

logger = logging.getLogger(__name__)

# 0.18.0：RRF 常数与子查询长度上限收敛到 `constants.py`（唯一来源），
# 此处 re-import 保持 `rag_service.RRF_K` / `rag_service.MAX_SUB_QUERY_LEN` 可用。
from app.services.rag.constants import (  # noqa: F401,E402
    DEFAULT_CANDIDATE_N,
    DEFAULT_TOP_K,
    MAX_SUB_QUERY_LEN,
    RRF_K,
)
from app.services.rag.storage.vector_store import VectorStore  # noqa: E402
from app.services.rag.retrieval.hybrid import HybridRetriever  # noqa: E402
from app.services.rag.retrieval.keyword_fallback import KeywordFallbackRetriever  # noqa: E402
from app.services.rag.postprocess.parent_expander import ParentExpander  # noqa: E402

# 父子块参数与 docstore 常量已迁移到 services/knowledge/（0.17.0）

# ---------------- 0.5.0 多路召回（Multi-Query Recall） ----------------
# 把复杂问题拆成 3-4 条聚焦的子查询，分别走混合检索，再按 RRF 累加融合
MULTI_QUERY_PROMPT = """你是一个高考志愿填报系统的查询改写专家。
请把用户的复杂问题拆解成 3-4 条**更聚焦**的子查询，用于分别检索知识库。

【拆解要求】：
1. 每条子查询聚焦一个语义单元：学校、专业、年份、省份、学费、位次、分数线、选科、批次。
2. 必须保留问题里的关键实体（学校名、专业名、年份、省份），不要凭空添加信息。
3. 每条子查询不超过 20 个字，是可以直接拿去检索的短语，不要写完整问句。
4. 子查询之间尽量不重复，覆盖问题的不同侧面。

【输出格式】（严格 JSON，不要输出任何其他文字）：
{{"queries": ["子查询1", "子查询2", "子查询3"]}}

【用户问题】：
{query}

【JSON输出】："""

# 子查询长度上限见 `constants.MAX_SUB_QUERY_LEN`（0.18.0 收敛）

# ---------------- Chroma 客户端（延迟初始化，避免导入即失败） ----------------
#
# 0.18.0：实现搬到 `storage/vector_store.py`，此处只保留薄封装。
# 下面四个模块级变量仍是**唯一状态来源**：`VectorStore(globals())` 直接读写它们，
# 因此测试里 `rag_service._collection = None` / `_collection_dim_cache = None`
# 这类 patch 依旧立即生效（下一次 collection() 会重建集合）。
_client = None
_collection = None
_chroma_error: Optional[str] = None
_collection_dim_cache: Optional[int] = None

_STORE = VectorStore(globals())
_KEYWORD_FALLBACK = KeywordFallbackRetriever(_STORE)
_PARENT_EXPANDER = ParentExpander()


def _get_collection():
    """获取（或创建）持久化集合。"""
    return _STORE.get_collection()


def collection():
    """供路由层直接操作（如按 file_id 删除向量）。"""
    return _STORE.collection()


def backend_info() -> dict:
    """向量库与模型通道状态（实现见 `VectorStore.backend_info`）。"""
    return _STORE.backend_info()


# ---------------- Embedding ----------------


def _collection_dimension() -> Optional[int]:
    """集合被 pin 住的向量维度（实现与取值顺序见 `VectorStore.collection_dimension`）。"""
    return _STORE.collection_dimension()


def get_embedding(text: str) -> Optional[List[float]]:
    """获取文本向量（0.7.1 统一通道）。

    顺序：Ali OpenAI 兼容 embedding（text-embedding-v3）→ 本地 Ollama（nomic-embed-text）→ None。
    维度：`dimensions` 优先取已有集合的真实维度（如历史上是 768），取不到才用 ALI_EMBED_DIMENSION(128)，
    这样新数据永远和历史数据同维，不会出现 Chroma 维度不匹配。
    """
    dim = _collection_dimension() or settings.ALI_EMBED_DIMENSION
    return llm_client.get_llm_client().embed(text, dimensions=dim)


def get_embeddings_batch(texts: List[str]) -> List[Optional[List[float]]]:
    """批量获取向量（0.7.1 提速）：一次网络往返算完一批 Query / 一批文档。

    多路召回一次要向量化 3-4 条 Query，逐条请求 = 3-4 次往返，合并后只剩 1 次。
    """
    dim = _collection_dimension() or settings.ALI_EMBED_DIMENSION
    return llm_client.get_llm_client().embed_batch(list(texts), dimensions=dim)


def _ollama_embedding(text: str) -> Optional[List[float]]:
    """本地 Ollama embedding 兜底（保留独立入口，供离线排查使用）。"""
    return llm_client.OllamaEmbeddingChannel().embed(text)


# ---------------- 分块：递归分块（Recursive Splitting） ----------------

# 递归分块的分隔符优先级：从"最粗粒度"到"最细粒度"依次尝试
#   1. "\n\n" 段落：政策文件里一个段落通常是一整条规则，优先按段落切开
#   2. "\n"   换行：段落仍超长时，退到按行切（PDF 抽取常以换行分条目）
#   3. "。"   句号：行还超长，按句切，保证语义完整
#   4. "，"   逗号：最后兜底才在逗号处断开（尽量不破坏句子）
# 注意：RecursiveCharacterTextSplitter 会"递归"地用下一个分隔符继续切超长的块，
#       直到每块 <= chunk_size，因此不会像定长切分那样把句子从中间切断。
# 分块函数已迁移到 services/knowledge/splitter.py（0.17.0）


# 父块存储已迁移到 services/knowledge/parent_store.py（0.17.0）


# ---------------- 写入 / 删除 / 检索 ----------------

def add_document(doc_id: str, text: str, metadata: dict, embedding: Optional[List[float]] = None) -> bool:
    """写入单个切片；embedding 为 None 时内部再计算一次。

    0.9.1：Chroma 拒绝维度不符的写入时会抛一段很难懂的原文字符串
    （"Collection expecting embedding with dimension of 768, got 128"），
    这里捕获后转成带处理建议的中文错误并抛出，让上传接口返回可读提示。
    """
    col = _get_collection()
    if col is None or not text:
        return False
    vec = embedding if embedding is not None else get_embedding(text)
    if vec is None:
        return False
    try:
        col.add(ids=[doc_id], embeddings=[vec], documents=[text], metadatas=[metadata])
    except Exception as exc:  # noqa: BLE001 维度不符等写入错误 → 转成可读错误
        expected = _collection_dimension()
        if expected and len(vec) != expected:
            raise RuntimeError(
                f"向量维度不匹配：集合要求 {expected} 维，实际生成 {len(vec)} 维。"
                f"请检查 ALI_EMBED_DIMENSION 配置或清空 chroma_db 目录后重新上传。"
            ) from exc
        raise
    return True


def add_documents(chunks: List[str], metadata: dict, key_fmt: str = "{idx}") -> int:
    """批量写入「父子块」，返回成功写入向量库的子块数量。

    入参 chunks 是递归分块得到的 500 字**父块**；这里对每个父块：
      1. 父块原文写入 docstore（只存不索引），parent_id = file_{file_id}_parent_{父块序号}
      2. 父块内部再切成 120 字**子块**，只有子块进向量库，
         child_id = file_{file_id}_chunk_{父块序号}_{子块序号}，
         metadata 里带上 parent_chunk_id 用于回填
      3. 父块本身不超过子块大小时，直接把它当作唯一子块索引（保证不漏内容）
    返回：写入向量库的子块数量（写库时记为 chunk_count）。
    """
    file_id = metadata.get("file_id")
    parents: List[Dict] = []
    ok = 0

    for parent_index, parent_text in enumerate(chunks):
        parent_text = (parent_text or "").strip()
        if not parent_text:
            continue

        parent_id = f"file_{file_id}_parent_{parent_index}"
        parents.append({
            "parent_id": parent_id,
            "text": parent_text,
            "file_id": file_id,
            "filename": metadata.get("filename"),
            "chunk_index": parent_index,
        })

        # 父块 → 子块；父块本身很短时直接作为唯一子块
        children = split_child_text(parent_text) or ([parent_text] if parent_text else [])
        for sub_index, child_text in enumerate(children):
            child_id = f"file_{file_id}_chunk_{parent_index}_{sub_index}"
            if add_document(
                child_id,
                child_text,
                {
                    **metadata,
                    "chunk_index": parent_index,   # 父块序号
                    "sub_index": sub_index,        # 父块内的子块序号
                    "parent_chunk_id": parent_id,  # 子块 → 父块 的关联 ID
                    "is_child": 1,                 # 标记：向量库存的是子块
                },
            ):
                ok += 1

    put_parents(parents)   # 父块原文入库（docstore）
    return ok


def delete_by_file(file_id: int) -> bool:
    """删除某个文件在向量库中的全部子块，并同步清理 docstore 里的父块。"""
    col = _get_collection()
    drop_parents_by_file(file_id)   # 先清父块，避免留下孤儿数据
    if col is None:
        return False
    try:
        col.delete(where={"file_id": file_id})
        return True
    except Exception:  # noqa: BLE001
        return False


def _expand_to_parents(hits: List[Dict]) -> List[Dict]:
    """子块命中 → 回填父块（实现与降级规则见 `ParentExpander`）。"""
    return _PARENT_EXPANDER.expand(hits)


# 0.18.0：混合检索实现搬到 `retrieval/hybrid.py`，此处保留旧类名做别名，
# 因此 `HybridRetrieval(col).search(...)`、`retriever.dense_search(...)` 等调用不受影响。
HybridRetrieval = HybridRetriever


def decompose_query(query: str, max_queries: int = 0) -> List[str]:
    """Query 分解：把复杂问题拆成 3-4 条聚焦的子查询（MULTI_QUERY_PROMPT）。

    处理链路：LLM 生成 JSON → 解析 → 去重 → 过滤空值/超长 → 保留原始 Query → 限条数
    参数：temperature=0.0（要确定性），num_predict=120

    **降级**：AI 关闭 / LLM 超时 / JSON 解析失败 → 返回 [原始 Query]，
    由调用方按单路检索处理，链路不中断。
    """
    from app.services.llm.ai_service import ai_enabled, ask

    limit = max_queries or settings.MULTI_QUERY_MAX
    original = (query or "").strip()
    if not original:
        return []

    if not ai_enabled() or not settings.MULTI_QUERY_ENABLED:
        return [original]

    raw = ask(
        MULTI_QUERY_PROMPT.format(query=original),
        temperature=0.0,   # 查询改写要稳定、可复现
        top_p=1.0,
        num_predict=120,
        timeout=20,
    )
    if not raw:
        return [original]

    # ---- JSON 解析：容错「模型多说了几句话」的情况 ----
    subs: List[str] = []
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, dict):
                subs = [str(x).strip() for x in (data.get("queries") or [])]
            elif isinstance(data, list):
                subs = [str(x).strip() for x in data]
    except Exception:  # noqa: BLE001 解析失败 → 降级
        subs = []

    # ---- 清洗：去空值、去超长（> MAX_SUB_QUERY_LEN 字）、去重 ----
    cleaned: List[str] = []
    seen: set = set()
    for s in subs:
        if not s or len(s) > MAX_SUB_QUERY_LEN:
            continue
        if s in seen:
            continue
        seen.add(s)
        cleaned.append(s)
    if not cleaned:
        return [original]

    # ---- 保留原始 Query 放首位，再限条数 ----
    merged = [original] + [s for s in cleaned if s != original]
    return merged[:limit]


def multi_route_search(query: str, top_k: int = 5, candidate_n: int = 0) -> List[Dict]:
    """多路召回：每条子查询独立走「向量 + BM25」混合检索，再跨路 RRF 累加。

    融合方式：把「子查询 × 检索路」看成多条独立的排名列表
      （如 4 条子查询 → 4 条稠密列表 + 4 条 BM25 列表 = 8 条），
      对候选文档逐条累加 1/(k + rank)，k=60。
    这样被多条子查询同时命中的文档会显著胜出（多面证据 > 单面证据）。

    **降级**：任一子查询检索异常都跳过该路；全部失败返回 []，由 search() 回落单路。
    """
    col = _get_collection()
    if col is None:
        return []

    queries = decompose_query(query)
    n = candidate_n or settings.MULTI_QUERY_CANDIDATE_N
    retriever = HybridRetrieval(col, k=RRF_K, top_k=top_k, candidate_n=n)
    corpus = retriever._load_corpus()  # noqa: SLF001 复用同一份语料快照（BM25 索引）
    if not corpus:
        return []

    # doc_id -> 累加的 RRF 分数
    scores: Dict[int, float] = {}
    best_distance: Dict[int, Optional[float]] = {}
    best_dense_rank: Dict[int, int] = {}
    best_bm25_rank: Dict[int, int] = {}
    matched: Dict[int, List[str]] = {}

    for q in queries:
        routes: List[tuple] = []
        try:
            routes.append(("dense", retriever.dense_search(q)))
            routes.append(("bm25", retriever.bm25_search(q)))
        except Exception:  # noqa: BLE001 单条子查询失败不影响其他路
            continue

        for route_name, ranking in routes:
            if not ranking:
                continue
            for rank, h in enumerate(ranking, start=1):
                idx = h["index"]
                scores[idx] = scores.get(idx, 0.0) + 1.0 / (RRF_K + rank)

                if route_name == "dense":
                    if idx not in best_dense_rank or rank < best_dense_rank[idx]:
                        best_dense_rank[idx] = rank
                        best_distance[idx] = h.get("distance")
                else:
                    if idx not in best_bm25_rank or rank < best_bm25_rank[idx]:
                        best_bm25_rank[idx] = rank

                if q not in matched.setdefault(idx, []):
                    matched[idx].append(q)

    if not scores:
        return []

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {
            "text": corpus[idx]["text"],
            "metadata": corpus[idx]["metadata"],
            "distance": best_distance.get(idx),
            "rrf_score": score,
            "dense_rank": best_dense_rank.get(idx),
            "bm25_rank": best_bm25_rank.get(idx),
            "matched_queries": matched.get(idx, []),
            "recall_mode": "multi_route",
        }
        for idx, score in ranked[:top_k]
    ]


def build_multi_recall(docs: Optional[List[Dict]] = None, embeddings: Optional[List] = None) -> "MultiRecall":
    """构建模块化多路召回（对接 app/services/retrieval.py）。

    通道配置（对应课堂案例「不同数据源 = 不同通道」的思路）：
      - dense：稠密向量通道（weight=1.0），复用 Chroma 中已存的向量，避免重复编码
      - bm25 ：稀疏关键词通道（weight=1.2，政策条款/专业代码这类字面量更依赖它）
      - hybrid：把「混合检索」当作一个复合通道（weight=1.0）
    docs 为空时自动从 Chroma 载入子块语料。
    """
    # 0.18.0：从新模块直接导入（`retrieval.py` 已降为 re-export 兼容层）
    from app.services.rag.retrieval.bm25 import BM25Channel
    from app.services.rag.retrieval.dense import DenseChannel
    from app.services.rag.retrieval.hybrid import HybridSearch
    from app.services.rag.retrieval.multi_recall import MultiRecallRetriever

    MultiRecall = MultiRecallRetriever

    if docs is None:
        docs, embeddings = _load_corpus_docs()
    if not docs:
        return MultiRecall(channels=[])

    channels: List = [
        DenseChannel("dense", docs, fields=["text"], weight=1.0, embeddings=embeddings),
        BM25Channel("bm25", docs, fields=["text"], weight=1.2),
        HybridSearch(docs, fields=["text"], k=RRF_K, embeddings=embeddings),
    ]
    return MultiRecall(channels=channels)


def _load_corpus_docs() -> tuple:
    """从 Chroma 取出子块语料，转成 retrieval 模块需要的结构。

    返回 (docs, embeddings)：
      docs       = [{"id": chunk_id, "text": ..., "metadata": {...}}]
      embeddings = Chroma 中已存的向量（可直接复用，省去重新编码全库）
    """
    col = _get_collection()
    if col is None:
        return [], None
    try:
        data = col.get(include=["documents", "metadatas", "embeddings"])
    except Exception:  # noqa: BLE001
        try:
            data = col.get(include=["documents", "metadatas"])
        except Exception:  # noqa: BLE001
            return [], None

    ids = data.get("ids") or []
    docs_list = data.get("documents") or []
    metas = data.get("metadatas") or []
    vecs = data.get("embeddings")
    docs = [
        {"id": i, "text": d or "", "metadata": m or {}}
        for i, d, m in zip(ids, docs_list, metas)
    ]
    return docs, (vecs if vecs is not None and len(vecs) == len(docs) else None)


def rerank(query: str, hits: List[Dict]) -> List[Dict]:
    """Rerank 精排（0.7.0 落地）：对多路召回的候选做二次排序。

    实现见 app/services/reranker.py：
      - 配置了 RERANK_MODEL 且 CrossEncoder 可用 → CrossEncoderReranker
      - 否则 → EmbeddingReranker（复用项目 embedding 的余弦分，无需额外模型）
      - 关闭 RERANK_ENABLED → NoopReranker（直传）
    精排失败时保持召回顺序，链路不中断。
    """
    if not hits:
        return hits
    try:
        from app.services.rag.reranker import Reranker

        return Reranker().rerank(query, hits)
    except Exception:  # noqa: BLE001
        return hits


def route_strategy(query: str) -> str:
    """Modular RAG 路由：按 Query 特征选择处理链路（不额外调用 LLM，零延迟）。

      - self_rag   ：判断/确认类问题（是不是、能不能、要不要、是否…）→ 需要模型自判断
      - corrective ：复合/多实体问题（同时问学校+专业+学费+位次，或含"多少/怎么/哪些"）
                     → 容易召回不全，走「过滤 + 重写重试」纠偏
      - standard   ：其余走常规 RAG（检索前预处理 + 多路召回 + 精排）
    """
    q = (query or "").strip()
    if not q:
        return "standard"

    judge_words = ("是不是", "能不能", "要不要", "是否", "可否", "有没有", "对不对")
    complex_words = ("多少", "怎么", "哪些", "分别", "以及", "和", "还是", "对比")

    if any(w in q for w in judge_words):
        return "self_rag"
    if sum(1 for w in complex_words if w in q) >= 2 or len(q) >= 18:
        return "corrective"
    return "standard"


def answer_with_strategy(
    query: str,
    top_k: int = 3,
    strategy: str = "auto",
    history_section: str = "",
) -> Dict:
    """Modular RAG 主流程：按策略选择 Self-RAG / Corrective RAG / 标准 RAG。

    三条链路**共用**同一个检索入口 search()（内含检索前预处理 + 多路召回 + 精排 + 父块回填），
    差别只在"拿到上下文之后怎么生成、要不要反思/纠偏"。

    0.17.1：`history_section` 由 `_generate` 闭包透传给 `generate_answer`，
    因此 Self-RAG / Corrective RAG / 标准 RAG **三条链路自动生效**，无需各改一遍。
    为空串时行为与 0.17.0 一致。
    """
    mode = strategy if strategy != "auto" else settings.ADVANCED_RAG_STRATEGY
    if mode == "auto":
        mode = route_strategy(query)

    def _retrieve(q: str, k: int) -> List[Dict]:
        return search(q, top_k=k)

    def _generate(q: str, context: str) -> str:
        return generate_answer(q, context, history_section=history_section) or ""

    if not settings.ADVANCED_RAG_ENABLED:
        mode = "standard"

    if mode == "self_rag":
        try:
            from app.services.rag.self_rag import SelfRAG

            res = SelfRAG(_retrieve, _generate, top_k=top_k).run(query)
            return {
                "answer": res.answer,
                "strategy": "self_rag",
                "steps": res.steps,
                # 复用 Self-RAG 已检索到的 hits 取来源，避免重复检索（省一整轮预处理 + 召回）
                "sources": _sources_from_hits(res.hits),
            }
        except Exception:  # noqa: BLE001 高级链路异常 → 回落标准 RAG
            mode = "standard"

    if mode == "corrective":
        try:
            from app.services.rag.corrective_rag import CorrectiveRAG

            res = CorrectiveRAG(_retrieve, _generate, top_k=top_k).run(query)
            return {
                "answer": res.answer,
                "strategy": "corrective",
                "steps": res.steps,
                "rewritten_query": res.rewritten_query,
                "sources": _sources_from_hits(res.hits),
            }
        except Exception:  # noqa: BLE001
            mode = "standard"

    hits = _retrieve(query, top_k)
    context = "\n".join(h.get("text", "") for h in hits)
    return {
        "answer": _generate(query, context) or OFF_TOPIC_ANSWER,
        "strategy": "standard",
        "steps": ["retrieve", "generate"],
        "sources": _sources_from_hits(hits),
    }


def _sources_from_hits(hits: List[Dict]) -> List[str]:
    """从命中结果中提取来源文件名（去重）。"""
    names = []
    for h in hits:
        name = (h.get("metadata") or {}).get("filename") or "知识库"
        if name not in names:
            names.append(name)
    return names


def search(query: str, top_k: int = 5, use_multi_route: bool = True) -> List[Dict]:
    """完整检索流程：检索前预处理 → 模块化多路召回 → Rerank 精排 → 父子块回填。

    ① 检索前：QueryPreprocessor.process()（重写 / 扩展 / 子查询）
    ② 检索中：build_multi_recall() 构建通道，按「子查询 × 通道」做 RRF 累加
    ③ 精排  ：rerank()（模型可用时才生效，当前为 no-op）
    ④ 回填  ：_expand_to_parents() 把命中子块换成父块上下文
    任一步失败都有兜底，链路不中断。
    """
    col = _get_collection()
    if col is None:
        return _keyword_fallback(query, top_k)

    # ===== ① 检索前预处理（0.6.0）=====
    queries: List[str] = [query]
    preprocess_info: Dict = {"enabled": False, "source": "raw", "queries": [query]}
    if settings.MULTI_QUERY_ENABLED:
        try:
            from app.services.rag.query_rewrite import QueryPreprocessor

            preprocessor = QueryPreprocessor(
                use_rewrite=settings.QUERY_REWRITE_ENABLED,
                use_expansion=settings.QUERY_EXPANSION_ENABLED,
                use_decompose=settings.QUERY_DECOMPOSE_ENABLED,
                max_queries=settings.QUERY_PREPROCESS_MAX,
            )
            bundle = preprocessor.process(query)
            queries = bundle.all_queries or [query]
            preprocess_info = {
                "enabled": True,
                "source": bundle.source,
                "rewritten": bundle.rewritten,
                "step_back": bundle.step_back,
                "sub_queries": bundle.sub_queries,
                "queries": queries,
            }
        except Exception:  # noqa: BLE001 预处理失败 → 用原始 Query
            queries = [query]

    # ===== ② 检索中：模块化多路召回 =====
    results = _recall(queries, top_k, use_multi_route)

    # ===== ③ Rerank 精排（模型未接入时为 no-op）=====
    if results:
        results = rerank(query, results)
        for h in results:
            h.setdefault("preprocess", preprocess_info)
        # ===== ④ 子块命中 → 回填父块 =====
        return _expand_to_parents(results)

    # 兜底：Chroma 有数据但都没命中，用老的关键词打分
    return _expand_to_parents(_keyword_fallback(query, top_k))


def _recall(queries: List[str], top_k: int, use_multi_route: bool) -> List[Dict]:
    """检索中执行：模块化多路召回，失败逐级回落。

    回落顺序：多路召回(模块化) → 多路召回(内置) → 单路混合检索
    """
    # ① 模块化多路召回（app/services/retrieval.py，课堂案例风格）
    if use_multi_route and settings.MULTI_QUERY_ENABLED:
        try:
            docs, embeddings = _load_corpus_docs()
            if docs:
                recall = build_multi_recall(docs, embeddings)
                fusion = settings.MULTI_RECALL_FUSION
                per_channel = settings.MULTI_RECALL_TOPK_PER_CHANNEL
                if fusion == "weight":
                    raw = recall.weight_fusion(queries[0], top_k=top_k, top_k_per_channel=per_channel)
                elif fusion == "round_robin":
                    raw = recall.round_robin_fusion(queries[0], top_k=top_k, top_k_per_channel=per_channel)
                else:
                    raw = recall.rrf_fusion(queries, top_k=top_k, top_k_per_channel=per_channel)
                return [_hit_from_channel(h) for h in raw]
        except Exception:  # noqa: BLE001
            pass

    # ② 内置多路召回（0.5.0）
    if use_multi_route and settings.MULTI_QUERY_ENABLED:
        try:
            hits = multi_route_search(queries[0], top_k)
            if hits:
                return hits
        except Exception:  # noqa: BLE001
            pass

    # ③ 单路混合检索兜底
    try:
        return HybridRetrieval(_get_collection(), k=RRF_K, top_k=top_k).search(queries[0], top_k)
    except Exception:  # noqa: BLE001
        return []


def _hit_from_channel(hit: Dict) -> Dict:
    """把 retrieval 模块的输出转换成项目内部的 hit 结构（保持字段一致）。"""
    doc = hit.get("full_doc") or {}
    return {
        "text": hit.get("text") or doc.get("text", ""),
        "metadata": doc.get("metadata", {}) or {},
        "distance": None,
        "rrf_score": hit.get("rrf_score") or hit.get("weighted_score") or hit.get("score"),
        "dense_rank": None,
        "bm25_rank": None,
        "channel": hit.get("channel"),
        "recall_mode": "multi_recall_module",
    }


def _keyword_fallback(query: str, top_k: int) -> List[Dict]:
    """无向量能力时的兜底：对库内文档做关键词打分（实现见 `KeywordFallbackRetriever`）。"""
    return _KEYWORD_FALLBACK.retrieve(query, top_k)


# ---------------- 0.4.0：Query 路由 + 防幻觉 Prompt ----------------

# 1) 路由拦截提示词：在 RAG 检索之前单独调用一次 LLM 做二分类
#    参数：temperature=0.0（要确定性），max_tokens=5（只要 YES / NO）
#    0.4.1 修正：0.4.0 的关键词列表太窄，跨省招生计划（"2025河南在福建招生的院校"）
#    这类长尾高考问题会被误判为 NO；这里改成「满足任意一条即为 YES」的宽松口径。
ROUTER_PROMPT = """你是一个高考志愿填报系统的意图分类器。
你的任务是判断用户的问题是否与【高考、志愿填报、院校、专业、招生、录取、分数线、学费、位次、选科、批次】相关。

【判断规则】（满足任意一条即为 YES）：
1. 问题中包含任何高考相关词汇（如：高考、志愿、院校、大学、专业、招生、录取、分数线、学费、位次、选科、批次、投档、调剂）。
2. 问题询问某所学校或某个专业的情况（如：XX大学怎么样、XX专业学什么、XX学校学费多少）。
3. 问题询问某省/某年的招生政策或招生计划（如：河南2025年招生计划、福建在河南招多少人）。
4. **主观咨询 / 征询意见类问题**（如：我该去哪所学校、你觉得我适合什么专业、帮我推荐几个志愿、
   能猜到我想去哪所学校吗、帮我把把关、这样填稳不稳）——这类问题属于志愿**规划**，
   即使没有提到具体院校名也应判 YES。

【严格规则】：
1. 如果问题与上述完全无关（例如：婚假、天气、编程、闲聊、历史事件），只输出：NO
2. 如果问题与上述相关，只输出：YES
3. 不要输出任何解释、标点符号或其他文字！只输出 YES 或 NO！

【用户问题】：
{query}

【输出】："""

# 0.12.1：主观咨询意图白名单。
# 命中这些词时**直接放行，不再调用 LLM 分类**——一是避免模型把「你能猜到我想去哪所学校吗」
# 这类规划类问题误判成闲聊而拦截，二是省掉一次 20-45 秒的 LLM 往返（超时的主要来源之一）。
SUBJECTIVE_INTENT_KEYWORDS: tuple = (
    "我该", "我该去哪", "该去哪", "该选哪", "该报哪", "去哪所学校", "哪个学校",
    "推荐", "建议", "帮我看看", "把把关", "稳不稳", "猜猜", "猜到",
    "适合我", "适合什么", "怎么填", "如何填", "怎么选", "如何选",
    "志愿怎么", "求指导", "帮忙分析", "分析一下", "评价一下",
)


def _has_subjective_intent(query: str) -> bool:
    """是否命中主观咨询白名单（确定性判断，不依赖大模型）。"""
    q = (query or "").strip()
    if not q:
        return False
    return any(word in q for word in SUBJECTIVE_INTENT_KEYWORDS)

# 2) 防幻觉提示词：RAG 检索之后，把父块 Context 与 Query 一起交给 LLM
#    参数：temperature=0.1，top_p=0.3
#    0.4.1 修正：0.4.0 用「绝对铁律 + top_p=0.1」过于保守，父块里明明有 23000 元/年，
#    模型也不敢生成、直接套用拒答话术；这里改成「回答规则」：有资料就完整回答，
#    只有上下文中完全没有相关信息时才拒答。
ANTI_HALLUCINATION_PROMPT = """你是一个严谨的高考志愿填报助手。请严格根据【检索上下文】回答用户问题。

【回答规则】：
1. 如果【检索上下文】中有明确答案（包括数字、学校名、专业名、政策条款），请**直接、完整地**回答，不要遗漏上下文中的关键数字。
2. 如果【检索上下文】中**完全没有**用户问的信息，才回答：“根据现有资料，未查询到具体信息，建议查阅学校官方招生简章。”
3. 禁止编造【检索上下文】中不存在的数字（如学费、分数线、位次）。
4. 如果上下文中有相关数字，**必须原样引用**，不要用“通常、大概、一般来说”等模糊词汇替换。
5. 回答必须完全基于上下文，不得添加任何外部信息。

【检索上下文】：
{context}

【用户问题】：
{question}

【回答】："""

# 3) 结构化数据提取提示词（预留，配合 Text-to-SQL）
#    参数：temperature=0.0（要确定性 JSON）；命中强结构化关键词时走 MySQL，不走 RAG
SQL_EXTRACT_PROMPT = """你是一个高考数据提取器。请从用户的问题中提取以下 JSON 格式的查询条件。
如果某个字段没有提到，值设为 null。

【字段说明】：
- school_name: 学校名称（字符串）
- major_name: 专业名称（字符串）
- year: 年份（整数）
- province: 省份（字符串）

【严格规则】：
1. 只输出 JSON，不要输出任何其他文字。
2. 不要编造不存在的字段。
3. 如果用户问的是“学费”，请确保 school_name 和 major_name 准确提取。

【用户问题】：
{query}

【JSON输出】："""

# 命中这些关键词时，优先考虑走 MySQL 结构化查询而不是 RAG（0.4.0 预留）
STRUCTURED_KEYWORDS = ("学费", "分数线", "位次", "录取分", "招生人数", "计划数")

# ============================================================
# 0.9.1 结构化意图识别：先判断「是不是字段型问题」，再决定要不要查 MySQL
# ============================================================
#
# ## 为什么需要这一层
# 0.9.0 的检索分发只看 use_graph 开关，无论问什么都走「图谱 + 向量」。
# 但「学费多少」「最低分多少」这类**字段型问题**的精确值就在 MySQL 的
# major_admission_{year}_henan 表里，绕道去 Chroma 翻 PDF 只会得到相似文本，
# 找不到就拒答。所以在并行检索之前必须先识别意图。
#
# ## 设计约束（单一职责）
# detect_structured_intent() 只做「意图识别」，不做查询、不碰数据库；
# 真正的查询由 services/sql_query_engine.py 的 MySQLQueryEngine 负责。
STRUCTURED_INTENT_KEYWORDS: Dict[str, List[str]] = {
    # 意图名 -> 触发关键词（命中任一即认为用户问了这个字段）
    "tuition": ["学费", "费用", "多少钱", "收费"],
    "min_score": ["分数线", "最低分", "录取分", "投档线", "多少分"],
    "min_rank": ["位次", "排名", "最低位次"],
    "subject_req": ["选科", "选考", "科目要求", "首选", "再选"],
    "plan_count": ["招生计划", "招多少人", "招生人数", "计划数"],
}

# 意图名 -> 输出给 LLM 的中文行模板（MySQLQueryEngine 复用同一套 key）
STRUCTURED_INTENT_TEMPLATES: Dict[str, str] = {
    "tuition": "{school}{major}专业{year}年学费为{value}元/年。",
    "subject_req": "{school}{major}专业选科要求：{value}。",
    "min_score": "{school}{major}专业{year}年最低录取分{value}分。",
    "min_rank": "{school}{major}专业{year}年最低位次{value}。",
    "plan_count": "{school}{major}专业{year}年招生计划{value}人。",
}


def detect_structured_intent(query: str) -> List[str]:
    """判断问题属于哪几类结构化查询（可多类命中）。

    :param query: 用户原始问题
    :return: 意图名列表，如 ["tuition", "subject_req"]；空列表表示不是结构化问题，
             调用方应直接走向量检索（政策 / 流程 / 介绍类问题）。

    例：「福州大学至诚学院计算机专业学费是多少？选科要求是什么？」
        → ["tuition", "subject_req"]
    例：「河南本科批志愿怎么填报？」→ []
    """
    q = query or ""
    return [intent for intent, words in STRUCTURED_INTENT_KEYWORDS.items() if any(w in q for w in words)]

# 路由被拦截时返回给用户的固定话术（与放宽后的路由口径保持一致）
OFF_TOPIC_ANSWER = (
    "抱歉，我是高考志愿填报助手，只回答与【高考、志愿填报、院校、专业、招生、录取、"
    "分数线、学费、位次、选科、批次】相关的问题。请换一个高考相关的问题再试。"
)


def route_query(query: str) -> bool:
    """Query 意图路由：返回 True 表示放行（走 RAG），False 表示拦截（无关问题）。

    - 在 RAG 检索**之前**调用，避免无关问题（婚假、天气、闲聊）污染检索与生成
    - 参数：temperature=0.0，max_tokens=5（num_predict=5）
    - **降级**：AI 关闭 / LLM 调用失败 / 返回为空 → 默认放行，不中断链路

    0.12.1：新增**确定性预检**。命中主观咨询白名单（"我该去哪"、"推荐"、"把把关"…）
    直接放行，不再调 LLM。既修复了「你能猜到我想去哪所学校吗」被误拦截的问题，
    又把一次 20-45 秒的 LLM 往返从关键路径上拿掉。
    """
    from app.services.llm.ai_service import ai_enabled, ask

    # ① 确定性预检：规划类问题一律放行（顺带省一次 LLM 调用）
    if _has_subjective_intent(query):
        logger.info("[RAG] 路由：命中主观咨询白名单 → 放行（query=%s）", query)
        return True

    if not ai_enabled():
        return True  # AI 未启用时不做拦截

    intent = ask(
        ROUTER_PROMPT.format(query=query),
        temperature=0.0,   # 意图分类要确定性
        top_p=1.0,
        num_predict=5,     # 只要 YES / NO 两个 token
        timeout=20,
    )
    if not intent:
        # LLM 不可用 → 放行，交回主流程兜底
        logger.info("[RAG] 路由：LLM 无返回 → 放行（query=%s）", query)
        return True
    ok = "YES" in intent.upper()
    # 留痕：路由误判是最难排查的线上问题，这里把「模型原话」写进日志
    logger.info("[RAG] 路由：模型输出=%r → %s（query=%s）", intent, "放行" if ok else "拦截", query)
    return ok


def generate_answer(
    query: str,
    context: str,
    temperature: float = 0.1,
    top_p: float = 0.3,
    profile_context: str = "",
    history_section: str = "",
) -> Optional[str]:
    """防幻觉生成：优先依据检索到的父块上下文回答，上下文中完全没有才拒答。

    - 参数默认：**temperature=0.1**，**top_p=0.3**
      （0.4.0 用的 top_p=0.1 过于保守，会导致上下文明明有数字时模型也放弃生成）
    - 返回 None 表示生成失败，由调用方降级（回退原 chat 逻辑或提示稍后重试）
    - 0.12.0：`profile_context` 非空时在规则前插入【考生画像】段落，
      要求模型结合画像给个性化建议，但**不得据此编造数字**。
    - 0.17.1：`history_section` 非空时插到【用户问题】之前，
      只用于消解「它 / 那个」等指代；**不并入【检索上下文】**，
      因此不会成为事实来源（见 services/rag/prompt_utils.py 的说明）。
      为空串时 Prompt 与 0.17.0 逐字一致。
    """
    from app.services.llm.ai_service import ask

    prompt = ANTI_HALLUCINATION_PROMPT.format(context=context, question=query)
    section = build_profile_section(profile_context)
    if section:
        # 插到【回答规则】之前，让画像先于规则被模型读到
        anchor = "【回答规则】："
        prompt = prompt.replace(anchor, section + "\n" + anchor, 1)
    if history_section:
        # 插到【用户问题】之前：先看上文，再看问题，指代才有落点
        prompt = prompt.replace("【用户问题】：", history_section + "【用户问题】：", 1)
    return ask(
        prompt,
        temperature=temperature,   # 低温度：减少自由发挥
        top_p=top_p,               # 适度收窄：抑制编造，但不至于不敢生成
        num_predict=400,
    )


def extract_sql_filters(query: str) -> Optional[Dict]:
    """结构化条件提取（0.4.0 预留，配合 Text-to-SQL 走 MySQL）。

    - 参数：temperature=0.0
    - 命中「学费/分数线/位次」等强结构化关键词时优先走 MySQL 精确查询，
      避免 RAG 召回不到导致编造；当前仅返回解析结果，实际 SQL 查询留给后续版本接入。
    """
    from app.services.llm.ai_service import ai_enabled, ask

    if not ai_enabled():
        return None
    if not any(k in (query or "") for k in STRUCTURED_KEYWORDS):
        return None

    raw = ask(
        SQL_EXTRACT_PROMPT.format(query=query),
        temperature=0.0,
        top_p=1.0,
        num_predict=120,
        timeout=20,
    )
    if not raw:
        return None
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        return json.loads(raw[start : end + 1])
    except Exception:  # noqa: BLE001 解析失败按未提取处理
        return None


# ============================================================
# 0.9.0 知识图谱双通道：向量 + 图谱在 rag_service 层「优先级 + Token 配额」融合
# ============================================================
#
# ## 为什么不做分数融合（RRF 不适用）
# 图谱结果是对/错的**精确事实**（学费 18000、最低分 512），向量结果是**相似度文本**
# （"该校学费适中，性价比高"）。二者量纲不可比：把 0.91 的向量相似度和一条 100% 正确的
# 图谱事实一起排序是没有意义的。因此 rag_service 扮演「中枢神经」，用两级策略融合：
#
#   Level 1 优先级：图谱上下文排在前面，Prompt 明确声明「图谱为权威事实，冲突时以图谱为准」
#   Level 2 配额  ：总上下文预算 4000 token，图谱最多 60%、向量最多 40%；
#                   某一路没用满时，剩余额度让给另一路（避免浪费预算）
#
# ## 第一版刻意不做 Level 3 串行筛选
# 「图谱不完整时才查向量」会把两路从并行变成串行，延迟翻倍；0.9.0 先只做 Level 1 + 2，
# Level 3 留到 1.0.0（见 CHANGELOG 演进方向）。
from dataclasses import dataclass, field  # noqa: E402

# 双通道融合后的 Prompt（Level 1 优先级在这里落地）
GRAPH_FUSION_PROMPT = """你是高考志愿填报助手。请根据以下两段背景回答用户问题。

{priority_hint}

【图谱事实】（权威精确数据）：
{graph_context}

【向量背景】（语义文本补充）：
{vector_context}

用户提问：{question}

回答要求：
1. 优先使用【图谱事实】中的结构化数据（分数线、学费、选科要求、招生人数）
2. 【向量背景】用于补充政策、介绍、背景类信息
3. 两段背景都没有相关信息时，回答"根据现有资料未查询到具体信息，建议查阅学校官方招生简章"
4. 禁止编造两段背景中不存在的数字
"""

# Token ↔ 字符换算：1 token ≈ 1.5 个中文字符（本项目统一用这个经验值做预算估算）
CHARS_PER_TOKEN = 1.5
# 融合总预算（token），图谱 60% / 向量 40%
TOTAL_CONTEXT_TOKENS = 4000

# 实际使用的融合策略名（透传给前端，便于评估模块做对比）
FUSION_STRATEGY = "priority_quota"


@dataclass
class HybridResult:
    """双通道检索 + 融合后的结果（交给 ai.py 生成最终回答）。"""

    graph_context: str = ""
    vector_context: str = ""
    graph_hit: bool = False
    vector_hit: bool = False
    fusion_strategy: str = FUSION_STRATEGY
    priority_hint: str = ""
    graph_cypher: str = ""
    graph_entities: List[Dict] = field(default_factory=list)
    graph_error: str = ""
    sources: List[str] = field(default_factory=list)


def _truncate_by_tokens(text: str, max_tokens: int) -> str:
    """按 token 预算截断文本（1 token ≈ 1.5 中文字符）。"""
    if not text:
        return ""
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + " …（上下文已按 Token 配额截断）"


def _build_priority_hint(graph_hit: bool, vector_hit: bool) -> str:
    """Level 1 优先级提示语：明确告诉 LLM 两段背景谁权威、冲突时听谁的。"""
    if graph_hit and vector_hit:
        return (
            "【图谱事实】为权威精确数据，与【向量背景】冲突时以图谱为准。"
            "【向量背景】用于补充政策、介绍类信息。"
        )
    if graph_hit:
        return "本次仅检索到【图谱事实】，请严格基于其回答，禁止编造。"
    if vector_hit:
        return "本次仅检索到【向量背景】，请基于其回答，找不到信息时明确说明。"
    return "两路均未检索到相关信息，请返回预设拒答话术。"


# 图谱引擎进程内单例：None=未初始化 / False=初始化失败（不再重试）/ GraphQueryEngine=可用
_graph_engine = None


def _get_graph_engine():
    """懒加载图谱引擎（进程内复用），并把 LLM 通道注入实体抽取器。

    依赖倒置：EntityExtractor / CypherGenerator 只依赖注入进来的 llm_chat 函数，
    不 import 具体 LLM 模块；图谱不可用时返回 None，由调用方走纯向量链路。
    """
    global _graph_engine
    if _graph_engine is not None:
        return _graph_engine or None
    try:
        from app.services.graph import build_default_engine

        _graph_engine = build_default_engine()
    except Exception as exc:  # noqa: BLE001 图谱模块整体不可用 → 走纯向量链路
        logger.info("[GRAPH] 图谱引擎初始化失败，降级为纯向量 RAG：%s", exc.__class__.__name__)
        _graph_engine = False
    return _graph_engine or None


def search_with_graph(query: str, top_k: int = 5) -> HybridResult:
    """双通道并行检索 + 「优先级 + Token 配额」融合（0.9.0 中枢神经）。

    流程：
      ① 并行：图谱通道（GraphQueryEngine.query）‖ 向量通道（search()）
             用 ThreadPoolExecutor 而非 asyncio.gather：两条链路内部都是同步阻塞调用
             （Neo4j bolt / Chroma / HTTP），线程池在无 GPU 的 i5 机器上更稳。
      ② Level 1 优先级：图谱上下文在前、向量在后，并生成 priority_hint。
      ③ Level 2 配额  ：总预算 4000 token，图谱 60% / 向量 40%，未用满的额度让给另一路。

    任一路失败都只让那一路为空，另一路照常工作（图谱挂了 = 退化成原来的纯向量 RAG）。
    """
    result = HybridResult()

    def _graph_channel():
        engine = _get_graph_engine()
        if engine is None:
            return None
        return engine.query(query)

    graph_out = None
    hits: List[Dict] = []
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            future_graph = pool.submit(_graph_channel)
            future_vector = pool.submit(search, query, top_k)
            graph_out = future_graph.result()
            hits = future_vector.result() or []
    except Exception as exc:  # noqa: BLE001 并行调度本身出错也不能中断问答
        logger.info("[GRAPH] 双通道并行调度异常：%s", exc.__class__.__name__)
        try:  # 兜底：至少把向量通道补回来
            hits = search(query, top_k) or []
        except Exception:  # noqa: BLE001
            hits = []

    # ---- 图谱通道结果 ----
    if graph_out is not None:
        result.graph_hit = graph_out.hit
        result.graph_context = graph_out.context or ""
        result.graph_cypher = graph_out.cypher or ""
        result.graph_entities = graph_out.entities or []
        result.graph_error = graph_out.error or ""

    # ---- 向量通道结果（沿用 ai.py 原有的 sources 收集口径）----
    if hits:
        result.vector_hit = True
        result.vector_context = "\n".join(
            f"[{(h.get('metadata') or {}).get('filename') or '知识库'}] {h.get('text', '')}"
            for h in hits
        )
        result.sources = sorted({
            (h.get("metadata") or {}).get("filename") or "知识库" for h in hits
        })

    # ---- Level 2 Token 配额融合（含额度互让）----
    graph_budget = int(TOTAL_CONTEXT_TOKENS * 0.6)
    vector_budget = int(TOTAL_CONTEXT_TOKENS * 0.4)
    graph_used = int(len(result.graph_context) / CHARS_PER_TOKEN)
    if graph_used < graph_budget:                      # 图谱没用满 → 剩余让给向量
        vector_budget += graph_budget - graph_used
    elif result.vector_context:
        spare = max(0, TOTAL_CONTEXT_TOKENS - graph_used)  # 图谱超配 → 向量只能用总量剩余
        vector_budget = min(vector_budget, spare)
    result.graph_context = _truncate_by_tokens(result.graph_context, graph_budget)
    result.vector_context = _truncate_by_tokens(result.vector_context, vector_budget)

    # ---- Level 1 优先级提示 ----
    result.priority_hint = _build_priority_hint(result.graph_hit, result.vector_hit)

    logger.info(
        "[GRAPH] 融合完成 strategy=%s graph_hit=%s(%d 字符) vector_hit=%s(%d 字符)",
        result.fusion_strategy, result.graph_hit, len(result.graph_context),
        result.vector_hit, len(result.vector_context),
    )
    return result


def answer_with_graph(query: str, top_k: int = 5) -> Dict:
    """双通道问答主流程：融合检索 → GRAPH_FUSION_PROMPT → 生成。

    返回 dict 直接给路由层（含 graph_hit / vector_hit / fusion_strategy / graph_cypher，
    便于前端调试与评估模块统计图谱命中率）。
    """
    hybrid = search_with_graph(query, top_k=top_k)

    # 两路都没命中：不走 LLM 生成，直接给保守话术，省一次网络往返
    if not hybrid.graph_hit and not hybrid.vector_hit:
        return {
            "answer": "根据现有资料未查询到具体信息，建议查阅学校官方招生简章。",
            "source": "graph+vector:empty",
            "sources": [],
            "graph_hit": False,
            "vector_hit": False,
            "fusion_strategy": hybrid.fusion_strategy,
            "graph_cypher": "",
            "graph_error": hybrid.graph_error,
        }

    prompt = GRAPH_FUSION_PROMPT.format(
        priority_hint=hybrid.priority_hint,
        graph_context=hybrid.graph_context or "（无）",
        vector_context=hybrid.vector_context or "（无）",
        question=query,
    )
    from app.services.llm.ai_service import ask

    answer = ask(prompt, temperature=0.1, top_p=0.3, num_predict=400, timeout=60)
    if not answer:
        raise RuntimeError("大模型响应超时")

    return {
        "answer": answer,
        "source": "graph+vector",
        "sources": hybrid.sources,
        "graph_hit": hybrid.graph_hit,
        "vector_hit": hybrid.vector_hit,
        "fusion_strategy": hybrid.fusion_strategy,
        "graph_cypher": hybrid.graph_cypher,
        "graph_error": hybrid.graph_error,
    }


# ============================================================
# 0.9.1 三路融合：图谱 + MySQL + 向量，按「图谱 > MySQL > 向量」优先级分发
# ============================================================
#
# ## 修复的问题（0.9.0 缺陷）
# 0.9.0 的 answer_with_graph() 只有「图谱 + 向量」两路：
#   · 学费 / 分数线 / 位次 / 选科 / 招生人数这些**字段型事实**的精确值在 MySQL 里，
#     系统却绕道去 Chroma 翻 PDF，翻不到就拒答；
#   · extract_sql_filters() 从 0.4.0 起就预留了，但从未真正接到 MySQL 查询；
#   · 图谱通道异常时 except → pass 直接落到纯向量，中间没有 MySQL 兜底。
#
# ## 核心原则：结构化事实 > 非结构化文档
# 三路**并联**（不是二选一），各管一段：
#   图谱通道（Neo4j）  适合关系型问题：「XX 学校开设了哪些专业」
#   MySQL 通道        适合字段型问题：「XX 专业 2025 年学费」
#   向量通道（Chroma） 适合政策 / 流程 / 介绍类问题
#
# ## 优先级融合（不做分数融合）
# 图谱与 MySQL 返回的都是「对/错的精确事实」，向量返回的是「相似度文本」，
# 三者量纲不可比，因此按 图谱 > MySQL > 向量 的顺序排列上下文，
# 并在 Prompt 里声明权威关系，而不是把相似度和精确值一起排序。
#
# ## 失败处理
# 任一路异常只跳过该路，其余两路继续；三路都空 → 返回拒答话术，
# 绝不允许本地模型用预训练知识编造数字。
HYBRID_FUSION_PROMPT = """你是高考志愿填报助手。请严格根据以下背景回答用户问题。

【优先级声明】
{priority_hint}
{profile_section}
【图谱事实】（权威精确数据）：
{graph_context}

【数据库精确值】（权威精确数据）：
{mysql_context}

【政策/介绍文本】（用于补充说明，不作为数字依据）：
{vector_context}

用户提问：{question}

回答要求：
1. 优先使用【图谱事实】和【数据库精确值】中的结构化数据（学费、分数线、位次、选科、招生人数）
2. 【政策/介绍文本】用于补充政策、流程、背景类信息，不用于数字依据
3. 如果两段权威数据冲突，以【图谱事实】为准
4. 所有背景都没有相关信息时，必须回答"根据现有资料未查询到具体信息，建议查阅学校官方招生简章"
5. 禁止使用预训练知识补充任何数字
6. 禁止使用"通常、大概、一般来说"来推测数字
"""


ADVISORY_PROMPT = """你是资深的高考志愿规划师。考生问的是一个**规划咨询类**问题，
请给出可执行的建议，不要让考生吃闭门羹。

{context_block}
【考生画像】
{profile_context}

【考生提问】
{question}

【回答要求】
1. 如果上面【参考资料】里确实有能回答问题的精确数据（分数线 / 位次 / 学费），**优先引用**。
2. 如果没有，请基于通识与考生画像给出**方向性、策略性**建议：地域选择、院校层次搭配、
   专业大类取舍、冲稳保结构、填报节奏。
3. 提到具体院校或专业时，只谈**公认的层次与特色**（如「省内重点」「工科见长」），
   **严禁编造**任何分数线、位次、学费、招生人数。
4. 若考生在问题里给了分数或位次，可基于该分数段做**层次判断**
   （如「这个分数段通常对应省属公办本科」），仍然不要给出精确数字。
5. 分点说明，控制在 250 字以内，语气务实、像一位有经验的老师。
"""


def build_advisory_prompt(
    question: str, profile_context: str = "", context_text: str = ""
) -> str:
    """规划咨询 Prompt（0.12.1）。

    :param context_text: 三路检索到的内容（可能为空，也可能是不相关资料）。
                         非空时放进【参考资料】，要求模型「有数据就引用、没数据靠通识」，
                         避免像 0.12.0 那样被防幻觉规则逼成拒答。
    """
    block = ""
    text = (context_text or "").strip()
    if text:
        block = f"【参考资料】（可能只部分相关，请自行判断可用性）：\n{text}\n"
    return ADVISORY_PROMPT.format(
        context_block=block,
        profile_context=profile_context or "（暂无画像，按普通考生处理）",
        question=question,
    )


def build_profile_section(profile_context: str = "") -> str:
    """把用户画像渲染成 Prompt 里的一个段落（0.12.0）。

    统一在这里拼，是为了让「三路融合」和「防幻觉生成」两条链路
    用完全相同的措辞（单一职责 + 合成复用），不会出现两套画像说法。

    :param profile_context: 画像总结文本（`user_profiles.summary_text`）
    :return: 可直接塞进 Prompt 的段落；无画像时返回空串
    """
    text = (profile_context or "").strip()
    if not text:
        return ""
    return (
        "\n【考生画像】（用于个性化建议，不得据此编造任何数字）：\n"
        f"{text}\n"
        "请在回答中结合这些特征给出建议（例如专业方向、地域与学费偏好），"
        "但分数线、学费、位次等数字仍必须以事实数据为准。\n"
    )


def build_hybrid_prompt(
    priority_hint: str,
    graph_context: str,
    mysql_context: str,
    vector_context: str,
    question: str,
    profile_context: str = "",
    history_section: str = "",
) -> str:
    """拼接三路融合 Prompt（单一职责：只负责组装，不负责检索与生成）。

    priority_hint 由调用方根据三路命中情况动态生成，见 _build_hybrid_priority_hint()。
    0.12.0：新增 `profile_context`（用户画像），为空时 Prompt 与 0.11.x 完全一致。
    0.17.1：新增 `history_section`（多轮上文），插到「用户提问」之前；
            为空串时 Prompt 与 0.17.0 逐字一致。
    """
    prompt = HYBRID_FUSION_PROMPT.format(
        priority_hint=priority_hint,
        profile_section=build_profile_section(profile_context),
        graph_context=graph_context or "（无）",
        mysql_context=mysql_context or "（无）",
        vector_context=vector_context or "（无）",
        question=question,
    )
    if history_section:
        prompt = prompt.replace("用户提问：", history_section + "用户提问：", 1)
    return prompt


def _build_hybrid_priority_hint(graph_hit: bool, mysql_hit: bool, vector_hit: bool) -> str:
    """按三路命中组合生成优先级声明（Prompt 的 Level 1 优先级在这里落地）。"""
    if graph_hit and mysql_hit:
        return "图谱事实和数据库精确值均为权威数据，冲突时以图谱为准。"
    if graph_hit and vector_hit:
        return "图谱事实为权威数据，政策文本用于补充说明。"
    if mysql_hit and vector_hit:
        return "数据库精确值为权威数据，政策文本用于补充说明。"
    if graph_hit:
        return "本次仅检索到图谱事实，请严格基于其回答，禁止编造。"
    if mysql_hit:
        return "本次仅检索到数据库精确值，请严格基于其回答，禁止编造。"
    if vector_hit:
        return "本次仅检索到政策文本，请基于其回答；找不到具体数字时明确说明，禁止编造。"
    return "三路均未检索到相关信息，请返回预设拒答话术，禁止编造。"


def answer_with_hybrid(
    question: str,
    top_k: int = 5,
    profile_context: str = "",
    history_section: str = "",
) -> Dict:
    """三路融合问答主流程：图谱 + MySQL + 向量并行检索，按优先级分发。

    流程：
      Step 1  detect_structured_intent() 判断是不是字段型问题（决定 MySQL 路是否参与）
      Step 2  ThreadPoolExecutor(max_workers=3) 三路并行
      Step 3  按 图谱 > MySQL > 向量 拼接上下文，向量按 VECTOR_MAX_TOKENS 裁剪
      Step 4  三路都空 → 直接返回拒答，不调用大模型（省一次网络往返，也防止编造）
      Step 5  build_hybrid_prompt() → ask() 生成

    :param question:        用户问题
    :param top_k:           向量通道召回条数
    :param profile_context: 0.12.0 用户画像总结，为空时行为与 0.11.x 完全一致
    :return:                见模块 docstring 的返回结构；任一路异常只跳过该路
    """
    # ---- Step 1：结构化意图识别 ----
    _t0 = time.time()
    intents = detect_structured_intent(question)

    # ---- Step 2：三路并行（任一路异常只让该路为空，不影响其他路）----
    graph_context, graph_cypher, graph_error = "", "", ""
    mysql_context, mysql_error = "", ""
    vector_text, vector_hit = "", False
    sources: List[str] = ["Neo4j 图谱"]  # 占位会在下面按命中情况重建

    def _graph_channel():
        engine = _get_graph_engine()
        return engine.query(question) if engine is not None else None

    def _mysql_channel():
        if not intents or not settings.MYSQL_QUERY_ENABLED:
            return None
        from app.services.sql.sql_query_engine import MySQLQueryEngine

        filters = rag_service_extract_sql_filters(question) or {}
        filters["intents"] = intents
        # 0.11.0：MySQL 通道改查全国总表，必须带上省份与科类，防止跨省数据污染。
        # 默认省份取项目配置（河南），科类由 MySQLQueryEngine 按省份自动推断。
        filters.setdefault("province", settings.DEFAULT_PROVINCE)
        return MySQLQueryEngine().query_structured(filters)

    def _vector_channel():
        hits = search(question, top_k) or []
        if not hits:
            return "", []
        text = "\n".join(
            f"[{(h.get('metadata') or {}).get('filename') or '知识库'}] {h.get('text', '')}"
            for h in hits
        )
        names = sorted({(h.get("metadata") or {}).get("filename") or "知识库" for h in hits})
        return text, names

    with ThreadPoolExecutor(max_workers=3) as pool:
        future_graph = pool.submit(_graph_channel)
        future_mysql = pool.submit(_mysql_channel)
        future_vector = pool.submit(_vector_channel)

        try:
            graph_out = future_graph.result()
        except Exception as exc:  # noqa: BLE001 图谱路异常 → 该路置空
            graph_out, graph_error = None, f"图谱通道异常：{exc.__class__.__name__}"
        try:
            mysql_out = future_mysql.result()
        except Exception as exc:  # noqa: BLE001 MySQL 路异常 → 该路置空
            mysql_out, mysql_error = None, f"MySQL 通道异常：{exc.__class__.__name__}"
        try:
            vector_text, vector_names = future_vector.result()
            vector_error = ""
        except Exception as exc:  # noqa: BLE001 向量路异常 → 该路置空
            vector_text, vector_names = "", []
            vector_error = f"向量通道异常：{exc.__class__.__name__}"

    graph_hit = bool(graph_out is not None and graph_out.hit)
    if graph_out is not None:
        graph_context = graph_out.context or ""
        graph_cypher = graph_out.cypher or ""
        graph_error = graph_out.error or graph_error

    mysql_hit = bool(mysql_out is not None and mysql_out.get("hit"))
    if mysql_out is not None:
        mysql_context = mysql_out.get("context") or ""
        mysql_error = mysql_out.get("error") or mysql_error

    vector_hit = bool(vector_text)
    if vector_hit:
        # Level 2 配额：向量上下文按 VECTOR_MAX_TOKENS 裁剪（图谱 / MySQL 是精确值，不裁）
        vector_text = _truncate_by_tokens(vector_text, settings.VECTOR_MAX_TOKENS)

    # ---- Step 3：按优先级拼接（图谱 > MySQL > 向量）----
    contexts: List[str] = []
    if graph_hit:
        contexts.append("【图谱事实】（权威精确数据）：\n" + graph_context)
    if mysql_hit:
        contexts.append("【数据库精确值】（权威精确数据）：\n" + mysql_context)
    if vector_hit:
        contexts.append("【政策/介绍文本】（用于补充说明，不作为数字依据）：\n" + vector_text)

    # ---- 来源去重（图谱 / MySQL / 文件名）----
    sources = []
    if graph_hit:
        sources.append("Neo4j 图谱")
    if mysql_hit:
        sources.append("MySQL 招生数据")
    sources.extend(vector_names if vector_hit else [])

    # ---- Step 4：规划咨询类问题单独分流（0.12.1 核心修复）----
    #
    # 为什么不能只处理「三路全空」：
    # 实测「我高考502分，根据我的画像，我该去哪」时，向量通道会命中知识库里
    # **无关**的文档（MBTI 报告、各省专升本录取率…），于是 contexts 非空、
    # 走正常融合路径，最终被 ANTI_HALLUCINATION_PROMPT 的「上下文没有就拒答」
    # 规则逼成「根据现有资料未查询到」——这正是用户反馈的现象。
    #
    # 所以只要命中主观咨询意图，**无论有没有检索到内容**都走规划师 Prompt：
    # 有资料就把资料作为【参考资料】让其优先引用，没资料就基于画像 + 通识给建议。
    if _has_subjective_intent(question):
        from app.services.llm.ai_service import ask

        context_text = "\n\n".join(contexts) if contexts else ""
        advisory = ask(
            build_advisory_prompt(question, profile_context, context_text),
            temperature=0.3,
            top_p=0.85,
            num_predict=600,
            timeout=60,
        )
        if advisory:
            logger.info(
                "[HYBRID] 命中主观咨询意图 → 规划师模式（有资料=%s，query=%s）",
                bool(context_text), question,
            )
            return {
                "answer": advisory,
                "source": "hybrid:advisory" if not context_text else "hybrid:advisory_with_context",
                "sources": sources,
                "graph_hit": graph_hit,
                "mysql_hit": mysql_hit,
                "vector_hit": vector_hit,
                "fusion_strategy": FUSION_STRATEGY,
                "graph_cypher": graph_cypher,
                "graph_error": graph_error,
                "mysql_error": mysql_error,
                "vector_error": vector_error,
                "profile_injected": bool(profile_context),
            }
        logger.info("[HYBRID] 规划师模式生成失败，落回常规链路")

    # ---- Step 5：三路都空 → 拒答（客观问题才走这里）----
    if not contexts:
        return {
            "answer": "根据现有资料未查询到具体信息，建议查阅学校官方招生简章。",
            "source": "hybrid_empty",
            "sources": [],
            "graph_hit": False,
            "mysql_hit": False,
            "vector_hit": False,
            "fusion_strategy": FUSION_STRATEGY,
            "graph_cypher": "",
            "graph_error": graph_error,
            "mysql_error": mysql_error,
            "vector_error": vector_error,
            "profile_injected": bool(profile_context),
        }

    # ---- Step 5：组装 Prompt 并生成 ----
    priority_hint = _build_hybrid_priority_hint(graph_hit, mysql_hit, vector_hit)
    prompt = build_hybrid_prompt(
        priority_hint=priority_hint,
        graph_context=graph_context if graph_hit else "",
        mysql_context=mysql_context if mysql_hit else "",
        vector_context=vector_text if vector_hit else "",
        question=question,
        profile_context=profile_context,
        history_section=history_section,   # 0.17.1：多轮上文（仅消解指代）
    )

    from app.services.llm.ai_service import ask

    answer = ask(prompt, temperature=0.1, top_p=0.3, num_predict=500, timeout=60)
    if not answer:
        raise RuntimeError("大模型响应超时")

    logger.info(
        "[HYBRID] 三路融合完成 strategy=%s graph_hit=%s mysql_hit=%s vector_hit=%s intents=%s profile=%s 耗时=%.2fs",
        FUSION_STRATEGY, graph_hit, mysql_hit, vector_hit, intents,
        bool(profile_context), time.time() - _t0,
    )
    return {
        "answer": answer,
        "source": f"hybrid:{FUSION_STRATEGY}",
        "sources": sources,
        "graph_hit": graph_hit,
        "mysql_hit": mysql_hit,
        "vector_hit": vector_hit,
        "fusion_strategy": FUSION_STRATEGY,
        "graph_cypher": graph_cypher,
        "graph_error": graph_error,
        "mysql_error": mysql_error,
        "vector_error": vector_error,
        "profile_injected": bool(profile_context),
    }


def rag_service_extract_sql_filters(question: str) -> Optional[Dict]:
    """0.4.0 预留函数的薄封装：提取 MySQL 查询条件（school_name / major_name / year）。

    单独包一层是为了让 answer_with_hybrid() 里的 _mysql_channel 闭包
    不直接依赖模块级函数名，便于测试时替换（依赖倒置）。
    """
    return extract_sql_filters(question)


def answer_with_graph(question: str, top_k: int = 5) -> dict:
    """0.9.0 兼容别名：内部转发到 answer_with_hybrid（三路融合）。

    保留是为了不让 0.9.0 的调用方（测试脚本、外部脚本）报 AttributeError；
    新代码请直接调用 answer_with_hybrid()。
    """
    return answer_with_hybrid(question, top_k)


# ============================================================
# 0.10.0 多模态「以文搜图」
# ============================================================
#
# ## 设计边界
# 本次只做**以文搜图**：文字问题 → 检索图片 → 视觉模型解读成文字回答。
# 不做以图搜文，也不做图文混合融合（那是 0.11.0 的候选方向）。
#
# ## 为什么用关键词触发而不是所有问题都试
# 图像检索要额外跑一次编码 + 一次 Chroma 查询，给每个问题都做一遍是纯浪费。
# 只有问题里出现「图 / 照片 / 课程表 / 培养方案 / 校园 / 长什么样」这类词，
# 才说明用户想看图，此时才走图像通道；否则直接走 0.9.1 的三路融合。
#
# ## 合成复用
# 具体能力全部在 services/multimodal/ 里，这里只做「判断要不要用」与「转发」，
# 不重复实现编码、存储、检索（迪米特法则 + 单一职责）。
_multimodal_retriever = None


def _get_multimodal_retriever():
    """懒加载图像检索器（进程内复用）；不可用时返回 None。"""
    global _multimodal_retriever
    if _multimodal_retriever is not None:
        return _multimodal_retriever or None
    try:
        from app.services.multimodal import ImageRetriever

        _multimodal_retriever = ImageRetriever()
    except Exception as exc:  # noqa: BLE001 多模态模块整体不可用 → 回落到三路融合
        logger.info("[MM] 图像检索器初始化失败，回落到三路融合：%s", exc.__class__.__name__)
        _multimodal_retriever = False
    return _multimodal_retriever or None


def should_use_multimodal(question: str) -> bool:
    """是否应该走图像检索通道（委托给 ImageRetriever.should_trigger）。

    多模态总开关关闭、模块不可用、或问题没命中关键词时都返回 False。
    """
    if not settings.MULTIMODAL_ENABLED:
        return False
    retriever = _get_multimodal_retriever()
    if retriever is None:
        return False
    try:
        return retriever.should_trigger(question)
    except Exception:  # noqa: BLE001 判断失败按不走多模态处理
        return False


def answer_with_multimodal(question: str, top_k: int = 3) -> Optional[Dict]:
    """多模态问答：以文搜图 + 视觉模型解读。

    流程：Chinese-CLIP（或图注向量）编码问题 → 查 Chroma gaokao_images
          → 命中图片交给 qwen3.7-flash 解读 → 生成文字回答。

    :return: {"answer", "source": "multimodal:image", "images": [...], "image_hit": bool}
             未命中图片 / 模块不可用 / VLM 失败时返回 None，
             由 routers/ai.py 回落到 0.9.1 的三路融合（保证问答不中断）。
    """
    retriever = _get_multimodal_retriever()
    if retriever is None:
        return None
    try:
        result = retriever.answer(question, top_k=top_k)
    except Exception as exc:  # noqa: BLE001 多模态链路异常 → 回落三路融合
        logger.info("[MM] 多模态问答异常，回落三路融合：%s", exc.__class__.__name__)
        return None

    if not result or not result.get("image_hit"):
        return None

    logger.info(
        "[MM] 以文搜图命中 %d 张：%s",
        len(result.get("images") or []), question[:40],
    )
    return {
        "answer": result["answer"],
        "source": "multimodal:image",
        "sources": [
            f"{(im.get('filename') or '图片')}#P{im.get('page') or '?'}"
            for im in (result.get("images") or [])
        ],
        "image_hit": True,
        "images": result.get("images") or [],
    }
