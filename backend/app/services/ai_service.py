"""本地大模型服务（Ollama + Qwen3）。

设计原则：AI 只做「理解」和「表达」，不做录取概率计算；
任何一步失败都必须静默降级到规则实现，保证推荐列表永远可用。
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import requests

from app.config import settings

# ---------------------------------------------------------------- 基础调用


def ai_enabled() -> bool:
    return bool(settings.AI_ENABLED)


def ollama_health(timeout: float = 3.0) -> Tuple[bool, str]:
    """探测 Ollama 是否可用，返回 (是否可用, 说明)。"""
    if not settings.AI_ENABLED:
        return False, "AI 已在配置中关闭（AI_ENABLED=0）"
    try:
        resp = requests.get(f"{settings.OLLAMA_URL}/api/tags", timeout=timeout)
        if resp.status_code != 200:
            return False, f"Ollama 返回状态码 {resp.status_code}"
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        if settings.OLLAMA_MODEL not in models:
            return False, f"未找到模型 {settings.OLLAMA_MODEL}，请先执行 ollama pull"
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"无法连接 Ollama（{exc.__class__.__name__}）"


_THINK_RE = re.compile(r"<think>.*?</think>", re.S)
_JSON_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.S)


def _strip_think(text: str) -> str:
    text = _THINK_RE.sub("", text or "")
    return text.strip().strip("`").strip()


def ask(
    prompt: str,
    timeout: Optional[float] = None,
    num_predict: int = 256,
    temperature: float = 0.3,
    top_p: float = 0.85,
) -> Optional[str]:
    """调用 Ollama /api/generate，失败返回 None。

    v2.3.0 起支持按场景指定采样参数：
      - 意图路由：temperature=0.0（要确定性二分类）
      - 防幻觉生成：temperature=0.1, top_p=0.1（压低随机性，减少编造）
    """
    if not settings.AI_ENABLED:
        return None
    payload = {
        "model": settings.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
            "num_predict": num_predict,
        },
    }
    try:
        resp = requests.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json=payload,
            timeout=timeout or settings.OLLAMA_TIMEOUT,
        )
        if resp.status_code != 200:
            # 老版本 Ollama 不认识 think 字段，去掉重试一次
            payload.pop("think", None)
            resp = requests.post(
                f"{settings.OLLAMA_URL}/api/generate",
                json=payload,
                timeout=timeout or settings.OLLAMA_TIMEOUT,
            )
        resp.raise_for_status()
        return _strip_think(resp.json().get("response", ""))
    except Exception:  # noqa: BLE001
        return None


def _extract_json(text: str) -> Optional[Dict]:
    if not text:
        return None
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 意图解析

_MAJOR_VOCAB = [
    "计算机", "软件工程", "人工智能", "智能科学", "数据科学", "大数据",
    "电子信息", "电子科学", "通信工程", "集成电路", "微电子", "自动化",
    "电气工程", "电气", "机械", "车辆工程", "航空航天", "土木", "建筑",
    "城乡规划", "水利", "能源动力", "材料", "化工", "化学", "环境",
    "生物", "生物技术", "药学", "临床", "口腔", "医学", "护理", "中医",
    "预防医学", "医学影像", "金融", "金融工程", "经济学", "国际经济",
    "会计", "财务管理", "审计", "工商管理", "市场营销", "物流管理",
    "法学", "知识产权", "政治学", "社会学", "思想政治教育", "公安",
    "汉语言文学", "汉语国际教育", "外语", "英语", "日语", "翻译",
    "新闻传播", "广告学", "广播电视", "网络与新媒体", "历史学", "哲学",
    "教育学", "小学教育", "学前教育", "师范", "心理学", "应用心理学",
    "数学", "统计学", "物理学", "应用物理", "地理科学", "测绘",
    "农学", "园艺", "动物医学", "林学", "食品科学", "动物科学",
    "设计学", "视觉传达", "环境设计", "数字媒体", "动画", "音乐", "美术",
    "体育教育", "运动训练", "护理学", "康复治疗", "公共卫生",
]

_REGION_MAP = {
    "北京": "北京", "上海": "上海", "广东": "广东", "广州": "广东", "深圳": "广东",
    "江苏": "江苏", "南京": "江苏", "浙江": "浙江", "杭州": "浙江",
    "湖北": "湖北", "武汉": "湖北", "四川": "四川", "成都": "四川",
    "陕西": "陕西", "西安": "陕西", "山东": "山东", "天津": "天津",
    "重庆": "重庆", "福建": "福建", "湖南": "湖南", "辽宁": "辽宁",
    "吉林": "吉林", "黑龙江": "黑龙江", "河北": "河北", "山西": "山西",
    "安徽": "安徽", "江西": "江西", "河南": "河南", "甘肃": "甘肃",
    "云南": "云南", "贵州": "贵州", "广西": "广西", "海南": "海南",
}

# 河南邻省
_NEIGHBORS = ["河北", "山西", "陕西", "湖北", "安徽", "山东", "江苏"]


def _rule_parse_intent(text: str, province: str) -> Dict:
    """规则兜底的意图解析：关键词命中 + 简单语义。"""
    t = text or ""
    result: Dict = {
        "major_keyword": None,
        "exclude_keyword": None,
        "region_preference": None,
        "school_province": None,
        "tuition_max": None,
        "school_nature": None,
        "is_985": None,
        "is_211": None,
        "subject_req": None,
    }

    hits = [w for w in _MAJOR_VOCAB if w in t]
    if hits:
        # 取最长的命中词，避免「计算机」被「计算机科学与技术」覆盖
        hits.sort(key=len, reverse=True)
        result["major_keyword"] = hits[0]

    for kw in ["中外合作", "合作办学", "定向", "民族班", "预科", "高收费", "国际班"]:
        if kw in t:
            result["exclude_keyword"] = kw
            break

    if "985" in t:
        result["is_985"] = True
    if "211" in t or "二一一" in t:
        result["is_211"] = True
    if "双一流" in t:
        result["is_985"] = True if result["is_985"] is None else result["is_985"]

    if "公办" in t:
        result["school_nature"] = "公办"
    elif "民办" in t:
        result["school_nature"] = "民办"

    if "免费" in t or "公费师范" in t:
        result["tuition_max"] = 0
    for kw in ["学费便宜", "学费低", "便宜", "低学费", "省钱"]:
        if kw in t:
            result["tuition_max"] = result["tuition_max"] or 6000
            break
    m = re.search(r"学费\s*(?:不超过|低于|少于|小于|最多)?\s*(\d{3,6})", t)
    if m:
        result["tuition_max"] = int(m.group(1))

    if "离家近" in t or "本省" in t or "省内" in t or "不出省" in t:
        result["region_preference"] = "本省"
        result["school_province"] = province
    elif "邻省" in t or "周边" in t or "附近" in t:
        result["region_preference"] = "本省及邻省"
    elif "北上广" in t or "一线城市" in t or "发达" in t:
        result["region_preference"] = "北上广等发达地区"
        result["school_province"] = "北京"
    elif "南方" in t:
        result["region_preference"] = "南方地区"
    elif "北方" in t:
        result["region_preference"] = "北方地区"
    else:
        for k, v in _REGION_MAP.items():
            if k in t:
                result["school_province"] = v
                result["region_preference"] = f"{v}及周边"
                break

    m = re.search(r"(?:选考|选科|要求)\s*([化学生物政治地理]{1,4})", t)
    if m:
        result["subject_req"] = m.group(1)
    return result


_INTENT_PROMPT = """你是高考志愿填报助手。请把用户的自然语言需求转换成 JSON，只输出 JSON，不要任何解释。

