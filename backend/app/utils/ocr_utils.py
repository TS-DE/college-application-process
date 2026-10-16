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
  · OCR 模型不可用（首选 qwen-vl-ocr，失败时重试一次，仍失败则回落到
    MULTIMODAL_VLM_MODEL 指定的视觉模型）
  · 两条路都失败 → 返回空字符串，日志明确打印「OCR 失败：{error}」，上传流程继续（不会 500）
  · 页数超过 OCR_MAX_PAGES → 只处理前 N 页，避免上传接口被拖到超时
  · **禁止在循环里无限重试同一张图**：单页最多重试 OCR_PAGE_RETRY 次（默认 1 次）

## 通道说明（★ 容易踩坑）
OCR 通道与文本 LLM 通道的 base_url **不是同一个**：
  · 文本 LLM / Embedding / VLM → `settings.ALI_BASE_URL`
  · OCR（qwen-vl-ocr）          → `settings.OCR_BASE_URL`
两者共用同一个 `Ali_API_KEY`，区别只在 base_url 与 model。
用错 base_url 会一直 404 / 401，OCR 永远失败。
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

# 模块加载时明确打印 OCR 通道信息，便于启动日志排查 base_url / 模型是否配对
# 注：用 warning 级别——uvicorn 默认只输出 WARNING 及以上，info 会被过滤掉
logger.warning(
    "[OCR] 通道配置：base_url=%s model=%s fallback=%s timeout=%ss retry=%s",
    settings.OCR_BASE_URL,
    settings.OCR_MODEL,
    settings.MULTIMODAL_VLM_MODEL,
    settings.OCR_TIMEOUT,
    settings.OCR_PAGE_RETRY,
)


class OCRExtractor:
    """扫描件 PDF → 文字。所有方法都不抛异常，失败降级为空字符串。"""

    def __init__(self, api_key: str = "", base_url: str = "", model: str = "") -> None:
        """
        :param api_key:  阿里云 Key，默认读 OCR_API_KEY（其默认值即 Ali_API_KEY）
        :param base_url:  OpenAI 兼容 base_url，默认 settings.OCR_BASE_URL
                         （★ 是 OCR_BASE_URL，不是 ALI_BASE_URL，两者不是同一个域名）
        :param model:    首选 OCR 模型，默认 settings.OCR_MODEL（qwen-vl-ocr）
        """
        # OCR_API_KEY 默认值就是 Ali_API_KEY，环境变量里只需配 Ali_API_KEY
        self._api_key = api_key or settings.OCR_API_KEY
        self._base_url = base_url or settings.OCR_BASE_URL
        self._model = model or settings.OCR_MODEL
        # 回落模型：首选模型不可用（额度/权限）时改用它，走 ALI_BASE_URL 文本通道
        self._fallback_model = settings.MULTIMODAL_VLM_MODEL
        self._fallback_base_url = settings.ALI_BASE_URL
        self._timeout = float(settings.OCR_TIMEOUT)
        self._retry = max(0, int(settings.OCR_PAGE_RETRY))
        self._client: Optional[object] = None       # OCR 专用客户端
        self._fallback_client: Optional[object] = None  # 回落客户端（文本通道）

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
            logger.warning("[OCR] 失败：PDF 渲染无结果（%s）", os.path.basename(path))
            return "", False

        text = self.ocr_images(images)
        if not text:
            logger.warning(
                "[OCR] 失败：全部页面识别无结果（%s，共 %d 页，已重试 %d 次/页），"
                "降级为按原文提取",
                os.path.basename(path), len(images), self._retry,
            )
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

        重试策略（★ 禁止无限重试）：
          · 单页最多重试 `OCR_PAGE_RETRY` 次（默认 1 次，即最多 2 次调用）；
          · 仍失败则跳过该页（返回空串），**不影响其他页**；
          · 首选模型（qwen-vl-ocr，OCR 通道）整体失败后，才回落到
            MULTIMODAL_VLM_MODEL（文本通道），回落也只按同样次数重试。
        """
        url = self._to_data_url(image)
        if not url:
            return ""
        prompt = "请仅输出图像中的文本内容。"

        # 候选 (模型, base_url, 客户端) 三元组；首选与回落去重，避免重复消耗额度
        attempts: List[Tuple[str, str, object]] = []
        for model, base_url in ((self._model, self._base_url),
                                (self._fallback_model, self._fallback_base_url)):
            if not model:
                continue
            client = self._get_client(base_url)
            if client is None:
                continue
            if any(model == a[0] and base_url == a[1] for a in attempts):
                continue
            attempts.append((model, base_url, client))

        if not attempts:
            logger.warning("[OCR] 第 %d 页无可用客户端（未配置 Ali_API_KEY？）", index + 1)
            return ""

        for model, base_url, client in attempts:
            for retry in range(self._retry + 1):
                text = self._call_vlm(client, model, url, prompt, max_tokens=1500)
                if text:
                    if model != self._model:
                        logger.warning("[OCR] 首选模型 %s 不可用，第 %d 页已回落 %s",
                                       self._model, index + 1, model)
                    return text
                if retry < self._retry:
                    logger.warning("[OCR] 第 %d 页 model=%s 第 %d 次失败，重试一次",
                                   index + 1, model, retry + 1)
            logger.warning("[OCR] 第 %d 页 model=%s 重试 %d 次后仍失败，跳过该页",
                           index + 1, model, self._retry)
        return ""

    def _call_vlm(self, client, model: str, image_url: str, prompt: str,
                  max_tokens: int = 1500) -> str:
        """调用阿里云视觉模型做单图识别；任何异常都返回空串（不抛）。"""
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ]}],
                max_tokens=max_tokens,
                temperature=0,
                timeout=self._timeout,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001 额度/网络/限流/超时都按失败处理
            logger.warning("[OCR] 视觉模型调用失败 model=%s：%s %s",
                           model, exc.__class__.__name__, str(exc)[:150])
            return ""

    # ---------------- 内部工具 ----------------

    def _get_client(self, base_url: str):
        """按 base_url 延迟创建 OpenAI 兼容客户端（避免导入即失败，结果缓存）。"""
        cache = self._fallback_client if base_url == self._fallback_base_url else self._client
        if cache is not None:
            return cache
        if not self._api_key:
            return None
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self._api_key,   # 即 Ali_API_KEY
                base_url=base_url,       # ★ OCR 用 OCR_BASE_URL，回落用 ALI_BASE_URL
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("[OCR] OpenAI 客户端创建失败 base_url=%s：%s",
                        base_url, exc.__class__.__name__)
            return None
        if base_url == self._fallback_base_url:
            self._fallback_client = client
        else:
            self._client = client
        return client

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
