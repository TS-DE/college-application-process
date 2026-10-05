"""Pydantic 请求/响应模型。"""
from typing import List, Optional

from pydantic import BaseModel, Field


class StudentProfileIn(BaseModel):
    province: str = Field(default="河南", description="高考所在地")
    year: int = Field(default=2025, description="参考年份")
    category: str = Field(default="物理类", description="科类：物理类/历史类")
    batch: str = Field(default="本科批", description="批次：本科批/专科批")
    score: Optional[int] = Field(default=None, description="高考分数")
    rank: Optional[int] = Field(default=None, description="位次，不给则自动换算")
    name: Optional[str] = None


class StudentProfileOut(BaseModel):
    student_id: int
    province: str
    year: int
    category: str
    batch: str
    score: Optional[int]
    rank: Optional[int]
    control_score: Optional[int] = None
    score_diff: Optional[int] = None


class ScoreToRankOut(BaseModel):
    province: str
    year: int
    category: str
    batch: str
    score: float
    rank: int
    segment_count: Optional[int] = None
    rank_range: Optional[str] = None
    control_score: Optional[int] = None
    batch_used: Optional[str] = None
    exact: bool = True


class RankToScoreOut(BaseModel):
    province: str
    year: int
    category: str
    batch: str
    rank: int
    score: Optional[float] = None
    rank_range: Optional[str] = None
    control_score: Optional[int] = None


class RecommendFilters(BaseModel):
    major_keyword: Optional[str] = None          # 专业关键字，如「计算机」
    exclude_keyword: Optional[str] = None        # 排除关键字，如「中外合作」
    university_keyword: Optional[str] = None     # 院校名称关键字
    school_province: Optional[str] = None        # 院校所在省，如「北京」
    school_nature: Optional[str] = None          # 公办 / 民办
    tuition_max: Optional[int] = None            # 学费上限（元/年）
    subject_req: Optional[str] = None            # 选科要求关键字，如「化学」
    is_985: Optional[bool] = None
    is_211: Optional[bool] = None
    is_double_first_class: Optional[bool] = None  # 双一流（数据集中以 985/211 近似）
    subject_selected: Optional[List[str]] = Field(
        default=None, description="考生再选科目（3+1+2），如 ['化学','生物']"
    )


class RecommendIn(BaseModel):
    province: str = "河南"
    year: int = 2025
    category: str = "物理类"
    batch: str = "本科批"
    score: Optional[int] = None
    rank: Optional[int] = None
    filters: Optional[RecommendFilters] = None
    buffer: Optional[int] = Field(default=None, description="冲稳保位次缓冲，默认 5000")
    span_factor: Optional[int] = Field(default=None, description="冲/保 搜索倍数")
    limit: int = Field(default=60, ge=1, le=300, description="每档返回条数")
    with_ai: bool = Field(default=False, description="是否调用大模型生成推荐理由")
    ai_limit: int = Field(default=8, ge=0, le=60, description="调用大模型生成理由的最大条数")


class RecommendItem(BaseModel):
    university_code: Optional[str] = None
    university_name: Optional[str] = None
    major_code: Optional[str] = None
    major_name: Optional[str] = None
    major_group: Optional[str] = None
    major_note: Optional[str] = None
    subject_req: Optional[str] = None
    min_score: Optional[float] = None
    min_rank: Optional[int] = None
    max_score: Optional[float] = None
    avg_score: Optional[float] = None
    admit_count: Optional[float] = None
    plan_count: Optional[float] = None
    tuition: Optional[float] = None
    duration: Optional[str] = None
    school_province: Optional[str] = None
    school_nature: Optional[str] = None
    is_985: bool = False
    is_211: bool = False
    is_double_first_class: bool = False
    batch: Optional[str] = None
    year: Optional[int] = None
    rank_diff: Optional[int] = None      # 学校最低位次 - 考生位次，正=更稳妥
    tier: Optional[str] = None           # chong / wen / bao
    tier_label: Optional[str] = None     # 冲 / 稳 / 保
    probability: Optional[int] = None    # 规则估算的录取概率（%）
    reason: Optional[str] = None         # 规则生成的推荐理由
    ai_reason: Optional[str] = None      # 大模型生成的推荐理由
    ai: bool = False                     # ai_reason 是否真的来自大模型


class RecommendMeta(BaseModel):
    total_scanned: int = 0
    buffer: int = 0
    span_factor: int = 0
    table: Optional[str] = None
    ai_enabled: bool = False
    ai_generated: int = 0
    elapsed_ms: int = 0


class RecommendOut(BaseModel):
    student: dict
    chong: List[RecommendItem] = []
    wen: List[RecommendItem] = []
    bao: List[RecommendItem] = []
    meta: RecommendMeta


class UniversityQuery(BaseModel):
    province: str = "河南"
    year: int = 2025
    category: str = "物理类"
    batch: str = "本科批"
    keyword: Optional[str] = None
    school_province: Optional[str] = None
    school_nature: Optional[str] = None
    is_985: Optional[bool] = None
    is_211: Optional[bool] = None
    min_rank: Optional[int] = None
    max_rank: Optional[int] = None
    page: int = 1
    page_size: int = 20


class ParseIntentIn(BaseModel):
    text: str
    province: str = "河南"
    year: int = 2025
    category: str = "物理类"
    batch: str = "本科批"


class ParseIntentOut(BaseModel):
    major_keyword: Optional[str] = None
    exclude_keyword: Optional[str] = None
    region_preference: Optional[str] = None
    school_province: Optional[str] = None
    tuition_max: Optional[int] = None
    school_nature: Optional[str] = None
    is_985: Optional[bool] = None
    is_211: Optional[bool] = None
    subject_req: Optional[str] = None
    raw: Optional[str] = None
    source: str = "rule"   # llm / rule


class RecommendReasonIn(BaseModel):
    university_name: str
    major_name: Optional[str] = None
    min_rank: Optional[int] = None
    min_score: Optional[float] = None
    student_rank: Optional[int] = None
    student_score: Optional[int] = None
    tier: Optional[str] = None
    school_province: Optional[str] = None
    tuition: Optional[float] = None


class RecommendReasonOut(BaseModel):
    reason: str
    source: str = "rule"
