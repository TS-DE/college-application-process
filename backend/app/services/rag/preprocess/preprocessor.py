"""统一预处理入口（0.18.0 从 query_rewrite.py 搬出，逻辑未改）。

并发编排、短问句短路、去重限条三条规则与 0.17.x **完全一致**：
  · 三者互不依赖 → 线程池并发，单 Query 耗时 = 最慢的那一步；
  · 短问句（< QUERY_PREPROCESS_MIN_LEN）直接返回原始 Query，省一次 LLM 往返；
  · 结果「原始 Query 置顶 → 去重 → 限条数」，避免多路召回拖慢响应。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from app.services.rag.preprocess.base import get_api_key
from app.services.rag.preprocess.decomposer import QueryDecomposer
from app.services.rag.preprocess.expander import StepBackExpander
from app.services.rag.preprocess.rewriter import QueryRewriter


@dataclass
class QueryBundle:
    """检索前预处理的产物。"""

    original: str                                  # 原始 Query（必定保留，兜底用）
    rewritten: str = ""                            # 重写后的 Query
    step_back: str = ""                            # 后退一步的宽泛 Query
    sub_queries: List[str] = field(default_factory=list)  # 子查询列表
    all_queries: List[str] = field(default_factory=list)  # 最终送给检索的 Query 列表
    source: str = "raw"                            # ali / ollama / raw（便于排查）


class QueryPreprocessor:
    """检索前统一入口：按需执行 重写 → 扩展 → 分解，产出用于多路召回的 Query 列表。

    输出顺序：原始 Query 置顶（保证兜底召回），其后是重写 / 扩展 / 子查询，
    去重后限制条数，避免多路召回拖慢响应。
    """

    def __init__(
        self,
        use_rewrite: bool = True,
        use_expansion: bool = True,
        use_decompose: bool = True,
        max_queries: int = 4,
        model: Optional[str] = None,
        min_len: Optional[int] = None,
    ):
        self.use_rewrite = use_rewrite
        self.use_expansion = use_expansion
        self.use_decompose = use_decompose
        self.max_queries = max_queries
        # 短问句阈值：None → 取配置 QUERY_PREPROCESS_MIN_LEN；传 0 → 永不跳过（供回归测试用）
        from app.config import settings

        self.min_len = settings.QUERY_PREPROCESS_MIN_LEN if min_len is None else min_len
        self.rewriter = QueryRewriter(model=model)
        self.expander = StepBackExpander(model=model)
        self.decomposer = QueryDecomposer(model=model)

    def process(self, query: str) -> QueryBundle:
        """执行检索前预处理。任一步失败都不影响整体（降级为原始 Query）。"""
        original = (query or "").strip()
        bundle = QueryBundle(original=original, all_queries=[original] if original else [])

        # ⚡ 短问句短路：少于 QUERY_PREPROCESS_MIN_LEN 字认为意图已明确，不再花一次 LLM 往返
        if self.min_len > 0 and len(original) < self.min_len:
            bundle.source = "raw(short)"
            return bundle

        jobs: List[tuple] = []  # [(步骤名, 执行函数)]
        if self.use_rewrite:
            jobs.append(("rewrite", lambda: self.rewriter.rewrite(original)))
        if self.use_expansion:
            jobs.append(("expansion", lambda: self.expander.step_back(original)))
        if self.use_decompose:
            jobs.append(("decompose", lambda: self.decomposer.decompose(original)))

        results: Dict[str, object] = {}
        if jobs:
            with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
                futures = {name: pool.submit(fn) for name, fn in jobs}
                for name, fut in futures.items():
                    try:
                        results[name] = fut.result()
                    except Exception:  # noqa: BLE001 任一步失败都只降级自己那一路
                        results[name] = "" if name != "decompose" else []

        bundle.rewritten = str(results.get("rewrite", "") or "")
        bundle.step_back = str(results.get("expansion", "") or "")
        bundle.sub_queries = list(results.get("decompose") or [])

        # ④ 汇总去重 + 限条数（原始 Query 置顶）
        candidates = [original, bundle.rewritten, bundle.step_back, *bundle.sub_queries]
        seen, merged = set(), []
        for q in candidates:
            q = (q or "").strip()
            if not q or q in seen:
                continue
            seen.add(q)
            merged.append(q)
        bundle.all_queries = merged[: self.max_queries]

        # ⑤ 标注来源，便于排查：有 Key 走 ali，回落则标 ollama，没生成任何增强 Query 标 raw
        bundle.source = "ali" if get_api_key() else "ollama"
        if len(bundle.all_queries) <= 1:
            bundle.source = "raw"
        return bundle
