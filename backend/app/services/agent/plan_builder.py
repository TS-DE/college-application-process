"""人机协同志愿规划的业务组件（0.14.0）。

## 为什么与 workflow.py 分开
`workflow.py` 只负责「把节点连成图、管 Checkpoint」，是**编排**；
本文件负责「生成初稿 / 解析反馈 / 重新筛选」，是**业务**。

这样拆的三个好处（对应设计原则）：
  1. **单一职责**：图不需要知道怎么查位次、怎么筛院校；
  2. **可测试**：本文件的类不依赖 langgraph，桩版测试零安装、零网络；
  3. **可替换**：将来把 MemorySaver 换成 SQLite/Redis Checkpointer，
     业务代码一行都不用改（依赖倒置）。

## 与现有 RAG / Agent 的关系
**完全独立，零改动**：
  · 位次换算复用 `rank_service.score_to_rank()`
  · 冲稳保复用 `recommend_service.calculate_tiers()`
  · 学费富化复用 `recommend_service.enrich_with_plan()`
  · 反馈理解复用 `profile.llm_json.LLMJsonParser()` 与 `ai_service.ask()`
只读不写，不会影响 `/api/ai/chat` 的任何行为。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 每个档位在**初稿**里放多少条（候选池仍有 50 条，供重新规划时替换）
_DRAFT_PER_TIER = {"chong": 6, "wen": 8, "bao": 6}

# 最终方案最多保留多少条
_FINAL_PER_TIER = {"chong": 6, "wen": 8, "bao": 6}

# 「太冷 / 太远 / 太贵」这类模糊表达的语义展开（规则层，不依赖大模型）
_SEMANTIC_ALIASES: Dict[str, List[str]] = {
    "太冷": ["黑龙江", "吉林", "辽宁", "内蒙古", "新疆", "青海", "西藏"],
    "冷": ["黑龙江", "吉林", "辽宁", "内蒙古"],
    "东北": ["黑龙江", "吉林", "辽宁"],
    "太远": ["新疆", "西藏", "海南", "云南", "黑龙江"],
    "偏远": ["新疆", "西藏", "青海", "宁夏", "内蒙古"],
    "南方": ["广东", "广西", "福建", "海南", "云南", "贵州"],
    "江浙沪": ["江苏", "浙江", "上海"],
    "包邮区": ["江苏", "浙江", "上海"],
    "京津冀": ["北京", "天津", "河北"],
    "沿海": ["山东", "江苏", "浙江", "福建", "广东", "辽宁", "天津", "上海"],
}

# 常见专业方向关键词（用于「想学医 / 想学计算机」这类表达）
_MAJOR_KEYWORDS: Dict[str, List[str]] = {
    "计算机": ["计算机", "软件", "数据科学", "人工智能", "网络工程", "信息安全"],
    "医学": ["临床医学", "口腔", "医学", "药学", "护理", "中医"],
    "师范": ["师范", "教育"],
    "金融": ["金融", "经济", "会计", "财务", "审计"],
    "法学": ["法学", "法律"],
    "电子": ["电子", "通信", "微电子", "集成电路"],
    "机械": ["机械", "自动化", "车辆"],
    "土木": ["土木", "建筑", "测绘"],
    "电气": ["电气", "能源", "电力"],
}

# 否定表达（出现即认为该分句是在「排除」）
_NEGATIVE_WORDS = (
    "不去", "不要", "不想", "不喜欢", "不爱", "去掉", "删除", "剔除",
    "排除", "别去", "不考虑", "避开", "太冷", "太远", "太偏", "太贵",
    "不学", "别学", "不读", "不选", "讨厌", "反感",
)

# 肯定表达（出现即认为该分句是在「偏好」）
_POSITIVE_WORDS = ("想去", "想学", "喜欢", "偏好", "希望", "优先", "最好", "倾向")

#: 0.19.0 极性修正：用户说「去福建上学」时不含"想"字，但它显然是**想去**。
#: 规则：分句里出现「动词 + 省份」且无否定词 → 判为偏好。
_POSITIVE_VERBS = ("去", "报", "上", "选", "在")


class PlanInputError(ValueError):
    """规划入参不合法（省份/科类/分数），路由层转 400。"""


@dataclass
class PlanFeedback:
    """结构化的用户反馈（由自由文本解析而来）。"""

    exclude_universities: List[str] = field(default_factory=list)
    exclude_provinces: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    prefer_provinces: List[str] = field(default_factory=list)
    prefer_majors: List[str] = field(default_factory=list)
    max_tuition: Optional[int] = None
    note: str = ""

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PlanFeedback":
        """从字典还原（用于 State 里存的 `intent` / `feedback_parsed`）。"""
        d = data or {}
        max_t = d.get("max_tuition")
        return cls(
            exclude_universities=[str(x) for x in (d.get("exclude_universities") or []) if x],
            exclude_provinces=[str(x) for x in (d.get("exclude_provinces") or []) if x],
            exclude_keywords=[str(x) for x in (d.get("exclude_keywords") or []) if x],
            prefer_provinces=[str(x) for x in (d.get("prefer_provinces") or []) if x],
            prefer_majors=[str(x) for x in (d.get("prefer_majors") or []) if x],
            max_tuition=int(max_t) if isinstance(max_t, (int, float)) and max_t else None,
            note=str(d.get("note") or ""),
        )

    def is_empty(self) -> bool:
        return not any(
            [
                self.exclude_universities,
                self.exclude_provinces,
                self.exclude_keywords,
                self.prefer_provinces,
                self.prefer_majors,
                self.max_tuition,
            ]
        )

    def merge(self, other: "PlanFeedback") -> "PlanFeedback":
        """合并两份反馈（LLM 解析 + 规则解析），去重保序。"""
        def _u(a: List[str], b: List[str]) -> List[str]:
            out: List[str] = []
            for x in list(a) + list(b):
                if x and x not in out:
                    out.append(x)
            return out

        return PlanFeedback(
            exclude_universities=_u(self.exclude_universities, other.exclude_universities),
            exclude_provinces=_u(self.exclude_provinces, other.exclude_provinces),
            exclude_keywords=_u(self.exclude_keywords, other.exclude_keywords),
            prefer_provinces=_u(self.prefer_provinces, other.prefer_provinces),
            prefer_majors=_u(self.prefer_majors, other.prefer_majors),
            max_tuition=other.max_tuition or self.max_tuition,
            note=(self.note or other.note),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exclude_universities": self.exclude_universities,
            "exclude_provinces": self.exclude_provinces,
            "exclude_keywords": self.exclude_keywords,
            "prefer_provinces": self.prefer_provinces,
            "prefer_majors": self.prefer_majors,
            "max_tuition": self.max_tuition,
            "note": self.note,
        }


@dataclass
class PreferenceSource:
    """两个来源的偏好，分开保存、按权重合并（0.19.0）。

    ## 为什么必须分开
    0.14.0 把「用户本次显式输入」和「画像推断」拼成一个字符串再解析：
    `preference_text = user_preferences + " " + profile`。
    一旦两者冲突（画像说喜欢江浙沪，用户这次说想去福建），
    拼接后根本无法判断该听谁的，最后往往两边都进 `prefer_provinces`，
    硬过滤时互相稀释，用户会觉得「我说的话没被听」。

    ## 合并规则：用户显式表达优先，画像只补空缺
    | 维度 | 规则 |
    |---|---|
    | 偏好地区 / 偏好专业 | 用户有值 → **只用用户的**（画像的被抑制，避免稀释）；用户为空 → 用画像的 |
    | 排除地区 / 院校 / 方向 | 两者取并集（排除是硬约束，多一条不会误伤） |
    | 学费上限 | 用户的优先，用户没提才用画像的 |

    理由：用户**本次**说的话是对当前需求的直接表达，时效性与确定性都高于
    历史画像（画像是长期推断，可能过时、可能是闲聊时被误抽的）。
    只有用户没表态的维度，才让画像兜底——这就是「补空缺」的含义。
    """

    user_explicit: PlanFeedback = field(default_factory=PlanFeedback)
    from_profile: PlanFeedback = field(default_factory=PlanFeedback)

    def merge(self) -> PlanFeedback:
        """按「用户优先、画像补缺」合成一份可用反馈。"""
        u, p = self.user_explicit, self.from_profile

        def _first(user_vals: List[str], profile_vals: List[str]) -> List[str]:
            """用户有值就只用用户的，否则用画像的（保序去重）。"""
            src = user_vals or profile_vals
            return list(dict.fromkeys(x for x in src if x))

        def _union(a: List[str], b: List[str]) -> List[str]:
            return list(dict.fromkeys([x for x in list(a) + list(b) if x]))

        merged = PlanFeedback(
            exclude_universities=_union(u.exclude_universities, p.exclude_universities),
            exclude_provinces=_union(u.exclude_provinces, p.exclude_provinces),
            exclude_keywords=_union(u.exclude_keywords, p.exclude_keywords),
            prefer_provinces=_first(u.prefer_provinces, p.prefer_provinces),
            prefer_majors=_first(u.prefer_majors, p.prefer_majors),
            max_tuition=u.max_tuition or p.max_tuition,
            note=u.note or p.note,
        )
        # 用户明确想去的省份，不能被任何一侧的排除规则压掉
        merged.exclude_provinces = [
            x for x in merged.exclude_provinces if x not in u.prefer_provinces
        ]
        return merged


# ============================================================ 初稿生成


class PlanDraftBuilder:
    """生成初步志愿表（确定性引擎，秒级返回）。

    ## 为什么初稿不走大模型
    冲稳保的数学计算（位次窗口、概率映射）用规则引擎更准也更快；
    大模型的价值在 Node 4「根据人话反馈重新筛选」，那里才需要语义理解。
    这与 0.13.1 的结论一致：本地 CPU 上每多一轮 LLM 就多 25-60 秒。
    """

    def __init__(
        self,
        rank_fn=None,
        tiers_fn=None,
        enrich_fn=None,
        per_tier: Optional[Dict[str, int]] = None,
    ) -> None:
        # 依赖注入：默认懒加载真实实现，测试可传桩函数（DIP）
        self._rank_fn = rank_fn
        self._tiers_fn = tiers_fn
        self._enrich_fn = enrich_fn
        self._per_tier = per_tier or dict(_DRAFT_PER_TIER)

    # ---------------- 内部懒加载 ----------------

    def _rank(self, score, province, category, year):
        if self._rank_fn is None:
            from app.services.recommend.rank_service import score_to_rank

            self._rank_fn = score_to_rank
        return self._rank_fn(score, province, category, year)

    def _tiers(self, rank, province, category, year):
        if self._tiers_fn is None:
            from app.services.recommend.recommend_service import calculate_tiers

            self._tiers_fn = calculate_tiers
        return self._tiers_fn(rank, province, category, year)

    def _enrich(self, tiers, province, category, year):
        if self._enrich_fn is None:
            from app.services.recommend.recommend_service import enrich_with_plan

            self._enrich_fn = enrich_with_plan
        try:
            return self._enrich_fn(tiers, province, category, year)
        except Exception as exc:  # noqa: BLE001 富化失败不影响主结果
            logger.info("[PLAN] 学费富化失败：%s", exc.__class__.__name__)
            return tiers

    # ---------------- 对外入口 ----------------

    def build(
        self,
        province: str,
        category: str,
        score: float,
        year: int = 2025,
        rank: Optional[int] = None,
        profile_context: str = "",
    ) -> Dict[str, Any]:
        """生成初稿。

        :return: {
            "rank": int,
            "draft_plan": {chong:[...], wen:[...], bao:[...]},
            "candidate_pool": {chong:[...], ...},   # 全量候选，供重新规划替换
            "summary": str,
        }
        :raises PlanInputError: 省份/科类非法或分数查不到位次
        """
        from app.utils.region_mapper import (
            get_categories_by_province,
            has_data,
            normalize_province,
        )

        prov = normalize_province(province)
        cats = get_categories_by_province(prov) if prov else []
        if not prov or not cats:
            raise PlanInputError(f"不支持的省份：{province}")
        cat = (category or "").strip()
        if cat not in cats:
            raise PlanInputError(f"{prov} 仅支持科类：{'、'.join(cats)}")
        if not has_data(prov):
            raise PlanInputError(f"{prov} 暂无 {year} 年录取数据")

        # ① 分数 → 位次
        student_rank = int(rank or 0)
        if not student_rank:
            if not score:
                raise PlanInputError("请提供分数或位次")
            student_rank = int(self._rank(float(score), prov, cat, year) or 0)
        if student_rank <= 0:
            raise PlanInputError(f"未在 {year} 年 {prov}{cat} 一分一段表中找到该分数")

        # ② 位次 → 冲稳保（全量候选池）
        pool = self._tiers(student_rank, prov, cat, year) or {}
        pool = {k: list(v) for k, v in pool.items()}
        if not any(pool.values()):
            raise PlanInputError(f"{prov}{cat} 位次 {student_rank} 附近暂无可推荐院校")

        # ③ 富化学费 / 计划数 / 学制
        pool = self._enrich(pool, prov, cat, year)

        # ④ 截取初稿
        draft = {
            tier: items[: self._per_tier.get(tier, 6)]
            for tier, items in pool.items()
        }

        summary = self._summary(prov, cat, student_rank, draft, profile_context)
        logger.info(
            "[PLAN] 初稿生成 %s/%s rank=%s → 冲%d 稳%d 保%d",
            prov, cat, student_rank,
            len(draft.get("chong", [])), len(draft.get("wen", [])), len(draft.get("bao", [])),
        )
        return {
            "rank": student_rank,
            "draft_plan": draft,
            "candidate_pool": pool,
            "summary": summary,
        }

    @staticmethod
    def _summary(
        province: str, category: str, rank: int,
        draft: Dict[str, List[Dict]], profile_context: str,
    ) -> str:
        total = sum(len(v) for v in draft.values())
        parts = [
            f"按 {province} {category} 位次 {rank} 生成，共 {total} 条志愿。",
            "冲档用于博取更好的院校，稳档是主力，保档兜底。",
        ]
        if profile_context:
            parts.append("已结合你的画像（意向方向见右侧），如需调整请直接告诉我要改什么。")
        return "".join(parts)


# ============================================================ 反馈理解


class FeedbackInterpreter:
    """把用户的自由文本反馈解析成结构化条件。

    ## 双层策略
    1. **规则层**（永远执行，0 延迟）：分句 + 否定/肯定词 + 省份/院校/专业词典；
    2. **模型层**（可选，`PLAN_LLM_ENABLED=1`）：让大模型输出 JSON，
       覆盖「我其实不想去太冷的地方」这类需要常识的语义。

    两层结果 **合并**（取并集），规则层的确定性不受模型波动影响——
    即使用户说的是「把北京的学校都去掉」，模型抽风也不会漏掉。
    """

    def __init__(self, llm=None, llm_enabled: Optional[bool] = None,
                 llm_timeout: float = 0.0) -> None:
        self._llm = llm
        self._llm_enabled = llm_enabled
        self._llm_timeout = llm_timeout

    # ---------------- 对外入口 ----------------

    def interpret(
        self, text: str, draft: Optional[Dict[str, List[Dict]]] = None
    ) -> PlanFeedback:
        """解析反馈文本；任何异常都退化为规则层结果。

        ## 为什么先规则、后模型
        实测本机 CPU 上一次 LLM 调用 20-60 秒，而「不想去北京」「学费别超 6000」
        这类常见说法规则层 0 毫秒就能解析准确。
        因此采用**规则优先**：规则已解析出条件就不再调模型，
        只有「规则完全看不懂」时才交给大模型（`PLAN_LLM_ENABLED=1` 时）。
        需要强制走模型可设 `PLAN_LLM_ALWAYS=1`。
        """
        raw = (text or "").strip()
        rule_fb = self._rule_based(raw, draft or {})
        if not raw:
            return rule_fb

        if not self._enabled():
            return rule_fb

        # ★ 规则命中即返回（快速路径）
        if not rule_fb.is_empty() and not self._always_use_llm():
            logger.info("[PLAN] 规则层已解析出条件，跳过模型调用")
            return rule_fb

        llm_fb = self._llm_based(raw)
        if llm_fb is None:
            return rule_fb
        merged = rule_fb.merge(llm_fb)
        merged.note = merged.note or raw[:200]
        return merged

    @staticmethod
    def _always_use_llm() -> bool:
        try:
            from app.config import settings

            return bool(getattr(settings, "PLAN_LLM_ALWAYS", False))
        except Exception:  # noqa: BLE001
            return False

    def _enabled(self) -> bool:
        if self._llm_enabled is not None:
            return bool(self._llm_enabled)
        try:
            from app.config import settings

            return bool(settings.PLAN_LLM_ENABLED)
        except Exception:  # noqa: BLE001
            return False

    # ---------------- 规则层 ----------------

    def _rule_based(self, text: str, draft: Dict[str, List[Dict]]) -> PlanFeedback:
        from app.utils.region_mapper import PROVINCE_CATEGORIES

        fb = PlanFeedback()
        if not text:
            return fb

        provinces = list(PROVINCE_CATEGORIES.keys()) + ["北京", "上海", "天津", "重庆"]
        all_items = [it for items in draft.values() for it in items]
        univ_names = {str(it.get("university_name") or "") for it in all_items}

        # 按标点/连词切分句，逐句判断极性
        clauses = [
            c.strip()
            for c in re.split(r"[，,。;；\n、]|但是|不过|而且|可是|但", text)
            if c.strip()
        ]
        for clause in clauses:
            # ① 学费约束独立解析（任何分句都可能出现，与极性无关）
            self._parse_tuition(clause, fb)

            # ② 省份（先算出来：极性判断要用「省份 + 动词」这条规则）
            hit_provs = [p for p in provinces if p and p in clause]
            # ③ 语义别称（太冷 / 江浙沪 …）
            alias_provs: List[str] = []
            for alias, alias_list in _SEMANTIC_ALIASES.items():
                if alias in clause:
                    alias_provs.extend(alias_list)
            provs = list(dict.fromkeys(hit_provs + alias_provs))

            # ④ 极性：否定优先，其次「动词 + 省份」也算肯定
            #    0.19.0：修掉「去福建上学」被判成排除福建的地雷 —— 它不含"想"字，
            #    但「去 + 省份」显然是想去。否定词优先，所以「不想去北京」仍然是排除。
            negative = any(w in clause for w in _NEGATIVE_WORDS)
            positive = (
                any(w in clause for w in _POSITIVE_WORDS)
                or (not negative and bool(provs) and any(v in clause for v in _POSITIVE_VERBS))
            )

            # ④ 具体院校（只在初稿里找，避免瞎猜）
            hit_univs = [u for u in univ_names if u and u in clause]

            # ⑤ 专业方向
            hit_majors: List[str] = []
            for kw, aliases in _MAJOR_KEYWORDS.items():
                if kw in clause or any(a in clause for a in aliases):
                    hit_majors.append(kw)

            if negative:
                fb.exclude_provinces.extend(provs)
                fb.exclude_universities.extend(hit_univs)
                if hit_majors:
                    if positive:
                        # 「想学计算机但别太远」：专业是想要的，只有地区要排除
                        fb.prefer_majors.extend(hit_majors)
                    elif not provs and not hit_univs:
                        # 「不学土木」：专业本身要排除
                        fb.exclude_keywords.extend(hit_majors)
            elif positive:
                fb.prefer_provinces.extend(provs)
                fb.prefer_majors.extend(hit_majors)
            else:
                # 无明确极性：**用户主动提一个省份，多数是想去**（0.19.0 修正）。
                # 想排除时通常会说「不想 / 别 / 不要 / 不考虑」，已由 _NEGATIVE_WORDS 覆盖；
                # 旧实现默认当排除，导致「北京」这种中性提法被误伤。
                if provs:
                    fb.prefer_provinces.extend(provs)
                fb.prefer_majors.extend(hit_majors)

        # 去重
        fb.exclude_provinces = list(dict.fromkeys(fb.exclude_provinces))
        fb.exclude_universities = list(dict.fromkeys(fb.exclude_universities))
        fb.exclude_keywords = list(dict.fromkeys(fb.exclude_keywords))
        fb.prefer_provinces = [
            p for p in dict.fromkeys(fb.prefer_provinces)
            if p not in fb.exclude_provinces
        ]
        fb.prefer_majors = list(dict.fromkeys(fb.prefer_majors))
        fb.note = text[:200]
        return fb

    @staticmethod
    def _parse_tuition(clause: str, fb: PlanFeedback) -> None:
        """从分句里抽学费上限（独立于否定/肯定极性）。

        覆盖说法：
            「学费别超过 6000」/「学费 6000 以内」/「最多 8000」/「太贵了」（无数字→8000）
        """
        if not any(k in clause for k in ("学费", "费用", "元", "贵")):
            return
        nums = re.findall(r"(\d{3,6})", clause)
        capped = any(
            k in clause
            for k in ("超过", "别超", "不超过", "以内", "以下", "最多", "低于", "上限", "左右")
        )
        if nums and (capped or "贵" in clause):
            fb.max_tuition = int(nums[0])
        elif "贵" in clause and not nums:
            # 「太贵了」没给数字 → 用 8000 作为「公办普通专业」的经验上限
            fb.max_tuition = fb.max_tuition or 8000

    # ---------------- 模型层 ----------------

    _LLM_PROMPT = """你是志愿填报助手。请从考生的修改意见中抽取筛选条件。

