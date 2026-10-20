"""人机协同志愿规划的出入参（0.14.0）。

按**接口隔离**原则拆分：`start` 与 `resume` 的入参语义完全不同
（一个是考生信息，一个是修改意见），不共用一个「大而全」的模型。

志愿条目用 `Dict[str, Any]` 而不是强类型：
条目字段由 `recommend_service.calculate_tiers()` 产出（含 `probability` /
`rank_diff` / `reason` 等十几项），强类型化会绑死推荐引擎的内部结构调整，
这里保持「透传」，只在文档里说明关键字段。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class PlanStartIn(BaseModel):
    """生成初稿的入参。"""

    province: str = Field(..., min_length=1, description="考生省份，中文简称，如 河南")
    category: str = Field(..., min_length=1, description="科类，如 物理类 / 综合 / 理科")
    score: Optional[float] = Field(default=None, ge=0, le=750, description="高考分数")
    rank: Optional[int] = Field(default=None, ge=1, description="位次（有则优先于分数）")
    year: int = Field(default=2025, ge=2020, le=2030)
    #: 可选：考生的初步偏好（会与画像一起解析成筛选条件）
    preferences: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _need_score_or_rank(self) -> "PlanStartIn":
        """分数与位次至少给一个，否则无法换算冲稳保。

        用 `model_validator` 而不是 `model_post_init`：
        前者会正确转成 422 校验错误，后者抛出的异常会变成 500。
        """
        if not self.score and not self.rank:
            raise ValueError("score 与 rank 至少提供一个")
        return self


class PlanItemOut(BaseModel):
    """志愿条目（文档用，实际返回为 dict 透传）。"""

    university_name: Optional[str] = None
    major_name: Optional[str] = None
    school_province: Optional[str] = None
    min_score: Optional[int] = None
    min_rank: Optional[float] = None
    probability: Optional[float] = None
    tier: Optional[str] = None
    tier_label: Optional[str] = None
    tuition: Optional[int] = None
    reason: Optional[str] = None


class PlanStartOut(BaseModel):
    """初稿（此时图已暂停在 human_review）。"""

    thread_id: str
    rank: int
    draft_plan: Dict[str, List[Dict[str, Any]]]
    summary: str = ""
    intent: Dict[str, Any] = Field(default_factory=dict)
    stage: str = "draft_ready"
    elapsed_ms: int = 0
    #: 提示前端：现在轮到用户干预了
    awaiting_feedback: bool = True


class PlanResumeIn(BaseModel):
    """提交修改意见的入参。"""

    thread_id: str = Field(..., min_length=1)
    user_feedback: str = Field(default="", max_length=1000, description="自由文本修改意见")


class PlanChangeOut(BaseModel):
    """一条调整记录。"""

    action: str
    tier: str
    university: str
    major: str
    reason: str


class PlanResumeOut(BaseModel):
    """终稿。"""

    thread_id: str
    final_plan: Dict[str, List[Dict[str, Any]]]
    changes: List[Dict[str, str]] = Field(default_factory=list)
    feedback_parsed: Dict[str, Any] = Field(default_factory=dict)
    note: str = ""
    rank: Optional[int] = None
    stage: str = "final_ready"
    elapsed_ms: int = 0


class PlanStateOut(BaseModel):
    """会话现场（前端刷新后可恢复）。"""

    thread_id: str
    stage: str = ""
    rank: Optional[int] = None
    draft_plan: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    final_plan: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    changes: List[Dict[str, str]] = Field(default_factory=list)
    note: str = ""
    awaiting_feedback: bool = False


__all__ = [
    "PlanStartIn",
    "PlanStartOut",
    "PlanResumeIn",
    "PlanResumeOut",
    "PlanStateOut",
    "PlanItemOut",
    "PlanChangeOut",
]
