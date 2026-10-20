"""登录 / 注册 / 鉴权依赖。

- 使用 OAuth2PasswordBearer + python-jose(JWT) + passlib(bcrypt)
- get_current_user：解析 Token；get_current_admin：校验 role=admin
"""
import asyncio
import time
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
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

def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict:
    """解析 JWT 并返回用户身份（**纯 CPU 计算，不碰数据库/外部服务**）。

    0.15.0：移除原先未使用的 `db: Session = Depends(get_db)` 参数。
    它虽未被函数体引用，但 FastAPI 仍会为**每一次鉴权**从连接池取一个会话，
    在 AI 请求把线程池占满时，这一步本身就是额外的排队点。
    保持「只解码、只读 payload」是这条依赖能被高频调用的前提。
    """
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
    """注册（0.12.0：补充昵称与手机号）。

    只允许注册 student；管理员请用 scripts/create_admin.py 创建。
    昵称缺省时用用户名兜底，保证前端头像菜单永远有可展示的名字。
    """
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status_code=400, detail="用户名已存在")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    if body.phone and db.scalar(select(User).where(User.phone == body.phone)):
        raise HTTPException(status_code=400, detail="该手机号已被注册")

    role = "admin" if body.role == "admin" and settings.ALLOW_ADMIN_REGISTER else "student"
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=role,
        nickname=(body.nickname or "").strip() or body.username,
        phone=body.phone or None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


def _fetch_user(db: Session, user_id: int) -> Optional[User]:
    """同步 ORM 读取（在线程池中执行，不占用事件循环）。"""
    return db.get(User, user_id)


@router.get("/me", response_model=UserOut)
async def me(user: Dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """当前用户信息。

    0.15.0：改为 `async def` + 线程池执行 DB 访问。
    此前是同步 `def`，由 anyio 默认线程池调度；AI 请求把池子占满时，
    这个「刷新页面必调一次」的接口就要排队，前端 10 秒超时后误判掉登录。
    现在它走独立调度，并用 `AUTH_TIMEOUT_SECONDS` 兜底，超时直接 503
    （5xx 会让前端**保留 token**，而不是登出）。
    """
    _t0 = time.perf_counter()
    try:
        db_user = await asyncio.wait_for(
            run_in_threadpool(_fetch_user, db, user["id"]),
            timeout=settings.AUTH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        print(
            f"[AUTH] /me 超时 >{settings.AUTH_TIMEOUT_SECONDS}s user={user['id']}",
            flush=True,
        )
        raise HTTPException(
            status_code=503, detail="服务繁忙，请稍后重试（登录状态已保留）"
        ) from None
    finally:
        print(
            f"[AUTH] /me 耗时={(time.perf_counter() - _t0) * 1000:.0f}ms user={user['id']}",
            flush=True,
        )

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
