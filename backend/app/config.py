"""全局配置。

所有配置项优先读取环境变量，未设置时回退到本地开发默认值。
可通过同目录下的 .env 覆盖（见 .env.example）。
"""
import os
from urllib.parse import quote_plus


def _env(key: str, default: str) -> str:
    value = os.getenv(key, default)
    # .env 里写成空的（如 CHROMA_DB_PATH=）时回退到默认值
    return value if value not in (None, "") else default


def _load_dotenv() -> None:
    """极简 .env 加载，避免额外依赖 python-dotenv。"""
    path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


class Settings:
    # ---------- 数据库 ----------
    DB_HOST: str = _env("DB_HOST", "localhost")
    DB_PORT: int = int(_env("DB_PORT", "3306"))
    DB_USER: str = _env("DB_USER", "root")
    DB_PASSWORD: str = _env("DB_PASSWORD", "123456")
    DB_NAME: str = _env("DB_NAME", "gaokao")
    DB_CHARSET: str = _env("DB_CHARSET", "utf8mb4")

    # ---------- 本地大模型 ----------
    OLLAMA_URL: str = _env("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = _env("OLLAMA_MODEL", "qwen3:1.7b")
    OLLAMA_TIMEOUT: float = float(_env("OLLAMA_TIMEOUT", "45"))
    AI_ENABLED: bool = _env("AI_ENABLED", "1") not in {"0", "false", "False", "no"}
    # 并发调用大模型的线程数（批量生成推荐理由时使用）
    AI_MAX_WORKERS: int = int(_env("AI_MAX_WORKERS", "3"))

    # ---------- 业务默认值 ----------
    DEFAULT_PROVINCE: str = _env("DEFAULT_PROVINCE", "河南")

    # 冲稳保位次缓冲：|学校最低位次 - 考生位次| <= BUFFER 视为“稳”
    # 河南考生基数大（物理类本科批约 39 万人），默认 5000。
    RANK_BUFFER: int = int(_env("RANK_BUFFER", "5000"))
    # “冲”向下、“保”向上的最大搜索倍数（相对 buffer），避免给出完全不切实际的结果
    RANK_SPAN_FACTOR: int = int(_env("RANK_SPAN_FACTOR", "8"))
    # 每档默认返回条数
    TIER_LIMIT: int = int(_env("TIER_LIMIT", "60"))

    # ---------- 服务 ----------
    HOST: str = _env("HOST", "127.0.0.1")
    PORT: int = int(_env("PORT", "8000"))
    ALLOWED_ORIGINS: list = _env("ALLOWED_ORIGINS", "*").split(",")

    # ---------- 后台鉴权（JWT） ----------
    JWT_SECRET: str = _env("JWT_SECRET", "gaokao-dev-secret-change-me")
    JWT_ALGORITHM: str = _env("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = int(_env("JWT_EXPIRE_MINUTES", "720"))
    # 是否允许通过 /api/auth/register 注册管理员（默认关闭，管理员由脚本创建）
    ALLOW_ADMIN_REGISTER: bool = _env("ALLOW_ADMIN_REGISTER", "0") not in {"0", "false", "False"}

    # ---------- RAG 知识库 ----------
    # Chroma 持久化目录（相对 backend 目录）
    CHROMA_DB_PATH: str = _env(
        "CHROMA_DB_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma_db"),
    )
    CHROMA_COLLECTION: str = _env("CHROMA_COLLECTION", "gaokao_knowledge")
    # 上传的原始文件目录
    KNOWLEDGE_DIR: str = _env(
        "KNOWLEDGE_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge_files"),
    )
    # Ollama embedding 模型（离线优先）
    OLLAMA_BASE_URL: str = _env("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_EMBED_MODEL: str = _env("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    # 备选：DashScope 千问 text-embedding-v3（需 API Key）
    DASHSCOPE_API_KEY: str = _env("DASHSCOPE_API_KEY", "")
    DASHSCOPE_EMBED_MODEL: str = _env("DASHSCOPE_EMBED_MODEL", "text-embedding-v3")
    # 切片参数
    CHUNK_SIZE: int = int(_env("CHUNK_SIZE", "500"))
    CHUNK_OVERLAP: int = int(_env("CHUNK_OVERLAP", "50"))

    @property
    def DATABASE_URL(self) -> str:
        pwd = quote_plus(self.DB_PASSWORD)
        return (
            f"mysql+pymysql://{self.DB_USER}:{pwd}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset={self.DB_CHARSET}"
        )


settings = Settings()
