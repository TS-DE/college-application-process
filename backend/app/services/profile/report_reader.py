"""用户报告文件读取器（0.12.1）。

## 为什么单独一个类（单一职责 + 隐私隔离）
0.12.0 的用户报告上传被引导到了「知识库管理」——那是 Admin 的**公共**政策库，
普通用户的私人报告一旦进去就会被所有人检索到，属于隐私泄露。

本类只做一件事：把用户上传的报告文件转成文本，然后**立刻删除文件**。

## 与知识库链路的三处硬隔离
1. **目录隔离**：落盘在 `{UPLOAD_ROOT}/reports/`，不是 `KNOWLEDGE_DIR`；
2. **不写 Chroma**：全程不调用 `rag_service.add_documents()`、
   也不调 `ImageExtractor` / `ImageStore`——特质只进 `user_profiles` 表；
3. **不落台账**：不写 `knowledge_files` 表，知识库列表里看不到用户的报告。

## 支持格式
PDF（含扫描件，走 OCR）/ DOCX / TXT / MD / PNG / JPG / JPEG（走图片 OCR）
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# 扩展名 → 提取方式
_TEXT_EXTS = {".txt", ".md"}
_DOC_EXTS = {".docx"}
_PDF_EXTS = {".pdf"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


class ReportReadError(Exception):
    """报告读取失败（类型不支持 / 无文本 / 文件损坏）。"""


class ReportReader:
    """把报告文件读成纯文本（用完即删，不在磁盘留私人副本）。"""

    def __init__(self, max_size: int = 10 * 1024 * 1024) -> None:
        self._max_size = max_size

    # ---------------- 对外入口 ----------------

    def read(self, content: bytes, filename: str) -> str:
        """读取报告内容并返回文本；调用方负责把文本交给 ProfileService。

        :param content:  文件字节
        :param filename: 原始文件名（用于判断类型）
        :raises ReportReadError: 类型不支持 / 过大 / 提取不到文本
        """
        from app.utils.file_utils import (
            REPORT_ALLOWED_EXTS,
            ext_of,
            is_report_allowed,
            save_report_file,
        )

        original = os.path.basename(filename or "report")
        if not is_report_allowed(original):
            raise ReportReadError(
                f"不支持的文件类型，仅允许：{'、'.join(sorted(REPORT_ALLOWED_EXTS))}"
            )
        if len(content) > self._max_size:
            raise ReportReadError(
                f"文件过大，最大 {self._max_size // (1024 * 1024)}MB"
            )

        stored, path = save_report_file(content, original)
        try:
            text = self._extract(path, ext_of(original))
        finally:
            # ★ 无论成功失败都删除文件：私人报告不在服务器上过夜
            self._safe_remove(path)

        if not text or len(text.strip()) < 10:
            raise ReportReadError(
                "未能从文件中提取到足够文本（若是扫描件图片，请确认 OCR 通道可用，"
                "或改为直接粘贴报告文字）"
            )
        logger.info(
            "[PROFILE] 报告已读取并删除临时文件 user_file=%s 字符数=%d",
            stored, len(text),
        )
        return text

    # ---------------- 内部实现 ----------------

    def _extract(self, path: str, ext: str) -> str:
        """按扩展名分流提取（复用 file_utils 与 ocr_utils，不重复实现）。"""
        ext = (ext or "").lower()

        if ext in _TEXT_EXTS:
            return self._read_text(path)

        if ext in _DOC_EXTS:
            from app.utils.file_utils import _extract_docx

            return _extract_docx(path) or ""

        if ext in _PDF_EXTS:
            # 复用知识库同一条提取链：先抽文本，扫描件自动 OCR 兜底
            from app.utils.file_utils import extract_text

            text, _ocr_used = extract_text(path, "pdf")
            return text or ""

        if ext in _IMAGE_EXTS:
            from app.utils.ocr_utils import OCRExtractor

            text, _ocr_used = OCRExtractor().ocr_image_file(path)
            return text or ""

        return ""

    @staticmethod
    def _read_text(path: str) -> str:
        """读纯文本，自动尝试常见编码（GBK 报告在 Windows 上很常见）。"""
        for encoding in ("utf-8", "gb18030", "utf-16"):
            try:
                with open(path, "r", encoding=encoding) as f:
                    return f.read()
            except (UnicodeDecodeError, LookupError):
                continue
            except OSError:
                return ""
        # 最后兜底：忽略解码错误
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except OSError:
            return ""

    @staticmethod
    def _safe_remove(path: Optional[str]) -> None:
        if not path:
            return
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError as exc:  # noqa: BLE001 删不掉不能影响主流程
            logger.info("[PROFILE] 临时报告删除失败：%s", exc.__class__.__name__)


__all__ = ["ReportReader", "ReportReadError"]
