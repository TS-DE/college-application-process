"""RAG 服务：Chroma 向量库 + Ollama embedding + 递归分块 + 混合检索。

设计要点：
- 所有向量库操作都封装在本文件，将来换 Milvus 只需替换这几个函数
- 分块：RecursiveCharacterTextSplitter（递归分块），失败时退化为定长切分
- 检索：稠密（Chroma 向量）+ 稀疏（BM25 关键词）→ RRF 融合（k=60）
- 默认调用本地 Ollama embedding（离线可用），可通过 DASHSCOPE_API_KEY 切到千问 text-embedding-v3
- 若 Ollama / Chroma 不可用，退化为「关键词打分」的本地检索，保证链路不中断
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

import requests

from app.config import settings

# RRF 融合常数：k=60（消除前几名排名的剧烈波动，见 HybridRetrieval.rrf 注释）
RRF_K = 60

# ---------------- 父子块（Parent-Child Chunking）参数 ----------------
# 父块：递归分块得到的 500 字块（语义完整、适合喂给 LLM 当上下文）
# 子块：父块内部再切一次的 120 字小块（语义聚焦、适合做向量检索）
CHILD_CHUNK_SIZE = 120      # 子块大小
CHILD_CHUNK_OVERLAP = 20    # 子块重叠
# docstore 文件：父块原文按 parent_id 存这里，向量库只存子块（见 put_parents 注释）
PARENT_STORE_FILE = "parent_store.json"

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


def split_child_text(text: str, size: int | None = None, overlap: int | None = None) -> List[str]:
    """把「父块」再切成「子块」（默认 120 字、重叠 20 字）。

    子块只用于向量检索：块越小语义越聚焦，"婚假几天"这类短查询越容易命中；
    但子块太短不适合直接喂给 LLM（上下文不完整），所以命中的子块会再回填父块。
    切分逻辑与父块一致（递归分块），依赖缺失时退化为定长切分。
    """
    size = size or CHILD_CHUNK_SIZE
    overlap = overlap or CHILD_CHUNK_OVERLAP
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:
        return _split_text_fixed(text, size, overlap)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        length_function=len,
        is_separator_regex=False,
        separators=SEPARATORS,
    )
    return [c for c in splitter.split_text(text) if c.strip()]


# ---------------- docstore：父块原文存储 ----------------

_parent_store: Dict[str, Dict] = {}      # {parent_id: {"text":..., "file_id":...}}
_parent_store_loaded = False


def _parent_store_path() -> str:
    """docstore 落盘位置（与 Chroma 同目录，已在 .gitignore 中）。"""
    os.makedirs(settings.CHROMA_DB_PATH, exist_ok=True)
    return os.path.join(settings.CHROMA_DB_PATH, PARENT_STORE_FILE)


def _load_parent_store() -> Dict[str, Dict]:
    """首次访问时把父块原文从磁盘载入内存（幂等）。"""
    global _parent_store, _parent_store_loaded
    if _parent_store_loaded:
        return _parent_store
    try:
        path = _parent_store_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _parent_store = json.load(f)
    except Exception:  # noqa: BLE001  docstore 损坏不阻塞检索，按空库继续
        _parent_store = {}
    _parent_store_loaded = True
    return _parent_store


def _save_parent_store() -> None:
    """把父块原文持久化（每次写入/删除后调用）。"""
    try:
        with open(_parent_store_path(), "w", encoding="utf-8") as f:
            json.dump(_parent_store, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def put_parents(parents: List[Dict]) -> None:
    """批量写入父块到 docstore。

    docstore 的作用：向量库只索引 120 字的子块（检索精度高），
    父块的 500 字原文存在这里（不进向量库），检索命中子块后按 parent_id 取回，
    把完整上下文交给 LLM —— 即「小块命中、大块生成」。
    """
    store = _load_parent_store()
    for p in parents:
        store[p["parent_id"]] = p
    _save_parent_store()


def get_parent(parent_id: Optional[str]) -> Optional[Dict]:
    """按 parent_id 取回父块原文；不存在返回 None（调用方需降级返回子块）。"""
    if not parent_id:
        return None
    return _load_parent_store().get(parent_id)


def drop_parents_by_file(file_id: int) -> int:
    """删除某个文件的全部父块（与向量库删除子块配套）。"""
    store = _load_parent_store()
    keys = [k for k, v in store.items() if str(v.get("file_id")) == str(file_id)]
    for k in keys:
        store.pop(k, None)
    if keys:
        _save_parent_store()
    return len(keys)


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
    """子块命中 → 回填父块（"小块命中、大块生成"）。

    - 命中子块的 metadata 里有 parent_chunk_id，据此从 docstore 取回父块原文
    - 取回成功：把 text 换成父块（上下文更完整），并标记 context_level="parent"
    - **降级**：父块缺失 / 取回异常时，直接返回子块，标记 context_level="child"，链路不中断
    - 多个子块指向同一父块时按父块去重，保留得分最高的那个
    """
    expanded: List[Dict] = []
    seen_parents: set = set()

    for h in hits:
        meta = h.get("metadata") or {}
        parent_id = meta.get("parent_chunk_id")
        parent = get_parent(parent_id)

        if parent and parent.get("text"):
            if parent_id in seen_parents:
                continue  # 同一父块的多个子块只保留一次
            seen_parents.add(parent_id)
            expanded.append({
                **h,
                "text": parent["text"],           # 用父块原文替换子块，交给 LLM
                "metadata": {**meta, "chunk_index": meta.get("chunk_index")},
                "parent_chunk_id": parent_id,
                "context_level": "parent",
            })
        else:
            # 降级：docstore 没有该父块（旧数据 / 文件被清），直接返回子块
            expanded.append({
                **h,
                "parent_chunk_id": parent_id,
                "context_level": "child",
            })

    return expanded


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
    """语义 + 关键词混合检索（RRF 融合）；命中子块后回填父块。"""
    col = _get_collection()
    if col is None:
        return _keyword_fallback(query, top_k)

    try:
        retriever = HybridRetrieval(col, k=RRF_K, top_k=top_k)
        results = retriever.search(query, top_k)
    except Exception:  # noqa: BLE001 混合检索异常时退回纯向量 / 关键词
        results = []

    if results:
        # 子块命中 → 回填父块作为上下文（父块缺失时自动降级为子块）
        return _expand_to_parents(results)
    # 兜底：Chroma 有数据但两路都没命中，用老的关键词打分
    return _expand_to_parents(_keyword_fallback(query, top_k))


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


# ---------------- v2.3.0：Query 路由 + 防幻觉 Prompt ----------------

# 1) 路由拦截提示词：在 RAG 检索之前单独调用一次 LLM 做二分类
#    参数：temperature=0.0（要确定性），max_tokens=5（只要 YES / NO）
#    v2.3.1 修正：v2.3.0 的关键词列表太窄，跨省招生计划（"2025河南在福建招生的院校"）
#    这类长尾高考问题会被误判为 NO；这里改成「满足任意一条即为 YES」的宽松口径。
ROUTER_PROMPT = """你是一个高考志愿填报系统的意图分类器。
你的任务是判断用户的问题是否与【高考、志愿填报、院校、专业、招生、录取、分数线、学费、位次、选科、批次】相关。

