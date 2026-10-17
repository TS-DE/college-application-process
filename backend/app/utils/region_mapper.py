"""全国省份 → 高考科类 映射工具（0.11.0 全国多省自适应）。

## 单一职责
本模块**只**维护「省份 ↔ 科类」的对应关系与规范化，不查数据库、不写业务逻辑。
供路由层做参数校验、供前端拉取下拉选项、供服务层把入参归一成数据库里的真实取值。

## ★ 为什么 key 用中文名而不是拼音
数据库 `*_2025_all` 三张总表的 `province` 列存的是**中文名**
（实测 distinct 值：'安徽'、'北京'、'重庆'、'内蒙'…）。
因此本模块的**规范 key 就是中文名**，同时接受拼音作为别名入参，
两种写法都能用：

    get_categories_by_province("henan")   # 拼音别名
    get_categories_by_province("河南")     # 规范 key（= 数据库里的值）

## 三种高考模式
  3+3   （北京/天津/上海/浙江/山东/海南）      → 只有「综合」
  3+1+2 （河南/河北/江苏/广东/四川/陕西 等 20 省）→ 「物理类」「历史类」
  老高考 （新疆/西藏）                          → 「理科」「文科」

> ★ 与任务书假设的差异（已按**数据库实际取值**校正）
> 任务书把四川/云南/陕西/宁夏归为老高考「理科/文科」，但 2025 总表里这四省
> 实际存的是「物理类/历史类」；山西/内蒙古/青海在三张总表里**没有任何数据**。
> 若按任务书配置，这四个省会永远校验失败（400），因此这里以实测为准，
> 无数据省份单列在 `PROVINCES_NO_DATA` 里，由路由层给出更明确的报错。

> 注：数据库里内蒙古记作「内蒙」，两种写法都已收录为别名。
"""
from __future__ import annotations

from typing import Dict, List, Optional

# ---------------- 省份 → 科类 配置 ----------------
# key = 规范中文名（与数据库 province 列一致）；value = 该省支持的科类
PROVINCE_CATEGORIES: Dict[str, List[str]] = {
    # ---- 3+3 新高考：不分文理，只有一个「综合」 ----
    "北京": ["综合"],
    "天津": ["综合"],
    "上海": ["综合"],
    "浙江": ["综合"],
    "山东": ["综合"],
    "海南": ["综合"],
    # ---- 3+1+2 新高考：物理类 / 历史类 ----
    "河南": ["物理类", "历史类"],
    "河北": ["物理类", "历史类"],
    "辽宁": ["物理类", "历史类"],
    "江苏": ["物理类", "历史类"],
    "福建": ["物理类", "历史类"],
    "湖北": ["物理类", "历史类"],
    "湖南": ["物理类", "历史类"],
    "广东": ["物理类", "历史类"],
    "重庆": ["物理类", "历史类"],
    "安徽": ["物理类", "历史类"],
    "江西": ["物理类", "历史类"],
    "广西": ["物理类", "历史类"],
    "贵州": ["物理类", "历史类"],
    "甘肃": ["物理类", "历史类"],
    "黑龙江": ["物理类", "历史类"],
    "吉林": ["物理类", "历史类"],
    # 以下四省按任务书属老高考，但 2025 总表实际存的是「物理类/历史类」
    "四川": ["物理类", "历史类"],
    "云南": ["物理类", "历史类"],
    "陕西": ["物理类", "历史类"],
    "宁夏": ["物理类", "历史类"],
    # ---- 老高考：理科 / 文科 ----
    "新疆": ["理科", "文科"],
    "西藏": ["理科", "文科"],
    # ---- 任务书归为老高考，但三张总表里暂无数据（保留配置供前端展示）----
    "山西": ["理科", "文科"],
    "内蒙古": ["理科", "文科"],
    "青海": ["理科", "文科"],
}

# 2025 总表里没有任何数据的省份（查询必然落空，路由层据此给出明确报错）
PROVINCES_NO_DATA = {"山西", "内蒙古", "青海"}

