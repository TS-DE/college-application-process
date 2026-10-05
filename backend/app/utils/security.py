"""安全工具：密码哈希（bcrypt）+ JWT（python-jose）。"""
import hashlib
import hmac
import os
import time
from typing import Dict, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt 只取前 72 字节，长密码先做一次 sha256 摘要避免截断
MAX_BCRYPT_BYTES = 72


def _prehash(password: str) -> bytes:
    raw = password.encode("utf-8")
    return raw if len(raw) <= MAX_BCRYPT_BYTES else hashlib.sha256(raw).hexdigest().encode("utf-8")


def hash_password(password: str) -> str:
    return pwd_context.hash(_prehash(password))


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(_prehash(password), hashed)
    except Exception:  # noqa: BLE001
        return False


def create_token(user_id: int, username: str, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + settings.JWT_EXPIRE_MINUTES * 60,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[Dict]:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


__all__ = ["hash_password", "verify_password", "create_token", "decode_token"]
