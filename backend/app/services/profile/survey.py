"""业务问卷生成器（0.12.0，途径 B）。

## 为什么问卷要学会「自己保底」
大模型不一定可用（额度/网络/超时），但画像流程不能因此卡死。
`SurveyQuestionGenerator` 内置一套经过设计的业务题库，
LLM 失败时直接返回内置题并标记 `fallback=True`，前端提示「当前为内置题目」。

## 为什么不用心理学量表
MBTI / 霍兰德这类量表属于专业测评，由途径 A 上传报告获取；
本问卷只问**能直接影响志愿筛选**的业务维度（地域、学费、专业、就业），
避免和途径 A 重复采集，也避免让 AI 越权做心理诊断。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.services.profile.extractors import default_llm
from app.services.profile.llm_json import LLMJsonParser
from app.services.profile.prompts import SURVEY_QUESTION_PROMPT

logger = logging.getLogger(__name__)

#: 允许的领域（前端勾选这些值），同时也是内置题库的分组键
ALLOWED_DOMAINS: List[str] = [
    "地域倾向", "学费敏感度", "专业与就业偏好", "办学性质偏好", "升学与发展", "城市与生活",
]

#: 用户没勾选时默认使用的领域
DEFAULT_DOMAINS: List[str] = ["地域倾向", "学费敏感度", "专业与就业偏好", "城市与生活"]

#: 合法的题型
_QUESTION_TYPES = {"single", "multiple", "text"}


# ---------------------------------------------------------------- 内置题库

_BUILTIN_QUESTIONS: List[Dict[str, Any]] = [
    {
        "id": "region",
        "domain": "地域倾向",
        "title": "你希望就读的院校在哪个范围？",
        "type": "single",
        "options": [
            {"value": "local", "label": "本省即可"},
            {"value": "neighbor", "label": "本省或邻近省份"},
            {"value": "any", "label": "全国都可以，优先院校层次"},
        ],
        "hint": "地域会显著影响可选院校数量",
    },
    {
        "id": "tuition",
        "domain": "学费敏感度",
        "title": "家庭能接受的学费范围是？",
        "type": "single",
        "options": [
            {"value": "low", "label": "5000 元/年以内"},
            {"value": "mid", "label": "5000 - 10000 元/年"},
            {"value": "high", "label": "10000 元/年以上也可以"},
        ],
        "hint": "用于过滤中外合作与民办院校",
    },
    {
        "id": "major_pref",
        "domain": "专业与就业偏好",
        "title": "你更看重专业的哪个方面？",
        "type": "single",
        "options": [
            {"value": "interest", "label": "自己感兴趣的"},
            {"value": "employment", "label": "就业率和薪资高的"},
            {"value": "stability", "label": "工作稳定的（如师范、医学、公务员方向）"},
        ],
        "hint": "决定推荐时偏兴趣还是偏就业",
    },
    {
        "id": "major_types",
        "domain": "专业与就业偏好",
        "title": "以下哪些专业方向你有兴趣？（可多选）",
        "type": "multiple",
        "options": [
            {"value": "cs", "label": "计算机 / 电子信息"},
            {"value": "eng", "label": "机械 / 电气 / 土木等工科"},
            {"value": "med", "label": "医学 / 药学"},
            {"value": "edu", "label": "师范 / 教育"},
            {"value": "biz", "label": "经济 / 管理 / 金融"},
            {"value": "art", "label": "文学 / 新闻 / 外语"},
        ],
        "hint": "可多选，用于锁定专业大类",
    },
    {
        "id": "nature",
        "domain": "办学性质偏好",
        "title": "你能接受哪些办学性质？（可多选）",
        "type": "multiple",
        "options": [
            {"value": "public", "label": "公办"},
            {"value": "private", "label": "民办（学费较高）"},
            {"value": "joint", "label": "中外合作办学（学费很高）"},
        ],
        "hint": "民办与中外合作学费通常是公办的数倍",
    },
    {
        "id": "postgrad",
        "domain": "升学与发展",
        "title": "本科毕业后你的打算是？",
        "type": "single",
        "options": [
            {"value": "postgrad", "label": "继续读研"},
            {"value": "job", "label": "直接就业"},
            {"value": "unknown", "label": "还没想好"},
        ],
        "hint": "影响是否优先保研率高的院校",
    },
    {
        "id": "city",
        "domain": "城市与生活",
        "title": "你对城市规模的要求是？",
        "type": "single",
        "options": [
            {"value": "big", "label": "一线 / 新一线城市"},
            {"value": "medium", "label": "省会或地级市即可"},
            {"value": "any", "label": "不限，优先学校实力"},
        ],
        "hint": "大城市实习机会更多，但生活成本更高",
    },
    {
        "id": "extra",
        "domain": "地域倾向",
        "title": "还有其他需要说明的报考要求吗？",
        "type": "text",
        "options": [],
        "hint": "例如：不能离家太远、必须是 985、有专项计划资格等",
    },
]


class SurveyQuestionGenerator:
    """生成志愿填报业务问卷（LLM 优先，内置题库兜底）。"""

    def __init__(self, llm=None, parser: Optional[type] = None) -> None:
        self._llm = llm or default_llm
        self._parser = parser or LLMJsonParser

    # ---------------- 对外入口 ----------------

    def generate(
        self, domains: Optional[List[str]] = None, count: int = 5
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """生成问卷。

        :param domains: 用户勾选的领域；空则用默认领域
        :param count:   题目数量（3-5）
        :return: (questions, fallback)。fallback=True 表示用的是内置题库
        """
        picked = self._resolve_domains(domains)
        count = max(3, min(5, int(count or 5)))

        questions = self._generate_by_llm(picked, count)
        if questions:
            return questions, False

        logger.info("[PROFILE] 问卷 LLM 生成失败，使用内置题库")
        return self._pick_builtin(picked, count), True

    # ---------------- LLM 路 ----------------

    def _generate_by_llm(self, domains: List[str], count: int) -> List[Dict[str, Any]]:
        prompt = SURVEY_QUESTION_PROMPT.format(
            domains="、".join(domains), count=count
        )
        try:
            raw = self._llm(prompt, temperature=0.3, num_predict=1200)
        except Exception as exc:  # noqa: BLE001
            logger.info("[PROFILE] 问卷 LLM 调用异常：%s", exc.__class__.__name__)
            return []
        if not raw:
            return []

        arr = self._parser.parse_array(raw)
        if not arr:
            return []

        out: List[Dict[str, Any]] = []
        for idx, item in enumerate(arr[:count]):
            q = self._normalize_question(item, idx)
            if q:
                out.append(q)
        return out

    @staticmethod
    def _normalize_question(item: Any, idx: int) -> Optional[Dict[str, Any]]:
        """把 LLM 给的单道题收敛成前端可渲染结构；不合格返回 None。"""
        if not isinstance(item, dict):
            return None
        title = str(item.get("title") or "").strip()
        if not title:
            return None

        qtype = str(item.get("type") or "single").strip().lower()
        if qtype not in _QUESTION_TYPES:
            qtype = "single"

        options: List[Dict[str, str]] = []
        for opt in item.get("options") or []:
            if isinstance(opt, dict):
                value = str(opt.get("value") or "").strip()
                label = str(opt.get("label") or "").strip()
                if label:
                    options.append({"value": value or label, "label": label})
            elif isinstance(opt, str) and opt.strip():
                options.append({"value": opt.strip(), "label": opt.strip()})

        # 选择题必须有至少 2 个选项，否则降级成填空题（避免渲染出空卡片）
        if qtype != "text" and len(options) < 2:
            qtype, options = "text", []

        qid = str(item.get("id") or "").strip() or f"q{idx + 1}"
        return {
            "id": qid,
            "title": title,
            "type": qtype,
            "options": options,
            "hint": str(item.get("hint") or "").strip() or None,
        }

    # ---------------- 内置题库路 ----------------

    def _pick_builtin(self, domains: List[str], count: int) -> List[Dict[str, Any]]:
        """按领域筛选内置题，不够就用剩余题补齐。"""
        picked: List[Dict[str, Any]] = []
        for q in _BUILTIN_QUESTIONS:
            if q["domain"] in domains and len(picked) < count:
                picked.append(self._strip_domain(q))
        if len(picked) < count:
            for q in _BUILTIN_QUESTIONS:
                if len(picked) >= count:
                    break
                item = self._strip_domain(q)
                if item["id"] not in {p["id"] for p in picked}:
                    picked.append(item)
        return picked[:count]

    @staticmethod
    def _strip_domain(q: Dict[str, Any]) -> Dict[str, Any]:
        """内置题的 domain 只是分组用，不返回给前端（保持与 LLM 题结构一致）。"""
        return {k: v for k, v in q.items() if k != "domain"}

    # ---------------- 领域归一 ----------------

    @staticmethod
    def _resolve_domains(domains: Optional[List[str]]) -> List[str]:
        """过滤非法领域值；全部非法或为空时回落到默认集合。"""
        if not domains:
            return list(DEFAULT_DOMAINS)
        picked = [d for d in domains if d in ALLOWED_DOMAINS]
        return picked or list(DEFAULT_DOMAINS)


__all__ = [
    "SurveyQuestionGenerator",
    "ALLOWED_DOMAINS",
    "DEFAULT_DOMAINS",
]
