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

# 0.11.1 全国总表后缀：所有数据集统一存进 {kind}_{year}_all
NATIONAL_TABLE_SUFFIX = "all"

# 没有 _all 总表的数据集 → 回落到哪张表
# `school_admission`（院校投档）未参与合并，但 `major_admission` 含有
# university_name / min_score / min_rank / school_province / is_985 / is_211，
# 按院校聚合即可等价得到院校维度数据，因此回落过去。
KIND_FALLBACK = {
    KIND_SCHOOL: KIND_MAJOR,
}

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
    """省份中文名 → 拼音后缀（0.11.1 起**不再用于拼表名**，仅保留作标识/日志用途）。"""
    return PROVINCE_PINYIN.get(province, province)


def table_name(kind: str, year: int, province: str = "") -> str:
    """数据集表名（0.11.1 起统一返回**全国总表**）。

    ## 为什么改了
    0.11.0 之前是 `major_admission_2025_henan` 这种**分省表**；全国数据合并入库后
    分省表已全部删除，只剩 `*_2025_all` 三张总表，继续拼 `_henan` 会直接
    「数据表不存在或无法反射」。

    ## 现在的规则
    · `province` 参数**保留但不再参与命名**（调用方仍在传，避免大面积改签名）；
    · 省份维度的隔离改由 SQL 的 `WHERE province = :prov` 完成，见
      `services/dataset_access.py: province_conditions()`；
    · 返回形如 `major_admission_2025_all`。

    这样「表名只有一套、省份靠条件区分」比「按省拼表名」更安全：
    漏传省份最多查出全量，不会因为表名拼错直接 500。
    """
    return f"{kind}_{year}_{NATIONAL_TABLE_SUFFIX}"


def resolve_kind(kind: str) -> str:
    """把数据集类型映射到**实际存在**的全国总表类型。

    目前只有三类数据合并进了总表：
        major_admission / enrollment_plan / score_range
    `school_admission`（院校投档）**没有** `_all` 表，因此回落到

    `major_admission`——后者同样含 university_name / min_score / min_rank /
    school_province / is_985 / is_211，按院校分组即可得到院校维度数据。
    """
    return KIND_FALLBACK.get(kind, kind)


def table_name_or_none(kind: str, year: int, province: str = "") -> str:
    """同 `table_name`，但返回前先做类型回落（school_admission → major_admission）。"""
    return table_name(resolve_kind(kind), year, province)


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