【判断规则】（满足任意一条即为 YES）：
1. 问题中包含任何高考相关词汇（如：高考、志愿、院校、大学、专业、招生、录取、分数线、学费、位次、选科、批次、投档、调剂）。
2. 问题询问某所学校或某个专业的情况（如：XX大学怎么样、XX专业学什么、XX学校学费多少）。
3. 问题询问某省/某年的招生政策或招生计划（如：河南2025年招生计划、福建在河南招多少人）。

【严格规则】：
1. 如果问题与上述完全无关（例如：婚假、天气、编程、闲聊、历史事件），只输出：NO
2. 如果问题与上述相关，只输出：YES
3. 不要输出任何解释、标点符号或其他文字！只输出 YES 或 NO！

【用户问题】：
{query}

【输出】："""

# 2) 防幻觉提示词：RAG 检索之后，把父块 Context 与 Query 一起交给 LLM
#    参数：temperature=0.1，top_p=0.3
#    v2.3.1 修正：v2.3.0 用「绝对铁律 + top_p=0.1」过于保守，父块里明明有 23000 元/年，
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

# 命中这些关键词时，优先考虑走 MySQL 结构化查询而不是 RAG（v2.3.0 预留）
STRUCTURED_KEYWORDS = ("学费", "分数线", "位次", "录取分", "招生人数", "计划数")

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
    """
    from app.services.ai_service import ai_enabled, ask

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
        return True  # LLM 不可用 → 放行，交回主流程兜底
    return "YES" in intent.upper()


def generate_answer(
    query: str,
    context: str,
    temperature: float = 0.1,
    top_p: float = 0.3,
) -> Optional[str]:
    """防幻觉生成：优先依据检索到的父块上下文回答，上下文中完全没有才拒答。

    - 参数默认：**temperature=0.1**，**top_p=0.3**
      （v2.3.0 用的 top_p=0.1 过于保守，会导致上下文明明有数字时模型也放弃生成）
    - 返回 None 表示生成失败，由调用方降级（回退原 chat 逻辑或提示稍后重试）
    """
    from app.services.ai_service import ask

    prompt = ANTI_HALLUCINATION_PROMPT.format(context=context, question=query)
    return ask(
        prompt,
        temperature=temperature,   # 低温度：减少自由发挥
        top_p=top_p,               # 适度收窄：抑制编造，但不至于不敢生成
        num_predict=400,
    )


def extract_sql_filters(query: str) -> Optional[Dict]:
    """结构化条件提取（v2.3.0 预留，配合 Text-to-SQL 走 MySQL）。

    - 参数：temperature=0.0
    - 命中「学费/分数线/位次」等强结构化关键词时优先走 MySQL 精确查询，
      避免 RAG 召回不到导致编造；当前仅返回解析结果，实际 SQL 查询留给后续版本接入。
    """
    from app.services.ai_service import ai_enabled, ask

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
