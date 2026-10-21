"""对话域入口：本地问答（chat）、云端心理师（counselor）、环境状态（status）、结构化意图（intent）。

0.17.1 起按端点职责拆成 4 个 router，chat_router 只保留 /chat。
"""

from app.api.chat.chat_router import router as chat_router
from app.api.chat.counselor_router import router as counselor_router
from app.api.chat.intent_router import router as intent_router
from app.api.chat.status_router import router as status_router

__all__ = ["chat_router", "counselor_router", "status_router", "intent_router"]
