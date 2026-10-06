"""RAG 服务：Chroma 向量库 + Ollama embedding + 递归分块 + 混合检索。

设计要点：
- 所有向量库操作都封装在本文件，将来换 Milvus 只需替换这几个函数
- 分块：RecursiveCharacterTextSplitter（递归分块），失败时退化为定长切分
- 检索：稠密（Chroma 向量）+ 稀疏（BM25 关键词）→ RRF 融合（k=60）
- 默认调用本地 Ollama embedding（离线可用），可通过 DASHSCOPE_API_KEY 切到千问 text-embedding-v3
- 若 Ollama / Chroma 不可用，退化为「关键词打分」的本地检索，保证链路不中断
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

import requests

from app.config import settings

# RRF 融合常数：k=60（消除前几名排名的剧烈波动，见 HybridRetrieval.rrf 注释）
RRF_K = 60

# ---------------- Chroma 客户端（延迟初始化，避免导入即失败） ----------------

_client = None
_collection = None
_chroma_error: Optional[str] = None


def _get_collection():
    """获取（或创建）持久化集合。"""
    global _client, _collection, _chroma_error
    if _collection is not None:
        return _collection
    try:
        import chromadb

        os.makedirs(settings.CHROMA_DB_PATH, exist_ok=True)
        _client = chromadb.PersistentClient(path=settings.CHROMA_DB_PATH)
        _collection = _client.get_or_create_collection(name=settings.CHROMA_COLLECTION)
        return _collection
    except Exception as exc:  # noqa: BLE001
        _chroma_error = str(exc)
        return None


def collection():
    """供路由层直接操作（如按 file_id 删除向量）。"""
    return _get_collection()


def backend_info() -> dict:
    col = _get_collection()
    return {
        "vector_store": "chroma",
        "persist_path": settings.CHROMA_DB_PATH,
        "collection": settings.CHROMA_COLLECTION,
        "embedding_model": settings.OLLAMA_EMBED_MODEL,
        "embedding_provider": "dashscope" if settings.DASHSCOPE_API_KEY else "ollama",
        "ready": col is not None,
        "error": _chroma_error,
        "count": (col.count() if col else 0),
    }


# ---------------- Embedding ----------------

def get_embedding(text: str) -> Optional[List[float]]:
    """获取文本向量：优先 DashScope，其次 Ollama，都失败返回 None。"""
    if settings.DASHSCOPE_API_KEY:
        vec = _dashscope_embedding(text)
        if vec:
            return vec
    return _ollama_embedding(text)


def _ollama_embedding(text: str) -> Optional[List[float]]:
    try:
        resp = requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/embeddings",
            json={"model": settings.OLLAMA_EMBED_MODEL, "prompt": text},
            timeout=settings.OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("embedding")
    except Exception:  # noqa: BLE001
        return None


def _dashscope_embedding(text: str) -> Optional[List[float]]:
    """千问官方 text-embedding-v3（需 DASHSCOPE_API_KEY）。"""
    try:
        resp = requests.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
            headers={
                "Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": settings.DASHSCOPE_EMBED_MODEL, "input": text},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception:  # noqa: BLE001
        return None


# ---------------- 分块：递归分块（Recursive Splitting） ----------------

# 递归分块的分隔符优先级：从"最粗粒度"到"最细粒度"依次尝试
#   1. "\n\n" 段落：政策文件里一个段落通常是一整条规则，优先按段落切开
#   2. "\n"   换行：段落仍超长时，退到按行切（PDF 抽取常以换行分条目）
#   3. "。"   句号：行还超长，按句切，保证语义完整
#   4. "，"   逗号：最后兜底才在逗号处断开（尽量不破坏句子）
# 注意：RecursiveCharacterTextSplitter 会"递归"地用下一个分隔符继续切超长的块，
#       直到每块 <= chunk_size，因此不会像定长切分那样把句子从中间切断。
SEPARATORS = ["\n\n", "\n", "。", "，"]


def split_text(text: str, size: int | None = None, overlap: int | None = None) -> List[str]:
    """递归分块：优先按段落 / 换行 / 句号切，保证语义完整。

    参数含义：
      - size（chunk_size=500）：每块最多 500 字，太小会丢失上下文，太大则检索粒度变粗、噪声变多
      - overlap（chunk_overlap=50）：相邻块重叠 50 字，避免一条规则被切断后两边都检索不到

    langchain_text_splitters 未安装时自动退化为定长切分（行为同改造前），链路不中断。
    """
    size = size or settings.CHUNK_SIZE          # 默认 500
    overlap = overlap or settings.CHUNK_OVERLAP  # 默认 50
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:  # 未安装依赖时的兜底
        return _split_text_fixed(text, size, overlap)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,          # 单块最大字符数
        chunk_overlap=overlap,    # 相邻块重叠字符数
        length_function=len,      # 中文按字符计数（不用 token 计数）
        is_separator_regex=False, # 分隔符是普通字符串
        separators=SEPARATORS,    # 分隔符优先级：段落 → 换行 → 句号 → 逗号
    )
    return [c for c in splitter.split_text(text) if c.strip()]


def _split_text_fixed(text: str, size: int, overlap: int) -> List[str]:
    """兜底：定长滑动窗口切分（递归分块不可用时使用）。"""
    step = max(1, size - overlap)
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + size])
        start += step
    return chunks


# ---------------- 写入 / 删除 / 检索 ----------------

def add_document(doc_id: str, text: str, metadata: dict, embedding: Optional[List[float]] = None) -> bool:
    """写入单个切片；embedding 为 None 时内部再计算一次。"""
    col = _get_collection()
    if col is None or not text:
        return False
    vec = embedding if embedding is not None else get_embedding(text)
    if vec is None:
        return False
    col.add(ids=[doc_id], embeddings=[vec], documents=[text], metadatas=[metadata])
    return True


def add_documents(chunks: List[str], metadata: dict, key_fmt: str = "{idx}") -> int:
    """批量写入切片，返回成功写入数量。"""
    ok = 0
    for idx, chunk in enumerate(chunks):
        doc_id = key_fmt.format(idx=idx)
        if add_document(doc_id, chunk, {**metadata, "chunk_index": idx}):
            ok += 1
    return ok


def delete_by_file(file_id: int) -> bool:
    """删除某个文件在向量库中的全部切片。"""
    col = _get_collection()
    if col is None:
        return False
    try:
        col.delete(where={"file_id": file_id})
        return True
    except Exception:  # noqa: BLE001
        return False


class HybridRetrieval:
    """混合检索器：稠密向量（Chroma）+ 稀疏关键词（BM25）→ RRF 融合。

    对应《混合检索》文档「代码三：封装成类」的结构：
        dense_search()  ≈ bgeChou()   稠密路召回（本项目用 Chroma 自带 ANN 检索）
        bm25_search()   ≈ bm25Xi()    稀疏路召回（rank_bm25 + jieba 中文分词）
        rrf()           ≈ rrf()       倒数排名融合
        search()        ≈ get_rrf()   对外统一入口
    """

    def __init__(self, collection, k: int = 60, top_k: int = 5, candidate_n: int = 20):
        self.collection = collection
        self.k = k                    # RRF 常数，固定 60
        self.top_k = top_k            # 最终返回条数
        self.candidate_n = candidate_n  # 每一路各自召回的候选数量
        self._corpus: Optional[list] = None      # [(chunk_id, text, metadata)]
        self._bm25 = None                        # BM25Okapi 索引（按语料缓存）
        self._corpus_count = -1                  # 语料快照对应的 collection.count()

    # ========== 1. 语料 & BM25 索引 ==========

    def _load_corpus(self) -> list:
        """从 Chroma 取出全部文本构建 BM25 语料（按 count 变化做失效判断）。

        说明：BM25 需要"分词后的文本序列"，必须拿到原文；
        当前知识库规模（千级 chunk）全量取回可接受，
        若后续到十万级可改为「BM25 索引持久化 + 增量更新」。
        """
        count = self.collection.count()
        if self._corpus is not None and count == self._corpus_count:
            return self._corpus

        data = self.collection.get(include=["documents", "metadatas"])
        ids = data.get("ids") or []
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        self._corpus = [
            {"id": i, "text": d or "", "metadata": m or {}}
            for i, d, m in zip(ids, docs, metas)
        ]
        self._corpus_count = count
        self._bm25 = self._build_bm25([c["text"] for c in self._corpus])
        return self._corpus

    @staticmethod
    def _build_bm25(documents: List[str]):
        """构建 BM25Okapi 稀疏索引（中文用 jieba 分词）。"""
        try:
            from rank_bm25 import BM25Okapi
            import jieba

            tokenized = [list(jieba.cut(doc)) for doc in documents]
            return BM25Okapi(tokenized) if tokenized else None
        except Exception:  # noqa: BLE001  bm25 / jieba 缺失时关闭稀疏路
            return None

    # ========== 2. 稠密向量检索（Chroma 自带 ANN） ==========

    def dense_search(self, query: str) -> List[Dict]:
        """稠密路：Chroma 向量检索，返回 [{index, distance}]（按相似度降序）。"""
        vec = get_embedding(query)
        if vec is None:
            return []
        try:
            res = self.collection.query(
                query_embeddings=[vec],
                n_results=min(self.candidate_n, max(1, self.collection.count())),
                include=["documents", "metadatas", "distances"],
            )
        except Exception:  # noqa: BLE001
            return []

        corpus = self._load_corpus()
        id_to_idx = {c["id"]: i for i, c in enumerate(corpus)}
        hits = []
        for cid, dist in zip((res.get("ids") or [[]])[0], (res.get("distances") or [[]])[0]):
            if cid in id_to_idx:
                hits.append({"index": id_to_idx[cid], "distance": dist})
        return hits  # Chroma 已按距离升序返回，即相似度降序

    # ========== 3. 稀疏关键词检索（BM25） ==========

    def bm25_search(self, query: str) -> List[Dict]:
        """稀疏路：BM25 关键词检索，返回 [{index, score}]（按得分降序）。"""
        corpus = self._load_corpus()
        if not corpus or self._bm25 is None:
            return []
        try:
            import jieba

            scores = self._bm25.get_scores(list(jieba.cut(query)))
        except Exception:  # noqa: BLE001
            return []

        ranked = sorted(range(len(corpus)), key=lambda i: scores[i], reverse=True)
        hits = [
            {"index": i, "score": float(scores[i])}
            for i in ranked[: self.candidate_n]
            if scores[i] > 0
        ]
        if hits:
            return hits

        # 小语料兜底：rank_bm25 的 IDF 公式为 log((N-df+0.5)/(df+0.5))，
        # 语料很小时 N≈df，IDF 会变成 0 甚至负数，导致所有分数 <= 0。
        # 这时退化为「查询词命中计数」的稀疏打分，保证稀疏路仍然有效。
        return self._token_overlap_search(query, corpus)

    @staticmethod
    def _token_overlap_search(query: str, corpus: list) -> List[Dict]:
        """稀疏路兜底：按「查询词在文档中出现的次数」打分（BM25 分数全 ≤ 0 时使用）。"""
        try:
            import jieba

            tokens = [t for t in jieba.cut(query) if len(t) >= 2]
        except Exception:  # noqa: BLE001
            tokens = [query]
        tokens = tokens or [query]

        scored = []
        for i, c in enumerate(corpus):
            score = sum(c["text"].count(t) for t in tokens)
            if score:
                scored.append({"index": i, "score": float(score)})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    # ========== 4. RRF 融合 ==========

    def rrf(self, dense_ranking: List[Dict], bm25_ranking: List[Dict]):
        """倒数排名融合（Reciprocal Rank Fusion）。

        公式：score(doc) = Σ 1 / (k + rank_i)
          - k = 60：常数，用来"压平"前几名的分数差。
            没有 k 时 rank=1 得 1.0、rank=2 得 0.5，第一名权重过大；
            加了 60 之后 rank=1 → 1/61、rank=2 → 1/62，差距被平滑，
            让"两路都还行"的文档能压过"一路第一、另一路垫底"的文档。
          - rank_i：该文档在第 i 路检索结果里的名次（从 1 开始）
          - 用排名而不是分数：稠密距离与 BM25 得分量纲不同，无法直接加权平均，
            换成排名后无需归一化即可融合。

        示例（文档 A：稠密第 2、BM25 第 5）：
            score = 1/(60+2) + 1/(60+5) = 0.01613 + 0.01538 = 0.03151
        示例（文档 B：稠密第 1、BM25 第 20）：
            score = 1/(60+1) + 1/(60+20) = 0.01639 + 0.01250 = 0.02889
        → A > B：单路第一但另一路很差的 B 会被拉低。
        """
        # 第 1 步：把两路结果转成 {文档下标: 名次}（名次从 1 开始）
        dense_ranks = {h["index"]: rank for rank, h in enumerate(dense_ranking, start=1)}
        bm25_ranks = {h["index"]: rank for rank, h in enumerate(bm25_ranking, start=1)}

        # 第 2 步：候选池 = 两路召回的并集（去重）
        candidate_ids = list(dict.fromkeys([h["index"] for h in dense_ranking] + [h["index"] for h in bm25_ranking]))

        # 第 3 步：逐文档累加 1/(k+rank)
        rrf_scores: Dict[int, float] = {}
        for idx in candidate_ids:
            score = 0.0
            if idx in dense_ranks:
                score += 1.0 / (self.k + dense_ranks[idx])   # 稠密路贡献
            if idx in bm25_ranks:
                score += 1.0 / (self.k + bm25_ranks[idx])    # 稀疏路贡献
            rrf_scores[idx] = score

        # 第 4 步：按 RRF 分数降序，得到最终排名
        final_ranking = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        return final_ranking, dense_ranks, bm25_ranks

    # ========== 5. 对外入口 ==========

    def search(self, query: str, top_k: int | None = None) -> List[Dict]:
        """混合检索主流程：两路召回 → RRF 融合 → Top-K。"""
        top_k = top_k or self.top_k
        corpus = self._load_corpus()
        if not corpus:
            return []

        dense_hits = self.dense_search(query)
        bm25_hits = self.bm25_search(query)

        # 单路失效时自动退化：只有稠密 → 纯向量检索；只有 BM25 → 关键词检索
        if not dense_hits and not bm25_hits:
            return []
        if not bm25_hits:
            return [self._to_hit(corpus, h["index"], h.get("distance"), dense_rank=i + 1)
                    for i, h in enumerate(dense_hits[:top_k])]
        if not dense_hits:
            return [self._to_hit(corpus, h["index"], None, bm25_rank=i + 1)
                    for i, h in enumerate(bm25_hits[:top_k])]

        final_ranking, dense_ranks, bm25_ranks = self.rrf(dense_hits, bm25_hits)

        dist_map = {h["index"]: h.get("distance") for h in dense_hits}
        return [
            self._to_hit(
                corpus,
                idx,
                dist_map.get(idx),
                rrf_score=score,
                dense_rank=dense_ranks.get(idx),
                bm25_rank=bm25_ranks.get(idx),
            )
            for idx, score in final_ranking[:top_k]
        ]

    @staticmethod
    def _to_hit(corpus: list, index: int, distance, rrf_score=None, dense_rank=None, bm25_rank=None) -> Dict:
        c = corpus[index]
        return {
            "text": c["text"],
            "metadata": c["metadata"],
            "distance": distance,
            # 便于排查与对比（纯向量检索时后三项为 None）
            "rrf_score": rrf_score,
            "dense_rank": dense_rank,
            "bm25_rank": bm25_rank,
        }


def search(query: str, top_k: int = 5) -> List[Dict]:
    """语义 + 关键词混合检索（RRF 融合）；任一组件不可用时自动降级。"""
    col = _get_collection()
    if col is None:
        return _keyword_fallback(query, top_k)

    try:
        retriever = HybridRetrieval(col, k=RRF_K, top_k=top_k)
        results = retriever.search(query, top_k)
    except Exception:  # noqa: BLE001 混合检索异常时退回纯向量 / 关键词
        results = []

    if results:
        return results
    # 兜底：Chroma 有数据但两路都没命中，用老的关键词打分
    return _keyword_fallback(query, top_k)


def _keyword_fallback(query: str, top_k: int) -> List[Dict]:
    """无向量能力时的兜底：对库内文档做关键词打分。"""
    col = _get_collection()
    if col is None:
        return []
    try:
        data = col.get(include=["documents", "metadatas"])
    except Exception:  # noqa: BLE001
        return []
    docs = data.get("documents") or []
    metas = data.get("metadatas") or []
    keys = [k for k in re.split(r"[\s，。？！、,.;!?]+", query) if len(k) >= 2]
    scored = []
    for doc, meta in zip(docs, metas):
        score = sum(doc.count(k) for k in keys)
        if score:
            scored.append({"text": doc, "metadata": meta or {}, "distance": float(-score)})
    scored.sort(key=lambda x: x["distance"])
    return scored[:top_k]
