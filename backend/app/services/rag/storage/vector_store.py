"""向量存储：Chroma 客户端与集合的唯一管理者（0.18.0 从 rag_service 搬出）。

## 为什么状态要「注入」而不是自己持有
历史测试大量直接改 `rag_service` 的模块级变量来清缓存，例如：

    rag_service._collection = None            # 强制下次重建集合
    rag_service._collection_dim_cache = None  # 清维度缓存
    rag_service._client.delete_collection(..) # 直接操作客户端

如果 VectorStore 把状态藏进实例属性，这些 patch 就全部失效。
因此这里接受一个 **可变映射**（`rag_service` 传自己的 `globals()`），
读写都落在同一个命名空间上 —— 测试改模块变量 == 改存储状态，语义完全一致。

## 延迟初始化
Chroma 在导入期不可用（未安装 / 目录损坏）时不能让整个服务起不来，
所以客户端在首次访问时才创建，失败只记录 `_chroma_error` 并返回 None。
"""
from __future__ import annotations

import os
from typing import Any, Dict, MutableMapping, Optional

from app.config import settings
from app.services.llm import llm_client

#: 状态键与默认值（与 rag_service 的历史模块级变量一一对应）
_STATE_DEFAULTS: Dict[str, Any] = {
    "_client": None,              # chromadb.PersistentClient
    "_collection": None,          # 当前集合（None = 尚未创建或已失效）
    "_chroma_error": None,        # 最近一次创建失败的原因
    "_collection_dim_cache": None,  # 集合被 pin 住的向量维度（缓存一次）
}


class VectorStore:
    """Chroma 持久化集合的唯一管理者（延迟初始化）。"""

    def __init__(self, state: Optional[MutableMapping[str, Any]] = None):
        #: 状态容器；不传则自带一份（独立实例，便于单测）
        self._state: MutableMapping[str, Any] = state if state is not None else {}
        for key, default in _STATE_DEFAULTS.items():
            self._state.setdefault(key, default)

    # ---------------- 集合 ----------------

    def get_collection(self):
        """获取（或创建）持久化集合；失败返回 None 并记下原因。"""
        col = self._state.get("_collection")
        if col is not None:
            return col
        try:
            import chromadb

            os.makedirs(settings.CHROMA_DB_PATH, exist_ok=True)
            client = chromadb.PersistentClient(path=settings.CHROMA_DB_PATH)
            col = client.get_or_create_collection(name=settings.CHROMA_COLLECTION)
            self._state["_client"] = client
            self._state["_collection"] = col
            return col
        except Exception as exc:  # noqa: BLE001 向量库不可用不应阻断服务启动
            self._state["_chroma_error"] = str(exc)
            return None

    def collection(self):
        """兼容旧名：供路由层直接操作（如按 file_id 删除向量）。"""
        return self.get_collection()

    # ---------------- 状态报告 ----------------

    def backend_info(self) -> dict:
        """向量库与模型通道的当前状态（供 `/api/knowledge/status` 使用）。"""
        col = self.get_collection()
        has_key = bool(llm_client.get_api_key())
        return {
            "vector_store": "chroma",
            "persist_path": settings.CHROMA_DB_PATH,
            "collection": settings.CHROMA_COLLECTION,
            "embedding_model": settings.ALI_EMBED_MODEL if has_key else settings.OLLAMA_EMBED_MODEL,
            "embedding_provider": has_key and "ali" or "ollama",
            "llm_provider": has_key and "ali(openai-compatible)" or "ollama",
            "llm_model": settings.ALI_LLM_MODEL if has_key else settings.OLLAMA_FALLBACK_MODEL,
            "ready": col is not None,
            "error": self._state.get("_chroma_error"),
            "count": (col.count() if col else 0),
        }

    def collection_dimension(self) -> Optional[int]:
        """读取集合被 pin 住的向量维度（结果缓存一次，避免每次都查库）。

        用途：写入/查询前把 Ali embedding 的维度对齐到集合，
        否则 text-embedding-v3 默认 128 维会与历史 768 维数据冲突，Chroma 直接拒绝写入。

        取值顺序（★ 顺序是关键，0.9.1 修复的 bug 就出在这里）：
          ① `col._model.dimension`：Chroma 1.x 会把集合维度 pin 在集合元数据里，
             **即使集合被删空也依然保留 768**。
             旧实现只读「第一条向量的长度」，文件全部删除后读不到 → 回落到
             `ALI_EMBED_DIMENSION`(128) → 上传时报
             "Collection expecting embedding with dimension of 768, got 128"。
          ② 第一条向量的长度：兼容不暴露 `_model` 的旧版 chromadb；
          ③ None：由调用方回落到 `ALI_EMBED_DIMENSION`（仅全新集合时才是对的）。
        """
        cached = self._state.get("_collection_dim_cache")
        if cached is not None:
            return cached
        dim: Optional[int] = None
        try:
            col = self.get_collection()
            if col is not None:
                # ① 集合 pin 住的维度（删空后依然有效，优先用它）
                pinned = getattr(getattr(col, "_model", None), "dimension", None)
                if isinstance(pinned, int) and pinned > 0:
                    dim = pinned
                # ② 退化方案：读第一条向量的长度
                if dim is None:
                    data = col.get(include=["embeddings"], limit=1)
                    emb = (data or {}).get("embeddings")
                    if emb is not None and len(emb) and emb[0] is not None:
                        dim = len(emb[0])
        except Exception:  # noqa: BLE001 查不到就按配置走
            dim = None
        self._state["_collection_dim_cache"] = dim
        return self._state["_collection_dim_cache"]

    # ---------------- 测试辅助 ----------------

    def reset(self) -> None:
        """清空全部缓存（客户端 / 集合 / 错误 / 维度），下次访问重新建立。"""
        for key in _STATE_DEFAULTS:
            self._state[key] = None
