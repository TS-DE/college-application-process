"""用户画像仓储层（0.12.0）。

## 依赖倒置原则（DIP）的落地
`ProfileService` 依赖的是抽象类 `BaseProfileRepository`，
而不是具体的 SQLAlchemy Session 或 MySQL 表。
好处：
  · 单元测试可以注入 `InMemoryProfileRepository`（见测试脚本），无需连库；
  · 将来换存储（比如 MongoDB / Redis 缓存）只需新增一个实现类，
    Service 层一行都不用改。

## 单一职责
本层只负责「怎么存取」，不做任何 Prompt 组装、特征提取或业务判断；
那些都在 `service.py` 与 `extractors.py`。
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.profile import UserProfile
from app.models.user import User

logger = logging.getLogger(__name__)


class BaseProfileRepository(ABC):
    """画像仓储抽象接口（接口隔离：只暴露画像需要的方法）。"""

    @abstractmethod
    def get(self, user_id: int) -> Optional[UserProfile]:
        """取画像；不存在返回 None。"""

    @abstractmethod
    def get_or_create(self, user_id: int) -> UserProfile:
        """取画像，不存在则创建空画像。"""

    @abstractmethod
    def save(self, user_id: int, **fields: Any) -> UserProfile:
        """更新指定字段并提交（不存在则先创建）。"""

    @abstractmethod
    def delete(self, user_id: int) -> bool:
        """删除画像；返回是否真的删掉了一条。"""

    @abstractmethod
    def update_user(self, user_id: int, **fields: Any) -> Optional[User]:
        """更新账号表的基础资料字段（昵称/手机号等）。"""


class ProfileRepository(BaseProfileRepository):
    """MySQL 实现（依赖注入 Session，生命周期由调用方控制）。"""

    def __init__(self, session: Session) -> None:
        self._db = session

    # ---------------- 画像 ----------------

    def get(self, user_id: int) -> Optional[UserProfile]:
        return self._db.scalar(
            select(UserProfile).where(UserProfile.user_id == int(user_id))
        )

    def get_or_create(self, user_id: int) -> UserProfile:
        profile = self.get(user_id)
        if profile is not None:
            return profile
        profile = UserProfile(
            user_id=int(user_id),
            basic_info={},
            survey_answers={},
            summary_text="",
            source="",
        )
        self._db.add(profile)
        self._db.commit()
        self._db.refresh(profile)
        return profile

    def save(self, user_id: int, **fields: Any) -> UserProfile:
        profile = self.get_or_create(user_id)
        for key, value in fields.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        self._db.commit()
        self._db.refresh(profile)
        return profile

    def delete(self, user_id: int) -> bool:
        profile = self.get(user_id)
        if profile is None:
            return False
        self._db.delete(profile)
        self._db.commit()
        return True

    # ---------------- 账号资料 ----------------

    def update_user(self, user_id: int, **fields: Any) -> Optional[User]:
        """只更新白名单字段，避免误改 password_hash / role。"""
        allowed = {"nickname", "phone", "gender", "birthday", "email"}
        user = self._db.get(User, int(user_id))
        if user is None:
            return None
        for key, value in fields.items():
            if key in allowed and hasattr(user, key):
                setattr(user, key, value)
        self._db.commit()
        self._db.refresh(user)
        return user

    def get_user(self, user_id: int) -> Optional[User]:
        return self._db.get(User, int(user_id))


# ---------------------------------------------------------------- 测试用实现


class InMemoryProfileRepository(BaseProfileRepository):
    """纯内存实现（单元测试 / 演示用，不依赖数据库）。

    说明：返回的是轻量对象而不是 ORM 实例——测试只关心字段值，
    不需要真的走 SQLAlchemy 会话。
    """

    class _Row:
        def __init__(self, user_id: int) -> None:
            self.user_id = user_id
            self.basic_info: Dict[str, Any] = {}
            self.external_reports: Optional[str] = None
            self.survey_answers: Dict[str, Any] = {}
            self.summary_text: str = ""
            self.source: str = ""
            self.updated_at = None

        def __repr__(self) -> str:  # pragma: no cover - 调试用
            return f"<ProfileRow user={self.user_id}>"

    def __init__(self) -> None:
        self._rows: Dict[int, InMemoryProfileRepository._Row] = {}
        self._users: Dict[int, Dict[str, Any]] = {}

    def get(self, user_id: int):
        return self._rows.get(int(user_id))

    def get_or_create(self, user_id: int):
        row = self._rows.get(int(user_id))
        if row is None:
            row = self._Row(int(user_id))
            self._rows[int(user_id)] = row
        return row

    def save(self, user_id: int, **fields: Any):
        row = self.get_or_create(user_id)
        for key, value in fields.items():
            if hasattr(row, key):
                setattr(row, key, value)
        return row

    def delete(self, user_id: int) -> bool:
        return self._rows.pop(int(user_id), None) is not None

    def update_user(self, user_id: int, **fields: Any):
        data = self._users.setdefault(int(user_id), {})
        for key in ("nickname", "phone", "gender", "birthday", "email"):
            if key in fields:
                data[key] = fields[key]
        return data

    def get_user(self, user_id: int):
        return self._users.get(int(user_id))


__all__ = [
    "BaseProfileRepository",
    "ProfileRepository",
    "InMemoryProfileRepository",
]
