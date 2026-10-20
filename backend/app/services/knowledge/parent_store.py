"""父块原文存储（docstore）：小块检索、大块生成。

0.17.0 从 `services/rag_service.py` 原样拆出，**函数体与常量值均未改动**。
`rag_service` 通过 `from app.services.knowledge.parent_store import ...` 保留同名引用，
历史调用方（含测试里的 `rag_service.drop_parents_by_file`）无需改动。
"""
import json
import os
from typing import Dict, List, Optional

from app.config import settings

# docstore 文件：父块原文按 parent_id 存这里，向量库只存子块（见 put_parents 注释）
PARENT_STORE_FILE = "parent_store.json"

_parent_store: Dict[str, Dict] = {}      # {parent_id: {"text":..., "file_id":...}}
_parent_store_loaded = False


def _parent_store_path() -> str:
    """docstore 落盘位置（与 Chroma 同目录，已在 .gitignore 中）。"""
    os.makedirs(settings.CHROMA_DB_PATH, exist_ok=True)
    return os.path.join(settings.CHROMA_DB_PATH, PARENT_STORE_FILE)


def _load_parent_store() -> Dict[str, Dict]:
    """首次访问时把父块原文从磁盘载入内存（幂等）。"""
    global _parent_store, _parent_store_loaded
    if _parent_store_loaded:
        return _parent_store
    try:
        path = _parent_store_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _parent_store = json.load(f)
    except Exception:  # noqa: BLE001  docstore 损坏不阻塞检索，按空库继续
        _parent_store = {}
    _parent_store_loaded = True
    return _parent_store


def _save_parent_store() -> None:
    """把父块原文持久化（每次写入/删除后调用）。"""
    try:
        with open(_parent_store_path(), "w", encoding="utf-8") as f:
            json.dump(_parent_store, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def put_parents(parents: List[Dict]) -> None:
    """批量写入父块到 docstore。

    docstore 的作用：向量库只索引 120 字的子块（检索精度高），
    父块的 500 字原文存在这里（不进向量库），检索命中子块后按 parent_id 取回，
    把完整上下文交给 LLM —— 即「小块命中、大块生成」。
    """
    store = _load_parent_store()
    for p in parents:
        store[p["parent_id"]] = p
    _save_parent_store()


def get_parent(parent_id: Optional[str]) -> Optional[Dict]:
    """按 parent_id 取回父块原文；不存在返回 None（调用方需降级返回子块）。"""
    if not parent_id:
        return None
    return _load_parent_store().get(parent_id)


def drop_parents_by_file(file_id: int) -> int:
    """删除某个文件的全部父块（与向量库删除子块配套）。"""
    store = _load_parent_store()
    keys = [k for k, v in store.items() if str(v.get("file_id")) == str(file_id)]
    for k in keys:
        store.pop(k, None)
    if keys:
        _save_parent_store()
    return len(keys)
