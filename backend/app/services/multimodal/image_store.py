"""图像向量库（0.10.0）：Chroma 独立集合 `gaokao_images`。

## 为什么用独立集合而不是塞进文本集合
「以文搜图」用的是**另一套编码器**（Chinese-CLIP 或图注向量），
向量维度与语义空间都和文本向量不同。混在一个集合里会导致：
  · 检索时文本问题同时命中图片和文本切片，结果互相干扰；
  · 维度不一致直接报错（文本 768/1024，CLIP 512）。
因此按课堂「独立向量空间」方案单独建集合。

## 单一职责
只负责 Chroma 图像集合的读写删，不编码、不提取、不检索。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class ImageStore:
    """Chroma 图像集合读写。"""

    def __init__(self, collection_name: str = "") -> None:
        self._name = collection_name or settings.IMAGE_COLLECTION
        self._collection = None
        self._error: Optional[str] = None

    # ---------------- 集合生命周期 ----------------

    def _get_collection(self):
        """延迟获取（或创建）集合，避免导入即连库。"""
        if self._collection is not None:
            return self._collection
        try:
            import chromadb

            import os

            os.makedirs(settings.CHROMA_DB_PATH, exist_ok=True)
            client = chromadb.PersistentClient(path=settings.CHROMA_DB_PATH)
            self._collection = client.get_or_create_collection(name=self._name)
        except Exception as exc:  # noqa: BLE001 Chroma 不可用时整体降级
            self._error = str(exc)
            logger.info("[MM] 图像集合获取失败：%s", exc.__class__.__name__)
            return None
        return self._collection

    def available(self) -> bool:
        return self._get_collection() is not None

    def count(self) -> int:
        col = self._get_collection()
        return col.count() if col is not None else 0

    # ---------------- 维度管理（与文本集合同源的坑） ----------------

    def collection_dimension(self) -> Optional[int]:
        """读取图像集合被 pin 住的向量维度（删空后依然有效）。

        与 `rag_service._collection_dimension()` 同源：Chroma 1.x 把维度 pin 在
        `col._model.dimension`，**即使集合删空也保留**。只读「第一条向量长度」会在
        集合空时读不到，进而写入错误维度的向量被 Chroma 拒绝。
        """
        col = self._get_collection()
        if col is None:
            return None
        pinned = getattr(getattr(col, "_model", None), "dimension", None)
        if isinstance(pinned, int) and pinned > 0:
            return pinned
        return None

    def reset(self) -> bool:
        """清空并重建图像集合。

        用途：切换图像编码器时必须调用——Chinese-CLIP 是 512 维、图注方案是 768 维，
        旧向量与新向量不同维也不同空间，混在一个集合里检索会直接报错。
        调用前应确认不再需要旧图像向量（重新上传文件即可重建）。
        """
        try:
            import chromadb

            import os

            os.makedirs(settings.CHROMA_DB_PATH, exist_ok=True)
            client = chromadb.PersistentClient(path=settings.CHROMA_DB_PATH)
            try:
                client.delete_collection(name=self._name)
            except Exception:  # noqa: BLE001 集合本来不存在
                pass
            self._collection = client.get_or_create_collection(name=self._name)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.info("[MM] 图像集合重建失败：%s", exc.__class__.__name__)
            return False

    # ---------------- 写 ----------------

    def add_images(self, images: List[Dict[str, Any]], embeddings: List[List[float]],
                   encoder_name: str = "") -> int:
        """批量写入图片向量，返回成功条数。

        :param images:      [{"image_bytes", "page", "caption", "file_id", "filename"}, ...]
        :param embeddings:  与 images 等长的向量列表（None 表示该张编码失败）
        :param encoder_name: 编码器标识，写入 metadata 便于排查
        """
        col = self._get_collection()
        if col is None or not images:
            return 0

        ids, docs, metas, vecs = [], [], [], []
        for idx, (img, vec) in enumerate(zip(images, embeddings)):
            if vec is None:
                continue  # 编码失败跳过，不影响其他图片
            file_id = img.get("file_id")
            ids.append(f"file_{file_id}_img_{idx}")
            # documents 存图注（可能为空），供排查时肉眼确认这张图是什么
            docs.append(img.get("caption") or "")
            metas.append({
                "file_id": int(file_id) if file_id is not None else 0,
                "filename": img.get("filename") or "",
                "page": int(img.get("page") or 0),
                "encoder": encoder_name,
            })
            vecs.append(list(vec))

        if not ids:
            return 0

        # 写入前校验维度：集合可能被上次的编码器 pin 住（CLIP 512 / 图注 768 不同维）
        expected = self.collection_dimension()
        if expected and len(vecs[0]) != expected:
            logger.info(
                "[MM] 图像维度不匹配：集合要求 %d 维，编码器 %s 产出 %d 维。"
                "切换编码器需调用 ImageStore.reset() 重建集合后重新上传文件。",
                expected, encoder_name or "?", len(vecs[0]),
            )
            return 0

        try:
            col.add(ids=ids, embeddings=vecs, documents=docs, metadatas=metas)
            return len(ids)
        except Exception as exc:  # noqa: BLE001 维度不符等写入失败
            logger.info("[MM] 图像写入失败：%s %s", exc.__class__.__name__, str(exc)[:150])
            return 0

    # ---------------- 查 ----------------

    def search_by_text(self, embedding: List[float], top_k: int = 3) -> List[Dict[str, Any]]:
        """用文本向量检索最相似的图片。

        :return: [{"id", "distance", "metadata", "caption"}, ...]，按相似度升序
        """
        col = self._get_collection()
        if col is None or not embedding:
            return []
        try:
            res = col.query(
                query_embeddings=[list(embedding)],
                n_results=max(1, int(top_k)),
                include=["metadatas", "documents", "distances"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("[MM] 图像检索失败：%s", exc.__class__.__name__)
            return []

        ids = (res.get("ids") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]

        out: List[Dict[str, Any]] = []
        for i, image_id in enumerate(ids):
            out.append({
                "id": image_id,
                "distance": dists[i] if i < len(dists) else None,
                "metadata": metas[i] if i < len(metas) else {},
                "caption": (docs[i] if i < len(docs) else "") or "",
            })
        return out

    # ---------------- 删 ----------------

    def delete_by_file(self, file_id: int) -> int:
        """删除某文件的全部图片，返回删除条数（Chroma 不返回计数，这里返回删除前的数量）。"""
        col = self._get_collection()
        if col is None:
            return 0
        try:
            existing = col.get(where={"file_id": int(file_id)}, include=[])
            n = len(existing.get("ids") or [])
            if n:
                col.delete(where={"file_id": int(file_id)})
            return n
        except Exception as exc:  # noqa: BLE001
            logger.info("[MM] 图像删除失败 file_id=%s：%s", file_id, exc.__class__.__name__)
            return 0