字段说明：
- major_keyword: 专业方向关键词，如"计算机"，没有则空字符串
- exclude_keyword: 想排除的词，如"中外合作"，没有则空字符串
- region_preference: 地域偏好描述，如"本省""本省及邻省""北上广等发达地区"，没有则空字符串
- school_province: 具体省份（如"北京""河南"），不确定则空字符串
- tuition_max: 学费上限（整数，元/年），不确定则 0
- school_nature: "公办"/"民办"/空字符串
- is_985: true/false/null
- is_211: true/false/null
- subject_req: 选科要求关键词，如"化学"，没有则空字符串

示例：
用户输入：我想找个离家近、计算机强、学费便宜的学校
输出：{"major_keyword":"计算机","exclude_keyword":"","region_preference":"本省","school_province":"河南","tuition_max":6000,"school_nature":"","is_985":null,"is_211":null,"subject_req":""}

用户输入：分数一般，想去北上广读金融，公办优先
输出：{"major_keyword":"金融","exclude_keyword":"","region_preference":"北上广等发达地区","school_province":"北京","tuition_max":0,"school_nature":"公办","is_985":null,"is_211":null,"subject_req":""}

用户输入：__USER_TEXT__
输出："""


def parse_intent(text: str, province: str = None, use_llm: bool = True) -> Dict:
    """自然语言 -> 筛选条件。优先大模型，失败降级到规则。"""
    province = province or settings.DEFAULT_PROVINCE
    fallback = _rule_parse_intent(text, province)
    if not use_llm or not settings.AI_ENABLED:
        return {**fallback, "source": "rule"}

    prompt = _INTENT_PROMPT.replace("__USER_TEXT__", (text or "").strip())
    raw = ask(prompt, timeout=min(settings.OLLAMA_TIMEOUT, 30), num_predict=160)
    data = _extract_json(raw)
    if not data:
        return {**fallback, "source": "rule", "raw": raw}

    def _s(key: str) -> Optional[str]:
        v = data.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else None

    def _b(key: str) -> Optional[bool]:
        v = data.get(key)
        return v if isinstance(v, bool) else None

    def _i(key: str) -> Optional[int]:
        v = data.get(key)
        try:
            iv = int(v)
        except (TypeError, ValueError):
            return None
        return iv or None

    merged = {
        "major_keyword": _s("major_keyword") or fallback["major_keyword"],
        "exclude_keyword": _s("exclude_keyword") or fallback["exclude_keyword"],
        "region_preference": _s("region_preference") or fallback["region_preference"],
        "school_province": _s("school_province") or fallback["school_province"],
        "tuition_max": _i("tuition_max") or fallback["tuition_max"],
        "school_nature": _s("school_nature") or fallback["school_nature"],
        "is_985": _b("is_985") if _b("is_985") is not None else fallback["is_985"],
        "is_211": _b("is_211") if _b("is_211") is not None else fallback["is_211"],
        "subject_req": _s("subject_req") or fallback["subject_req"],
        "source": "llm",
        "raw": raw,
    }
    # 模型若把「离家近」理解成具体省份但没填，规则补一次
    if not merged["school_province"] and merged["region_preference"] == "本省":
        merged["school_province"] = province
    return merged


# ---------------------------------------------------------------- 推荐理由

_REASON_PROMPT = """你是高考志愿规划师。请根据下面的信息，生成一段 60 字以内的推荐理由。

