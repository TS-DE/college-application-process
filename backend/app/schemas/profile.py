"""用户画像相关的 Pydantic 模型（0.12.0）。

## 接口隔离原则（ISP）的落地
前端有 5 类完全不同的交互，绝不共用一个「大而全」的模型：

| 交互 | 模型 | 说明 |
|---|---|---|
| 注册 | `schemas.user.RegisterIn` | 账号 + 昵称 + 手机号 |
| 改基础资料 | `ProfileBasicIn` | 只含可编辑的资料字段 |
| 生成问卷 | `SurveyQuestionIn` | 只有「想了解哪些领域」 |
| 提交问卷 | `SurveySubmitIn` | 只有作答列表 |
| 上传报告 | `ReportUploadIn` | 只有报告文本 |

这样做的好处：任一接口新增字段都不会影响其他接口的校验规则，
前端也不会因为一个必填字段变更而被连带报错。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------- 基础资料


class ProfileBasicIn(BaseModel):
    """完善 / 修改基础资料（个人主页）。

    全部字段可选：用户可能只想改昵称，不应该被强制重填其他项。
    """

    nickname: Optional[str] = Field(default=None, max_length=50)
    phone: Optional[str] = Field(default=None, max_length=20)
    gender: Optional[str] = Field(default=None, max_length=10)
    birthday: Optional[date] = None
    email: Optional[str] = Field(default=None, max_length=120)
    # 画像用的补充信息（不落 users 表，只进 basic_info 快照）
    province: Optional[str] = Field(default=None, max_length=30)
    category: Optional[str] = Field(default=None, max_length=30)
    score: Optional[float] = Field(default=None, ge=0, le=750)

    @field_validator("gender")
    @classmethod
    def _check_gender(cls, v: Optional[str]) -> Optional[str]:
        """性别只接受三种取值，空值表示「未填写」。"""
        if v in (None, ""):
            return None
        allowed = {"male", "female", "other"}
        if v not in allowed:
            raise ValueError(f"gender 只能是 {'/'.join(sorted(allowed))}")
        return v


# ---------------------------------------------------------------- 问卷（途径 B）


class SurveyQuestionIn(BaseModel):
    """生成问卷：用户勾选想被了解的领域。

    `domains` 为空时由 Service 使用默认领域集合（地域 / 学费 / 专业 / 就业 / 学习方式）。
    """

    domains: List[str] = Field(default_factory=list, max_length=10)
    count: int = Field(default=5, ge=3, le=5)


class SurveyOption(BaseModel):
    """单个选项：value 供程序使用，label 供展示。"""

    value: str
    label: str


class SurveyQuestion(BaseModel):
    """一道题：type 决定前端渲染成单选 / 多选 / 填空。"""

    id: str
    title: str
    type: str = "single"                      # single / multiple / text
    options: List[SurveyOption] = Field(default_factory=list)
    hint: Optional[str] = None


class SurveyQuestionOut(BaseModel):
    """问卷生成结果。`fallback=True` 表示大模型不可用、返回了内置题库。"""

    questions: List[SurveyQuestion]
    fallback: bool = False
    message: Optional[str] = None


class SurveySubmitIn(BaseModel):
    """提交问卷作答。

    `answers` 用「题目 id → 答案」的字典，而不是并列数组：
    题目顺序/数量变化时不会错位，也天然支持跳题。
    """

    questions: List[SurveyQuestion] = Field(default_factory=list)
    answers: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("answers")
    @classmethod
    def _non_empty(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not v:
            raise ValueError("answers 不能为空")
        return v


# ---------------------------------------------------------------- 报告解析（途径 A）


class ReportUploadIn(BaseModel):
    """上传 MBTI / 霍兰德等报告文本。

    不直接收文件：文件由现有 `/api/knowledge/upload` 的 OCR 链路转成文本后
    再调本接口，避免画像模块重复实现 PDF/OCR 逻辑（合成复用）。
    """

    text: str = Field(..., min_length=10, max_length=20000)
    source_hint: Optional[str] = Field(
        default=None, max_length=50,
        description="报告类型提示，如 MBTI / 霍兰德 / 其他；留空则由大模型自行判断",
    )


# ---------------------------------------------------------------- 画像输出


class ProfileOut(BaseModel):
    """画像完整视图（前端 Step 3 展示 + 个人主页回显）。"""

    user_id: int
    basic_info: Dict[str, Any] = Field(default_factory=dict)
    # 结构化特征：{"mbti": "INTJ", "holland": "IRC", "traits": [...]}
    external_reports: Optional[Dict[str, Any]] = None
    survey_answers: Optional[Dict[str, Any]] = None
    summary_text: Optional[str] = None
    source: Optional[str] = None
    updated_at: Optional[str] = None
    # 是否已有可用画像（summary_text 非空），前端据此决定是否提示「先构建」
    ready: bool = False


class SummaryOut(BaseModel):
    """画像汇总结果（报告解析 / 问卷提交 / 手动重建都返回它）。"""

    summary_text: str
    source: str
    ready: bool = True
    # 便于前端调试：本次提取到的结构化特征
    features: Optional[Dict[str, Any]] = None
