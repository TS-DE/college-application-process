"""知识库路由：上传（切片 + 向量化 + 图片入库）/ 列表 / 详情 / 删除 / 检索。

权限：上传、列表、详情、删除 仅管理员；检索（/search）开放给所有登录用户，
因为考生端 AI 助手需要调用它做 RAG。
"""
import logging
import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.knowledge import KnowledgeFile
from app.models.user import User
from app.routers.auth import get_current_admin, get_current_user
from app.schemas.knowledge import (
    ChunkHit,
    KnowledgeFileOut,
    KnowledgeListOut,
    SearchOut,
)

logger = logging.getLogger(__name__)
from app.services.rag import rag_service
from app.utils.file_utils import (
    ALLOWED_EXTS,
    MAX_FILE_SIZE,
    extract_text,
    file_type_of,
    is_allowed,
    save_upload_file,
)
# 切片改用 rag_service 的「递归分块」（RecursiveCharacterTextSplitter）
from app.services.rag.rag_service import split_text

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _delete_file_images(file_id: int) -> int:
    """0.10.0：删除文件时同步清理 Chroma 图像集合，避免残留图片被检索到。"""
    try:
        from app.services.multimodal import ImageRetriever

        return ImageRetriever().remove_file(file_id)
    except Exception as exc:  # noqa: BLE001 图像清理失败不影响文件删除
        logger.info("[MM] 图片清理跳过 file_id=%s：%s", file_id, exc.__class__.__name__)
        return 0


def _index_pdf_images(file_path: str, file_id: int, filename: str) -> int:
    """0.10.0：抽取 PDF 内嵌图片 → 编码 → 写入 Chroma 图像集合。

    独立成函数是为了不让上传接口变得过长（单一职责）；
    任何失败都只记日志返回 0，**不影响文本向量化的成功结果**——
    以文搜图是增强能力，不该让它的故障把上传整个打挂。
    """
    try:
        from app.services.multimodal import ImageRetriever

        return ImageRetriever().index_pdf(file_path, file_id, filename)
    except Exception as exc:  # noqa: BLE001 多模态模块不可用 → 跳过图片入库
        logger.info("[MM] 图片入库跳过 file_id=%s：%s", file_id, exc.__class__.__name__)
        return 0


def _to_out(r: KnowledgeFile) -> KnowledgeFileOut:
    return KnowledgeFileOut(
        id=r.id,
        filename=r.filename,
        stored_filename=r.stored_filename,
        file_type=r.file_type,
        file_size=r.file_size,
        upload_time=r.upload_time,
        chunk_count=r.chunk_count or 0,
        status=r.status,
        uploaded_by=r.uploaded_by,
        uploader_name=(r.uploader.username if r.uploader else None),
        # 0.10.0：OCR 兜底标记与入库图片数（老库可能为 NULL，统一归一成 0）
        ocr_used=r.ocr_used or 0,
        image_count=r.image_count or 0,
    )


@router.get("/status")
def rag_status(user: dict = Depends(get_current_admin)) -> dict:
    """向量库 / embedding 后端状态，便于排查。"""
    return rag_service.backend_info()


@router.post("/upload")
async def upload_knowledge(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
) -> dict:
    """上传：保存 → 提取文本 → 写库 → 切片 + 向量化 → 回写 chunk_count / status。"""
    if not is_allowed(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型，仅允许：{'、'.join(sorted(ALLOWED_EXTS))}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件过大，最大 20MB")

    original = os.path.basename(file.filename or "unnamed")
    stored_filename, file_path = save_upload_file(content, original)

    record = KnowledgeFile(
        filename=original,
        stored_filename=stored_filename,
        file_path=file_path,
        file_type=file_type_of(original),
        file_size=len(content),
        uploaded_by=current_user["id"],
        status="已上传",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # 切片 + 向量化
    ocr_used, image_count = 0, 0
    try:
        # 0.10.0：扫描件 PDF 会在这里走 OCR 兜底，返回 (文本, 是否用了 OCR)
        text, ocr_used = extract_text(file_path, record.file_type)
        chunks = split_text(text)
        written = rag_service.add_documents(
            chunks,
            {"file_id": record.id, "filename": original, "file_type": record.file_type},
            key_fmt=f"file_{record.id}_chunk_{{idx}}",
        )
        record.chunk_count = written
        record.status = "已向量化" if written else "失败"
        if not chunks:
            record.status = "失败"
        record.ocr_used = 1 if ocr_used else 0

        # 0.10.0 多模态：文本向量化成功后，再抽取 PDF 内嵌图片写入独立图像集合
        if record.status == "已向量化" and record.file_type == "pdf":
            image_count = _index_pdf_images(file_path, record.id, original)
            record.image_count = image_count
    except Exception as exc:  # noqa: BLE001 单个文件失败不影响列表
        record.status = "失败"
        record.chunk_count = 0
        db.commit()
        raise HTTPException(status_code=500, detail=f"解析或向量化失败：{exc}")

    db.commit()
    db.refresh(record)
    return {"code": 200, "msg": "上传并向量化成功", "file_id": record.id, "data": _to_out(record)}


@router.get("/list", response_model=KnowledgeListOut)
def list_knowledge(
    keyword: str = Query("", description="按文件名搜索"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    stmt = select(KnowledgeFile)
    if keyword.strip():
        stmt = stmt.where(KnowledgeFile.filename.like(f"%{keyword.strip()}%"))
    rows = db.scalars(stmt.order_by(KnowledgeFile.upload_time.desc(), KnowledgeFile.id.desc())).all()
    return KnowledgeListOut(total=len(rows), data=[_to_out(r) for r in rows])


@router.get("/detail/{file_id}", response_model=KnowledgeFileOut)
def detail_knowledge(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    r = db.get(KnowledgeFile, file_id)
    if r is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    return _to_out(r)


@router.get("/download/{file_id}")
def download_knowledge(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    r = db.get(KnowledgeFile, file_id)
    if r is None or not os.path.exists(r.file_path):
        raise HTTPException(status_code=404, detail="文件不存在或已丢失")
    return FileResponse(r.file_path, filename=r.filename)


@router.delete("/delete/{file_id}")
def delete_knowledge(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
) -> dict:
    r = db.get(KnowledgeFile, file_id)
    if r is None:
        raise HTTPException(status_code=404, detail="文件不存在")

    rag_service.delete_by_file(file_id)  # 先删文本向量
    _delete_file_images(file_id)          # 0.10.0：再删图像集合里的图片
    if r.file_path and os.path.exists(r.file_path):
        try:
            os.remove(r.file_path)
        except OSError:
            pass
    db.delete(r)
    db.commit()
    return {"code": 200, "msg": "删除成功"}


@router.get("/search", response_model=SearchOut)
def search_knowledge(
    query: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
    current_user: dict = Depends(get_current_user),
) -> SearchOut:
    """检索（供考生端 AI 助手做 RAG）。所有登录用户可用。"""
    hits = rag_service.search(query, top_k)
    return SearchOut(
        query=query,
        data=[
            ChunkHit(
                text=h["text"],
                metadata=h.get("metadata", {}),
                distance=h.get("distance"),
                # 混合检索融合信息：便于前端/排查时对比两路召回
                rrf_score=h.get("rrf_score"),
                dense_rank=h.get("dense_rank"),
                bm25_rank=h.get("bm25_rank"),
                # 父子块：命中的子块所属父块，以及返回的上下文粒度
                parent_chunk_id=h.get("parent_chunk_id"),
                context_level=h.get("context_level"),
            )
            for h in hits
        ],
    )
