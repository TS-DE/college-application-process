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


# .env 搜索顺序（先找到的先写入，后面的只补空缺）
# ★ 0.13.0 修复：原先只读 `app/.env`，而项目真实的 `.env` 在 `backend/` 下，
#   导致 README/文档里让用户改的配置**全部不生效**（一直走 config.py 的硬编码默认值）。
#   这个 bug 极难排查：配置看起来改了、日志却还是旧值。
#   现在优先读 `backend/.env`，`app/.env` 仅作历史兼容（只补前者的空缺）。
_ENV_FILES = (
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),  # backend/.env
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),                  # backend/app/.env
)


def _load_dotenv() -> None:
    """极简 .env 加载，避免额外依赖 python-dotenv。

    用 `setdefault` 写入：**真实环境变量优先级最高**（例如 Windows 系统
    环境变量里配的 `Ali_API_KEY` 不会被 `.env` 覆盖）。
    """
    for path in _ENV_FILES:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    key = k.strip()
                    val = v.strip().strip('"').strip("'")
                    # 空值不写入，保持「空 = 用默认值」的语义
                    if key and val:
                        os.environ.setdefault(key, val)
        except OSError:
            continue


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
    # 0.13.0：本地问答模型由 qwen3:1.7b 升级为 qwen3:4b。
    # 1.7b 在「工具调用 + 多轮规划」上稳定性不足（经常不按 JSON 返回、选错工具），
    # 4b 能稳定输出 tool_calls，且响应仍在秒级，适合做本地 Agent 的执行模型。
    OLLAMA_MODEL: str = _env("OLLAMA_MODEL", "qwen3:4b")
    OLLAMA_TIMEOUT: float = float(_env("OLLAMA_TIMEOUT", "60"))
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
    # 0.12.1：上传根目录（用户报告落盘在 {UPLOAD_ROOT}/reports，与知识库物理隔离）
    UPLOAD_ROOT: str = _env(
        "UPLOAD_ROOT",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    # Ollama embedding 模型（离线优先）
    OLLAMA_BASE_URL: str = _env("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_EMBED_MODEL: str = _env("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    # ---------------- 0.7.1 LLM / Embedding 统一通道（★ 热修复） ----------------
    # 说明：必须走 OpenAI 兼容接口，base_url 是「工作空间专属域名」，
    #       不能是通用 dashscope 域名，也不能用 dashscope SDK。
    # 0.10.0：模型由限时版 qwen3.7-flash-2026-07-15 换成 qwen3.7-flash
    #       （前者的免费额度已耗尽，后者继续可用且同样支持图文输入）。
    ALI_API_KEY: str = _env("Ali_API_KEY", "")
    ALI_BASE_URL: str = _env(
        "ALI_BASE_URL",
        "https://ws-66jxf85tc3oa6b98.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    ALI_LLM_MODEL: str = _env("ALI_LLM_MODEL", "qwen3.7-flash")
    # 向量模型与大语言模型共用同一个 Key 和同一个 base_url
    ALI_EMBED_MODEL: str = _env("ALI_EMBED_MODEL", "text-embedding-v3")
    # text-embedding-v3 支持指定维度；实际维度会由 rag_service 对齐已有 Chroma 集合
    ALI_EMBED_DIMENSION: int = int(_env("ALI_EMBED_DIMENSION", "128"))
    # 线上通道超时（秒），超时即降级到本地 Ollama，避免用户干等
    ALI_TIMEOUT: float = float(_env("ALI_TIMEOUT", "30"))
    # 是否允许模型「先思考再回答」：关掉后同一请求实测 9.7s → 2.6s，默认关闭
    ALI_ENABLE_THINKING: bool = _env("ALI_ENABLE_THINKING", "0") not in {"0", "false", "False"}
    # 0.12.1：`/api/ai/chat` 整体链路超时（秒）。
    # 链路里最多串 3 次 LLM 调用（意图路由 + 图谱实体识别/Cypher + 最终生成），
    # 单次超时若不生效就会叠加到 120 秒以上，前端一直转圈。
    # 设为 100 秒留 20 秒余量给序列化与网络往返，超时直接返回 504。
    CHAT_TOTAL_TIMEOUT: float = float(_env("CHAT_TOTAL_TIMEOUT", "100"))
    # 0.12.1：图谱通道单次 LLM 超时（秒）。图谱链路要串「实体识别 + Cypher 生成」
    # 两次调用，若沿用默认 30 秒，最坏 60 秒会挤占最终生成的预算。
    # 图谱是增强项，宁可快速失败回落到 MySQL/向量，也不要拖死整条链路。
    GRAPH_LLM_TIMEOUT: float = float(_env("GRAPH_LLM_TIMEOUT", "20"))

    # ---------------- 0.17.1 多轮对话上下文 ----------------
    # 历史只用于消解指代，不参与事实判定；两个上限同时约束 Prompt 体积。
    # 4 轮 ≈ 4 次问答，足够覆盖「那学费呢」「这个学校呢」这类追问；
    # 600 字是实测下来既够用、又不会把检索资料挤出上下文窗口的取值。
    CHAT_HISTORY_MAX_TURNS: int = int(_env("CHAT_HISTORY_MAX_TURNS", "4"))
    CHAT_HISTORY_MAX_CHARS: int = int(_env("CHAT_HISTORY_MAX_CHARS", "600"))

    # ---------------- 0.15.0 认证与 AI 线程隔离 ----------------
    # ★ 背景：修复「超时掉登录」。
    #   此前 /chat、/counselor 走 FastAPI 的 anyio 默认线程池（上限 40），
    #   单次可占用 100-200 秒；几个 AI 请求就能占满，导致同步的 /auth/me
    #   排队超过前端 10 秒超时，触发误判 logout —— 一条 AI 请求就能打掉登录态。
    #
    # 认证接口的独立超时预算（秒）。前端 axios 侧按 30s 配置，
    # 后端这里再多留一倍余量，避免「前端还没超时、后端先掐断」。
    AUTH_TIMEOUT_SECONDS: int = int(_env("AUTH_TIMEOUT_SECONDS", "30"))
    # AI 专用线程池大小。与认证/普通查询彻底隔离：即使 AI 池满，认证仍可立即调度。
    # 取 8 而非更大值，是因为本机 CPU 推理并发过高只会互相拖慢（本地模型不是 IO 密集）。
    AI_THREADPOOL_SIZE: int = int(_env("AI_THREADPOOL_SIZE", "8"))
    # AI 线程池排队超过该秒数就告警，便于定位「池子被占满」的时段。
    AI_QUEUE_WAIT_WARN_SECONDS: float = float(_env("AI_QUEUE_WAIT_WARN_SECONDS", "5"))
    # 在途任务上限系数（0.15.1）：上限 = AI_THREADPOOL_SIZE × 本系数。
    # 线程池队列本身无界，池满后任务会无限排队、最终只能等超时；
    # 超过该上限直接返回 503「AI 服务繁忙」，让用户立刻得到反馈而不是白等。
    # 取 2 的含义：允许「正在跑的一批 + 等一批」，再多就说明确实过载了。
    AI_MAX_INFLIGHT_FACTOR: int = int(_env("AI_MAX_INFLIGHT_FACTOR", "2"))
    # 槽位最长持有时间（秒，0.17.1）。名额改由工作线程结束时归还后，
    # 若线程因死循环/阻塞 IO 永久挂死，名额就永远收不回来。
    # 超过该时长视为僵尸槽位，在下次准入检查时强制回收并告警。
    # 取 600 秒：远大于最慢链路（Agent 约 200 秒），不会误杀正常任务。
    AI_SLOT_MAX_HOLD_SECONDS: float = float(_env("AI_SLOT_MAX_HOLD_SECONDS", "600"))

    # ---------------- 0.13.0 本地 Agent（Function Calling） ----------------
    # 是否启用 Agent 模式（默认开启）。关闭后 /api/ai/chat 回落到 0.12.x 的三路融合，
    # 保留这条回退路径是为了「模型不支持 tools 时系统仍可用」。
    AGENT_ENABLED: bool = _env("AGENT_ENABLED", "1") not in {"0", "false", "False"}
    # 0.13.1：**极速模式**（默认开启）。
    # 实测纯 CPU 下 qwen3:4b 跑两轮 Agent 要 150 秒（规划 32-55s + 工具 + 生成 70-90s），
    # 演示不可接受；而 0.12.x 的确定性融合链路最终生成走 Ali 通道，通常 6-15 秒。
    # 默认走快速链路；把 AGENT_FAST_MODE 设为 0 才启用 Agent（用于演示工具调用能力）。
    AGENT_FAST_MODE: bool = _env("AGENT_FAST_MODE", "1") not in {"0", "false", "False"}
    # 单轮问答最多允许几轮「模型 → 工具 → 模型」，防止小模型陷入循环。
    # 默认 2：实测本机 CPU 推理单次约 20-45 秒，3 轮必然超过前端耐心上限。
    AGENT_MAX_STEPS: int = int(_env("AGENT_MAX_STEPS", "2"))
    # 单个工具的执行超时（秒）：向量检索 ~1s、MySQL ~1s、图谱可能 40s，分开给预算
    AGENT_TOOL_TIMEOUT: float = float(_env("AGENT_TOOL_TIMEOUT", "60"))
    # 规划轮 / 生成轮的 token 预算。
    #
    # ★ 0.13.1 实测（短 Prompt + /no_think + 本机 CPU）：
    #     num_predict=150 → 3/3 拿不到 tool_calls（推理吃光预算，done_reason=length）
    #     num_predict=250 → 1/2 拿到（政策类问题仍失败）
    #     num_predict=350 → 2/2 拿到，耗时 20-27s  ← 可靠下限
    #   任务书建议的 150 不可行，故取 350；配合精简 Prompt，
    #   规划轮从 0.13.0 的 32-55s 压到 20-27s。
    AGENT_PLAN_TOKENS: int = int(_env("AGENT_PLAN_TOKENS", "350"))
    # 生成轮 300：回答本身 200-300 字即可；超出就走兜底（返回清洗后的检索摘要）
    AGENT_ANSWER_TOKENS: int = int(_env("AGENT_ANSWER_TOKENS", "300"))
    # 单路工具结果喂回模型的字符上限（越长越慢）
    AGENT_TOOL_TEXT_LIMIT: int = int(_env("AGENT_TOOL_TEXT_LIMIT", "600"))
    # 分工超时：规划轮愿意等；生成轮必须快速失败——
    # 0.13.0 实测生成轮 110s 仍会超时，白等 1 分半；0.13.1 压到 25s，
    # 超时立刻返回「已为你直接提取检索结果」，整体控制在 60s 内。
    AGENT_PLAN_TIMEOUT: float = float(_env("AGENT_PLAN_TIMEOUT", "60"))
    AGENT_ANSWER_TIMEOUT: float = float(_env("AGENT_ANSWER_TIMEOUT", "25"))
    # Agent 链路整体预算：规划 27s + 工具 10s + 生成 25s ≈ 62s，留余量取 90
    AGENT_TOTAL_TIMEOUT: float = float(_env("AGENT_TOTAL_TIMEOUT", "90"))
    # 传给本地模型的候选工具条数上限（工具太多小模型会选错）
    AGENT_MAX_TOOLS: int = int(_env("AGENT_MAX_TOOLS", "8"))
    # 是否让 Agent 看到用户画像（本地模型上下文小，样本长时可关掉）
    AGENT_INJECT_PROFILE: bool = _env("AGENT_INJECT_PROFILE", "1") not in {"0", "false", "False"}

    # ---------------- 0.14.0 人机协同志愿规划（LangGraph HITL） ----------------
    # 是否允许用大模型解析用户的自由文本反馈。
    # 规则层能解析的常见说法（「不想去北京」「学费别超 6000」）不会调用模型，
    # 只有规则看不懂时才走这里，因此默认开启也不会拖慢常规操作。
    PLAN_LLM_ENABLED: bool = _env("PLAN_LLM_ENABLED", "1") not in {"0", "false", "False"}
    # 强制每次都调模型（默认关闭：规则优先，快）
    PLAN_LLM_ALWAYS: bool = _env("PLAN_LLM_ALWAYS", "0") not in {"0", "false", "False"}
    # 反馈解析的模型超时：超时就用规则层结果，不阻塞用户
    PLAN_LLM_TIMEOUT: float = float(_env("PLAN_LLM_TIMEOUT", "20"))
    # 初稿每个档位的条数上限
    PLAN_DRAFT_PER_TIER: int = int(_env("PLAN_DRAFT_PER_TIER", "8"))
    # 终稿每个档位的条数上限
    PLAN_FINAL_PER_TIER: int = int(_env("PLAN_FINAL_PER_TIER", "8"))
    # 人机回环最多几轮（0.19.0）：节点内 interrupt() 后可以反复「改 → 再改」，
    # 必须设上限，否则用户可以无限循环、每次都触发一次模型解析。
    PLAN_MAX_REVIEW_ROUNDS: int = int(_env("PLAN_MAX_REVIEW_ROUNDS", "5"))
    # Checkpointer 类型（0.19.0）：memory = 进程内（重启即丢）；sqlite = 落盘（跨重启恢复）
    PLAN_CHECKPOINTER: str = (_env("PLAN_CHECKPOINTER", "sqlite") or "sqlite").strip().lower()
    # sqlite checkpoint 文件路径（相对 backend/ 目录）
    PLAN_CHECKPOINT_DB: str = _env("PLAN_CHECKPOINT_DB", "data/plan_checkpoints.db")

    # ---------------- 0.13.0 云端「心理师」通道 ----------------
    # 心理疏导与画像采集**强制**走云端大模型（本地 4b 的情感推理能力不足），
    # 因此这里单独配置模型与超时，不走 LLMClient 的「Ali → Ollama」降级链。
    COUNSELOR_MODEL: str = _env("COUNSELOR_MODEL", "")   # 空表示沿用 ALI_LLM_MODEL
    COUNSELOR_TIMEOUT: float = float(_env("COUNSELOR_TIMEOUT", "60"))
    # 多轮上下文最多保留多少条历史（user + assistant 各算一条）
    COUNSELOR_MAX_HISTORY: int = int(_env("COUNSELOR_MAX_HISTORY", "20"))

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
    OLLAMA_FALLBACK_MODEL: str = _env("OLLAMA_FALLBACK_MODEL", _env("OLLAMA_MODEL", "qwen3:4b"))
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

    # ---------------- 0.9.1 三路融合（图谱 + MySQL + 向量） ----------------
    # MySQL 结构化查询总开关：关闭后 answer_with_hybrid 只走「图谱 + 向量」两路。
    # 开启时，学费 / 分数线 / 位次 / 选科 / 招生人数这类字段型问题直接查
    # major_admission_{year}_henan 拿精确值，不再绕道 Chroma 翻 PDF。
    MYSQL_QUERY_ENABLED: bool = _env("MYSQL_QUERY_ENABLED", "1") not in {"0", "false", "False"}
    # MySQL 单次查询最大返回行数（限制上下文长度，避免一次回传过多行）
    MYSQL_MAX_ROWS: int = int(_env("MYSQL_MAX_ROWS", "5"))

    # ---------------- 0.10.0 OCR 专用通道（base_url 与文本通道不同） ----------------
    # OCR 总开关：关闭后扫描件 PDF 仍按原方式提取（提不到文字就只能切出极少片段）
    OCR_ENABLED: bool = _env("OCR_ENABLED", "1") not in {"0", "false", "False"}
    # 首选 OCR 模型（阿里云 OpenAI 兼容接口）；不可用（如额度耗尽）时自动回落到
    # MULTIMODAL_VLM_MODEL 指定的视觉模型
    OCR_MODEL: str = _env("OCR_MODEL", "qwen-vl-ocr")
    # ★ OCR 通道的 base_url 与文本 LLM 的 ALI_BASE_URL **不是同一个**，
    #   用错会一直 404 / 401。qwen-vl-ocr 走的是独立的 MaaS 域名。
    OCR_BASE_URL: str = _env(
        "OCR_BASE_URL",
        "https://maas.qianwenaiapi.com/compatible-mode/v1",
    )
    # OCR 通道与文本 / Embedding / VLM 通道**共用同一个 Ali_API_KEY**，
    # 不再单独读取 OCR_API_KEY / DASHSCOPE_API_KEY（环境变量里已删除）。
    # 这里保留 OCR_API_KEY 读取只是为了兼容历史配置，默认可留空。
    OCR_API_KEY: str = _env("OCR_API_KEY", _env("Ali_API_KEY", ""))
    # 扫描件判定阈值：每页平均字符数低于该值即认为是扫描件，触发 OCR
    OCR_SCANNED_THRESHOLD: int = int(_env("OCR_SCANNED_THRESHOLD", "50"))
    # OCR 单次请求超时（秒）：单页识别 20-35 秒，给足余量避免读超时
    OCR_TIMEOUT: float = float(_env("OCR_TIMEOUT", "60"))
    # 单次 OCR 最多处理的页数（防止超大 PDF 把上传接口拖到超时）
    OCR_MAX_PAGES: int = int(_env("OCR_MAX_PAGES", "50"))
    # OCR 并发页数：每页都要走一次视觉模型调用，串行太慢（实测单页 20-35 秒）
    OCR_CONCURRENCY: int = int(_env("OCR_CONCURRENCY", "4"))
    # 单页识别失败时的重试次数：重试 1 次后仍失败就跳过该页，**禁止无限重试**
    OCR_PAGE_RETRY: int = int(_env("OCR_PAGE_RETRY", "1"))

    # ---------------- 0.10.0 多模态「以文搜图」 ----------------
    # 触发关键词：问题命中任一关键词才走图像检索通道，其余问题仍走三路融合
    # 注：除任务给定词表外补了「课程」——「XX 专业有哪些课程」这类问题的答案通常在
    # 培养方案 / 课程体系图里，不加这个词就以文搜图永远触发不了。
    # 触发但搜不到图时会自动回落三路融合，不会误伤纯文本问题。
    MULTIMODAL_TRIGGER_KEYWORDS: str = _env(
        "MULTIMODAL_TRIGGER_KEYWORDS",
        "图,图片,照片,截图,图表,课程表,培养方案,校园,环境,长什么样,课程体系,学分结构,流程图,课程",
    )
    # 多模态总开关：关闭后 answer_with_multimodal 直接返回 None，回落到三路融合
    MULTIMODAL_ENABLED: bool = _env("MULTIMODAL_ENABLED", "1") not in {"0", "false", "False"}
    # 图像向量集合名（与文本集合 gaokao_knowledge 分开，独立向量空间）
    IMAGE_COLLECTION: str = _env("IMAGE_COLLECTION", "gaokao_images")
    # 图像编码器优先级：clip 优先用 Chinese-CLIP（需额外安装），不可用则用
    # caption 方案（视觉模型生成图注 → 文本向量编码，无需本地模型）
    IMAGE_ENCODER: str = _env("IMAGE_ENCODER", "auto")
    # 多模态问答用的视觉语言模型（阿里云 OpenAI 兼容，支持图文输入）
    # 多模态问答用的视觉语言模型（支持图文输入）
    # 0.10.0：由限时版 qwen3.7-flash-2026-07-15 换成 qwen3.7-flash（前者额度已耗尽）
    MULTIMODAL_VLM_MODEL: str = _env("MULTIMODAL_VLM_MODEL", "qwen3.7-flash")
    # 单张图片送 VLM 前的最长边（像素）：控制 base64 体积与调用耗时
    IMAGE_MAX_SIDE: int = int(_env("IMAGE_MAX_SIDE", "1024"))
    # 单个文件最多提取并入库多少张图片（防止图多的 PDF 把上传拖到超时）
    MULTIMODAL_MAX_IMAGES: int = int(_env("MULTIMODAL_MAX_IMAGES", "30"))
    # 图像检索默认返回条数
    MULTIMODAL_TOP_K: int = int(_env("MULTIMODAL_TOP_K", "3"))

    @property
    def DATABASE_URL(self) -> str:
        pwd = quote_plus(self.DB_PASSWORD)
        return (
            f"mysql+pymysql://{self.DB_USER}:{pwd}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset={self.DB_CHARSET}"
        )


settings = Settings()
