"""维度归一化与表名解析。

数据集的两个坑（必须在这里抹平，否则查出来是空列表）：
1. 河南 2024 是老高考（理科/文科 + 本科一批/本科二批），2025 是新高考
   （物理类/历史类 + 本科批/专科批），同一份语义在不同表里写法不同。
2. 2024 的 major_admission / school_admission 表 category 列整列为空，
   batch 列写的是「本一 / 本二 / 专科」，而 enrollment_plan / score_range
   写的是「本科一批 / 本科二批 / 专科批」。

因此所有查询都不直接拼 category/batch，而是先经过本模块解析成该表里的真实取值。
"""
from typing import List, Optional
import re

# 省份 -> 表名后缀（数据集使用拼音）
PROVINCE_PINYIN = {
    "河南": "henan",
    "henan": "henan",
}

KIND_PLAN = "enrollment_plan"
KIND_MAJOR = "major_admission"
KIND_SCHOOL = "school_admission"
KIND_SCORE = "score_range"
ALL_KINDS = (KIND_PLAN, KIND_MAJOR, KIND_SCHOOL, KIND_SCORE)

# 2024 这两张表用「本一/本二/专科」简写
_SHORT_BATCH_TABLES = {KIND_MAJOR, KIND_SCHOOL}

# 老高考（2024）科类映射：新高考 -> 老高考
_CATEGORY_LEGACY = {
    "物理类": "理科",
    "历史类": "文科",
    "综合": "理科",
    "理科": "理科",
    "文科": "文科",
}

# 批次归一到「新高考口径」的规范值
_BATCH_CANON = {
    "本科一批": "本科批",
    "本科二批": "本科批",
    "本科三段": "本科批",
    "本一": "本科批",
    "本二": "本科批",
    "本科": "本科批",
    "本科批": "本科批",
    "专科": "专科批",
    "专科批": "专科批",
    "高职高专": "专科批",
    "本科提前批": "本科提前批",
    "专科提前批": "专科提前批",
    "艺术类本科批": "艺术类本科批",
    "高校专项计划批": "高校专项计划批",
    "国家专项计划批": "国家专项计划批",
    "地方专项计划批": "地方专项计划批",
}


def province_suffix(province: str) -> str:
    return PROVINCE_PINYIN.get(province, province)


def table_name(kind: str, year: int, province: str) -> str:
    """如 major_admission + 2025 + 河南 -> major_admission_2025_henan"""
    return f"{kind}_{year}_{province_suffix(province)}"


def canonical_batch(batch: str) -> str:
    if not batch:
        return "本科批"
    return _BATCH_CANON.get(batch.strip(), batch.strip())


def resolve_batch(batch: str, year: int, kind: str) -> Optional[List[str]]:
    """把规范批次翻译成指定表在该年份下的真实 batch 取值。

    返回 None 表示「该表这一列不可用/不需要过滤」。
    """
    if not batch:
        return None
    canon = canonical_batch(batch)
    if year >= 2025:
        return [canon]
    # 2024 老高考
    if kind in _SHORT_BATCH_TABLES:
        mapping = {
            "本科批": ["本一", "本二"],
            "专科批": ["专科"],
            "本科提前批": ["本科提前批"],
            "专科提前批": ["专科提前批"],
        }
    else:
        mapping = {
            "本科批": ["本科一批", "本科二批"],
            "专科批": ["专科批"],
            "本科提前批": ["本科提前批"],
            "专科提前批": ["专科提前批"],
        }
    return mapping.get(canon, [canon])


def resolve_category(category: str, year: int, kind: str) -> Optional[List[str]]:
    """把规范科类翻译成指定表在该年份下的真实 category 取值。

    2024 的录取表 category 整列为空，必须返回 None 跳过过滤，否则结果为空。
    """
    if not category:
        return None
    if year >= 2025:
        return [category.strip()]
    if kind in _SHORT_BATCH_TABLES:
        return None
    return [_CATEGORY_LEGACY.get(category.strip(), category.strip())]


def normalize_code(value) -> Optional[str]:
    """院校代码/专业代码在库里是 DOUBLE。

    pymysql 会返回 Decimal('2385.0000000000')，前端拿到会很难看，
    这里统一成 '2385'；非数字原样返回。
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    try:
        f = float(s)
    except ValueError:
        return s
    if f != f:  # NaN
        return None
    return str(int(round(f))) if abs(f - round(f)) < 1e-9 else str(f)


def normalize_duration(value) -> Optional[str]:
    """学制：2025 数据集是数字 4，2024 是「四年」，统一成「4年」形式。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        f = float(s)
    except ValueError:
        return s
    if f != f:
        return None
    return f"{int(round(f))}年"


def normalize_score(value) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def normalize_int(value) -> Optional[int]:
    f = normalize_score(value)
    return int(f) if f is not None else None


# ------------------------------------------------------------ 3+1+2 选科

# 再选科目（数据集中写作「思想政治」，前端展示为「政治」）
SUBJECTS = ["化学", "生物", "思想政治", "地理"]
_SUBJECT_ALIAS = {"政治": "思想政治", "思想品德": "思想政治"}


def normalize_subject(name: str) -> str:
    return _SUBJECT_ALIAS.get((name or "").strip(), (name or "").strip())


def subject_match(req_text, selected: Optional[List[str]]) -> bool:
    """判断专业的再选科目要求是否被考生的选科组合满足。

    数据集中的写法（河南 2025）：
      首选物理，再选不限
      首选物理，再选化学
      首选物理，再选化学、生物(2科必选)
    规则：
      · 考生未填再选科目 / 数据缺失 / 「不限」 → 不过滤
      · 含「或」且非「必选」 → 任一命中即可
      · 命中 2 门及以上（或标注「必选」） → 必须全部包含
    """
    if not selected:
        return True
    if not req_text:
        return True  # 2024 数据无选科信息，不做过滤
    req = str(req_text)
    if "不限" in req:
        return True
    part = req.split("再选")[-1]
    subs = [s for s in SUBJECTS if s in part]
    if not subs:
        return True
    sel = {normalize_subject(s) for s in selected}
    if "或" in part and "必选" not in part:
        return bool(sel & set(subs))
    if len(subs) >= 2 or "必选" in part:
        return set(subs) <= sel
    return subs[0] in sel
