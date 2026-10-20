"""元信息接口：可用维度、省份分布、热门院校、一分一段表。

0.11.1：所有查询改走全国总表，表解析与省份/科类/批次条件统一由
`services/dataset_access.py` 提供，路由层不再拼表名。
"""
import re
from typing import Dict, List

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, text

from app.config import settings
from app.database import engine, fetch_all, table_exists
from app.models.dataset import (
    KIND_MAJOR,
    KIND_SCHOOL,
    KIND_SCORE,
    NATIONAL_TABLE_SUFFIX,
    normalize_code,
    normalize_int,
    normalize_score,
)
from app.services.recommend.dataset_access import (
    DatasetUnavailable,
    province_conditions,
    resolve_table,
    scope_conditions,
)

router = APIRouter(prefix="/api/meta", tags=["meta"])

_YEAR_IN_TABLE = re.compile(r"_(\d{4})_")

# ---------------------------------------------------------------- 环境探测（0.13.1）
#
# 前端要用两个指示灯告诉用户「为什么有些问题答不上来」：
#   · 政策库红灯 → 知识库里没有任何文档（向量检索必然落空）
#   · 图谱红灯   → Neo4j 未启动（tool_search_graph 已被自动剔除）
# 探测本身有成本（Chroma count / Neo4j 连接），因此做 30 秒 TTL 缓存，
# 避免每次进 AI 页面都打一次外部依赖。
_ENV_STATUS_TTL = 30.0
_env_status_cache: Dict[str, object] = {"at": 0.0, "data": None}


def _probe_vector() -> Dict:
    """探测向量库：集合存在且文档数 > 0 才算「政策库就绪」。"""
    try:
        from app.services.rag.rag_service import backend_info

        info = backend_info()
        count = int(info.get("count") or 0)
        return {
            "vector_ready": bool(info.get("ready")) and count > 0,
            "vector_count": count,
            "vector_error": "" if count > 0 else (info.get("error") or "知识库暂无文档"),
            "embedding_model": info.get("embedding_model") or "",
        }
    except Exception as exc:  # noqa: BLE001 探测失败不能影响页面
        return {
            "vector_ready": False,
            "vector_count": 0,
            "vector_error": f"{exc.__class__.__name__}",
            "embedding_model": "",
        }


def _probe_graph(timeout: float = 3.0) -> Dict:
    """探测 Neo4j（限时，避免连接超时把接口拖死）。"""
    if not settings.GRAPH_ENABLED:
        return {"graph_ready": False, "graph_error": "图谱通道已关闭（GRAPH_ENABLED=0）"}
    try:
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as FutureTimeout

        from app.services.graph.graph_store import GraphStore

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(GraphStore().available)
            try:
                ok = bool(future.result(timeout=timeout))
            except FutureTimeout:
                return {"graph_ready": False, "graph_error": "Neo4j 连接超时"}
        return {
            "graph_ready": ok,
            "graph_error": "" if ok else "Neo4j 未启动",
        }
    except Exception as exc:  # noqa: BLE001
        return {"graph_ready": False, "graph_error": f"{exc.__class__.__name__}"}


@router.get("/agent-status")
def agent_status(refresh: bool = Query(default=False, description="true 表示跳过缓存")) -> Dict:
    """AI 环境状态：前端据此点亮「政策库 / 图谱」指示灯（0.13.1）。

    返回：
        {
          "vector_ready": true,        # 政策库有文档
          "graph_ready": false,        # Neo4j 可连接
          "local_model": "qwen3:4b",
          "agent_mode": "fast",        # fast=确定性链路 / agent=两轮工具推理
          "vector_count": 3,
          "graph_error": "Neo4j 未启动"
        }
    """
    import time as _time

    now = _time.time()
    cached = _env_status_cache.get("data")
    if not refresh and cached and (now - float(_env_status_cache.get("at") or 0)) < _ENV_STATUS_TTL:
        return dict(cached)  # type: ignore[arg-type]

    data: Dict = {}
    data.update(_probe_vector())
    data.update(_probe_graph())
    data.update(
        {
            "local_model": settings.OLLAMA_MODEL,
            "agent_mode": "fast" if settings.AGENT_FAST_MODE else "agent",
            "agent_enabled": settings.AGENT_ENABLED,
            "checked_at": now,
        }
    )
    _env_status_cache["at"] = now
    _env_status_cache["data"] = data
    return dict(data)


