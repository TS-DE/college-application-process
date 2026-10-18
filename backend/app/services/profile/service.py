"""用户画像编排服务（0.12.0）。

## 职责
把「仓储 + 提取器 + 问卷生成器 + 汇总器」编排成 4 个业务动作：
    update_basic     完善基础资料
    generate_survey  生成业务问卷（途径 B 第一步）
    submit_survey    提交问卷并重算画像（途径 B 第二步）
    extract_report   解析报告并重算画像（途径 A）
    rebuild          手动重算画像（两条轨道都走它来汇合）

## 依赖倒置（DIP）
本类只依赖抽象：`BaseProfileRepository` + 「可调用的 LLM 通道」。
不 import 任何具体数据库驱动或 HTTP 客户端，测试时全部可替换。

## 里氏替换（LSP）
`report_extractor` / `survey_extractor` 都声明为 `BaseProfileExtractor`，
本类按统一契约调用 `.extract()` / `.render()`，不关心具体是哪种来源。

## 单一职责（SRP）
路由层拿到的是「已经算好的 dict」，本层不感知 HTTP；
本层也不写 SQL（交给 Repository），不拼 Prompt（交给 prompts.py）。
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.profile.extractors import (
    BaseProfileExtractor,
    ReportExtractor,
    SurveyExtractor,
)
from app.services.profile.repository import BaseProfileRepository
from app.services.profile.summarizer import ProfileSummarizer
from app.services.profile.survey import SurveyQuestionGenerator

logger = logging.getLogger(__name__)

#: 账号表上的资料字段（其余字段只进画像快照）
_USER_FIELDS = ("nickname", "phone", "gender", "birthday", "email")
#: 画像快照里的补充字段
_PROFILE_FIELDS = ("province", "category", "score")


class ProfileService:
    """画像业务编排器（无状态，可安全复用）。"""

    def __init__(
        self,
        repo: BaseProfileRepository,
        report_extractor: Optional[BaseProfileExtractor] = None,
        survey_extractor: Optional[BaseProfileExtractor] = None,
        survey_generator: Optional[SurveyQuestionGenerator] = None,
        summarizer: Optional[ProfileSummarizer] = None,
    ) -> None:
        self._repo = repo
        self._report_extractor = report_extractor or ReportExtractor()
        self._survey_extractor = survey_extractor or SurveyExtractor()
        self._survey_generator = survey_generator or SurveyQuestionGenerator()
        self._summarizer = summarizer or ProfileSummarizer()

    # ============================================================ 读取

    def get(self, user_id: int) -> Dict[str, Any]:
        """返回前端可直接渲染的画像视图。"""
        row = self._repo.get(user_id)
        if row is None:
            user = self._repo.get_user(user_id)
            return {
                "user_id": int(user_id),
                "basic_info": self._basic_from_user(user),
                "external_reports": None,
                "survey_answers": None,
                "summary_text": "",
                "source": "",
                "updated_at": None,
                "ready": False,
            }
        return self._to_view(row)

    def get_summary_for_prompt(self, user_id: int) -> str:
        """供 `/api/ai/chat` 注入：返回画像总结文本，没有则空串。

        注意：本方法**不抛异常**——画像查不到不应该让问答失败。
        """
        try:
            row = self._repo.get(user_id)
        except Exception as exc:  # noqa: BLE001
            logger.info("[PROFILE] 读取画像失败（忽略）：%s", exc.__class__.__name__)
            return ""
        if row is None:
            return ""
        return (row.summary_text or "").strip()

    # ============================================================ 基础资料

    def update_basic(self, user_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """更新基础资料：账号字段写 users，补充字段写画像快照。"""
        user_fields = {
            k: self._coerce(v) for k, v in payload.items()
            if k in _USER_FIELDS and v is not None
        }
        if user_fields:
            self._repo.update_user(user_id, **user_fields)

        # 合并画像快照（已有值不被空值覆盖）
        row = self._repo.get_or_create(user_id)
        snapshot: Dict[str, Any] = dict(row.basic_info or {})

        user = self._repo.get_user(user_id)
        base = self._basic_from_user(user)
        for k, v in base.items():
            if v not in (None, ""):
                snapshot[k] = v

        for key in _PROFILE_FIELDS:
            value = payload.get(key)
            if value not in (None, ""):
                snapshot[key] = self._coerce(value)

        self._repo.save(user_id, basic_info=snapshot)

        # 资料变化后重算画像（若已有任意来源的数据）
        if (row.external_reports or "") or (row.survey_answers or {}):
            self.rebuild(user_id)
        return self.get(user_id)

    # ============================================================ 途径 B：问卷

    def generate_survey(
        self, domains: Optional[List[str]] = None, count: int = 5
    ) -> Tuple[List[Dict[str, Any]], bool]:
        return self._survey_generator.generate(domains, count)

    def submit_survey(
        self,
        user_id: int,
        questions: List[Dict[str, Any]],
        answers: Dict[str, Any],
    ) -> Dict[str, Any]:
        """保存问卷作答 → 提炼特征 → 重算画像。"""
        features = self._survey_extractor.extract(
            {"questions": questions, "answers": answers}
        )
        payload = {
            "questions": questions,
            "answers": answers,
            "features": features,
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._repo.save(user_id, survey_answers=payload)
        return self.rebuild(user_id, fallback_features={"survey": features})

    # ============================================================ 途径 A：报告

    def extract_report(
        self, user_id: int, text: str, source_hint: str = ""
    ) -> Dict[str, Any]:
        """解析报告文本 → 保存特征 → 重算画像。"""
        features = self._report_extractor.extract(text, source_hint=source_hint)
        if not features or not any(
            features.get(k) for k in ("mbti", "holland", "traits", "interests", "majors")
        ):
            raise ValueError(
                "未能从这段文本中识别出 MBTI / 霍兰德等有效特征，"
                "请确认内容是对测评报告的描述后重试"
            )
        self._repo.save(user_id, external_reports=self._dump(features))
        return self.rebuild(user_id, fallback_features={"report": features})

    # ============================================================ 汇总

    def rebuild(
        self,
        user_id: int,
        fallback_features: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """基于当前所有来源重算 `summary_text`。

        :param fallback_features: 刚提取但尚未从库里读回的特征
                                  （`{"report": {...}}` / `{"survey": {...}}`），
                                  避免 save 后立刻再查一次库。
        """
        row = self._repo.get_or_create(user_id)
        fallback = fallback_features or {}

        basic_info = dict(row.basic_info or {})
        user = self._repo.get_user(user_id)
        for k, v in self._basic_from_user(user).items():
            if v not in (None, ""):
                basic_info.setdefault(k, v)

        report_features = fallback.get("report") or self._load(row.external_reports) or {}

        survey_raw = row.survey_answers or {}
        survey_features = (
            fallback.get("survey")
            or (survey_raw.get("features") if isinstance(survey_raw, dict) else None)
            or {}
        )

        summary = self._summarizer.summarize(basic_info, report_features, survey_features)
        source = self._resolve_source(report_features, survey_features)

        self._repo.save(
            user_id,
            summary_text=summary,
            source=source,
            basic_info=basic_info,
        )
        logger.info(
            "[PROFILE] 画像已更新 user=%s source=%s 长度=%d",
            user_id, source, len(summary or ""),
        )
        return {
            "summary_text": summary,
            "source": source,
            "ready": bool(summary),
            "features": {
                "report": report_features,
                "survey": survey_features,
            },
        }

    def delete(self, user_id: int) -> bool:
        return self._repo.delete(user_id)

    # ============================================================ 内部工具

    @staticmethod
    def _resolve_source(
        report_features: Dict[str, Any], survey_features: Dict[str, Any]
    ) -> str:
        has_report = bool(report_features)
        has_survey = bool(survey_features)
        if has_report and has_survey:
            return "both"
        if has_report:
            return "report"
        if has_survey:
            return "survey"
        return "manual"

    def _to_view(self, row) -> Dict[str, Any]:
        summary = (row.summary_text or "").strip()
        updated = getattr(row, "updated_at", None)
        return {
            "user_id": int(row.user_id),
            "basic_info": dict(row.basic_info or {}),
            "external_reports": self._load(row.external_reports),
            "survey_answers": row.survey_answers or None,
            "summary_text": summary,
            "source": row.source or "",
            "updated_at": self._format_dt(updated),
            "ready": bool(summary),
        }

    @staticmethod
    def _basic_from_user(user: Any) -> Dict[str, Any]:
        """从 users 行取基础资料快照（user 可能是 ORM 或普通 dict）。"""
        if user is None:
            return {}
        def pick(name: str) -> Any:
            if isinstance(user, dict):
                return user.get(name)
            return getattr(user, name, None)

        return {
            "username": pick("username"),
            "nickname": pick("nickname"),
            "gender": pick("gender"),
            "birthday": ProfileService._coerce(pick("birthday")),
            "email": pick("email"),
        }

    @staticmethod
    def _coerce(value: Any) -> Any:
        """把 date/datetime 转成字符串，None 原样返回（便于写 JSON 列）。"""
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value

    @staticmethod
    def _format_dt(value: Any) -> Optional[str]:
        if isinstance(value, (datetime, date)):
            return value.isoformat(timespec="seconds") if isinstance(value, datetime) else value.isoformat()
        return str(value) if value else None

    @staticmethod
    def _load(raw: Optional[str]) -> Optional[Dict[str, Any]]:
        """把 TEXT 里的 JSON 字符串解析回 dict；坏数据返回 None（不抛异常）。"""
        if not raw:
            return None
        if isinstance(raw, dict):
            return raw
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _dump(data: Dict[str, Any]) -> str:
        try:
            return json.dumps(data, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            return "{}"


__all__ = ["ProfileService"]
