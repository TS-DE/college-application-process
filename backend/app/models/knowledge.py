"""知识库文件表 ORM。"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# 必须先导入 User：下面的 uploader = relationship("User") 在 SQLAlchemy 配置 mapper 时
# 才解析得到。若调用方只 import 了本模块（例如 services/multimodal 懒加载查询），
# 会抛 "expression 'User' failed to locate a name"。
from app.models.user import User  # noqa: F401  顺序敏感，勿删


class KnowledgeFile(Base):
    __tablename__ = "knowledge_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(20))
    file_size: Mapped[int | None] = mapped_column(Integer)
    upload_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="已上传")
    uploaded_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    # 0.10.0 OCR：该文件是否走了 OCR 兜底（扫描件 PDF 为 1，其余为 0）
    ocr_used: Mapped[int | None] = mapped_column(Integer, default=0)
    # 0.10.0 多模态：从该文件提取并写入 Chroma gaokao_images 的图片数量
    image_count: Mapped[int | None] = mapped_column(Integer, default=0)

    uploader = relationship("User", lazy="selectin")
