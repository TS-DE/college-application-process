"""用户表 ORM（0.12.0：补齐个人资料字段）。

新增字段（对应「右上角完善基础信息」）：
    nickname  昵称（展示用，可与 username 不同）
    phone     手机号（唯一，可用作找回凭据）
    gender    性别（male / female / other，空表示未填）
    birthday  生日（日期，用于推算年龄/考生身份）
    email     邮箱

> 迁移方式：项目没有 `Base.metadata.create_all()`，新增列由
> `app.database.ensure_columns()` 在启动时幂等 ALTER（见 `_COLUMN_MIGRATIONS`）。
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(Enum("admin", "student", name="user_role"), default="student")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # ---- 0.12.0 个人资料 ----
    nickname: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    gender: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    birthday: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    @property
    def display_name(self) -> str:
        """展示名：优先昵称，其次用户名（避免前端到处写 `nickname || username`）。"""
        return (self.nickname or "").strip() or self.username
