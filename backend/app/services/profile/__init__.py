"""用户画像服务包（0.12.0）。

对外只暴露编排器与仓储抽象，内部实现（Prompt / 解析器 / 提取器）不直接对外，
调用方（路由层）不需要知道画像由几个步骤组成——迪米特法则。

    from app.services.profile import ProfileService, ProfileRepository

    service = ProfileService(ProfileRepository(db))
    service.submit_survey(user_id, questions, answers)
"""
from app.services.profile.extractors import (
    BaseProfileExtractor,
    ReportExtractor,
    SurveyExtractor,
    build_extractor,
    default_llm,
)
from app.services.profile.llm_json import LLMJsonParser
from app.services.profile.repository import (
    BaseProfileRepository,
    InMemoryProfileRepository,
    ProfileRepository,
)
from app.services.profile.report_reader import ReportReadError, ReportReader
from app.services.profile.service import ProfileService
from app.services.profile.summarizer import ProfileSummarizer
from app.services.profile.survey import (
    ALLOWED_DOMAINS,
    DEFAULT_DOMAINS,
    SurveyQuestionGenerator,
)

__all__ = [
    # 编排
    "ProfileService",
    # 仓储
    "BaseProfileRepository",
    "ProfileRepository",
    "InMemoryProfileRepository",
    # 提取器
    "BaseProfileExtractor",
    "ReportExtractor",
    "SurveyExtractor",
    "build_extractor",
    "default_llm",
    # 工具
    "LLMJsonParser",
    "ProfileSummarizer",
    "SurveyQuestionGenerator",
    "ReportReader",
    "ReportReadError",
    "ALLOWED_DOMAINS",
    "DEFAULT_DOMAINS",
]
