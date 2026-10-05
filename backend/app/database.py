"""数据库连接与动态表反射。

数据集按「省份 + 年份」拆表（如 major_admission_2025_henan），
表结构相同但表名动态，因此这里用 SQLAlchemy Core 反射，而不是写死 ORM 模型；
业务表（users / knowledge_files）则用 ORM（见 app.models）。
"""
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.engine import Engine, Result
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine: Engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=5,
    max_overflow=10,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """ORM 基类（users / knowledge_files）。"""


def get_db():
    """FastAPI 依赖：会话生命周期与请求一致。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


metadata = MetaData()
_table_cache: Dict[str, Table] = {}


class TableNotFound(Exception):
    pass


def get_table(name: str) -> Table:
    """反射并缓存一张表，避免每次请求都查 information_schema。"""
    if name in _table_cache:
        return _table_cache[name]
    try:
        tbl = Table(name, metadata, autoload_with=engine)
    except Exception as exc:  # noqa: BLE001
        raise TableNotFound(f"数据表不存在或无法反射：{name}（{exc}）") from exc
    _table_cache[name] = tbl
    return tbl


def rows_to_dicts(result: Result) -> List[Dict[str, Any]]:
    return [dict(row._mapping) for row in result]


def fetch_all(stmt) -> List[Dict[str, Any]]:
    with engine.connect() as conn:
        return rows_to_dicts(conn.execute(stmt))


def fetch_one(stmt) -> Optional[Dict[str, Any]]:
    rows = fetch_all(stmt)
    return rows[0] if rows else None


def fetch_all_params(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """带参数的原生 SQL 查询，返回 dict 列表。"""
    with engine.connect() as conn:
        return rows_to_dicts(conn.execute(text(sql), params or {}))


def fetch_one_params(sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    rows = fetch_all_params(sql, params)
    return rows[0] if rows else None


def table_exists(name: str) -> bool:
    sql = text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = :db AND table_name = :t LIMIT 1"
    )
    with engine.connect() as conn:
        return conn.execute(sql, {"db": settings.DB_NAME, "t": name}).first() is not None


# 需要加速的索引：按 (科类, 批次, 位次/分数) 查询是最主要的热点
_INDEXES: Dict[str, str] = {
    "major_admission": "category(16), batch(16), min_rank",
    "school_admission": "category(16), batch(16), min_rank",
    "score_range": "category(16), batch(16), score",
    "enrollment_plan": "category(16), batch(16), university_code, major_code",
}


def ensure_indexes(kinds: Sequence[str] = tuple(_INDEXES.keys())) -> List[str]:
    """为已导入的表补索引（幂等）。TEXT 列必须指定前缀长度。"""
    created: List[str] = []
    with engine.begin() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :db"
                ),
                {"db": settings.DB_NAME},
            )
        ]
        for tname in tables:
            kind = next((k for k in kinds if tname.startswith(k)), None)
            if kind is None:
                continue
            idx = f"idx_{tname}"
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.statistics "
                    "WHERE table_schema = :db AND table_name = :t AND index_name = :i LIMIT 1"
                ),
                {"db": settings.DB_NAME, "t": tname, "i": idx},
            ).first()
            if exists:
                continue
            try:
                conn.execute(
                    text(f"CREATE INDEX `{idx}` ON `{tname}` ({_INDEXES[kind]})")
                )
                created.append(idx)
            except Exception:  # noqa: BLE001  索引失败不影响主流程
                pass
    return created
