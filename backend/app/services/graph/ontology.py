"""知识图谱本体常量（0.9.0）。

把「节点标签 / 关系类型 / 属性键」集中定义在这里，避免中文字符串散落在各个文件里：
- Cypher 里的中文标签必须用反引号包裹（如 `` MATCH (n:`院校`) ``），集中管理后只需在一处处理转义；
- 后续要扩展本体（加节点、加关系）只改本文件，符合开闭原则。

## 图谱结构（高考志愿领域）

    节点：院校 / 专业 / 专业组 / 省份 / 批次 / 选科要求 / 分数段 / 年份
    关系：
        (院校)-[:OPENS]->(专业)       院校在豫开设该专业（携带分数/位次事实）
        (院校)-[:TUITION]->(专业)     该院校该专业的学费（携带 year/province/tuition/duration）
        (院校)-[:ENROLLS]->(专业)     该院校该专业的招生计划（携带 year/batch/plan_count）
        (院校)-[:RANKS]->(分数段)     院校投档线（学校维度）
        (专业)-[:ADMITS]->(分数段)    专业投档线（专业维度）
        (院校)-[:LOCATED_IN]->(省份)  院校所在地
        (专业)-[:BELONGS_TO]->(专业组) 专业归属
        (专业组)-[:REQUIRES]->(选科要求) 选科约束
"""
from __future__ import annotations

# ---------------- 节点标签（Node Labels） ----------------
SCHOOL = "院校"
MAJOR = "专业"
MAJOR_GROUP = "专业组"
PROVINCE = "省份"
BATCH = "批次"
SUBJECT_REQ = "选科要求"
SCORE_SEGMENT = "分数段"
YEAR = "年份"

ALL_LABELS = (SCHOOL, MAJOR, MAJOR_GROUP, PROVINCE, BATCH, SUBJECT_REQ, SCORE_SEGMENT, YEAR)

# ---------------- 关系类型（Relationship Types） ----------------
OPENS = "OPENS"            # 院校 -开设-> 专业
BELONGS_TO = "BELONGS_TO"  # 专业 -属于-> 专业组
LOCATED_IN = "LOCATED_IN"  # 院校 -位于-> 省份
REQUIRES = "REQUIRES"      # 专业组 -要求-> 选科要求
ADMITS = "ADMITS"          # 专业 -录取分-> 分数段
TUITION = "TUITION"        # 专业 -学费（挂在 院校->专业 边上，携带 year/tuition）
ENROLLS = "ENROLLS"        # 专业 -招生人数（挂在 院校->专业 边上，携带 plan_count）
RANKS = "RANKS"            # 院校 -投档分-> 分数段

ALL_REL_TYPES = (OPENS, BELONGS_TO, LOCATED_IN, REQUIRES, ADMITS, TUITION, ENROLLS, RANKS)

# ---------------- 属性键（Property Keys） ----------------
NAME = "name"
CODE = "code"
SCORE = "min_score"
RANK = "min_rank"
TUITION_PROP = "tuition"
PLAN_COUNT = "plan_count"
SUBJECT_REQ_PROP = "subject_req"
PROVINCE_PROP = "province"
YEAR_PROP = "year"


def q(value: str) -> str:
    """Cypher 字符串字面量转义（防止实体名里的单引号注入 / 破坏语句）。"""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def label(label_name: str) -> str:
    """Cypher 标签包裹：中文/含特殊字符的标签必须用反引号。"""
    return "`" + str(label_name).replace("`", "") + "`"
