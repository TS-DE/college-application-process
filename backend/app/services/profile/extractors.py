"""画像特征提取器（0.12.0）。

## 设计要点

**依赖倒置（DIP）**：提取器只依赖一个可调用的 LLM 通道
`llm(prompt, temperature, num_predict) -> str`，不 import 具体是阿里云还是 Ollama；
测试时注入桩函数即可，零网络开销。

**里氏替换（LSP）**：`ReportExtractor` 与 `SurveyExtractor` 都继承
`BaseProfileExtractor`，对外暴露完全相同的 `extract()` / `render()` 契约，
`ProfileService` 可以无差别地持有任意一个（甚至将来新增的实现）。

**合成复用（CRP）**：两个子类共用基类的「调 LLM → 解析 JSON → 归一化」骨架，
子类只实现「怎么拼 Prompt」和「怎么归一化」两个差异点，不重复写解析逻辑。

**开闭原则（OCP）**：新增来源（比如「性格测试」）只需继承基类并注册，
不用改 `service.py` 的编排。
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.services.profile.llm_json import LLMJsonParser
from app.services.profile.prompts import REPORT_EXTRACT_PROMPT, SURVEY_EXTRACT_PROMPT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- 默认 LLM 通道


def default_llm(prompt: str, temperature: float = 0.0, num_predict: int = 800) -> str:
    """默认 LLM 通道：统一走 `ai_service.ask`（阿里云 → Ollama 兜底）。

    单独包一层是为了满足 DIP：提取器不直接依赖 ai_service 的具体实现，
    只依赖这个函数签名；测试时替换成桩函数即可。
    """
    from app.services.llm.ai_service import ask

    return ask(prompt, temperature=temperature, top_p=0.85, num_predict=num_predict, timeout=60) or ""


# ---------------------------------------------------------------- 抽象基类


class BaseProfileExtractor(ABC):
    """画像特征提取器基类：定义「提取 → 归一化 → 渲染」的统一契约。"""

    #: 来源标识，写进 `user_profiles.source`，便于前端区分与统计
    kind: str = "base"

    def __init__(self, llm=None, parser: Optional[type] = None) -> None:
        """
        :param llm:    可调用对象 (prompt, temperature, num_predict) -> str
        :param parser: JSON 解析器类（默认 LLMJsonParser）
        """
        self._llm = llm or default_llm
        self._parser = parser or LLMJsonParser

    # ---------------- 对外唯一入口 ----------------

    def extract(self, payload: Any, **kwargs: Any) -> Dict[str, Any]:
        """提取结构化特征；任何失败都返回「空但合法」的 dict，绝不抛异常。"""
        try:
            prompt = self.build_prompt(payload, **kwargs)
        except Exception as exc:  # noqa: BLE001 拼 Prompt 失败也要降级
            logger.info("[PROFILE] %s 拼 Prompt 失败：%s", self.kind, exc.__class__.__name__)
            return self.empty()
        if not prompt:
            return self.empty()

        try:
            raw = self._llm(prompt, temperature=0.0, num_predict=900)
        except Exception as exc:  # noqa: BLE001
            logger.info("[PROFILE] %s LLM 调用失败：%s", self.kind, exc.__class__.__name__)
            return self.empty()

        data = self._parser.parse_object(raw) or {}
        if not data:
            # 少数模型会直接输出数组（如问卷总结给了 traits 列表），再试一次
            arr = self._parser.parse_array(raw)
            if arr:
                data = {"items": arr}
        return self.normalize(data)

    # ---------------- 子类必须实现 ----------------

    @abstractmethod
    def build_prompt(self, payload: Any, **kwargs: Any) -> str:
        """把入参渲染成 Prompt；返回空串表示「无有效输入，跳过 LLM」。"""

    @abstractmethod
    def normalize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """把 LLM 解析结果收敛成固定结构（补齐缺失键、剔除类型不对的值）。"""

    # ---------------- 可选覆写 ----------------

    def empty(self) -> Dict[str, Any]:
        """空结果（子类可覆写以给出对应的空结构）。"""
        return {}

    def render(self, features: Dict[str, Any]) -> str:
        """把特征渲染成给「汇总 Prompt」看的可读文本（默认 JSON 美化输出）。"""
        if not features:
            return "（无）"
        try:
            return json.dumps(features, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            return str(features)


# ---------------------------------------------------------------- 途径 A：报告


class ReportExtractor(BaseProfileExtractor):
    """从 MBTI / 霍兰德等测评报告文本里抽取结构化特征。"""

    kind = "report"

    def empty(self) -> Dict[str, Any]:
        return {"mbti": "", "holland": "", "traits": [], "interests": [], "majors": [], "summary": ""}

    def build_prompt(self, payload: Any, source_hint: str = "", **kwargs: Any) -> str:
        text = (str(payload) if payload is not None else "").strip()
        if len(text) < 10:
            return ""
        # 报告可能很长，截断到 6000 字，避免超出上下文预算
        return REPORT_EXTRACT_PROMPT.format(
            text=text[:6000],
            source_hint=(source_hint or "未知（请自行判断是 MBTI / 霍兰德 / 其他）").strip(),
        )

    def normalize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        out = self.empty()

        for key in ("mbti", "holland", "summary"):
            value = data.get(key)
            if isinstance(value, str):
                out[key] = value.strip().upper() if key != "summary" else value.strip()

        for key in ("traits", "interests", "majors"):
            out[key] = _as_str_list(data.get(key), limit=10)

        # 兜底：模型可能把 traits 塞在别的键名下
        if not out["traits"]:
            out["traits"] = _as_str_list(data.get("personality"), limit=10)
        return out


# ---------------------------------------------------------------- 途径 B：问卷


class SurveyExtractor(BaseProfileExtractor):
    """把业务问卷的「题目 + 作答」压缩成画像特征。"""

    kind = "survey"

    def empty(self) -> Dict[str, Any]:
        return {"answers": [], "traits": [], "preferences": {}, "summary": ""}

    def build_prompt(self, payload: Any, **kwargs: Any) -> str:
        """payload 期望是 {"questions": [...], "answers": {...}}。"""
        if not isinstance(payload, dict):
            return ""
        questions = payload.get("questions") or []
        answers = payload.get("answers") or {}
        if not answers:
            return ""

        lines: List[str] = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            qid = str(q.get("id") or "").strip()
            if not qid or qid not in answers:
                continue
            title = str(q.get("title") or qid)
            raw = answers[qid]
            # 把选项 value 翻译成 label，让模型读到的是人话而不是 "low"/"mid"
            label_map = {
                str(o.get("value")): str(o.get("label"))
                for o in (q.get("options") or [])
                if isinstance(o, dict)
            }
            if isinstance(raw, list):
                human = "、".join(label_map.get(str(v), str(v)) for v in raw)
            else:
                human = label_map.get(str(raw), str(raw))
            lines.append(f"- 题目：{title}\n  作答：{human}")

        if not lines:
            return ""
        return SURVEY_EXTRACT_PROMPT.format(answers="\n".join(lines))

    def normalize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        out = self.empty()
        out["answers"] = data.get("answers") if isinstance(data.get("answers"), list) else []
        out["traits"] = _as_str_list(data.get("traits"), limit=10)
        prefs = data.get("preferences")
        if isinstance(prefs, dict):
            # 只保留「字符串 → 字符串/数字」的简单键值，避免嵌套噪声
            out["preferences"] = {
                str(k): v for k, v in prefs.items()
                if isinstance(v, (str, int, float)) and str(v).strip()
            }
        summary = data.get("summary")
        out["summary"] = summary.strip() if isinstance(summary, str) else ""
        return out


# ---------------------------------------------------------------- 工具


def _as_str_list(value: Any, limit: int = 10) -> List[str]:
    """把任意输入收敛成「去重后的非空字符串列表」。"""
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("，", ",").split(",")]
        items = parts
    elif isinstance(value, (list, tuple)):
        items = [str(v).strip() for v in value]
    else:
        return []
    out: List[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out[:limit]


#: 已注册的提取器（OCP：新增来源只需在此追加一个子类）
EXTRACTOR_REGISTRY: Dict[str, type] = {
    ReportExtractor.kind: ReportExtractor,
    SurveyExtractor.kind: SurveyExtractor,
}


def build_extractor(kind: str, **kwargs: Any) -> Optional[BaseProfileExtractor]:
    """按来源标识构造提取器（工厂，调用方不直接依赖具体类）。"""
    cls = EXTRACTOR_REGISTRY.get(kind)
    if cls is None:
        return None
    return cls(**kwargs)


__all__ = [
    "BaseProfileExtractor",
    "ReportExtractor",
    "SurveyExtractor",
    "EXTRACTOR_REGISTRY",
    "build_extractor",
    "default_llm",
]
