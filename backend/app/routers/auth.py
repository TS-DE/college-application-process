"""登录 / 注册 / 鉴权依赖。

- 使用 OAuth2PasswordBearer + python-jose(JWT) + passlib(bcrypt)
- get_current_user：解析 Token；get_current_admin：校验 role=admin
"""
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.user import (
    ChangePasswordIn,
    LoginIn,
    RegisterIn,
    TokenOut,
    UserOut,
)
from app.utils.security import (
    create_token,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# auto_error=False：由 get_current_user 自己返回 401，避免 Swagger 直接吞掉错误
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


# ---------------- 依赖注入 ----------------

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Dict:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或缺少 Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "id": int(payload.get("sub", 0)),
        "username": payload.get("username", ""),
        "role": payload.get("role", "student"),
    }


def get_current_admin(user: Dict = Depends(get_current_user)) -> Dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


# ---------------- 登录 / 注册 ----------------

async def _read_credentials(request: Request) -> tuple[str, str]:
    """同时支持 JSON 与 form 提交（Swagger 的 OAuth2 表单用得上）。"""
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        body = await request.json()
        return str(body.get("username", "")), str(body.get("password", ""))
    form = await request.form()
    return str(form.get("username", "")), str(form.get("password", ""))


@router.post("/login", response_model=TokenOut)
async def login(request: Request, db: Session = Depends(get_db)):
    username, password = await _read_credentials(request)
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_token(user.id, user.username, user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": UserOut.model_validate(user),
    }


@router.post("/register", response_model=UserOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """注册：只允许注册 student；管理员请用 scripts/create_admin.py 创建。"""
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status_code=400, detail="用户名已存在")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    role = "admin" if body.role == "admin" and settings.ALLOW_ADMIN_REGISTER else "student"
    user = User(username=body.username, password_hash=hash_password(body.password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/me", response_model=UserOut)
def me(user: Dict = Depends(get_current_user), db: Session = Depends(get_db)):
    db_user = db.get(User, user["id"])
    if db_user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return UserOut.model_validate(db_user)


@router.post("/change-password")
def change_password(
    body: ChangePasswordIn,
    user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_user = db.get(User, user["id"])
    if db_user is None or not verify_password(body.old_password, db_user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    db_user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"code": 200, "msg": "密码已更新"}
