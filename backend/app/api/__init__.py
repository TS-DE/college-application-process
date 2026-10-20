"""入口层：所有 APIRouter 在此汇总，供 main.py 一处注册。

0.17.0 起 router 按业务域分目录（account / chat / knowledge / plan / recommend），
只做参数校验与异常映射，业务逻辑全部在 services/。
"""
from app.api.account.auth_router import router as auth_router
from app.api.account.profile_router import router as profile_router
from app.api.chat.chat_router import router as chat_router
from app.api.chat.counselor_router import router as counselor_router
from app.api.knowledge.knowledge_router import router as knowledge_router
from app.api.knowledge.rag_eval_router import router as rag_eval_router
from app.api.plan.plan_router import router as plan_router
from app.api.recommend.meta_router import router as meta_router
from app.api.recommend.recommend_router import router as recommend_router
from app.api.recommend.stats_router import router as stats_router
from app.api.recommend.student_router import router as student_router
from app.api.recommend.university_router import router as university_router

#: 注册顺序与 0.16.0 保持一致（不影响功能，但能保证 OpenAPI 文档顺序不变）
ALL_ROUTERS = (
    student_router,
    recommend_router,
    university_router,
    meta_router,
    chat_router,
    counselor_router,
    stats_router,
    auth_router,
    knowledge_router,
    rag_eval_router,
    profile_router,
    plan_router,
)

__all__ = ["ALL_ROUTERS"]