【修改意见】
{text}

【输出格式】只输出 JSON，不要解释、不要 markdown 围栏：
{{
  "exclude_provinces": ["要排除的省份，中文简称，如 北京"],
  "exclude_universities": ["要删除的院校全名"],
  "prefer_provinces": ["偏好的省份"],
  "prefer_majors": ["偏好的专业方向，如 计算机"],
  "max_tuition": null
}}

【规则】
1. 「不想去太冷的地方」→ exclude_provinces 里列出东北与西北省份（黑龙江、吉林、辽宁、内蒙古、新疆、青海、西藏）。
2. 「太贵了」→ max_tuition 设为 8000。
3. 没提到的字段给空数组 / null。省份用简称（北京、江苏），不要带「省」字。
"""

    def _llm_based(self, text: str) -> Optional[PlanFeedback]:
        try:
            from app.services.llm.ai_service import ask

            raw = ask(
                self._LLM_PROMPT.format(text=text[:500]),
                temperature=0.0,
                top_p=1.0,
                num_predict=300,
                timeout=self._llm_timeout or 25.0,
            )
            if not raw:
                return None
            from app.services.profile.llm_json import LLMJsonParser

            data = LLMJsonParser.parse_object(raw)
            if not isinstance(data, dict):
                return None
            max_t = data.get("max_tuition")
            return PlanFeedback(
                exclude_provinces=[str(x) for x in (data.get("exclude_provinces") or []) if x],
                exclude_universities=[str(x) for x in (data.get("exclude_universities") or []) if x],
                prefer_provinces=[str(x) for x in (data.get("prefer_provinces") or []) if x],
                prefer_majors=[str(x) for x in (data.get("prefer_majors") or []) if x],
                max_tuition=int(max_t) if isinstance(max_t, (int, float)) and max_t else None,
                note=text[:200],
            )
        except Exception as exc:  # noqa: BLE001 模型不可用 → 只用规则层
            logger.info("[PLAN] 反馈解析模型不可用：%s", exc.__class__.__name__)
            return None


# ============================================================ 重新规划


def blocked_reason(item: Dict, feedback: PlanFeedback) -> Optional[str]:
    """该条目被排除的原因；None 表示保留。

    抽成模块级函数是为了让 `refine()`（多轮改写）与
    `build_with_preference()`（初稿硬过滤）共用同一套排除规则，
    避免两处判断口径不一致（0.19.0）。
    """
    name = str(item.get("university_name") or "")
    major = str(item.get("major_name") or "")
    prov = str(item.get("school_province") or "")
    for u in feedback.exclude_universities:
        if u and u in name:
            return f"按院校排除（{u}）"
    for p in feedback.exclude_provinces:
        if p and p == prov:
            return f"按地区排除（{p}）"
    for kw in feedback.exclude_keywords:
        if kw and (kw in name or kw in major):
            return f"按方向排除（{kw}）"
    if feedback.max_tuition:
        tuition = item.get("tuition")
        if isinstance(tuition, (int, float)) and tuition > feedback.max_tuition:
            return f"学费超限（{int(tuition)} > {feedback.max_tuition}）"
    return None


def is_preferred(item: Dict, feedback: PlanFeedback) -> bool:
    """该条目是否命中偏好（地区或专业）。"""
    if str(item.get("school_province") or "") in feedback.prefer_provinces:
        return True
    major = str(item.get("major_name") or "")
    return any(m and m in major for m in feedback.prefer_majors)


class PlanRefiner:
    """根据结构化反馈重新筛选志愿表（只做筛选与排序，不新增院校）。"""

    def __init__(self, per_tier: Optional[Dict[str, int]] = None) -> None:
        self._per_tier = per_tier or dict(_FINAL_PER_TIER)

    def refine(
        self,
        draft: Dict[str, List[Dict]],
        pool: Dict[str, List[Dict]],
        feedback: PlanFeedback,
    ) -> Dict[str, Any]:
        """返回 {"final_plan": {...}, "changes": [...], "note": str}。"""
        changes: List[Dict[str, str]] = []

        def _blocked(item: Dict) -> Optional[str]:
            """返回被排除的原因；None 表示保留（实现见 `blocked_reason`）。"""
            return blocked_reason(item, feedback)

        def _score(item: Dict) -> int:
            """偏好加权：命中偏好地区/专业越多的越靠前。"""
            s = 0
            if str(item.get("school_province") or "") in feedback.prefer_provinces:
                s += 2
            major = str(item.get("major_name") or "")
            if any(m and m in major for m in feedback.prefer_majors):
                s += 1
            return s

        final: Dict[str, List[Dict]] = {}
        for tier in ("chong", "wen", "bao"):
            # 从**候选池**里选，这样排除后还能用后面的补上
            source = pool.get(tier) or draft.get(tier) or []
            kept: List[Dict] = []
            for item in source:
                reason = _blocked(item)
                if reason:
                    changes.append({
                        "action": "remove",
                        "tier": tier,
                        "university": str(item.get("university_name") or ""),
                        "major": str(item.get("major_name") or ""),
                        "reason": reason,
                    })
                    continue
                kept.append(dict(item))

            # 偏好优先（稳定排序，不改变相对顺序）
            if feedback.prefer_provinces or feedback.prefer_majors:
                kept.sort(key=lambda x: -_score(x))

            limit = self._per_tier.get(tier, 6)
            final[tier] = kept[:limit]

        note = ""
        if feedback.is_empty():
            note = "未识别到明确修改条件，已保留原方案。可以试试「不想去北方」「学费别超 6000」这样的说法。"
        elif all(not v for v in final.values()):
            # 全部被排除掉 → 回退原稿，避免给用户一张空表
            final = {k: list(v) for k, v in draft.items()}
            note = "按你的条件筛选后没有剩余院校，已保留原方案；可以放宽一点条件再试。"
            changes = []

        added = sum(len(v) for v in final.values())
        if not note:
            note = f"已按你的意见调整，最终保留 {added} 条志愿。"

        logger.info(
            "[PLAN] 重新规划完成：排除 %d 条，最终 冲%d 稳%d 保%d",
            len(changes),
            len(final.get("chong", [])), len(final.get("wen", [])), len(final.get("bao", [])),
        )
        return {"final_plan": final, "changes": changes, "note": note}


    def build_with_preference(
        self,
        draft: Dict[str, List[Dict]],
        pool: Dict[str, List[Dict]],
        feedback: PlanFeedback,
        per_tier: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """初稿生成：**硬过滤优先**，不足再补位（0.19.0）。

        与 `refine()` 的区别：
          · `refine()` 是「在已有方案上按新意见重筛」，偏好只参与排序（+2 分），
            候选池里的福建院校排到第 30 位时永远进不了前 8；
          · 本方法用于**第一次生成**：命中偏好的条目先占满每一档，
            不足才用其余条目补足 —— 用户说「想去福建」就**一定**能看到福建院校。

        三步：
          ① 硬过滤：每档先取 `school_province ∈ prefer_provinces`
             （或专业命中 `prefer_majors`）的条目，保持候选池原序；
          ② 补足：不足 per_tier 时，用「未命中偏好且未被排除」的条目按原序补；
          ③ 说明：偏好一条都没选出来时，note 必须写明原因，不允许静默返回其它省份。
        """
        changes: List[Dict[str, str]] = []
        final: Dict[str, List[Dict]] = {}
        has_pref = bool(feedback.prefer_provinces or feedback.prefer_majors)
        limits = per_tier or self._per_tier
        pool_provinces: set = set()
        kept_provinces: set = set()

        for tier in ("chong", "wen", "bao"):
            source = pool.get(tier) or draft.get(tier) or []
            kept: List[Dict] = []
            for item in source:
                pool_provinces.add(str(item.get("school_province") or ""))
                reason = blocked_reason(item, feedback)
                if reason:
                    changes.append({
                        "action": "remove",
                        "tier": tier,
                        "university": str(item.get("university_name") or ""),
                        "major": str(item.get("major_name") or ""),
                        "reason": reason,
                    })
                    continue
                kept.append(dict(item))
                kept_provinces.add(str(item.get("school_province") or ""))

            limit = limits.get(tier, 6)
            if not has_pref:
                final[tier] = kept[:limit]
                continue

            preferred = [i for i in kept if is_preferred(i, feedback)]
            rest = [i for i in kept if not is_preferred(i, feedback)]
            picked = preferred[:limit]
            if len(picked) < limit:
                picked += rest[: limit - len(picked)]
            final[tier] = picked

        note = ""
        if has_pref:
            missing = [p for p in feedback.prefer_provinces if p not in kept_provinces]
            if missing:
                absent = [p for p in missing if p not in pool_provinces]
                blocked = [p for p in missing if p in pool_provinces]
                parts: List[str] = []
                if absent:
                    parts.append(
                        f"候选池中没有位于{'、'.join(absent)}的院校，可适当放宽位次范围"
                    )
                if blocked:
                    parts.append(
                        f"候选池中的{'、'.join(blocked)}院校均被其他条件（学费/院校/方向）排除，"
                        f"可适当放宽条件"
                    )
                note = "；".join(parts) + "。已按其余条件为你生成方案。"

        if not note:
            added = sum(len(v) for v in final.values())
            note = f"已按你的偏好生成方案，共 {added} 条志愿。"
        return {"final_plan": final, "changes": changes, "note": note}


__all__ = [
    "PlanInputError",
    "PlanFeedback",
    "PreferenceSource",
    "PlanDraftBuilder",
    "FeedbackInterpreter",
    "PlanRefiner",
    "blocked_reason",
    "is_preferred",
]
