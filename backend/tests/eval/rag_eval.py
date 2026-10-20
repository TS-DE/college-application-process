# -*- coding: utf-8 -*-
"""RAG 量化评估脚本（轻量自研版，不依赖 ragas / chromadb / langchain）

设计目标（对应《企业级 RAG 落地优化与量化评估实战》第二章～第八章）：
    1. 检索质量：Context Precision / Context Recall / Hit Rate / MRR / NDCG@k
    2. 生成质量：Faithfulness（规则版，数字+实体核验）/ Answer Relevance
    3. 端到端：语义相似度（Embedding 余弦）
    4. 输出量化报告 + 按阈值自动生成优化建议（报告生成器）

为什么不用官方 ragas：
    - 本机 chromadb 安装损坏（site-packages/chromadb 只剩一个空 proto 目录），无法 import 项目 rag_service
    - 官方 ragas 需要 langchain + sentence-transformers，依赖极重
    - 老师课上也给了「本地实现检索指标 + BGE 端到端评估」的做法，本脚本遵循同一思路

依赖（本机已具备，无需安装）：
    requests, numpy
    Python 3.12（E:\\Anaconda_download\\envs\\py312_env\\python.exe）

用法：
    python rag_eval.py                      # 完整评估
    python rag_eval.py --no-llm             # 跳过需要大模型的指标（省时间/省额度）
    python rag_eval.py --no-generate        # 不做答案生成，只评检索
    python rag_eval.py --top-k 5            # 改检索条数
    python rag_eval.py --limit 10           # 只跑前 10 条（调试用）
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import sqlite3
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import requests

# ====================== 路径与默认配置 ======================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))      # .../backend
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)                    # 项目根目录
CHROMA_SQLITE = os.path.join(PROJECT_ROOT, 'backend', 'chroma_db', 'chroma.sqlite3')
ENV_FILE = os.path.join(PROJECT_ROOT, 'backend', '.env')
DATASET_FILE = os.path.join(PROJECT_ROOT, 'rag_eval_dataset.json')
OUT_DIR = os.path.join(PROJECT_ROOT, 'rag_eval_out')

# Embedding 缓存（避免重复调用 API）
# 注意：不能放到 _assistant_docs/ —— 该目录对子进程只读，脚本写入会 PermissionError
CACHE_FILE = os.path.join(PROJECT_ROOT, 'rag_eval_embedding_cache.json')

# 集合实际维度：chroma_db 里 collections 表记录的 768
COLLECTION_DIM = 768
# 命中判定阈值：检索 chunk 与参考答案任意句余弦相似度 ≥ 该值算命中（老师文档用例 0.65）
HIT_THRESHOLD = 0.65

# 报告评级阈值（老师文档：≥0.85 优秀 / ≥0.75 良好 / ≥0.65 合格 / <0.65 需优化）
GRADE_LEVELS = [(0.85, '优秀'), (0.75, '良好'), (0.65, '合格'), (0.0, '需优化')]

# 告警阈值（老师文档「生产核心监控告警清单」）
ALERT_RULES = [
    ('hit_rate', 0.70, '检索质量', '更新知识库索引、优化检索策略'),
    ('context_recall', 0.70, '检索质量', '启用混合检索、查询扩展、增加召回数量'),
    ('context_precision', 0.60, '检索质量', '优化切片策略、调高重排序权重、精简 top_k'),
    ('mrr', 0.50, '检索质量', '接入 cross-encoder 重排序模型'),
    ('faithfulness', 0.75, '生成质量', '优化提示词、降低模型随机性、添加答案校验'),
    ('answer_relevance', 0.70, '生成质量', '优化 prompt、查询重写、Few-shot 示例'),
    ('semantic_similarity', 0.65, '端到端效果', '全链路复盘迭代优化'),
]

DEBUG = False


def log(msg: str) -> None:
    if DEBUG:
        print(msg, flush=True)


# ====================== 配置读取 ======================

def load_env_file(path: str) -> Dict[str, str]:
    """极简 dotenv：项目自己实现过一套，这里保持一致的风格。"""
    values: Dict[str, str] = {}
    if not os.path.exists(path):
        return values
    for line in io.open(path, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, val = line.split('=', 1)
        values[key.strip()] = val.strip()
    return values


def get_api_key() -> str:
    """与项目 llm_client.get_api_key() 一致的读取顺序：环境变量 → Windows 注册表。

    实测本机 Key 位于 HKLM 的 Session Manager\\Environment 下，变量名是 Ali_API_KEY（大小写混写）。
    """
    key = (os.getenv('Ali_API_KEY') or '').strip()
    if key:
        return key
    if os.name != 'nt':
        return ''
    try:
        import winreg
        for hive, sub in (
            (winreg.HKEY_CURRENT_USER, 'Environment'),
            (winreg.HKEY_LOCAL_MACHINE,
             r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'),
        ):
            try:
                with winreg.OpenKey(hive, sub) as h:
                    value, _ = winreg.QueryValueEx(h, 'Ali_API_KEY')
                    if value:
                        return str(value).strip()
            except OSError:
                continue
    except Exception:
        pass
    return ''


class AliChannel:
    """阿里云 OpenAI 兼容通道：只实现本脚本用到的 embeddings / chat。"""

    def __init__(self, api_key: str, base_url: str, embed_model: str,
                 llm_model: str, timeout: float = 60.0):
        self.api_key = api_key
        self.base_url = (base_url or '').rstrip('/')
        self.embed_model = embed_model
        self.llm_model = llm_model
        self.timeout = timeout
        self.session = requests.Session()
        self._emb_cache: Dict[str, List[float]] = {}
        self._load_cache()
        self.embed_calls = 0
        self.chat_calls = 0

    # ---------- 缓存 ----------
    def _load_cache(self) -> None:
        if os.path.exists(CACHE_FILE):
            try:
                self._emb_cache = json.load(io.open(CACHE_FILE, encoding='utf-8'))
                log('embedding 缓存载入 %d 条' % len(self._emb_cache))
            except Exception:
                self._emb_cache = {}

    def save_cache(self) -> None:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with io.open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(self._emb_cache, f, ensure_ascii=False)

    # ---------- 接口 ----------
    @property
    def available(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _headers(self) -> Dict[str, str]:
        return {'Authorization': 'Bearer ' + self.api_key,
                'Content-Type': 'application/json'}

    def embed(self, texts: Sequence[str], dimensions: int = COLLECTION_DIM,
              batch_size: int = 10, retries: int = 3) -> List[Optional[List[float]]]:
        """批量向量化。带本地缓存 + 失败重试 + 降并发。

        注意：老师文档强调「对接国内接口要降并发、加重试」——阿里云 embedding 单次
        最多 10 条，这里按 batch_size=10 切批。
        """
        texts = ['' if t is None else str(t) for t in texts]
        results: List[Optional[List[float]]] = [None] * len(texts)
        pending: List[Tuple[int, str]] = []
        for i, t in enumerate(texts):
            cached = self._emb_cache.get(t)
            if cached is not None:
                results[i] = cached
            else:
                pending.append((i, t))

        if not pending:
            return results
        if not self.available:
            log('!! 通道不可用，%d 条文本无法向量化' % len(pending))
            return results

        url = self.base_url + '/embeddings'
        for start in range(0, len(pending), batch_size):
            chunk = pending[start:start + batch_size]
            payload = {'model': self.embed_model,
                       'input': [t for _, t in chunk],
                       'dimensions': dimensions}
            for attempt in range(1, retries + 1):
                try:
                    resp = self.session.post(url, headers=self._headers(),
                                             json=payload, timeout=self.timeout)
                    if resp.status_code != 200:
                        raise RuntimeError('HTTP %s %s' % (resp.status_code, resp.text[:200]))
                    data = resp.json()
                    self.embed_calls += 1
                    # 接口不保证顺序，必须按 index 归位（项目代码里也踩过这个坑）
                    by_index = {item.get('index', 0): item['embedding'] for item in data['data']}
                    for local_i, (orig_i, text) in enumerate(chunk):
                        vec = by_index.get(local_i)
                        if vec:
                            results[orig_i] = list(vec)
                            self._emb_cache[text] = list(vec)
                    break
                except Exception as exc:
                    if attempt >= retries:
                        print('  [warn] embedding 批次失败（%d 条）：%s'
                              % (len(chunk), str(exc)[:160]), flush=True)
                    else:
                        time.sleep(1.5 * attempt)
            time.sleep(0.2)  # 限速，避免触发频控
        return results

    def chat(self, prompt: str, system: str = '', temperature: float = 0.1,
             top_p: float = 0.3, max_tokens: int = 500, retries: int = 3) -> str:
        """调用大模型。默认参数与项目防幻觉生成一致（temperature=0.1 / top_p=0.3）。"""
        if not self.available:
            return ''
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})
        payload = {'model': self.llm_model, 'messages': messages,
                   'temperature': temperature, 'top_p': top_p,
                   'max_tokens': max_tokens}
        url = self.base_url + '/chat/completions'
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.post(url, headers=self._headers(),
                                         json=payload, timeout=self.timeout)
                if resp.status_code != 200:
                    raise RuntimeError('HTTP %s %s' % (resp.status_code, resp.text[:200]))
                self.chat_calls += 1
                data = resp.json()
                return (data['choices'][0]['message']['content'] or '').strip()
            except Exception as exc:
                if attempt >= retries:
                    print('  [warn] LLM 调用失败：%s' % str(exc)[:160], flush=True)
                    return ''
                time.sleep(1.5 * attempt)
        return ''


# ====================== 轻量中文分词（无 jieba 依赖） ======================

_TOKEN_RE = re.compile(r'[A-Za-z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]')


def tokenize(text: str) -> List[str]:
    """中文按字 + 相邻双字组合，英文/数字整体保留。

    没有 jieba 时这是可用近似：BM25 的 IDF 作用在词项上，双字组合已能提供
    足够的区分度（"批次""控线""投档"等术语都以双字为主）。
    """
    if not text:
        return []
    raw = _TOKEN_RE.findall(text.lower())
    tokens: List[str] = []
    for item in raw:
        if '\u4e00' <= item[0] <= '\u9fff':
            tokens.append(item)
        else:
            tokens.append(item)
    # 追加相邻汉字双字组合
    han = [t for t in raw if '\u4e00' <= t[0] <= '\u9fff']
    for i in range(len(han) - 1):
        tokens.append(han[i] + han[i + 1])
    return tokens


class SimpleBM25:
    """纯 numpy 实现的 BM25Okapi（替代 rank_bm25，避免装包）。"""

    def __init__(self, corpus_tokens: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = corpus_tokens
        self.n = len(corpus_tokens)
        self.doc_len = np.array([len(d) for d in corpus_tokens], dtype=float)
        self.avgdl = float(self.doc_len.mean()) if self.n else 0.0
        self.tf: List[Dict[str, int]] = []
        df: Dict[str, int] = {}
        for doc in corpus_tokens:
            counts: Dict[str, int] = {}
            for t in doc:
                counts[t] = counts.get(t, 0) + 1
            self.tf.append(counts)
            for t in counts:
                df[t] = df.get(t, 0) + 1
        # IDF：语料很小时可能为负，用 log(1 + ...) 形式保证非负（对应项目的「小语料降级」）
        self.idf: Dict[str, float] = {}
        for t, freq in df.items():
            self.idf[t] = math.log(1.0 + (self.n - freq + 0.5) / (freq + 0.5))

    def get_scores(self, query_tokens: Sequence[str]) -> np.ndarray:
        scores = np.zeros(self.n, dtype=float)
        if not self.n:
            return scores
        for t in query_tokens:
            idf = self.idf.get(t)
            if not idf:
                continue
            for i, counts in enumerate(self.tf):
                f = counts.get(t)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.doc_len[i] / (self.avgdl or 1.0))
                scores[i] += idf * (f * (self.k1 + 1)) / (denom or 1.0)
        return scores


# ====================== 知识库读取（绕过 chromadb，直接读 sqlite） ======================

def load_chunks() -> List[Dict]:
    """从 Chroma 的 sqlite 读出全部子块：id / 文本 / 父块 / 文件名。

    表关系（已实测确认）：embeddings.id = embedding_metadata.id = embedding_fulltext_search_content.rowid
    """
    if not os.path.exists(CHROMA_SQLITE):
        raise SystemExit('找不到向量库文件：%s' % CHROMA_SQLITE)
    con = sqlite3.connect(CHROMA_SQLITE)
    cur = con.cursor()
    cur.execute("""
        SELECT e.id, f.c0,
               MAX(CASE WHEN m.key='filename'        THEN m.string_value END),
               MAX(CASE WHEN m.key='parent_chunk_id' THEN m.string_value END),
               MAX(CASE WHEN m.key='chunk_index'     THEN m.int_value    END)
        FROM embeddings e
        JOIN embedding_fulltext_search_content f ON f.rowid = e.id
        LEFT JOIN embedding_metadata m            ON m.id = e.id
        GROUP BY e.id
        ORDER BY e.id
    """)
    chunks = []
    for cid, text, filename, parent_id, chunk_index in cur.fetchall():
        chunks.append({'id': int(cid), 'text': text or '',
                       'filename': filename or '?',
                       'parent_id': parent_id or '',
                       'chunk_index': chunk_index})
    con.close()
    return chunks


def load_parents() -> Dict[str, str]:
    """父块原文（用于回填，模拟项目 _expand_to_parents）。"""
    path = os.path.join(PROJECT_ROOT, 'backend', 'chroma_db', 'parent_store.json')
    if not os.path.exists(path):
        return {}
    data = json.load(io.open(path, encoding='utf-8'))
    out: Dict[str, str] = {}
    for key, val in data.items():
        out[key] = val.get('text', '') if isinstance(val, dict) else str(val)
    return out


# ====================== RAG 类型自检 ======================

# 判断依据：代码里是否存在这条链路的函数定义（比字符串匹配更可靠）
_RAG_TYPE_PROBES = [
    ('图谱 RAG（向量+图谱双通道融合）', 'services/rag_service.py',
     ('def search_with_graph', 'def answer_with_graph'),
     'GRAPH_ENABLED 且 use_graph=true（默认）；异常自动降级'),
    ('Advanced RAG（Modular）', 'services/rag_service.py',
     ('def answer_with_strategy', 'def route_strategy'),
     'ADVANCED_RAG_ENABLED 且图谱链路异常时'),
    ('标准 RAG（Advanced 检索链）', 'services/rag_service.py',
     ('def search(', 'def generate_answer'),
     'answer_with_strategy 内部 strategy=standard'),
    ('Naive RAG（兜底）', 'routers/ai.py',
     ('rag_service.search', 'generate_answer'),
     '高级链路全部异常时的最朴素 检索+拼接+生成'),
    ('无 RAG 通用问答', 'routers/ai.py',
     ('你是高考志愿填报助手',),
     'use_rag=false 或未检索到资料'),
]


def report_rag_types() -> None:
    """静态扫描源码，列出当前代码里实际存在的 RAG 形态。

    存在的意义：防止「以为基础 RAG 被删了、其实还在」这类误判——
    交材料、答辩、写文档时都需要一个确定答案。
    """
    app_dir = os.path.join(PROJECT_ROOT, 'backend', 'app')
    print('RAG 类型自检（按代码实际存在判断）')
    print('-' * 68)
    for name, rel, markers, condition in _RAG_TYPE_PROBES:
        path = os.path.join(app_dir, rel.replace('/', os.sep))
        found = False
        try:
            if os.path.exists(path):
                src = io.open(path, encoding='utf-8').read()
                found = all(m in src for m in markers)
        except Exception:
            found = False
        print('  [%s] %-30s 触发：%s' % ('存在' if found else '缺失', name, condition))
    print('-' * 68)



# ====================== 向量工具 ======================

def l2_normalize(mat: np.ndarray) -> np.ndarray:
    if mat.size == 0:
        return mat
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def cosine_matrix(query_vec: np.ndarray, doc_mat: np.ndarray) -> np.ndarray:
    """query_vec 与 doc_mat 每一行的余弦相似度（两者都需已归一化时等价于点积）。"""
    if doc_mat.size == 0:
        return np.zeros(0, dtype=float)
    q = np.asarray(query_vec, dtype=float).reshape(1, -1)
    q_norm = np.linalg.norm(q) or 1.0
    d_norms = np.linalg.norm(doc_mat, axis=1)
    d_norms[d_norms == 0] = 1.0
    return (doc_mat @ q.T).ravel() / (d_norms * q_norm)


def rrf_fuse(rankings: List[List[int]], k: int = 60, top_n: int = 20) -> List[Tuple[int, float]]:
    """RRF 融合：只取排名，量纲无关。score += 1/(k+rank)。

    与项目 retrieval._rrf_fuse 保持一致（k=60）。
    """
    scores: Dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ordered[:top_n]


# ====================== 检索（稠密 + BM25 + RRF） ======================

class Retriever:
    """复刻项目检索策略：混合检索（稠密 + BM25）→ RRF 融合 → 父块回填。"""

    def __init__(self, chunks: List[Dict], parents: Dict[str, str],
                 channel: AliChannel, use_dense: bool = True):
        self.chunks = chunks
        self.parents = parents
        self.channel = channel
        self.texts = [c['text'] for c in chunks]
        self.child_tokens = [tokenize(t) for t in self.texts]
        self.bm25 = SimpleBM25(self.child_tokens)
        self.use_dense = use_dense
        self.embeddings: Optional[np.ndarray] = None
        if use_dense and channel.available:
            vecs = channel.embed(self.texts, dimensions=COLLECTION_DIM)
            valid = [v for v in vecs if v]
            if len(valid) == len(self.texts):
                self.embeddings = l2_normalize(np.asarray(valid, dtype=float))
            else:
                print('  [warn] 知识库向量化不完整（%d/%d），稠密路降级为仅 BM25'
                      % (len(valid), len(self.texts)), flush=True)
                self.use_dense = False

    def search(self, query: str, top_k: int = 5, recall_n: int = 20) -> List[Dict]:
        rankings: List[List[int]] = []

        if self.use_dense and self.embeddings is not None:
            qv = self.channel.embed([query], dimensions=COLLECTION_DIM)[0]
            if qv:
                sims = cosine_matrix(np.asarray(qv, dtype=float), self.embeddings)
                dense_rank = list(np.argsort(-sims)[:recall_n])
                rankings.append([int(i) for i in dense_rank])

        bm25_scores = self.bm25.get_scores(tokenize(query))
        bm_rank = [int(i) for i in np.argsort(-bm25_scores)[:recall_n] if bm25_scores[int(i)] > 0]
        if bm_rank:
            rankings.append(bm_rank)

        if not rankings:
            return []

        fused = rrf_fuse(rankings, k=60, top_n=top_k)
        hits = []
        for doc_id, score in fused:
            chunk = self.chunks[doc_id]
            parent_text = self.parents.get(chunk['parent_id']) or chunk['text']
            hits.append({
                'child_id': chunk['id'],
                'child_text': chunk['text'],
                'context': parent_text,          # 回填父块，交给生成的是父块
                'filename': chunk['filename'],
                'rrf_score': score,
            })
        return hits


# ====================== 指标计算 ======================

def split_sentences(text: str) -> List[str]:
    parts = re.split(r'[。！？；\n]', text or '')
    return [p.strip() for p in parts if len(p.strip()) >= 4]


NUMBER_RE = re.compile(r'\d+(?:\.\d+)?%?')


def numbers_in(text: str) -> List[str]:
    return NUMBER_RE.findall(text or '')


def retrieval_metrics(hits: List[Dict], gt_sentences: List[str], gt_embs: Optional[np.ndarray],
                      threshold: float = HIT_THRESHOLD) -> Dict[str, float]:
    """检索质量：命中率 / 精确率 / 召回率 / MRR / NDCG@k。

    命中判定（老师文档做法）：检索 chunk 与「参考答案任意句」的余弦相似度 ≥ 阈值即算命中。
    通道不可用（无向量）时退化为「关键词重合」判定，保证脚本仍可出基线数字。
    """
    if not hits:
        return {'hit_rate': 0.0, 'context_precision': 0.0, 'context_recall': 0.0,
                'mrr': 0.0, 'ndcg': 0.0, 'relevant_flags': []}

    flags: List[bool] = []
    if gt_embs is not None and getattr(retrieval_metrics, '_chan', None) is not None:
        chan: AliChannel = retrieval_metrics._chan  # type: ignore[attr-defined]
        hit_texts = [h['context'] for h in hits]
        hit_vecs = chan.embed(hit_texts, dimensions=COLLECTION_DIM)
        for vec in hit_vecs:
            if not vec:
                flags.append(False)
                continue
            sims = cosine_matrix(np.asarray(vec, dtype=float), gt_embs)
            flags.append(bool(sims.size and float(sims.max()) >= threshold))
    else:
        gt_tokens = set()
        for s in gt_sentences:
            gt_tokens.update(tokenize(s))
        for h in hits:
            hit_tokens = set(tokenize(h['context']))
            if not gt_tokens:
                flags.append(False)
                continue
            overlap = len(gt_tokens & hit_tokens) / float(len(gt_tokens))
            flags.append(overlap >= 0.5)

    n_rel = sum(1 for f in flags if f)
    # Context Precision：命中的排在前面才有价值，按位次加权
    prec_sum, rel_seen = 0.0, 0
    for i, f in enumerate(flags, start=1):
        if f:
            rel_seen += 1
            prec_sum += rel_seen / i
    context_precision = (prec_sum / n_rel) if n_rel else 0.0

    # Context Recall：参考答案的句子有多少被检索上下文覆盖
    context_recall = 0.0
    if gt_sentences:
        if gt_embs is not None and getattr(retrieval_metrics, '_chan', None) is not None:
            chan = retrieval_metrics._chan  # type: ignore[attr-defined]
            hit_vecs = [v for v in chan.embed([h['context'] for h in hits],
                                              dimensions=COLLECTION_DIM) if v]
            if hit_vecs:
                hit_mat = l2_normalize(np.asarray(hit_vecs, dtype=float))
                covered = 0
                for i in range(gt_embs.shape[0]):
                    sims = cosine_matrix(gt_embs[i], hit_mat)
                    if sims.size and float(sims.max()) >= threshold:
                        covered += 1
                context_recall = covered / float(gt_embs.shape[0])
        else:
            ctx_tokens = set()
            for h in hits:
                ctx_tokens.update(tokenize(h['context']))
            covered = sum(1 for s in gt_sentences
                          if len(set(tokenize(s)) & ctx_tokens) / max(1, len(set(tokenize(s)))) >= 0.5)
            context_recall = covered / float(len(gt_sentences))

    # MRR：第一个命中位置的倒数
    mrr = 0.0
    for i, f in enumerate(flags, start=1):
        if f:
            mrr = 1.0 / i
            break

    # NDCG@k：二值相关性
    dcg = sum((1.0 / math.log2(i + 1)) for i, f in enumerate(flags, start=1) if f)
    ideal = sum((1.0 / math.log2(i + 1)) for i in range(1, min(n_rel, len(flags)) + 1))
    ndcg = (dcg / ideal) if ideal else 0.0

    return {'hit_rate': 1.0 if n_rel else 0.0,
            'context_precision': round(context_precision, 4),
            'context_recall': round(context_recall, 4),
            'mrr': round(mrr, 4),
            'ndcg': round(ndcg, 4),
            'relevant_flags': flags}


def faithfulness_rule(answer: str, contexts: str) -> float:
    """忠实度（规则版）：答案里的数字是否都能在上下文中找到。

    审慎原则：答案里「没有数字」时返回 -1（不参与统计），因为规则版无法判断
    纯文字陈述是否忠于上下文——这种样本需要 LLM 裁判，脚本里标注为「需人工/LLM核验」。
    """
    nums = numbers_in(answer)
    if not nums:
        return -1.0
    ctx_nums = set(numbers_in(contexts))
    hit = sum(1 for n in nums if n in ctx_nums)
    return round(hit / float(len(nums)), 4)


def grade_of(score: float) -> str:
    for threshold, label in GRADE_LEVELS:
        if score >= threshold:
            return label
    return '需优化'


# ====================== 报告生成 ======================

def build_recommendations(summary: Dict[str, float]) -> List[str]:
    tips = []
    for key, threshold, dimension, action in ALERT_RULES:
        value = summary.get(key)
        if value is None or value < 0:
            continue
        if value < threshold:
            tips.append('[%s] %s = %.3f < %.2f → %s' % (dimension, key, value, threshold, action))
    if not tips:
        tips.append('全部指标达到告警阈值以上，无需紧急优化；可进入参数网格调优阶段。')
    return tips


def write_report(summary: Dict[str, float], details: List[Dict], meta: Dict,
                 out_path: str) -> None:
    overall = float(np.mean([v for k, v in summary.items()
                            if k not in ('samples', 'faithfulness_rule_samples') and v >= 0])) \
        if summary else 0.0
    lines = []
    lines.append('# RAG 量化评估报告')
    lines.append('')
    lines.append('> 生成时间：%s' % meta.get('generated_at', ''))
    lines.append('> 评估脚本：`backend/rag_eval.py`（轻量自研版，不依赖 ragas / chromadb）')
    lines.append('')
    lines.append('## 一、环境与配置（复现用）')
    lines.append('')
    lines.append('| 项 | 值 |')
    lines.append('|---|---|')
    for k, v in meta.items():
        lines.append('| %s | %s |' % (k, v))
    lines.append('')
    lines.append('## 二、指标总览')
    lines.append('')
    lines.append('| 维度 | 指标 | 得分 | 评级 |')
    lines.append('|---|---|---|---|')
    dim_map = {
        'context_precision': '检索质量', 'context_recall': '检索质量',
        'hit_rate': '检索质量', 'mrr': '检索质量', 'ndcg': '检索质量',
        'faithfulness': '生成质量', 'answer_relevance': '生成质量',
        'semantic_similarity': '端到端效果',
    }
    for key in ('context_precision', 'context_recall', 'hit_rate', 'mrr', 'ndcg',
                'faithfulness', 'answer_relevance', 'semantic_similarity'):
        if key not in summary:
            continue
        val = summary[key]
        shown = '不适用' if val < 0 else '%.4f' % val
        lines.append('| %s | %s | %s | %s |'
                     % (dim_map.get(key, '-'), key, shown,
                        '-' if val < 0 else grade_of(val)))
    lines.append('')
    lines.append('**综合得分（各适用指标均值）：%.4f —— %s**' % (overall, grade_of(overall)))
    lines.append('')
    lines.append('## 三、自动诊断与优化建议（依据告警阈值）')
    lines.append('')
    for tip in build_recommendations(summary):
        lines.append('- %s' % tip)
    lines.append('')
    lines.append('## 四、逐题明细')
    lines.append('')
    lines.append('| # | 问题 | 类型 | Precision | Recall | MRR | 忠实度 | 命中片段 |')
    lines.append('|---|---|---|---|---|---|---|---|')
    for i, d in enumerate(details, start=1):
        lines.append('| %d | %s | %s | %.2f | %.2f | %.2f | %s | %s |' % (
            i, (d['question'][:28] + ('…' if len(d['question']) > 28 else '')),
            d['question_type'],
            d['metrics']['context_precision'], d['metrics']['context_recall'],
            d['metrics']['mrr'],
            ('-' if d['faithfulness'] < 0 else '%.2f' % d['faithfulness']),
            ' / '.join(d.get('hit_files', [])) or '无',
        ))
    lines.append('')
    with io.open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


# ====================== 主流程 ======================

def main() -> int:
    global DEBUG
    parser = argparse.ArgumentParser(description='RAG 量化评估（轻量自研版）')
    parser.add_argument('--dataset', default=DATASET_FILE)
    parser.add_argument('--top-k', type=int, default=5)
    parser.add_argument('--recall-n', type=int, default=20)
    parser.add_argument('--limit', type=int, default=0, help='只跑前 N 条（调试）')
    parser.add_argument('--no-llm', action='store_true', help='不做 LLM 生成的指标')
    parser.add_argument('--no-generate', action='store_true', help='完全不调用 LLM（只评检索）')
    parser.add_argument('--types-only', action='store_true',
                        help='只做 RAG 类型自检后退出（交材料前快速确认实现清单）')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()
    DEBUG = args.debug

    print('=' * 68)
    print('RAG 量化评估（轻量自研版）')
    print('=' * 68)
    report_rag_types()
    if args.types_only:
        return 0

    env = load_env_file(ENV_FILE)
    api_key = get_api_key()
    channel = AliChannel(
        api_key=api_key,
        base_url=env.get('ALI_BASE_URL', ''),
        embed_model=env.get('ALI_EMBED_MODEL', 'text-embedding-v3'),
        llm_model=env.get('ALI_LLM_MODEL', 'qwen3.7-flash-2026-07-15'),
    )

    print('=' * 68)
    print('API Key      : %s' % ('已读取（长度 %d）' % len(api_key) if api_key else '未读取到'))
    print('Embedding    : %s @ %d 维' % (channel.embed_model, COLLECTION_DIM))
    print('LLM          : %s（%s）' % (channel.llm_model,
                                       '启用' if not args.no_generate else '已禁用'))
    print('-' * 68)

    # 1) 载入测试集
    if not os.path.exists(args.dataset):
        print('找不到测试集：%s' % args.dataset)
        return 2
    dataset = json.load(io.open(args.dataset, encoding='utf-8'))
    if args.limit:
        dataset = dataset[:args.limit]
    print('测试集       : %d 条' % len(dataset))

    # 2) 载入知识库
    chunks = load_chunks()
    parents = load_parents()
    print('知识库子块   : %d 条（父块 %d 条）' % (len(chunks), len(parents)))
    from collections import Counter
    for name, cnt in Counter(c['filename'] for c in chunks).most_common():
        print('               - %-28s %d 条' % (name, cnt))

    # 3) 检索器
    retriever = Retriever(chunks, parents, channel, use_dense=channel.available)
    print('检索模式     : %s' % ('稠密 + BM25 → RRF' if retriever.use_dense else '仅 BM25（稠密不可用）'))
    print('-' * 68)

    # 4) 逐题评估
    retrieval_metrics._chan = channel  # type: ignore[attr-defined]
    details: List[Dict] = []
    acc = {'context_precision': [], 'context_recall': [], 'hit_rate': [],
           'mrr': [], 'ndcg': [], 'faithfulness': [], 'answer_relevance': [],
           'semantic_similarity': []}

    for idx, item in enumerate(dataset, start=1):
        q = item['question']
        gt = item.get('ground_truth', '')
        qtype = item.get('question_type', 'fact')
        hits = retriever.search(q, top_k=args.top_k, recall_n=args.recall_n)

        gt_sents = split_sentences(gt) or [gt]
        gt_embs = None
        if channel.available:
            vecs = [v for v in channel.embed(gt_sents, dimensions=COLLECTION_DIM) if v]
            if len(vecs) == len(gt_sents):
                gt_embs = l2_normalize(np.asarray(vecs, dtype=float))

        m = retrieval_metrics(hits, gt_sents, gt_embs)
        context_text = '\n\n'.join(h['context'] for h in hits)

        answer = ''
        faith = -1.0
        relevance = -1.0
        sem_sim = -1.0
        if not args.no_generate:
            prompt = (
                '请严格依据下面提供的资料回答问题。'
                '如果资料中没有相关信息，必须直接回答「根据现有资料，未查询到具体信息」，禁止编造、推测或扩展。\n\n'
                '【资料】\n%s\n\n【问题】%s\n\n【回答】' % (context_text[:3000], q)
            )
            answer = channel.chat(prompt, system='你是严谨的高考志愿知识库问答助手。')
            faith = faithfulness_rule(answer, context_text)
            if answer and channel.available:
                vecs = channel.embed([q, answer], dimensions=COLLECTION_DIM)
                if vecs[0] and vecs[1]:
                    relevance = round(float(cosine_matrix(
                        np.asarray(vecs[1], dtype=float),
                        l2_normalize(np.asarray([vecs[0]], dtype=float)))[0]), 4)

        if channel.available and answer and gt:
            vecs = channel.embed([answer, gt], dimensions=COLLECTION_DIM)
            if vecs[0] and vecs[1]:
                sem_sim = round(float(cosine_matrix(
                    np.asarray(vecs[0], dtype=float),
                    l2_normalize(np.asarray([vecs[1]], dtype=float)))[0]), 4)

        for key, val in (('context_precision', m['context_precision']),
                         ('context_recall', m['context_recall']),
                         ('hit_rate', m['hit_rate']), ('mrr', m['mrr']),
                         ('ndcg', m['ndcg'])):
            acc[key].append(val)
        if faith >= 0:
            acc['faithfulness'].append(faith)
        if relevance >= 0:
            acc['answer_relevance'].append(relevance)
        if sem_sim >= 0:
            acc['semantic_similarity'].append(sem_sim)

        details.append({
            'id': item.get('id', 'q%03d' % idx), 'question': q, 'question_type': qtype,
            'ground_truth': gt, 'answer': answer, 'hits': hits, 'metrics': m,
            'faithfulness': faith, 'answer_relevance': relevance,
            'semantic_similarity': sem_sim,
            'hit_files': sorted({h['filename'] for h in hits}),
        })
        print('[%2d/%d] %-6s P=%.2f R=%.2f MRR=%.2f  忠实度=%s  %s'
              % (idx, len(dataset), qtype, m['context_precision'], m['context_recall'],
                 m['mrr'], ('-' if faith < 0 else '%.2f' % faith), q[:30]), flush=True)

    channel.save_cache()

    summary = {k: (round(float(np.mean(v)), 4) if v else -1.0) for k, v in acc.items()}
    summary['samples'] = len(dataset)
    summary['faithfulness_rule_samples'] = len(acc['faithfulness'])

    # 5) 输出
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    detail_path = os.path.join(OUT_DIR, 'rag_eval_details_%s.json' % stamp)
    report_path = os.path.join(OUT_DIR, 'RAG评估报告_%s.md' % stamp)

    meta = {
        '测试集': os.path.basename(args.dataset),
        '知识库子块数': len(chunks),
        '知识库父块数': len(parents),
        'top_k': args.top_k,
        'recall_n': args.recall_n,
        '命中阈值': HIT_THRESHOLD,
        'embedding 模型': channel.embed_model,
        'embedding 维度': COLLECTION_DIM,
        'LLM 模型': channel.llm_model if not args.no_generate else '未使用',
        'embedding 请求次数': channel.embed_calls,
        'LLM 请求次数': channel.chat_calls,
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }

    with io.open(detail_path, 'w', encoding='utf-8') as f:
        json.dump({'summary': summary, 'meta': meta, 'details': details},
                  f, ensure_ascii=False, indent=2)
    write_report(summary, details, meta, report_path)

    print('=' * 68)
    print('评估结果（%d 条样本）' % len(dataset))
    print('=' * 68)
    for key in ('context_precision', 'context_recall', 'hit_rate', 'mrr', 'ndcg',
                'faithfulness', 'answer_relevance', 'semantic_similarity'):
        val = summary.get(key, -1.0)
        print('  %-22s %s' % (key, ('不适用' if val < 0 else '%.4f  (%s)' % (val, grade_of(val)))))
    valid = [v for k, v in summary.items()
             if k not in ('samples', 'faithfulness_rule_samples') and isinstance(v, float) and v >= 0]
    if valid:
        print('  %-22s %.4f  (%s)' % ('综合得分', float(np.mean(valid)), grade_of(float(np.mean(valid)))))
    print('-' * 68)
    print('诊断建议：')
    for tip in build_recommendations(summary):
        print('  - %s' % tip)
    print('-' * 68)
    print('明细：%s' % detail_path)
    print('报告：%s' % report_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
