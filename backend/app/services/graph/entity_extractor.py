"""实体识别：LLM 抽取 + 词典匹配双路混合（0.9.0）。

## 为什么必须双路（Hybrid）
- **LLM 路**：能识别口语化 / 简称 / 未见过的写法（"至诚学院" → "福州大学至诚学院"），但慢（一次网络往返）且可能幻觉；
- **词典路**：从 MySQL 的院校名 / 专业名列生成词典做字符串匹配，零延迟、零幻觉，但只能命中库里真实存在的全称。
两路**合并去重**，词典路结果**优先**（来自权威数据源，见需求 2.2）。

## 单一职责
本类只负责「从 query 里抽出 (实体类型, 实体名)」，不生成 Cypher、不查库。

## 降级契约
- LLM 路失败 → 只用词典路；词典路为空 → 只用 LLM 路；两路都空 → 返回 []；
- 任何一路抛异常都被吞掉返回 []，绝不中断问答链路。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 实体类型 → 中文说明（LLM Prompt 与词典共用，避免两处写法不一致）
ENTITY_TYPES = ("院校", "专业", "省份", "年份", "专业组")

# LLM 抽取 Prompt：严格 JSON 输出 + temperature=0（实体识别要确定性，不能自由发挥）
ENTITY_EXTRACT_PROMPT = """你是高考志愿填报领域的实体识别专家。请从用户问题中抽取实体。

【可识别的实体类型】
- 院校：大学 / 学院 / 职业技术学院的全称或简称，如「郑州大学」「福州大学至诚学院」
- 专业：专业名称，如「计算机科学与技术」「临床医学」
- 省份：省级行政区，如「河南」「北京」
- 年份：4 位数字年份，如「2025」
- 专业组：如「2025 本科批物理类专业组 101」

【抽取规则】
1. 只抽取问题中**真实出现**的实体，不要推测、不要补全；
2. 院校名尽量保留完整写法（"至诚学院"补成"福州大学至诚学院"）；
3. 年份必须是 4 位数字；抽不到某类实体就不要输出该类；
4. 不要输出解释文字。

【输出格式】（严格 JSON，不要输出任何其他文字）
{{"entities": [{{"type": "院校", "name": "福州大学至诚学院"}}, {{"type": "专业", "name": "计算机科学与技术"}}]}}

【用户问题】
{query}

