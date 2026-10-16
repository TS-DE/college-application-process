"""OCR 预处理（0.10.0）：扫描件 PDF 先转文字，再走现有文本 RAG。

## 为什么需要
大量招生简章 / 录取顺序资料是**扫描件**（整页一张图，没有文字层）。
pypdf 对这类文件只能提出每页 1 个字符（页码），`split_text()` 因此只能切出 1 片，
知识库等于没收录。实测《高考志愿录取顺序.pdf》：19 页、共 29 字符、平均 1 字符/页。

## 单一职责
本模块只负责「把 PDF 变成文字」：
  · `is_scanned_pdf()`      判断是不是扫描件（按页平均字符数）
  · `pdf_to_images()`       PDF 页 → 图片（用 pypdfium2，**不需要 poppler**）
  · `ocr_images()`          图片 → 文字（阿里云视觉模型，页间并发）
  · `extract_text_with_ocr_fallback()`  对外唯一入口，返回 (文本, 是否用了 OCR)

## 降级策略（任何一步失败都不抛异常）
  · OCR 模型不可用（首选 qwen-vl-ocr，额度耗尽时自动回落到 MULTIMODAL_VLM_MODEL）
  · 两条路都失败 → 返回空字符串，日志记录，上传流程继续（不会 500）
  · 页数超过 OCR_MAX_PAGES → 只处理前 N 页，避免上传接口被拖到超时

## 为什么用 pypdfium2 而不是 pdf2image
`pdf2image` 依赖系统级 poppler（Windows 上要单独装并配 PATH），
而 `pypdfium2` 是 pdfplumber 的传递依赖、自带二进制，装完即用。
"""
from __future__ import annotations

import base64
import io
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)


