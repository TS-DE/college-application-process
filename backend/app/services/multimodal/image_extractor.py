"""图片提取器（0.10.0）：从 PDF 里抽出嵌图与图注。

## 单一职责
只负责「把 PDF 里的图片拿出来」，不编码、不写库、不检索。

## 抽取策略
优先用 pdfplumber 的 `page.images` 拿**原始嵌图**（保真、体积小）；
对扫描件 PDF（整页就是一张图）会退化为「按页渲染」，
这样扫描件里的图表也能进图像库——与 OCR 走的是同一条渲染路径。
"""
from __future__ import annotations

import io
import logging
from typing import Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# 小于该边长的图片直接丢弃（图标、分割线、装饰条没有检索价值）
MIN_IMAGE_SIDE = 80


class ImageExtractor:
    """从 PDF 提取图片，返回 [{image_bytes, page, caption}, ...]。"""

    def __init__(self, min_side: int = MIN_IMAGE_SIDE) -> None:
        self._min_side = min_side

    # ---------------- 对外唯一入口 ----------------

    def extract_images(self, pdf_path: str, max_images: Optional[int] = None) -> List[Dict]:
        """提取 PDF 内嵌图片；扫措件退化为按页渲染。

        :param pdf_path:   PDF 文件路径
        :param max_images: 最多提取多少张，默认 settings.MULTIMODAL_MAX_IMAGES
        :return: [{"image_bytes": bytes, "page": int, "caption": str}, ...]
        """
        limit = max_images or settings.MULTIMODAL_MAX_IMAGES
        out: List[Dict] = []
        try:
            out = self._extract_embedded(pdf_path, limit)
        except Exception as exc:  # noqa: BLE001 嵌图提取失败 → 退化按页渲染
            logger.info("[MM] 嵌图提取失败，退化为按页渲染：%s", exc.__class__.__name__)
            out = []

        if not out:
            out = self._extract_by_render(pdf_path, limit)

        for item in out:
            item.setdefault("caption", "")
        if len(out) < limit:
            logger.info("[MM] 图片提取完成：%s 共 %d 张", pdf_path.split("\\")[-1], len(out))
        return out[:limit]

    # ---------------- 策略 1：原始嵌图 ----------------

    def _extract_embedded(self, pdf_path: str, limit: int) -> List[Dict]:
        """用 pdfplumber 抽原始嵌图（保真、体积小）。"""
        import pdfplumber

        results: List[Dict] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_no, page in enumerate(pdf.pages, start=1):
                if len(results) >= limit:
                    break
                for img in page.images:
                    if len(results) >= limit:
                        break
                    raw = self._image_bytes(page, img)
                    if raw is None:
                        continue
                    if not self._big_enough(raw):
                        continue
                    results.append({
                        "image_bytes": raw,
                        "page": page_no,
                        "caption": "",
                    })
        return results

    def _image_bytes(self, page, img: dict) -> Optional[bytes]:
        """从页面里裁出这张图并转成 PNG 字节。

        用 `page.crop(img["bbox"])` 而不是解析 `img["stream"]`：
        pdfplumber 官方推荐裁剪法，能正确处理旋转、颜色空间与各种滤镜组合，
        解析原始流则要自己处理 CMYK / 掩码 / 多位深，很容易失败。
        """
        try:
            bbox = img.get("bbox")
            if not bbox:
                return None
            cropped = page.crop(bbox)
            pil = cropped.to_image(resolution=150).original.convert("RGB")
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:  # noqa: BLE001 单张失败就跳过，不影响其他图
            return None

    # ---------------- 策略 2：按页渲染（扫描件） ----------------

    def _extract_by_render(self, pdf_path: str, limit: int) -> List[Dict]:
        """扫描件 PDF 整页就是图：按页渲染后当作图片入库。"""
        try:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(pdf_path)
            total = len(doc)
            take = min(total, limit)
            results: List[Dict] = []
            for i in range(take):
                img = doc[i].render(scale=1.2).to_pil().convert("RGB")
                if not self._big_enough_pil(img):
                    continue
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                results.append({
                    "image_bytes": buf.getvalue(),
                    "page": i + 1,
                    "caption": "",
                })
            return results
        except Exception as exc:  # noqa: BLE001
            logger.info("[MM] 按页渲染失败：%s", exc.__class__.__name__)
            return []

    # ---------------- 内部工具 ----------------

    def _big_enough(self, image_bytes: bytes) -> bool:
        try:
            from PIL import Image

            with Image.open(io.BytesIO(image_bytes)) as im:
                return min(im.size) >= self._min_side
        except Exception:  # noqa: BLE001
            return False

    def _big_enough_pil(self, image) -> bool:
        return min(image.size) >= self._min_side
