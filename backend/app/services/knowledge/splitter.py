"""文本分块：父块（500 字）与子块（120 字）的切分策略。

0.17.0 从 `services/rag_service.py` 原样拆出，**函数体与常量值均未改动**，
`rag_service` 通过 `from app.services.knowledge.splitter import ...` 保留同名引用，
因此历史调用方（含测试）无需改动。
"""
from typing import List

from app.config import settings

# ---------------- 父子块（Parent-Child Chunking）参数 ----------------
# 父块：递归分块得到的 500 字块（语义完整、适合喂给 LLM 当上下文）
# 子块：父块内部再切一次的 120 字小块（语义聚焦、适合做向量检索）
CHILD_CHUNK_SIZE = 120      # 子块大小
CHILD_CHUNK_OVERLAP = 20    # 子块重叠


# 递归分块的分隔符优先级：段落 → 换行 → 句号 → 逗号
SEPARATORS = ["\n\n", "\n", "。", "，"]


def split_text(text: str, size: int | None = None, overlap: int | None = None) -> List[str]:
    """递归分块：优先按段落 / 换行 / 句号切，保证语义完整。

    参数含义：
      - size（chunk_size=500）：每块最多 500 字，太小会丢失上下文，太大则检索粒度变粗、噪声变多
      - overlap（chunk_overlap=50）：相邻块重叠 50 字，避免一条规则被切断后两边都检索不到

    langchain_text_splitters 未安装时自动退化为定长切分（行为同改造前），链路不中断。
    """
    size = size or settings.CHUNK_SIZE          # 默认 500
    overlap = overlap or settings.CHUNK_OVERLAP  # 默认 50
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:  # 未安装依赖时的兜底
        return _split_text_fixed(text, size, overlap)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,          # 单块最大字符数
        chunk_overlap=overlap,    # 相邻块重叠字符数
        length_function=len,      # 中文按字符计数（不用 token 计数）
        is_separator_regex=False, # 分隔符是普通字符串
        separators=SEPARATORS,    # 分隔符优先级：段落 → 换行 → 句号 → 逗号
    )
    return [c for c in splitter.split_text(text) if c.strip()]


def _split_text_fixed(text: str, size: int, overlap: int) -> List[str]:
    """兜底：定长滑动窗口切分（递归分块不可用时使用）。"""
    step = max(1, size - overlap)
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + size])
        start += step
    return chunks


def split_child_text(text: str, size: int | None = None, overlap: int | None = None) -> List[str]:
    """把「父块」再切成「子块」（默认 120 字、重叠 20 字）。

    子块只用于向量检索：块越小语义越聚焦，"婚假几天"这类短查询越容易命中；
    但子块太短不适合直接喂给 LLM（上下文不完整），所以命中的子块会再回填父块。
    切分逻辑与父块一致（递归分块），依赖缺失时退化为定长切分。
    """
    size = size or CHILD_CHUNK_SIZE
    overlap = overlap or CHILD_CHUNK_OVERLAP
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:
        return _split_text_fixed(text, size, overlap)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        length_function=len,
        is_separator_regex=False,
        separators=SEPARATORS,
    )
    return [c for c in splitter.split_text(text) if c.strip()]
