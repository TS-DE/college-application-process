"""AI 相关出入参（0.13.0）。

接口隔离：`/chat`（本地 Agent）与 `/counselor`（云端心理师）语义完全不同，
入参模型分开定义，任一接口加字段都不影响另一个。

`/chat` 仍用 `dict` 接收（历史原因 + 字段高度可选），
`/counselor` 是新增接口，直接用强类型模型把契约固定下来。
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    """一条对话消息。"""

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class CounselorIn(BaseModel):
    """心理师对话入参。

    `messages` 是完整历史（不含 system），后端会裁剪到最近 N 条；
    只允许 user / assistant 两种角色，防止前端注入 system 覆盖人设。
    """

    messages: List[ChatMessage] = Field(..., min_length=1, max_length=40)
    #: 可选：用户明确表示「我说的这些可以记进画像」时，前端可置 true
    allow_profile_update: bool = False

    @field_validator("messages")
    @classmethod
    def _last_is_user(cls, v: List[ChatMessage]) -> List[ChatMessage]:
        if not v or v[-1].role != "user":
            raise ValueError("最后一条消息必须是 user")
        return v


class CounselorOut(BaseModel):
    """心理师回复。"""

    answer: str
    source: str = "counselor:ali"
    model: Optional[str] = None
    elapsed_ms: int = 0
    profile_injected: bool = False
    error: Optional[str] = None


class AgentChatOut(BaseModel):
    """/chat 的结构化说明（实际返回仍是 dict，这里仅作文档与前端类型参考）。"""

    answer: str
    source: str
    sources: List[str] = Field(default_factory=list)
    tool_trace: List[dict] = Field(default_factory=list)
    steps: int = 0
    elapsed_ms: int = 0
    profile_injected: bool = False
    model: Optional[str] = None


__all__ = ["ChatMessage", "CounselorIn", "CounselorOut", "AgentChatOut"]
