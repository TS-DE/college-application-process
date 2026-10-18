"""账号相关模型（0.12.0：注册补充昵称/手机号，输出补充个人资料）。

接口隔离：
    LoginIn        登录只要账号密码
    RegisterIn     注册 = 账号密码 + 昵称 + 手机号（其余资料后补）
    UserBasicUpdateIn  个人主页改资料（全部可选，见 schemas/profile.py 的 ProfileBasicIn）
"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1)


class RegisterIn(BaseModel):
    """注册接口只允许注册普通考生，管理员由脚本创建。

    0.12.0：新增 nickname / phone。两者都不是强制的，
    但前端注册页会引导填写，缺失时由后端回退用 username 作昵称。
    """

    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=64)
    nickname: Optional[str] = Field(default=None, max_length=50)
    phone: Optional[str] = Field(default=None, max_length=20)
    role: str = "student"

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: Optional[str]) -> Optional[str]:
        """手机号只做「11 位数字」的轻量校验，不引入 phonenumbers 依赖。"""
        if v in (None, ""):
            return None
        digits = v.strip()
        if not digits.isdigit() or len(digits) != 11 or not digits.startswith("1"):
            raise ValueError("手机号格式不正确（需 11 位数字且以 1 开头）")
        return digits

    @field_validator("username")
    @classmethod
    def _check_username(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) < 2:
            raise ValueError("用户名至少 2 位")
        return v


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    # ---- 0.12.0 个人资料 ----
    nickname: Optional[str] = None
    phone: Optional[str] = None
    gender: Optional[str] = None
    birthday: Optional[date] = None
    email: Optional[str] = None
    # 展示名（昵称优先），由 ORM 的 display_name 属性提供
    display_name: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)
