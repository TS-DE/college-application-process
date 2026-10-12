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
    # ---------------- 0.7.1 LLM / Embedding 统一通道（★ 热修复） ----------------
    # 说明：限时模型 qwen3.7-flash-2026-07-15 只能走 OpenAI 兼容接口，
    #       base_url 必须是「工作空间专属域名」，不能是通用 dashscope 域名，也不能用 dashscope SDK。
    ALI_API_KEY: str = _env("Ali_API_KEY", "")
    ALI_BASE_URL: str = _env(
        "ALI_BASE_URL",
        "https://ws-66jxf85tc3oa6b98.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    ALI_LLM_MODEL: str = _env("ALI_LLM_MODEL", "qwen3.7-flash-2026-07-15")
    # 向量模型与大语言模型共用同一个 Key 和同一个 base_url
    ALI_EMBED_MODEL: str = _env("ALI_EMBED_MODEL", "text-embedding-v3")
    # text-embedding-v3 支持指定维度；实际维度会由 rag_service 对齐已有 Chroma 集合
    ALI_EMBED_DIMENSION: int = int(_env("ALI_EMBED_DIMENSION", "128"))
    # 线上通道超时（秒），超时即降级到本地 Ollama，避免用户干等
    ALI_TIMEOUT: float = float(_env("ALI_TIMEOUT", "30"))
    # 是否允许模型「先思考再回答」：关掉后同一请求实测 9.7s → 2.6s，默认关闭
    ALI_ENABLE_THINKING: bool = _env("ALI_ENABLE_THINKING", "0") not in {"0", "false", "False"}
    # 切片参数
    CHUNK_SIZE: int = int(_env("CHUNK_SIZE", "500"))
    CHUNK_OVERLAP: int = int(_env("CHUNK_OVERLAP", "50"))

    # ---------------- 0.5.0 多路召回（Multi-Query Recall） ----------------
    MULTI_QUERY_ENABLED: bool = _env("MULTI_QUERY_ENABLED", "1") not in {"0", "false", "False"}
    # 子查询条数上限（含原始 Query）
    MULTI_QUERY_MAX: int = int(_env("MULTI_QUERY_MAX", "4"))
    # 每条子查询在稠密/稀疏路各召回多少候选
    MULTI_QUERY_CANDIDATE_N: int = int(_env("MULTI_QUERY_CANDIDATE_N", "20"))
    # ---------------- 0.7.0 检索后优化（Re-ranking）+ 高级 RAG ----------------
    # 注：统一模型名已上移为 ALI_LLM_MODEL（0.7.1 起 Ali API Key 与 Ollama 共用一套通道）
    # 本地兜底模型（Ollama）
    OLLAMA_FALLBACK_MODEL: str = _env("OLLAMA_FALLBACK_MODEL", _env("OLLAMA_MODEL", "qwen3:1.7b"))
    # Rerank 总开关：1=开启（默认用向量余弦精排，无需额外模型）
    RERANK_ENABLED: bool = _env("RERANK_ENABLED", "1") not in {"0", "false", "False"}
    # CrossEncoder 模型路径（留空则用项目 embedding 做余弦精排；配置了则优先用 CrossEncoder）
    RERANK_MODEL: str = _env("RERANK_MODEL", "")
    # 高级 RAG 总开关与策略：auto / self_rag / corrective / standard
    ADVANCED_RAG_ENABLED: bool = _env("ADVANCED_RAG_ENABLED", "1") not in {"0", "false", "False"}
    ADVANCED_RAG_STRATEGY: str = _env("ADVANCED_RAG_STRATEGY", "auto")
    # Corrective RAG 重试次数（信息不足时重写 Query 重试）
    CORRECTIVE_MAX_RETRY: int = int(_env("CORRECTIVE_MAX_RETRY", "1"))

    # ---------------- 0.6.0 检索前预处理 + 模块化多路召回 ----------------
    # 检索前：查询重写 / 查询扩展 / 子查询分解 开关
    QUERY_REWRITE_ENABLED: bool = _env("QUERY_REWRITE_ENABLED", "1") not in {"0", "false", "False"}
    QUERY_EXPANSION_ENABLED: bool = _env("QUERY_EXPANSION_ENABLED", "1") not in {"0", "false", "False"}
    QUERY_DECOMPOSE_ENABLED: bool = _env("QUERY_DECOMPOSE_ENABLED", "1") not in {"0", "false", "False"}
    QUERY_PREPROCESS_MAX: int = int(_env("QUERY_PREPROCESS_MAX", "4"))
    # 短问句阈值：少于 N 个字认为意图已经很明确，**跳过**重写/扩展/分解（设 0 表示永不跳过）
    # 目的：检索前预处理是 1 次 LLM 往返（约 5s），短问句收益 < 代价，砍掉后整链能进 10 秒
    QUERY_PREPROCESS_MIN_LEN: int = int(_env("QUERY_PREPROCESS_MIN_LEN", "20"))
    # 检索中：多路召回融合策略 rrf / weight / round_robin
    MULTI_RECALL_FUSION: str = _env("MULTI_RECALL_FUSION", "rrf")
    # 每个通道每条 Query 召回多少候选
    MULTI_RECALL_TOPK_PER_CHANNEL: int = int(_env("MULTI_RECALL_TOPK_PER_CHANNEL", "20"))

    # ---------------- 0.8.0 RAG 量化评估与自动调优 ----------------
    # 评估模块总开关
    EVAL_ENABLED: bool = _env("EVAL_ENABLED", "1") not in {"0", "false", "False"}
    # 评估数据集目录（相对仓库根目录）
    EVAL_DATA_DIR: str = _env("EVAL_DATA_DIR", "data/eval")
    # 评估报告输出目录（相对仓库根目录）
    EVAL_REPORT_DIR: str = _env("EVAL_REPORT_DIR", "data/eval_reports")
    # 是否启用 LLM 打分指标（Faithfulness / Answer Relevance / Answer Correctness）
    # 默认关闭：本地可算的核心指标已经够用，避免额度耗尽 + API 报错影响评估流程
    EVAL_LLM_METRICS_ENABLED: bool = _env("EVAL_LLM_METRICS_ENABLED", "0") not in {"0", "false", "False"}
    # 语义相似度阈值（用于判定「召回片段是否命中标准答案」）
    EVAL_SIM_THRESHOLD: float = float(_env("EVAL_SIM_THRESHOLD", "0.65"))
    # 单次评估的检索条数
    EVAL_TOP_K: int = int(_env("EVAL_TOP_K", "5"))
    # 单次评估最大样本数（防止 LLM 链路太慢导致接口超时）
    EVAL_MAX_SAMPLES: int = int(_env("EVAL_MAX_SAMPLES", "50"))
    # 防幻觉 Prompt 版本：standard / strict（faithfulness 低时由自动调优切到 strict）
    PROMPT_VERSION: str = _env("PROMPT_VERSION", "standard")
    # 自动调优总开关
    AUTO_TUNE_ENABLED: bool = _env("AUTO_TUNE_ENABLED", "1") not in {"0", "false", "False"}
    # 自动调优白名单：只有白名单内的参数才允许被「一键应用」修改
    AUTO_TUNE_WHITELIST: str = _env(
        "AUTO_TUNE_WHITELIST",
        "CHUNK_SIZE,CHUNK_OVERLAP,MULTI_RECALL_TOPK_PER_CHANNEL,RERANK_ENABLED,RERANK_MODEL,"
        "MULTI_QUERY_ENABLED,QUERY_REWRITE_ENABLED,QUERY_EXPANSION_ENABLED,QUERY_DECOMPOSE_ENABLED,"
        "ADVANCED_RAG_ENABLED,PROMPT_VERSION",
    )

    # ---------------- 0.9.0 知识图谱双通道（向量 + 图谱融合） ----------------
    # Neo4j 连接信息（本地开发默认值，生产环境务必走 .env 覆盖）
    NEO4J_URI: str = _env("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = _env("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = _env("NEO4J_PASSWORD", "12345678")
    # 图谱通道总开关：关闭后 /api/ai/chat 走纯向量链路（向后兼容）
    GRAPH_ENABLED: bool = _env("GRAPH_ENABLED", "1") not in {"0", "false", "False"}
    # 融合层 Token 配额：总预算 4000，图谱 60% / 向量 40%
    # 注：1 token ≈ 1.5 个中文字符，故 2400 token ≈ 3600 字符
    GRAPH_MAX_TOKENS: int = int(_env("GRAPH_MAX_TOKENS", "2400"))
    VECTOR_MAX_TOKENS: int = int(_env("VECTOR_MAX_TOKENS", "1600"))
    # 实体识别双路开关：LLM 抽取路 / 词典匹配路（两路都关则图谱通道直接不可用）
    GRAPH_LLM_EXTRACT_ENABLED: bool = _env("GRAPH_LLM_EXTRACT_ENABLED", "1") not in {"0", "false", "False"}
    GRAPH_DICT_EXTRACT_ENABLED: bool = _env("GRAPH_DICT_EXTRACT_ENABLED", "1") not in {"0", "false", "False"}

    @property
    def DATABASE_URL(self) -> str:
        pwd = quote_plus(self.DB_PASSWORD)
        return (
            f"mysql+pymysql://{self.DB_USER}:{pwd}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset={self.DB_CHARSET}"
        )


settings = Settings()