def _available_years(province: str = "") -> List[int]:
    """扫描 information_schema，找出**总表**实际导入了哪些年份。

    0.11.1：不再按省份后缀（`score_range_%_henan`）扫表——分省表已不存在。
    现在扫 `score_range_{年份}_all`，因此年份是**全局**的，与省份无关
    （哪一年有没有数据对所有省份是同一个答案）。
    `province` 参数保留兼容调用方，不参与匹配。
    """
    pattern = f"{KIND_SCORE}_%_{NATIONAL_TABLE_SUFFIX}"
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :db AND table_name LIKE :p"
            ),
            {"db": settings.DB_NAME, "p": pattern},
        ).fetchall()
    years = set()
    for (tname,) in rows:
        m = _YEAR_IN_TABLE.search(tname)
        if m:
            years.add(int(m.group(1)))
    return sorted(years) or [2025]


@router.get("/options")
def options(province: str = Query(default=settings.DEFAULT_PROVINCE)) -> Dict:
    """返回该省份可用的年份 / 科类 / 批次，避免前端写死下拉框。

    0.11.0：新增 `provinces`（全国 31 省）与 `categories_map`（省份 → 科类），
    前端一次拉全即可做「选省份 → 联动科类」的下钻，无需再为每省写死选项。
    """
    from app.utils.region_mapper import (
        categories_map,
        gaokao_mode,
        list_provinces,
        normalize_province,
    )

    years = _available_years(province)
    categories: List[str] = []
    batches: List[str] = []
    for y in years:
        try:
            tbl = resolve_table(KIND_SCORE, y, province)
        except DatasetUnavailable:
            continue
        # ★ 0.11.1：总表含 30+ 省，必须按省份隔离后再取 DISTINCT
        stmt = select(tbl.c.category, tbl.c.batch).distinct()
        prov_conds = province_conditions(tbl, province)
        if prov_conds:
            stmt = stmt.where(*prov_conds)
        rows = fetch_all(stmt)
        for r in rows:
            c, b = r.get("category"), r.get("batch")
            if c and c not in categories:
                categories.append(c)
            if b and b not in batches:
                batches.append(b)
    # 前端按新高考口径展示
    canon_batches: List[str] = []
    for b in batches:
        cb = "本科批" if b in ("本科一批", "本科二批", "本一", "本二", "本科批") else b
        if cb not in canon_batches:
            canon_batches.append(cb)

    # 0.11.0 全国省份 / 科类映射（归一化后的中文名为 key）
    cats_map = categories_map()
    prov_cn = normalize_province(province)
    return {
        "province": prov_cn or province,
        "years": years,
        "categories": categories,
        "batches": canon_batches,
        "raw_batches": batches,
        # ---- 0.11.0 新增：全国多省自适应下拉选项 ----
        "provinces": list_provinces(),
        "categories_map": cats_map,
        "province_modes": {p: gaokao_mode(p) for p in list_provinces()},
        "default": {
            "year": years[-1] if years else 2025,
            "category": "物理类" if "物理类" in categories else (categories[0] if categories else "物理类"),
            "batch": "本科批",
        },
    }


@router.get("/province-stats")
def province_stats(
    province: str = Query(default=settings.DEFAULT_PROVINCE),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
    batch: str = Query(default="本科批"),
) -> Dict:
    """各省份在 `province` 招生的院校专业数量，供首页地图渲染。

    0.11.1：查全国总表并按考生省份隔离。
    """
    tbl = resolve_table(KIND_MAJOR, year, province)
    stmt = select(tbl.c.school_province, func.count().label("cnt")).where(
        tbl.c.school_province.isnot(None)
    )
    # ★ 省份 + 科类 + 批次三重隔离
    conds = scope_conditions(KIND_MAJOR, tbl, province, year, category, batch)
    if conds:
        stmt = stmt.where(*conds)
    stmt = stmt.group_by(tbl.c.school_province)
    rows = fetch_all(stmt)
    return {
        "year": year,
        "category": category,
        "batch": batch,
        "items": [{"name": r["school_province"], "value": r["cnt"]} for r in rows],
    }


