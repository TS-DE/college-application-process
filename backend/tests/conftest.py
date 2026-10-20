"""pytest 统一 fixtures：把 backend/ 挂到 sys.path，并提供测试客户端与临时向量目录。

## 为什么这里只做「轻量装配」
现有测试脚本（`tests/**/test_*.py`）大量是**可直接 `python xxx.py` 运行**的脚本式用例，
它们自己做了 `sys.path` 引导与 main() 入口，不依赖 pytest。
本文件的作用是让 `pytest tests/` 也能跑起来，并为将来新增的 pytest 风格用例提供公共夹具。

## 为什么 fixture 内部才 import
`app.main` 在导入阶段会读配置、建引擎；如果在收集阶段就 import，
没配数据库的机器上连 `--collect-only` 都会失败。因此全部延迟到 fixture 首次调用。
"""
import sys
from pathlib import Path

#: backend/ 根目录（tests/conftest.py → tests → backend）
BACKEND_ROOT = Path(__file__).resolve().parents[1]

# 让 `import app.xxx` 在任何工作目录下都成立
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def backend_root() -> Path:
    """backend/ 根目录。"""
    return BACKEND_ROOT


@pytest.fixture(scope="session")
def client():
    """FastAPI 测试客户端（首次使用时才导入 app，避免收集阶段连库）。"""
    from fastapi.testclient import TestClient

    import app.main as main

    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def tmp_vector_dir(tmp_path, monkeypatch):
    """临时向量库目录：把 CHROMA_DB_PATH 指到临时目录，避免污染真实库。"""
    from app.config import settings

    vector_dir = tmp_path / "chroma"
    vector_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "CHROMA_DB_PATH", str(vector_dir), raising=False)
    return vector_dir