class OCRExtractor:
    """扫描件 PDF → 文字。所有方法都不抛异常，失败降级为空字符串。"""

    def __init__(self, api_key: str = "", base_url: str = "", model: str = "") -> None:
        """
        :param api_key:  阿里云 Key，默认读环境变量 Ali_API_KEY
        :param base_url:  OpenAI 兼容 base_url，默认 settings.ALI_BASE_URL
        :param model:    首选 OCR 模型，默认 settings.OCR_MODEL（qwen-vl-ocr）
        """
        self._api_key = api_key or os.getenv("Ali_API_KEY", "")
        self._base_url = base_url or settings.ALI_BASE_URL
        self._model = model or settings.OCR_MODEL
        # 回落模型：首选模型不可用（额度/权限）时改用它，仍是同一个 Ali 通道
        self._fallback_model = settings.MULTIMODAL_VLM_MODEL
        self._client = None

    # ---------------- 对外唯一入口 ----------------

    def extract_text_with_ocr_fallback(self, path: str) -> Tuple[str, bool]:
        """提取 PDF 文本，扫描件自动走 OCR。

        :return: (文本, 是否用了 OCR)。非 PDF / OCR 关闭 / 非扫描件时 ocr_used=False
        """
        if not settings.OCR_ENABLED:
            return "", False
        if not self.is_scanned_pdf(path):
            return "", False
        if not self._api_key:
            logger.info("[OCR] 未配置 Ali_API_KEY，跳过 OCR")
            return "", False

        images = self.pdf_to_images(path)
        if not images:
            return "", False

        text = self.ocr_images(images)
        if not text:
            logger.info("[OCR] 识别结果为空：%s", os.path.basename(path))
            return "", False

        logger.info(
            "[OCR] 扫描件识别，共 %d 页，%d 字：%s",
            len(images), len(text), os.path.basename(path),
        )
        return text, True

    # ---------------- 步骤 1：判定扫描件 ----------------

    def is_scanned_pdf(self, path: str) -> bool:
        """按「每页平均字符数」判断是否为扫描件。

        阈值来自 settings.OCR_SCANNED_THRESHOLD（默认 50 字/页）。
        读取失败 / 非 PDF 一律返回 False（宁可漏判，也不要误把正常 PDF 送去做昂贵的 OCR）。
        """
        try:
            from pypdf import PdfReader

            reader = PdfReader(path)
            pages = reader.pages or []
            if not pages:
                return False
            total = sum(len((p.extract_text() or "").strip()) for p in pages)
            avg = total / len(pages)
            return avg < settings.OCR_SCANNED_THRESHOLD
        except Exception as exc:  # noqa: BLE001 读不了就不是扫描件
            logger.info("[OCR] 扫描件判定失败，按非扫描件处理：%s", exc.__class__.__name__)
            return False

    # ---------------- 步骤 2：PDF 页 → 图片 ----------------

    def pdf_to_images(self, path: str, max_pages: Optional[int] = None) -> List[Image.Image]:
        """把 PDF 前 N 页渲染成图片（用 pypdfium2，无需 poppler）。

        页数上限取 settings.OCR_MAX_PAGES，防止超大 PDF 把上传接口拖到超时。
        """
        limit = max_pages or settings.OCR_MAX_PAGES
        try:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(path)
            total = len(doc)
            take = min(total, max(1, limit))
            # scale=1.5 ≈ 108 DPI：实测对 5 号字扫描件足够，且 base64 体积可控
            images = [doc[i].render(scale=1.5).to_pil().convert("RGB") for i in range(take)]
            if total > take:
                logger.info("[OCR] PDF 共 %d 页，超过上限仅处理前 %d 页", total, take)
            return images
        except Exception as exc:  # noqa: BLE001 渲染失败 → 无图可识别
            logger.info("[OCR] PDF 渲染失败：%s %s", exc.__class__.__name__, str(exc)[:150])
            return []

    # ---------------- 步骤 3：图片 → 文字 ----------------

    def ocr_images(self, images: List[Image.Image]) -> str:
        """逐页识别并拼接。页间用线程池并发（单页 20-35 秒，串行太慢）。

        并发按 settings.OCR_CONCURRENCY；单页失败只留空，不影响其他页。
        """
        if not images:
            return ""
        workers = max(1, int(settings.OCR_CONCURRENCY))
        if workers == 1 or len(images) == 1:
            parts = [self._ocr_one(img, i) for i, img in enumerate(images)]
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                parts = list(pool.map(
                    lambda pair: self._ocr_one(pair[1], pair[0]),
                    enumerate(images),
                ))
        return "\n".join(p for p in parts if p).strip()

    def _ocr_one(self, image: Image.Image, index: int) -> str:
        """识别单页，返回纯文本；失败返回空串。

        模型选择：先试首选模型（qwen-vl-ocr），额度/权限不可用时回落到
        settings.MULTIMODAL_VLM_MODEL（同一个 Ali Key 与 base_url）。
        """
        url = self._to_data_url(image)
        if not url:
            return ""
        prompt = "请识别图片中的全部文字内容，按原样输出，不要添加任何解释。"

        # 候选模型去重（首选与回落相同时只试一次，避免重复消耗额度）
        candidates: List[str] = []
        for model in (self._model, self._fallback_model):
            if model and model not in candidates:
                candidates.append(model)

        for model in candidates:
            text = self._call_vlm(model, url, prompt, max_tokens=1500)
            if text:
                if model != self._model:
                    logger.info("[OCR] 首选模型 %s 不可用，已回落 %s", self._model, model)
                return text
            logger.info("[OCR] 第 %d 页用 %s 识别失败，尝试下一个模型", index + 1, model)
        return ""

    def _call_vlm(self, model: str, image_url: str, prompt: str, max_tokens: int = 1500) -> str:
        """调用阿里云视觉模型做单图识别；任何异常都返回空串（不抛）。"""
        client = self._get_client()
        if client is None:
            return ""
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ]}],
                max_tokens=max_tokens,
                temperature=0,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001 额度/网络/限流都按失败处理
            logger.info("[OCR] 视觉模型调用失败 model=%s：%s %s",
                        model, exc.__class__.__name__, str(exc)[:150])
            return ""

    # ---------------- 内部工具 ----------------

    def _get_client(self):
        """延迟创建 OpenAI 兼容客户端（避免导入即失败）。"""
        if self._client is not None:
            return self._client
        if not self._api_key:
            return None
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        except Exception as exc:  # noqa: BLE001
            logger.info("[OCR] OpenAI 客户端创建失败：%s", exc.__class__.__name__)
            return None
        return self._client

    @staticmethod
    def _to_data_url(image: Image.Image) -> str:
        """PIL 图片 → base64 data URL（PNG）。超长边先缩放，控制请求体积。"""
        try:
            img = image
            side = int(settings.IMAGE_MAX_SIDE)
            longest = max(img.size)
            if longest > side:
                ratio = side / longest
                img = img.resize((max(1, int(img.size[0] * ratio)),
                                  max(1, int(img.size[1] * ratio))), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception as exc:  # noqa: BLE001
            logger.info("[OCR] 图片编码失败：%s", exc.__class__.__name__)
            return ""