@router.get("/hot-schools")
def hot_schools(
    province: str = Query(default=settings.DEFAULT_PROVINCE),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
    batch: str = Query(default="本科批"),
    limit: int = Query(default=12, ge=1, le=50),
) -> Dict:
    """首页热门院校卡片：优先 985/211，按投档位次排序。

    0.11.1：`school_admission` 无 `_all` 表，`resolve_table` 自动回落到
    `major_admission_{year}_all`，按院校分组后等价得到院校维度数据。
    """
    tbl = resolve_table(KIND_SCHOOL, year, province)
    conds = [tbl.c.min_rank.isnot(None), tbl.c.university_name.isnot(None)]
    # ★ 省份 + 科类 + 批次三重隔离
    conds += scope_conditions(KIND_SCHOOL, tbl, province, year, category, batch)

    stmt = (
        select(
            tbl.c.university_code,
            tbl.c.university_name,
            tbl.c.school_province,
            tbl.c.school_nature,
            tbl.c.is_985,
            tbl.c.is_211,
            func.min(tbl.c.min_score).label("min_score"),
            func.min(tbl.c.min_rank).label("min_rank"),
        )
        .where(*conds)
        .group_by(
            tbl.c.university_code,
            tbl.c.university_name,
            tbl.c.school_province,
            tbl.c.school_nature,
            tbl.c.is_985,
            tbl.c.is_211,
        )
        .order_by(func.min(tbl.c.min_rank))
    )
    rows = fetch_all(stmt)

    def _tags(r) -> List[str]:
        tags = []
        if int(r.get("is_985") or 0) == 1:
            tags.append("985")
        if int(r.get("is_211") or 0) == 1:
            tags.append("211")
        if tags:
            tags.append("双一流")
        return tags

    featured = [r for r in rows if _tags(r)]
    others = [r for r in rows if not _tags(r)]
    picked = (featured + others)[:limit]
    return {
        "items": [
            {
                "university_code": normalize_code(r.get("university_code")),
                "university_name": r.get("university_name"),
                "school_province": r.get("school_province"),
                "school_nature": r.get("school_nature"),
                "min_score": normalize_score(r.get("min_score")),
                "min_rank": normalize_int(r.get("min_rank")),
                "tags": _tags(r),
            }
            for r in picked
        ]
    }


@router.get("/score-table")
def score_table(
    province: str = Query(default=settings.DEFAULT_PROVINCE),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
    batch: str = Query(default="本科批"),
) -> Dict:
    """一分一段表（快捷工具）。"""
    from app.services.recommend.rank_service import score_table as _tbl

    rows = _tbl(province, year, category, batch)
    return {"items": rows}


@router.get("/control-lines")
def control_lines(
    province: str = Query(default=settings.DEFAULT_PROVINCE),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
) -> Dict:
    """各批次省控线 + 本科/专科的可填写分数区间（按年份、科类动态变化）。

    前端用 bounds 控制「成绩类型 = 本科/专科」时预估分数的合法区间，
    用 lines 渲染「分数未过线」的温馨提示弹窗。
    """
    from app.services.recommend.rank_service import control_lines as _lines

    try:
        return _lines(province, year, category)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/score-check")
def score_check(
    score: float = Query(..., ge=0, le=750, description="预估分数"),
    province: str = Query(default=settings.DEFAULT_PROVINCE),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
) -> Dict:
    """分数校验三合一：是否过线 + 自动推荐批次 + 自动换算位次。

    below_all=True 时 rank / recommend_batch 为空，前端应弹出温馨提示。
    """
    from app.services.recommend.rank_service import score_check as _check

    try:
        return _check(province, year, category, score)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