# ---------------- 拼音别名 → 规范中文名 ----------------
# 前端 / 接口可以传拼音（任务书用 province_code），内部统一归一成中文名再查库
_PROVINCE_ALIAS: Dict[str, str] = {
    "beijing": "北京", "tianjin": "天津", "shanghai": "上海", "zhejiang": "浙江",
    "shandong": "山东", "hainan": "海南",
    "henan": "河南", "hebei": "河北", "liaoning": "辽宁", "jiangsu": "江苏",
    "fujian": "福建", "hubei": "湖北", "hunan": "湖南", "guangdong": "广东",
    "chongqing": "重庆", "anhui": "安徽", "jiangxi": "江西", "guangxi": "广西",
    "guizhou": "贵州", "gansu": "甘肃", "heilongjiang": "黑龙江", "jilin": "吉林",
    "shanxi": "山西", "neimenggu": "内蒙古", "inner_mongolia": "内蒙古",
    "sichuan": "四川", "yunnan": "云南", "shaanxi": "陕西", "qinghai": "青海",
    "ningxia": "宁夏", "xinjiang": "新疆", "xizang": "西藏", "tibet": "西藏",
    # 数据库里内蒙古记作「内蒙」，也登记成别名
    "内蒙": "内蒙古",
}

# 高考模式标签（用于 README / 前端展示，不参与查询逻辑）
GAOKAO_MODE: Dict[str, str] = {
    "北京": "3+3", "天津": "3+3", "上海": "3+3", "浙江": "3+3",
    "山东": "3+3", "海南": "3+3",
    "新疆": "老高考", "西藏": "老高考",
    "山西": "老高考", "内蒙古": "老高考", "青海": "老高考",
}


def normalize_province(province: Optional[str]) -> str:
    """把入参归一成规范中文名（数据库 province 列的取值）。

    接受中文名或拼音；无法识别时原样返回（交给上层校验报错），不猜。
    """
    raw = (province or "").strip()
    if not raw:
        return ""
    if raw in PROVINCE_CATEGORIES:
        return raw
    # 拼音大小写都认
    return _PROVINCE_ALIAS.get(raw) or _PROVINCE_ALIAS.get(raw.lower()) or raw


def get_categories_by_province(province_code: str) -> List[str]:
    """返回该省份支持的科类列表；省份无法识别时返回空列表。

    :param province_code: 中文名（"河南"）或拼音（"henan"）均可
    """
    canonical = normalize_province(province_code)
    return list(PROVINCE_CATEGORIES.get(canonical, []))


def gaokao_mode(province_code: str) -> str:
    """返回高考模式：'3+3' / '3+1+2' / '老高考' / ''（未识别）。"""
    canonical = normalize_province(province_code)
    if canonical not in PROVINCE_CATEGORIES:
        return ""
    return GAOKAO_MODE.get(canonical, "3+1+2")


def is_new_gaokao(province_code: str) -> bool:
    """是否新高考省份（3+3 或 3+1+2）。

    新高考与老高考的科类名不同（物理类/综合 vs 理科/文科），
    服务层据此决定要不要做科类归一。
    """
    return gaokao_mode(province_code) in {"3+3", "3+1+2"}


def is_supported(province_code: str, category: Optional[str] = None) -> bool:
    """省份（+ 科类）是否在支持范围内。"""
    cats = get_categories_by_province(province_code)
    if not cats:
        return False
    if category is None:
        return True
    return category.strip() in cats


def list_provinces() -> List[str]:
    """全国省份列表（规范中文名，按配置文件顺序）。"""
    return list(PROVINCE_CATEGORIES.keys())


def categories_map() -> Dict[str, List[str]]:
    """省份 → 科类 全量映射，供 /api/meta/options 一次性返回给前端。"""
    return {p: list(c) for p, c in PROVINCE_CATEGORIES.items()}


def has_data(province_code: str) -> bool:
    """该省份在 2025 总表里是否有数据（False 表示查询必然落空）。

    路由层用它把「该省暂无数据」和「分数超出范围」区分开，报错更明确。
    """
    return normalize_province(province_code) not in PROVINCES_NO_DATA
