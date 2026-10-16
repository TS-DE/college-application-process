"""图像检索器（0.10.0 以文搜图）：合成复用提取 / 编码 / 存储 / VLM 四者。

## 定位（合成复用，而非继承）
本类自己不实现任何底层能力，而是把
`ImageExtractor` / `BaseImageEncoder` / `ImageStore` / `VLMClient` 组合起来，
对外只暴露三个方法：
  · `should_trigger(question)`  关键词触发判断
  · `retrieve(question, top_k)` 纯检索，返回图片列表
  · `answer(question)`          检索 + VLM 解读，返回完整回答

这样调用方（rag_service）只依赖这一个类，不知道也不需要知道内部有四个协作者（迪米特法则）。

## 关键词触发（本次唯一多模态方向）
只有问题命中「图 / 照片 / 课程表 / 培养方案 / 校园 …」等词才走图像通道，
其余问题仍走 0.9.1 的三路融合。避免给每个问题都白跑一次图像检索。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.multimodal.image_encoder import BaseImageEncoder, create_image_encoder
from app.services.multimodal.image_extractor import ImageExtractor
from app.services.multimodal.image_store import ImageStore
from app.services.multimodal.vlm_client import VLMClient

logger = logging.getLogger(__name__)


class ImageRetriever:
    """以文搜图 + VLM 解读。"""

    def __init__(self, extractor: Optional[ImageExtractor] = None,
                 encoder: Optional[BaseImageEncoder] = None,
                 store: Optional[ImageStore] = None,
                 vlm: Optional[VLMClient] = None) -> None:
        """
        四个协作者都可外部注入（依赖倒置）：测试时传桩对象即可，
        不需要真实 Chroma、真实模型、真实阿里云 Key。
        """
        self.extractor = extractor or ImageExtractor()
        self.store = store or ImageStore()
        self.vlm = vlm or VLMClient()
        self._encoder = encoder  # 延迟到首次使用时创建（模型加载较重）
        self._encoder_name = ""

    # ---------------- 编码器（懒加载） ----------------

    @property
    def encoder(self) -> BaseImageEncoder:
        if self._encoder is None:
            self._encoder = create_image_encoder()
            self._encoder_name = self._encoder.name
        return self._encoder

    # ---------------- 触发判断 ----------------

    def should_trigger(self, question: str) -> bool:
        """问题是否命中多模态触发关键词。

        关键词来自 settings.MULTIMODAL_TRIGGER_KEYWORDS（逗号分隔）。
        任一命中即返回 True；配置为空或总开关关闭时返回 False。
        """
        if not settings.MULTIMODAL_ENABLED:
            return False
        keywords = [k.strip() for k in (settings.MULTIMODAL_TRIGGER_KEYWORDS or "").split(",")
                    if k.strip()]
        if not keywords:
            return False
        q = question or ""
        return any(k in q for k in keywords)

    # ---------------- 检索 ----------------

    def retrieve(self, question: str, top_k: int = 0) -> List[Dict[str, Any]]:
        """以文搜图：编码问题 → 查图像集合 → 按相关度返回图片。

        :return: [{"id", "distance", "metadata", "caption", "image_bytes"}, ...]
                 image_bytes 从磁盘按 file_path 取回（Chroma 只存向量与元数据）。
        """
        if not self.should_trigger(question):
            return []
        if not self.store.available():
            return []

        query_vec = self.encoder.encode_text(question)
        if query_vec is None:
            logger.info("[MM] 问题编码失败，跳过图像检索")
            return []

        hits = self.store.search_by_text(query_vec, top_k or settings.MULTIMODAL_TOP_K)
        for hit in hits:
            hit["image_bytes"] = self._load_image_bytes(hit.get("metadata") or {})
        return hits

    # ---------------- 问答 ----------------

    def answer(self, question: str, top_k: int = 0) -> Dict[str, Any]:
        """以文搜图 + VLM 解读。

        :return: {
            "answer": str, "source": "multimodal:image",
            "images": [{"id","page","filename","distance"}], "image_hit": bool
        }
                 未命中图片或 VLM 失败时 image_hit=False，由调用方回落到文本链路。
        """
        hits = self.retrieve(question, top_k=top_k)
        usable = [h for h in hits if h.get("image_bytes")]
        if not usable:
            return {"answer": "", "source": "multimodal:image", "images": [],
                    "image_hit": False}

        images_meta = [{
            "id": h.get("id"),
            "page": (h.get("metadata") or {}).get("page"),
            "filename": (h.get("metadata") or {}).get("filename") or "",
            "distance": h.get("distance"),
            "caption": h.get("caption") or "",
        } for h in usable]

        answer = self.vlm.generate_with_images(
            question, [h["image_bytes"] for h in usable],
        )
        if not answer:
            return {"answer": "", "source": "multimodal:image",
                    "images": images_meta, "image_hit": False}

        return {
            "answer": answer,
            "source": "multimodal:image",
            "images": images_meta,
            "image_hit": True,
        }

    # ---------------- 入库（供上传接口调用） ----------------

    def index_pdf(self, pdf_path: str, file_id: int, filename: str) -> int:
        """提取 PDF 图片 → 编码 → 入库，返回成功条数。

        上传接口在文本向量化之后调用；失败只记日志，不影响上传主流程。
        """
        if not self.store.available():
            return 0
        images = self.extractor.extract_images(pdf_path)
        if not images:
            return 0

        for img in images:
            img["file_id"] = file_id
            img["filename"] = filename

        embeddings = [self.encoder.encode_image(img["image_bytes"]) for img in images]
        written = self.store.add_images(images, embeddings, encoder_name=self.encoder.name)
        logger.info("[MM] 图片入库 file_id=%s 提取 %d 张 / 写入 %d 张",
                    file_id, len(images), written)
        return written

    def remove_file(self, file_id: int) -> int:
        """删除某文件的全部图片（供删除接口调用）。"""
        return self.store.delete_by_file(file_id)

    # ---------------- 内部工具 ----------------

    def _load_image_bytes(self, metadata: Dict[str, Any]) -> Optional[bytes]:
        """按 metadata 里的 file_id 找回原文件，再从 PDF 里裁出这张图。

        图像集合只存向量，原图要从 `knowledge_files` 记录的文件路径重新提取。
        找不到文件 / 提取失败都返回 None（该张图不参与 VLM 解读）。
        """
        file_id = metadata.get("file_id")
        if not file_id:
            return None
        try:
            from app.database import SessionLocal
            # 必须先导入 User：KnowledgeFile.uploader = relationship("User")，
            # 若 User 模型还没注册，SQLAlchemy 配 mapper 时会抛
            # "expression 'User' failed to locate a name"
            from app.models.knowledge import KnowledgeFile  # noqa: F401
            from app.models.user import User  # noqa: F401

            with SessionLocal() as db:
                record = db.get(KnowledgeFile, int(file_id))
                if record is None or not record.file_path:
                    return None
                path = record.file_path
                if (record.file_type or "").lower() != "pdf":
                    return None  # 目前只支持从 PDF 提图
                page_no = int(metadata.get("page") or 0)

            return self._extract_one_page(path, page_no)
        except Exception as exc:  # noqa: BLE001
            logger.info("[MM] 原图取回失败 file_id=%s：%s", file_id, exc.__class__.__name__)
            return None

    def _extract_one_page(self, pdf_path: str, page_no: int) -> Optional[bytes]:
        """从 PDF 指定页重新裁出图片（1-based 页码）。"""
        import os

        if not page_no or not os.path.exists(pdf_path):
            return None
        try:
            import pdfplumber

            with pdfplumber.open(pdf_path) as pdf:
                if page_no < 1 or page_no > len(pdf.pages):
                    return None
                page = pdf.pages[page_no - 1]
                # 优先取该页第一张够大的嵌图；没有则整页渲染（扫描件）
                for img in page.images:
                    raw = self.extractor._image_bytes(page, img)
                    if raw and self.extractor._big_enough(raw):
                        return raw
                import pypdfium2 as pdfium

                doc = pdfium.PdfDocument(pdf_path)
                pil = doc[page_no - 1].render(scale=1.2).to_pil().convert("RGB")
                import io

                buf = io.BytesIO()
                pil.save(buf, format="PNG")
                return buf.getvalue()
        except Exception as exc:  # noqa: BLE001
            logger.info("[MM] 页面取图失败 page=%s：%s", page_no, exc.__class__.__name__)
            return None
