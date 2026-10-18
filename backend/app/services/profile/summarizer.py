"""画像汇总器（0.12.0）：把多源信息合成一段注入 AI 的自然语言画像。

## 单一职责
只做「汇总文本生成」，不碰数据库、不碰路由、不解析原始报告
（那些由 `extractors.py` 完成）。输入已经是三份结构化数据：
    basic_info       基础信息快照
    report_features  途径 A 提取的特征
    survey_features  途径 B 提取的特征

## 为什么要规则兜底
画像注入属于「锦上添花」：大模型不可用时，宁可用模板拼一句朴素的画像，
也不能让 `/api/profile/report/upload` 直接 500 —— 用户上传了报告却什么都没保存，
体验比没有画像更差。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.services.profile.extractors import default_llm
from app.services.profile.prompts import PROFILE_SUMMARY_PROMPT

logger = logging.getLogger(__name__)


class ProfileSummarizer:
    """生成画像总结文本（LLM 优先，规则模板兜底）。"""

    def __init__(self, llm=None) -> None:
        self._llm = llm or default_llm

    # ---------------- 对外入口 ----------------

    def summarize(
        self,
        basic_info: Optional[Dict[str, Any]] = None,
        report_features: Optional[Dict[str, Any]] = None,
        survey_features: Optional[Dict[str, Any]] = None,
    ) -> str:
        """返回画像正文（非空字符串）。LLM 失败时返回规则版。"""
        basic = basic_info or {}
        report = report_features or {}
        survey = survey_features or {}

        prompt = PROFILE_SUMMARY_PROMPT.format(
            basic_info=self._render_basic(basic),
            report_features=self._render_json(report),
            survey_answers=self._render_json(survey),
        )
        try:
            text = self._llm(prompt, temperature=0.3, num_predict=500)
        except Exception as exc:  # noqa: BLE001
            logger.info("[PROFILE] 汇总 LLM 调用异常：%s", exc.__class__.__name__)
            text = ""

        cleaned = self._clean(text)
        if cleaned:
            return cleaned

        logger.info("[PROFILE] 汇总 LLM 无输出，使用规则模板")
        return self.rule_summary(basic, report, survey)

    # ---------------- 规则兜底 ----------------

    def rule_summary(
        self,
        basic_info: Dict[str, Any],
        report_features: Dict[str, Any],
        survey_features: Dict[str, Any],
    ) -> str:
        """用模板拼一段朴素但信息准确的画像（不编造任何数据）。"""
        parts: List[str] = []

        # ① 性格 / 能力特征
        traits: List[str] = []
        for src in (report_features.get("traits"), survey_features.get("traits")):
            for t in (src or []):
                if isinstance(t, str) and t and t not in traits:
                    traits.append(t)
        mbti = (report_features.get("mbti") or "").strip()
        holland = (report_features.get("holland") or "").strip()
        if mbti:
            parts.append(f"你的 MBTI 类型为 {mbti}。")
        if holland:
            parts.append(f"霍兰德代码为 {holland}。")
        if traits:
            parts.append("你的主要特点是" + "、".join(traits[:5]) + "。")

        # ② 专业倾向
        interests: List[str] = []
        for src in (report_features.get("interests"), report_features.get("majors")):
            for t in (src or []):
                if isinstance(t, str) and t and t not in interests:
                    interests.append(t)
        if interests:
            parts.append("可重点考虑" + "、".join(interests[:4]) + "等方向。")

        # ③ 报考偏好（问卷来的键值）
        prefs = survey_features.get("preferences") or {}
        if isinstance(prefs, dict) and prefs:
            kv = [f"{k}：{v}" for k, v in list(prefs.items())[:5] if v]
            if kv:
                parts.append("报考偏好为" + "，".join(kv) + "。")

        # ④ 基础信息
        geo = []
        if basic_info.get("province"):
            geo.append(f"生源地 {basic_info['province']}")
        if basic_info.get("category"):
            geo.append(f"科类 {basic_info['category']}")
        if basic_info.get("score"):
            geo.append(f"预估分数 {basic_info['score']}")
        if geo:
            parts.append("，".join(geo) + "。")

        if not parts:
            return (
                "你还没有提供足够的信息来生成画像。"
                "建议先填写基础资料，或上传一份 MBTI / 霍兰德报告，或完成一次业务问卷，"
                "这样我可以给出更贴合你情况的志愿建议。"
            )

        parts.append("建议结合上述特征优先筛选匹配的专业大类，再按位次确定冲稳保梯度。")
        return "".join(parts)

    # ---------------- 渲染工具 ----------------

    @staticmethod
    def _render_basic(basic: Dict[str, Any]) -> str:
        if not basic:
            return "（无）"
        # 只挑对志愿有意义的键，避免把手机号等隐私喂给模型
        keys = ("nickname", "gender", "province", "category", "score", "birthday")
        picked = {k: basic.get(k) for k in keys if basic.get(k) not in (None, "")}
        return ProfileSummarizer._render_json(picked)

    @staticmethod
    def _render_json(data: Dict[str, Any]) -> str:
        if not data:
            return "（无）"
        try:
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            return str(data)

    @staticmethod
    def _clean(text: Optional[str]) -> str:
        """清理模型输出的元叙述与多余标记。"""
        if not text:
            return ""
        out = str(text).strip()
        # 去掉可能的 markdown 标题 / 加粗
        out = out.lstrip("#").replace("**", "").strip()
        # 去掉「好的，以下是画像：」这类前缀
        for prefix in ("好的，以下是", "以下是根据", "根据您提供的信息，", "画像总结："):
            if out.startswith(prefix):
                out = out[len(prefix):].lstrip("：:，, ")
        if len(out) < 10:
            return ""
        return out[:800]


__all__ = ["ProfileSummarizer"]
