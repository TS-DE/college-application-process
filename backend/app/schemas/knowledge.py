from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class KnowledgeFileOut(BaseModel):
    id: int
    filename: str
    stored_filename: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    upload_time: Optional[datetime] = None
    chunk_count: int = 0
    status: Optional[str] = None
    uploaded_by: Optional[int] = None
    uploader_name: Optional[str] = None

    class Config:
        from_attributes = True


class KnowledgeListOut(BaseModel):
    code: int = 200
    msg: str = "ok"
    total: int = 0
    data: List[KnowledgeFileOut] = []


class ChunkHit(BaseModel):
    text: str
    metadata: dict = {}
    distance: Optional[float] = None


class SearchOut(BaseModel):
    code: int = 200
    msg: str = "ok"
    query: str
    data: List[ChunkHit] = []
