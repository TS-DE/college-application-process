"""数据提纯（0.11.2）：从 `major_note` 文本里补回缺失的学费与学制。

## 为什么需要这一层
部分省份的 `enrollment-plan.csv` 结构不规范，导入总表后
`tuition`（学费）/ `duration`（学制）大量为 NULL，信息其实混在
`major_note` 的纯文本里。重新导库成本高，因此在 **Service 层读取时提纯**：
查询结果返回前端之前，用正则把缺的字段补上。

## 实测到的真实写法（2025 总表抽样）
```
(6000元/年;报名参加综合评价招生...)                  → 学费 6000
(4年,5000元/年,要求外语语种为英语)                    → 学制 4年、学费 5000
(国家公费师范生,师范类,4年,免费,在北京校区办学...)      → 学制 4年、学费 0
（中外合作办学）（学费9.5万元/年；外语单科...）           → 学费 95000（万 单位）
（学费暂定49000元/年，最终以发改委批复为准；大庆校区）    → 学费 49000
(免收学费,只招男生,...)                              → 学费 0
（国内学费6480元/年，...学费约53000澳元/年）            → 学费 6480（只取首个人民币值）
```
含学费字样的记录量：安徽 39117 / 广西 36532 / 陕西 24867（其余省份也有零星）。

## 边界处理（都是踩过的坑）
1. **万 单位**：`9.5万元/年` 必须换算成 95000，不能漏；
2. **外币**：`53000澳元/年` 中数字与「元」之间有「澳」，正则不会误配，
   所以不会被当成人民币；
3. **`第1~3年` / `第四、五学年` / `第4年`** 不能当学制，
   用「前一字符不能是 第/~/至/-/数字」的后行断言排除；
4. **年份**：`2025年` 不能当学制，`\\d{1,2}` 配不上四位数，再加数字后行断言双保险；
5. **多处学费**：只取**第一个**人民币值（通常是国内学费，后面的多为海外阶段费用）；
6. **★ 列错位**：四川等省的 CSV 结构不规范，**学费被写进了 `duration` 列**
   （实测 `duration` 取值是 `'5000' / '5500' / '免费'` 这类学费值，不是年数）。
   `_fix_shifted_fields()` 负责把这类错位数据搬回 `tuition`，否则会渲染成
   「学制 5000 年」这种荒谬结果。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# ---------------- 学费 ----------------

# 万 单位在前：9.5万元/年 → 95000（必须比「元/年」先试，否则漏掉）
_TUITION_WAN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*万\s*元\s*/\s*年")
# 普通：6000元/年 → 6000。数字与「元」必须紧邻，
# 因此「53000澳元/年」这类外币写法天然不会命中
_TUITION_YUAN_RE = re.compile(r"(\d+)\s*元\s*/\s*年")

# 免费类措辞（实测真实数据里三种都有）
_FREE_WORDS = ("免学费", "免收学费", "免缴学费", "免费")

# 学费合理上限：超过这个数基本是误配（中外合作最贵约 15 万/年）
_TUITION_MAX = 1_000_000

# ---------------- 学制 ----------------

# 明确写「学制 N 年」或「N 年制」
_DURATION_STRICT_RE = re.compile(r"(?:学制|修业年限)\s*(\d+)\s*年|(\d+)\s*年\s*制")
# 通用：N年 后面紧跟分隔符/结尾；前面不能是 第/~/～/至/-/数字（排除 第1~3年、2025年）
_DURATION_LOOSE_RE = re.compile(
    r"(?<![第~～\-—至\d.])(\d{1,2})\s*年(?=\s*[,，;；、)）]|\s*$)"
)

# 学制合理区间（本科 4-5 年、专科 3 年、医学/本博连读最长 9 年）
_DURATION_MIN, _DURATION_MAX = 1, 12

# 判断「duration 列里装的其实是学费」的量级门槛：
# 真实学费至少三位数（最便宜的师范/农林也在千元级），
# 而学制最多两位数，因此 >= 100 一律按学费处理。
# 这样既能把四川的 '5000' 搬回 tuition，又不会误伤广西的 '9年'（真实学制）。
_TUITION_SHIFT_MIN = 100


def extract_tuition(note: Optional[str]) -> Optional[int]:
    """从说明文本里提取学费（元/年）。

    :return: 学费整数；文本含「免学费 / 免收学费 / 免费」返回 **0**；
             提不到返回 **None**（调用方据此保留原值或显示「暂无」）
    """
    if not note:
        return None
    text = str(note)

    # ① 万 单位（放最前，否则 9.5万元/年 会被忽略）
    m = _TUITION_WAN_RE.search(text)
    if m:
        try:
            value = int(round(float(m.group(1)) * 10000))
        except (TypeError, ValueError):
            value = 0
        if 0 < value <= _TUITION_MAX:
            return value

    # ② 普通元/年
    m = _TUITION_YUAN_RE.search(text)
    if m:
        try:
            value = int(m.group(1))
        except (TypeError, ValueError):
            value = 0
        if 0 < value <= _TUITION_MAX:
            return value

    # ③ 免费类措辞（放在最后：避免「免学费」与具体金额同时出现时误判为 0）
    if any(w in text for w in _FREE_WORDS):
        return 0
    return None


def extract_duration(note: Optional[str]) -> Optional[str]:
    """从说明文本里提取学制，返回形如 `"4年"`。

    :return: 学制字符串；提不到或值不合理（不在 1-8 年）返回 **None**
    """
    if not note:
        return None
    text = str(note)

    # ① 明确写「学制 N 年」/「N 年制」的最可信，优先采用
    m = _DURATION_STRICT_RE.search(text)
    if m:
        raw = m.group(1) or m.group(2)
        years = _safe_years(raw)
        if years is not None:
            return f"{years}年"

    # ② 通用匹配：逐个试，取第一个落在合理区间的
    for m in _DURATION_LOOSE_RE.finditer(text):
        years = _safe_years(m.group(1))
        if years is not None:
            return f"{years}年"
    return None


def _safe_years(raw: Any) -> Optional[int]:
    """把捕获到的数字转成合理学制年数，不合理返回 None。"""
    try:
        years = int(raw)
    except (TypeError, ValueError):
        return None
    if _DURATION_MIN <= years <= _DURATION_MAX:
        return years
    return None


def _fix_shifted_fields(item: Dict[str, Any]) -> None:
    """修「列错位」：把误写进 `duration` 的学费搬回 `tuition`。

    实测四川 `enrollment_plan_2025_all.duration` 的取值是
    `'5000' / '5500' / '6500' / '免费'`——明显是学费而不是年数，
    原因是 CSV 结构不规范（列顺序/含义与标准模板不一致）。

    判定规则：
      · `duration` 是纯数字且 **大于 8** → 不可能是学制，按学费处理；
      · `duration` 含「免费 / 免学费」 → 学费记为 0；
      · `duration` 是 1-8 的纯数字（如 `'4'`）→ 是学制，规范成 `'4年'`。
    """
    raw = item.get("duration")
    if raw in (None, ""):
        return
    text = str(raw).strip()

    # 允许带「年」后缀：上游 normalize_duration 会把 '5000' 先变成 '5000年'，
    # 若只判 isdigit() 就漏掉了错位值
    num_match = re.fullmatch(r"(\d+)\s*年?", text)
    if num_match:
        number = int(num_match.group(1))
        if number >= _TUITION_SHIFT_MIN:      # 5000 / 7000 量级 → 其实是学费
            if item.get("tuition") in (None, ""):
                item["tuition"] = number
            item["duration"] = None
        elif _DURATION_MIN <= number <= _DURATION_MAX:
            item["duration"] = f"{number}年"  # '4' / '4年' / '9年' → 规范化
        else:
            item["duration"] = None
        return

    if any(w in text for w in _FREE_WORDS):   # 四川把「免费」写进了 duration 列
        if item.get("tuition") in (None, ""):
            item["tuition"] = 0
        item["duration"] = None


def clean_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """就地把缺失的 `tuition` / `duration` 从 `major_note` 补上。

    这是给「组装成 dict 之后」用的统一入口，符合调用方的伪代码预期：

        if not item.get("tuition") and item.get("major_note"):
            item["tuition"] = extract_tuition(item["major_note"])

    执行顺序（顺序很重要）：
      ① 先修列错位（duration 里装学费的省）；
      ② 再从 major_note 提纯缺失字段。

    :param item: 含 `major_note` / `tuition` / `duration` 键的 dict（原地修改）
    :return: 同一个 dict，便于链式调用
    """
    if not isinstance(item, dict):
        return item

    # ① 列错位修复
    _fix_shifted_fields(item)

    # ② 从说明文本提纯
    note = item.get("major_note")

    if item.get("tuition") in (None, ""):
        value = extract_tuition(note)
        if value is not None:
            item["tuition"] = value

    if item.get("duration") in (None, ""):
        value = extract_duration(note)
        if value is not None:
            item["duration"] = value

    # ③ 金额统一成整数：上游 normalize_score 可能给出 float（6000.0）
    #    或 Decimal（'5500.00'），前端会显示成「6000.0 元」，这里统一收敛成 int
    tuition = item.get("tuition")
    if tuition not in (None, ""):
        try:
            as_float = float(tuition)
            if as_float.is_integer():
                item["tuition"] = int(as_float)
        except (TypeError, ValueError):
            pass
    return item


def clean_items(items) -> list:
    """批量版本：对列表里每个 dict 调 `clean_item`（保留类型）。"""
    return [clean_item(dict(it)) if isinstance(it, dict) else it for it in (items or [])]


__all__ = [
    "extract_tuition",
    "extract_duration",
    "clean_item",
    "clean_items",
]
