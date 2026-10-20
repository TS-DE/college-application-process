"""高考志愿填报系统 · FastAPI 入口（app 包）。

启动：
    cd backend
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""
import asyncio
import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.config import settings
from app.database import TableNotFound, ensure_columns, ensure_indexes, ensure_tables
from app.routers import (
    ai,
    auth,
    eval as eval_router,
    knowledge,
    meta,
    profile as profile_router,
    recommend,
    stats,
    student,
    university,
)

app = FastAPI(
    title="高考志愿填报系统",
    description="河南 2024-2025 录取数据冲稳保推荐 + RAG 知识库（Ollama / Chroma）",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 业务路由
app.include_router(student.router)
app.include_router(recommend.router)
app.include_router(university.router)
app.include_router(meta.router)
app.include_router(ai.router)
# 统计（首页地图）
app.include_router(stats.router)
# 鉴权与知识库（RAG）
app.include_router(auth.router)
app.include_router(knowledge.router)
# RAG 量化评估（0.8.0）
app.include_router(eval_router.router)
# 用户画像（0.12.0）
app.include_router(profile_router.router)


# 健康检查缓存：避免每次 /api/health 都探测 Ollama / Chroma，防止 AI 通道拖慢非 AI 接口
_HEALTH_CACHE: Dict[str, Any] = {
    "time": 0.0,
    "data": {"status": "ok", "database": settings.DB_NAME, "ollama": False, "ollama_message": "探测中", "rag": {"ready": None}},
}
_HEALTH_TTL_SECONDS = 5.0


async def _background_indexes() -> None:
    """后台补建索引 + 建表 + 补列，不阻塞服务启动。

    0.12.0：新增 `ensure_tables()`，负责创建 `user_profiles`。
    顺序很关键——先建表（画像表有指向 users 的外键），再补列（users 新字段）。
    """
    try:
        tables = await run_in_threadpool(ensure_tables)
        if tables:
            print(f"[startup] 已建表：{', '.join(tables)}")
        created = await run_in_threadpool(ensure_indexes)
        if created:
            print(f"[startup] 已创建索引：{', '.join(created)}")
        # 0.10.0：knowledge_files 新增 ocr_used / image_count
        # 0.12.0：users 新增 nickname / phone / gender / birthday / email
        added = await run_in_threadpool(ensure_columns)
        if added:
            print(f"[startup] 已补列：{', '.join(added)}")
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] 索引/建表检查跳过：{exc}")


async def _background_rag_info() -> None:
    """后台采集 RAG 状态，不阻塞主线程。"""
    try:
        from app.services import rag_service

        info = await run_in_threadpool(rag_service.backend_info)
        print(
            f"[startup] RAG: store={info['vector_store']} model={info['embedding_model']} "
            f"ready={info['ready']}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] RAG 初始化跳过：{exc}")


def _log_ocr_channel() -> None:
    """0.10.0：启动时明确打印 OCR 通道的 base_url 与模型名，便于排查配置是否配对。

    OCR 通道与文本 LLM 通道的 base_url **不是同一个域名**（用错会一直 404/401），
    而 ocr_utils 是懒加载，不在启动时 import，所以这里显式打印。
    """
    if not settings.OCR_ENABLED:
        print("[startup] OCR: 已关闭（OCR_ENABLED=0）")
        return
    print(
        f"[startup] OCR: base_url={settings.OCR_BASE_URL} model={settings.OCR_MODEL} "
        f"fallback={settings.MULTIMODAL_VLM_MODEL}@ALI_BASE_URL "
        f"timeout={settings.OCR_TIMEOUT}s retry={settings.OCR_PAGE_RETRY} "
        f"key={'set' if settings.OCR_API_KEY else 'EMPTY'}"
    )


_NEO4J_CANDIDATE_DIRS = (
    r"E:\Neo4j_NOSQL",
    r"E:\neo4j",
    r"D:\neo4j",
    r"C:\neo4j",
)


def _find_neo4j_bat() -> str:
    """尽量找到本项目机器上的 neo4j.bat，好在警告里直接给出可复制的命令。

    找不到就返回空串，由调用方给出通用示例。
    """
    import os

    for root in _NEO4J_CANDIDATE_DIRS:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            if "neo4j.bat" in filenames:
                return os.path.join(dirpath, "neo4j.bat")
            # 只在浅层找，避免大目录全盘遍历拖慢启动
            if dirpath.count(os.sep) - root.count(os.sep) >= 3:
                _dirnames[:] = []
    return ""


def _check_neo4j_sync() -> None:
    """检测 Neo4j 连通性，不可用时打印**红色**警告（0.13.0）。

    为什么做成启动检查：
    图谱通道不可用时，Agent 的 `tool_search_graph` 会被静默排除，
    用户只看到「图谱没命中」，很难联想到是 Neo4j 没启动。
    在启动日志里红字提示 + 给出启动命令，能省掉大量排查时间。
    """
    if not settings.GRAPH_ENABLED:
        print("[startup] 知识图谱：已关闭（GRAPH_ENABLED=0），问答只用向量库 + 数据库")
        return

    try:
        from app.services.graph.graph_store import GraphStore

        GraphStore().get_schema()
        print(f"[startup] Neo4j 连接正常（{settings.NEO4J_URI}），知识图谱可用")
    except Exception as exc:  # noqa: BLE001 连接失败就是没启动，不需要细分异常类型
        bat = _find_neo4j_bat()
        hint = (
            f'请执行："{bat}" console'
            if bat
            else r"请执行：<Neo4j安装目录>\bin\neo4j.bat console"
        )
        red = "\033[91m"
        reset = "\033[0m"
        print(
            f"{red}[WARN] Neo4j 未启动！知识图谱功能将不可用。"
            f"{reset}\n"
            f"{red}       {hint}{reset}\n"
            f"{red}       连接串：{settings.NEO4J_URI}  原因：{exc.__class__.__name__}{reset}",
            flush=True,
        )


async def _background_neo4j_check() -> None:
    """后台检测 Neo4j（限时 8 秒，绝不阻塞启动）。"""
    try:
        await asyncio.wait_for(run_in_threadpool(_check_neo4j_sync), timeout=8.0)
    except asyncio.TimeoutError:
        print(
            "\033[91m[WARN] Neo4j 连接检测超时（8s）！知识图谱功能可能不可用。\033[0m",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] Neo4j 检测跳过：{exc.__class__.__name__}")


@app.on_event("startup")
async def on_startup() -> None:
    # 0.7.2：启动阶段严禁同步调用 AI / Embedding / Ollama 探测，防止前端首个请求被阻塞
    asyncio.create_task(_background_indexes())
    asyncio.create_task(_background_rag_info())
    # 0.10.0：打印 OCR 通道配置（base_url 与文本通道不同，是最常见的配错点）
    _log_ocr_channel()
    # 0.13.0：检测 Neo4j，未启动时红字提示启动命令
    asyncio.create_task(_background_neo4j_check())


async def _refresh_health() -> None:
    """后台刷新健康缓存：Ollama 与 RAG 各限时 1 秒，失败不会抛给调用方。"""
    try:
        from app.services.ai_service import ollama_health
        from app.services.rag_service import backend_info

        ok, msg = await asyncio.wait_for(
            run_in_threadpool(ollama_health), timeout=1.0
        )
        rag = await asyncio.wait_for(
            run_in_threadpool(backend_info), timeout=1.0
        )
        _HEALTH_CACHE["data"] = {
            "status": "ok",
            "database": settings.DB_NAME,
            "ollama": ok,
            "ollama_message": msg,
            "rag": rag,
        }
    except asyncio.TimeoutError:
        _HEALTH_CACHE["data"] = {
            "status": "degraded",
            "database": settings.DB_NAME,
            "ollama": False,
            "ollama_message": "AI 通道探测超时",
            "rag": {"ready": None},
        }
    except Exception as exc:  # noqa: BLE001
        _HEALTH_CACHE["data"] = {"status": "error", "database": settings.DB_NAME, "detail": str(exc)}
    # 只有后台任务真正完成（或失败）后才更新时间戳，避免前端拿到长期初始值
    _HEALTH_CACHE["time"] = asyncio.get_event_loop().time()


@app.get("/api/health")
async def health() -> dict:
    """轻量健康检查：立即返回缓存；若缓存过期则在后台刷新。

    即使 Ollama 或 Ali 通道完全不可用，本接口也应在 50ms 内返回，绝不阻塞首页与登录。
    """
    now = asyncio.get_event_loop().time()
    if now - _HEALTH_CACHE["time"] > _HEALTH_TTL_SECONDS:
        # 不等待后台任务完成：直接返回旧缓存或初始值，保证接口低延迟
        asyncio.create_task(_refresh_health())
    return _HEALTH_CACHE["data"]


@app.exception_handler(TableNotFound)
def _table_not_found(_, exc: TableNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


# 若前端已 build（frontend/dist），由后端托管，并提供 SPA 回退
FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend"
)
DIST_DIR = os.path.join(FRONTEND_DIR, "dist")

if os.path.isdir(DIST_DIR):
    INDEX_FILE = os.path.join(DIST_DIR, "index.html")

    @app.get("/{full_path:path}")
    def _spa_fallback(full_path: str):  # noqa: ANN001
        """Vue history 模式回退：/admin/knowledge 等前端路由交给前端处理；
        同时提供 dist 下的静态文件（如 /china.json）。"""
        if full_path:
            target = os.path.normpath(os.path.join(DIST_DIR, full_path))
            if target.startswith(os.path.abspath(DIST_DIR)) and os.path.isfile(target):
                return FileResponse(target)
        if os.path.exists(INDEX_FILE):
            return FileResponse(INDEX_FILE)
        raise HTTPException(status_code=404, detail="前端未构建")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
