"""高考志愿填报系统 · FastAPI 入口（app 包）。

启动：
    cd backend
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.config import settings
from app.database import TableNotFound, ensure_indexes
from app.routers import ai, auth, knowledge, meta, recommend, student, university

app = FastAPI(
    title="高考志愿填报系统",
    description="河南 2024-2025 录取数据冲稳保推荐 + RAG 知识库（Ollama / Chroma）",
    version="2.0.0",
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
# 鉴权与知识库（RAG）
app.include_router(auth.router)
app.include_router(knowledge.router)


@app.on_event("startup")
def on_startup() -> None:
    try:
        created = ensure_indexes()
        if created:
            print(f"[startup] 已创建索引：{', '.join(created)}")
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] 索引检查跳过：{exc}")

    try:
        from app.services import rag_service

        info = rag_service.backend_info()
        print(
            f"[startup] RAG: store={info['vector_store']} model={info['embedding_model']} "
            f"ready={info['ready']}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] RAG 初始化跳过：{exc}")


@app.get("/api/health")
def health() -> dict:
    from app.services.ai_service import ollama_health
    from app.services.rag_service import backend_info

    ok, msg = ollama_health()
    return {
        "status": "ok",
        "database": settings.DB_NAME,
        "ollama": ok,
        "ollama_message": msg,
        "rag": backend_info(),
    }


@app.exception_handler(TableNotFound)
def _table_not_found(_, exc: TableNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


# 若前端已 build（frontend/dist），由后端托管，并提供 SPA 回退
FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend"
)
DIST_DIR = os.path.join(FRONTEND_DIR, "dist")

if os.path.isdir(DIST_DIR):
    from fastapi.staticfiles import StaticFiles

    INDEX_FILE = os.path.join(DIST_DIR, "index.html")

    @app.get("/{full_path:path}")
    def _spa_fallback(full_path: str):  # noqa: ANN001
        """Vue history 模式回退：/admin/knowledge 等前端路由交给前端处理。"""
        if os.path.exists(INDEX_FILE):
            return FileResponse(INDEX_FILE)
        raise HTTPException(status_code=404, detail="前端未构建")

    app.mount("/assets", StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="assets")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