【JSON输出】"""


def default_llm_chat(prompt: str, temperature: float = 0.0, max_tokens: int = 400) -> str:
    """默认 LLM 通道适配器：统一走阿里云 OpenAI 兼容接口（Ali → Ollama 兜底）。

    放在这里而不是各调用方里，是为了让 `EntityExtractor()` / `CypherGenerator()`
    不注入也能开箱即用；测试时仍然可以传桩函数覆盖（依赖倒置不被破坏）。
    局部导入 `ai_service` 避免循环依赖。
    """
    from app.services.llm.ai_service import ask

    return ask(prompt, temperature=temperature, top_p=1.0,
               num_predict=max_tokens, timeout=30) or ""


class EntityExtractor:
    """双路混合实体识别器。"""

    def __init__(self, llm_chat=None, entity_dict: Optional[Dict[str, List[str]]] = None,
                 use_llm: bool = True) -> None:
        """
        :param llm_chat: 可调用对象 (prompt, temperature, max_tokens) -> str。
                          依赖倒置：注入函数而不是 import 具体 LLM 模块，
                          测试时可传桩函数，无需真实调用阿里云接口。
                          为 None 时用 `default_llm_chat`（阿里云 OpenAI 兼容通道）。
        :param entity_dict: {"院校": [...], "专业": [...], "省份": [...]}
        :param use_llm:  False 时关闭 LLM 抽取路（只留词典路，零网络开销），
                         对应配置项 GRAPH_LLM_EXTRACT_ENABLED。
        """
        self._llm_chat = llm_chat or default_llm_chat
        self.entity_dict = entity_dict or {}
        self.use_llm = use_llm

    # ---------------- 对外入口 ----------------

    def extract(self, query: str) -> List[Dict[str, str]]:
        """双路合并去重；词典路结果排在前面（优先级更高）。"""
        query = (query or "").strip()
        if not query:
            return []

        dict_hits = self.extract_by_dict(query)
        llm_hits = self.extract_by_llm(query)

        merged: List[Dict[str, str]] = []
        seen = set()
        for item in list(dict_hits) + list(llm_hits):
            key = (item.get("type"), item.get("name"))
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            merged.append({"type": key[0], "name": key[1]})

        # 实体消歧：把 LLM 抽到的简称归一到词典里的权威全称
        # （"计算机" → "计算机科学与技术"），否则 Cypher 按简称查节点会一条都匹配不上
        merged = self.canonicalize(merged)

        logger.info("[GRAPH] 实体识别：词典 %d 条 + LLM %d 条 → 合并 %d 条（query=%s）",
                    len(dict_hits), len(llm_hits), len(merged), query)
        return merged

    # ---------------- 实体消歧（简称 → 权威全称） ----------------

    def canonicalize(self, entities: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """把实体名归一到词典全称；词典里没有的原样保留（库里可能真没有）。

        匹配优先级：完全相等 > 词典名以简称开头 > 词典名包含简称；
        同优先级取最长的词典名（"计算机" 优先归到 "计算机科学与技术" 而不是 "计算机网络技术"）。
        """
        out: List[Dict[str, str]] = []
        seen = set()
        for item in entities:
            etype = str(item.get("type") or "").strip()
            name = str(item.get("name") or "").strip()
            if not etype or not name:
                continue
            if etype in ("院校", "专业"):
                name = self._match_dict(etype, name) or name
            key = (etype, name)
            if key in seen:
                continue
            seen.add(key)
            out.append({"type": etype, "name": name})
        return out

    def _match_dict(self, etype: str, name: str) -> Optional[str]:
        """在词典里给实体名找权威全称；找不到返回 None。"""
        names = self.entity_dict.get(etype) or []
        if not names or not name:
            return None
        if name in names:
            return name
        prefixed = [n for n in names if n.startswith(name)]
        if prefixed:
            return max(prefixed, key=len)
        contained = [n for n in names if name in n]
        if contained:
            return max(contained, key=len)
        return None

    # ---------------- 词典路 ----------------

    def extract_by_dict(self, query: str) -> List[Dict[str, str]]:
        """词典字符串匹配：长名优先，避免「郑州大学」抢先于「郑州大学体育学院」。"""
        if not self.entity_dict:
            return []
        hits: List[Dict[str, str]] = []
        for etype, names in self.entity_dict.items():
            for name in sorted((n for n in names if n), key=len, reverse=True):
                if len(name) >= 2 and name in query:
                    hits.append({"type": etype, "name": name})
        return hits

    # ---------------- LLM 路 ----------------

    def extract_by_llm(self, query: str) -> List[Dict[str, str]]:
        """LLM 抽取；关闭 / 调用失败 / 解析失败均返回 []（由调用方降级到词典路）。"""
        if not self.use_llm:
            return []
        try:
            raw = self._llm_chat(ENTITY_EXTRACT_PROMPT.format(query=query), temperature=0.0, max_tokens=200)
        except Exception as exc:  # noqa: BLE001
            logger.info("[GRAPH] LLM 实体抽取失败，降级到词典路：%s", exc.__class__.__name__)
            return []
        return self._parse_entities(raw)

    @staticmethod
    def _parse_entities(raw: Optional[str]) -> List[Dict[str, str]]:
        """解析 LLM 输出：优先整体 JSON，失败则逐个 {} 块兜底。"""
        if not raw:
            return []
        text = raw.strip().strip("`").strip()
        data = None
        try:
            data = json.loads(text)
        except Exception:  # noqa: BLE001 模型爱在 JSON 前后加废话，用正则抠第一个对象
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                try:
                    data = json.loads(m.group(0))
                except Exception:  # noqa: BLE001
                    data = None
        if not isinstance(data, dict):
            return []

        out: List[Dict[str, str]] = []
        for item in data.get("entities") or []:
            if not isinstance(item, dict):
                continue
            etype = str(item.get("type") or "").strip()
            name = str(item.get("name") or "").strip()
            if etype in ENTITY_TYPES and name:
                out.append({"type": etype, "name": name})
        return out

    # ---------------- 词典构建（MySQL → 词典） ----------------

    def load_entity_dict_from_mysql(self, year: int = 2025, province: str = "河南") -> Dict[str, List[str]]:
        """从 MySQL 的院校名 / 专业名列生成实体词典（权威数据源，词典路优先的依据）。

        只做 SELECT DISTINCT，不写入；表不存在时该路返回空 dict，不影响 LLM 路。
        """
        from app.database import fetch_all_params, table_exists
        from app.models.dataset import table_name

        result: Dict[str, List[str]] = {"院校": [], "专业": [], "省份": []}
        table = table_name("major_admission", year, province)
        try:
            if not table_exists(table):
                logger.info("[GRAPH] 词典构建跳过：表 %s 不存在", table)
                return result
            rows = fetch_all_params(
                f"SELECT DISTINCT university_name AS school, major_name AS major, "
                f"school_province AS province FROM `{table}`"
            )
        except Exception as exc:  # noqa: BLE001 数据库不可用时词典路为空，靠 LLM 路兜底
            logger.info("[GRAPH] 词典构建失败：%s", exc.__class__.__name__)
            return result

        schools, majors, provinces = set(), set(), set()
        for r in rows:
            school = (r.get("school") or "").strip()
            major = (r.get("major") or "").strip()
            prov = (r.get("province") or "").strip()
            if school:
                schools.add(school)
            if major:
                majors.add(major)
            if prov:
                provinces.add(prov)

        result["院校"] = sorted(schools)
        result["专业"] = sorted(majors)
        result["省份"] = sorted(provinces)
        logger.info("[GRAPH] 实体词典：院校 %d / 专业 %d / 省份 %d",
                    len(result["院校"]), len(result["专业"]), len(result["省份"]))
        self.entity_dict = result
        return result
