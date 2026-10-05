"""文件处理工具：UUID 重命名保存 + 文本提取（PDF / DOCX / TXT）。"""
import os
import uuid

from app.config import settings

ALLOWED_EXTS = {".pdf", ".txt", ".docx"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

TYPE_MAP = {
    ".pdf": "pdf",
    ".txt": "txt",
    ".docx": "docx",
}


def ensure_dir() -> str:
    os.makedirs(settings.KNOWLEDGE_DIR, exist_ok=True)
    return settings.KNOWLEDGE_DIR


def ext_of(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def is_allowed(filename: str) -> bool:
    return ext_of(filename) in ALLOWED_EXTS


def save_upload_file(content: bytes, original_filename: str) -> tuple[str, str]:
    """保存上传内容，返回 (stored_filename, file_path)。

    stored_filename 使用 UUID 重命名，避免冲突与路径遍历。
    """
    ext = ext_of(original_filename)
    safe_original = os.path.basename(original_filename).replace(" ", "_")
    stored = f"{uuid.uuid4().hex}_{safe_original}"
    if ext and not stored.endswith(ext):
        stored += ext
    directory = ensure_dir()
    path = os.path.join(directory, stored)
    with open(path, "wb") as f:
        f.write(content)
    return stored, path


def file_type_of(filename: str) -> str:
    return TYPE_MAP.get(ext_of(filename), ext_of(filename).lstrip(".") or "unknown")


def extract_text(file_path: str, file_type: str) -> str:
    """按类型提取纯文本。"""
    ext = (file_type or ext_of(file_path)).lower().lstrip(".")
    if ext == "pdf":
        return _extract_pdf(file_path)
    if ext == "docx":
        return _extract_docx(file_path)
    return _extract_txt(file_path)


def _extract_txt(file_path: str) -> str:
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _extract_pdf(file_path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(file_path)
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(file_path: str) -> str:
    from docx import Document

    doc = Document(file_path)
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def split_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """按字数切分，默认 500 字一片、重叠 50 字。"""
    size = size or settings.CHUNK_SIZE
    overlap = overlap or settings.CHUNK_OVERLAP
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = max(1, size - overlap)
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + size])
        start += step
    return chunks