院校：{university_name}
专业：{major_name}
所在地区：{school_province}
办学性质：{school_nature}
去年最低分：{min_score}
去年最低位次：{min_rank}
考生位次：{student_rank}
位次差：{rank_diff}（正数表示该专业去年位次比你低，更稳妥）
档位：{tier_label}
学费：{tuition}

要求：
1. 语气亲切、像老师在给建议，口语化，不要书面套话。
2. 必须点出位次差带来的机会或风险，突出一个具体优势。
3. 只使用上面给出的信息，绝对不要编造排名、学科评估、就业率等数据。
4. 直接输出理由正文，不要加引号、序号或前缀。"""


def _rule_reason(ctx: Dict) -> str:
    """规则兜底的推荐理由（一定可用，写得尽量像人话）。"""
    uni = ctx.get("university_name") or "该校"
    major = ctx.get("major_name") or "该专业"
    r = ctx.get("student_rank")
    m = ctx.get("min_rank")
    tier = ctx.get("tier_label") or "稳"
    parts: List[str] = []

    tags = []
    if ctx.get("is_985"):
        tags.append("985")
    elif ctx.get("is_211"):
        tags.append("211")
    if ctx.get("school_nature"):
        tags.append(ctx["school_nature"])
    if ctx.get("school_province"):
        tags.append(ctx["school_province"])
    tag_txt = "、".join(tags)

    parts.append(f"{uni}（{tag_txt}）" if tag_txt else uni)

    if r and m:
        diff = int(m) - int(r)
        if tier == "冲":
            parts.append(
                f"{major}去年最低位次 {m}，比你高 {abs(diff)} 名，属于需要跳一跳的【冲】档，"
                f"放在前面搏一把是合理的"
            )
        elif tier == "保":
            parts.append(
                f"{major}去年最低位次 {m}，比你低 {abs(diff)} 名，兜底很扎实，"
                f"建议放在志愿表靠后位置保底"
            )
        else:
            parts.append(
                f"{major}去年最低位次 {m}，与你位次仅差 {abs(diff)} 名，"
                f"匹配度高，可作为核心志愿"
            )
    else:
        parts.append(f"{major}往年录取数据与你的位次接近，属于【{tier}】档")

    if ctx.get("min_score"):
        parts.append(f"去年最低分 {int(ctx['min_score'])}")
    extra = []
    if ctx.get("plan_count"):
        extra.append(f"今年计划招 {int(ctx['plan_count'])} 人")
    elif ctx.get("admit_count"):
        extra.append(f"去年录取 {int(ctx['admit_count'])} 人")
    if ctx.get("tuition"):
        extra.append(f"学费 {int(ctx['tuition'])} 元/年")
    if ctx.get("subject_req"):
        extra.append(f"选科要求：{ctx['subject_req']}")
    if extra:
        parts.append("；".join(extra))
    return "，".join(parts) + "。"


def build_reason_context(item: Dict, student: Dict) -> Dict:
    r = student.get("rank")
    m = item.get("min_rank")
    tier = {"chong": "冲", "wen": "稳", "bao": "保"}.get(item.get("tier"), "稳")
    return {
        "university_name": item.get("university_name"),
        "major_name": item.get("major_name"),
        "school_province": item.get("school_province"),
        "school_nature": item.get("school_nature"),
        "min_score": item.get("min_score"),
        "min_rank": m,
        "student_rank": r,
        "student_score": student.get("score"),
        "rank_diff": (int(m) - int(r)) if (r is not None and m is not None) else None,
        "tier_label": tier,
        "tuition": item.get("tuition"),
        "plan_count": item.get("plan_count"),
        "admit_count": item.get("admit_count"),
        "subject_req": item.get("subject_req"),
        "is_985": item.get("is_985"),
        "is_211": item.get("is_211"),
    }


def recommend_reason(item: Dict, student: Dict, use_llm: bool = True) -> Tuple[str, str]:
    """返回 (理由文本, 来源 llm/rule)。"""
    ctx = build_reason_context(item, student)
    fallback = _rule_reason(ctx)
    if not use_llm or not settings.AI_ENABLED:
        return fallback, "rule"

    prompt = _REASON_PROMPT.format(
        university_name=ctx["university_name"] or "未知院校",
        major_name=ctx["major_name"] or "未知专业",
        school_province=ctx["school_province"] or "未知",
        school_nature=ctx["school_nature"] or "未知",
        min_score=int(ctx["min_score"]) if ctx["min_score"] else "未知",
        min_rank=int(ctx["min_rank"]) if ctx["min_rank"] else "未知",
        student_rank=int(ctx["student_rank"]) if ctx["student_rank"] else "未知",
        rank_diff=ctx["rank_diff"] if ctx["rank_diff"] is not None else "未知",
        tier_label=ctx["tier_label"],
        tuition=int(ctx["tuition"]) if ctx["tuition"] else "未知",
    )
    text = ask(prompt, timeout=min(settings.OLLAMA_TIMEOUT, 40), num_predict=180)
    if not text:
        return fallback, "rule"
    text = text.replace("\n", " ").strip()
    if len(text) < 8 or len(text) > 220:
        return fallback, "rule"
    return text, "llm"


def batch_reasons(
    items: List[Dict], student: Dict, limit: int = 8, workers: Optional[int] = None
) -> int:
    """就地为前 limit 条生成 AI 理由（并发）。返回真正由大模型生成的条数。"""
    if not settings.AI_ENABLED or limit <= 0:
        return 0
    targets = [it for it in items if isinstance(it, dict)][:limit]
    if not targets:
        return 0

    def _job(it: Dict) -> Tuple[Dict, str, str]:
        return it, *recommend_reason(it, student)

    ok = 0
    with ThreadPoolExecutor(max_workers=workers or settings.AI_MAX_WORKERS) as pool:
        for it, text, source in pool.map(_job, targets):
            if source == "llm":
                it["ai_reason"] = text
                it["ai"] = True
                ok += 1
    return ok
