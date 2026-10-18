"""用户画像表 ORM（0.12.0）。

## 为什么单独一张表（单一职责）
`users` 只存「账号」相关（认证、角色），画像属于「业务档案」，
生命周期与更新频率都不同（画像会被 AI 反复读写），拆表后互不干扰。

## 双轨制的数据落点
    途径 A：上传 MBTI / 霍兰德报告 → 大模型抽特征 → `external_reports`
    途径 B：回答业务问卷          → 结构化作答   → `survey_answers`
两者最终都汇入 `summary_text`（注入 AI 的 Prompt 文本）。

`basic_info` 存注册与个人主页补充的信息快照（性别、生日、所在地等），
与 `users` 表冗余一份是为了让画像自洽：即使账号资料变更，
画像仍能还原「生成时」的上下文。
"""
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 一个用户只有一份画像（唯一约束，Service 层据此做「有则更新、无则新建」）
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        unique=True, nullable=False, index=True,
    )

    # 基础信息快照：{"nickname":..., "gender":..., "birthday":..., "province":..., "category":...}
    basic_info: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # 途径 A：大模型从报告中提取的特征（JSON 字符串，保留原始结构便于回溯）
    external_reports: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 途径 B：业务问卷作答（题目 + 答案的完整快照，便于重新生成总结）
    survey_answers: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # 最终注入 Prompt 的画像总结（人工可读的自然语言）
    summary_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 画像来源标记：report / survey / both / manual，用于前端展示与统计
    source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )
