"""创建 / 重置后台用户（管理员）。

用法（在 backend 目录下执行）：
    python scripts/create_admin.py                       # 默认 admin / admin123
    python scripts/create_admin.py 用户名 密码 [role]     # role: admin / student
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402
from app.utils.security import hash_password  # noqa: E402


def main() -> None:
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    password = sys.argv[2] if len(sys.argv) > 2 else "admin123"
    role = sys.argv[3] if len(sys.argv) > 3 else "admin"
    if role not in {"admin", "student"}:
        print("role 只能是 admin 或 student")
        sys.exit(1)

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(username=username, password_hash=hash_password(password), role=role)
            db.add(user)
            action = "已创建"
        else:
            user.password_hash = hash_password(password)
            user.role = role
            action = "已更新"
        db.commit()
        print(f"{action}用户：{username}（角色 {role}）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
