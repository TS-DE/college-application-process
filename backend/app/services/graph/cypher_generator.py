"""Cypher 生成器：实体列表 + 用户问题 → Cypher 语句（0.9.0）。

## 单一职责
本类只负责「把自然语言问题翻成 Cypher」，不连数据库、不执行、不识别实体。

## 设计要点
- Schema 由 `GraphStore.get_schema()` 动态注入，图谱结构变化时无需改 Prompt 模板；
- 内嵌 4 条高考领域 Few-shot 样例（学费 / 最低分位次 / 所在地 / 招生人数），
  让小模型也能稳定产出可执行语句（课堂案例 CYPHER_GENERATION_TEMPLATE 的高考版）；
- 生成的语句一律过 `_clean()` 去掉 ```cypher ``` 包裹，并用参数化占位符 `$name`
  传实体名，避免实体名里的单引号破坏语句。

## 降级契约
LLM 调用失败 / 输出不含 MATCH → 返回空串，由上层返回空结果，不抛异常。
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from app.services.graph import ontology as onto
from app.services.graph.entity_extractor import default_llm_chat

logger = logging.getLogger(__name__)

CYPHER_GENERATION_TEMPLATE = """你是一个高考志愿填报知识图谱的 Cypher 查询生成专家。
请根据【图谱 Schema】和用户问题，生成**一条**合法的 Neo4j Cypher 只读查询语句。

【图谱 Schema】
{schema}

【本体说明】
- 节点标签：`院校` / `专业` / `专业组` / `省份` / `批次` / `选科要求` / `分数段` / `年份`
- 关系：
  (院校)-[:OPENS]->(专业)     院校开设专业，边上带 year / province / batch / category / min_score / min_rank
  (院校)-[:TUITION]->(专业)   学费，边上带 year / province / tuition / duration
  (院校)-[:ENROLLS]->(专业)   招生计划，边上带 year / province / batch / plan_count
  (院校)-[:RANKS]->(分数段)   院校投档线
  (专业)-[:ADMITS]->(分数段)  专业投档线
  (院校)-[:LOCATED_IN]->(省份)
  (专业)-[:BELONGS_TO]->(专业组)
  (专业组)-[:REQUIRES]->(选科要求)

【已识别的实体】（查询条件请优先使用这些实体，不要自己编造）
{entities}

【生成规则】
1. 只输出 Cypher 语句本身，不要输出解释、不要输出 Markdown 代码块标记；
2. 中文标签与关系名一律用反引号包裹，例如 `MATCH (s:`院校` {{name: $院校_0}})`；
3. 节点属性过滤用 {{name: $参数名}} 形式占位，参数名从上面的实体里取，禁止把实体名硬编码进语句；
4. 数值属性（year / min_score / tuition / plan_count）可以直接写常量；
5. 只做查询（MATCH ... RETURN），禁止使用 CREATE / MERGE / DELETE / SET / DROP；
6. RETURN 的别名用中文，方便直接展示；
7. 必须加 LIMIT（默认 20），避免一次拉回全表。

【参考样例】
用户问「福州大学至诚学院计算机专业学费多少」：
MATCH (s:`院校` {{name: $院校_0}})-[r:TUITION]->(m:`专业` {{name: $专业_0}})
WHERE r.year = 2025
RETURN s.name AS 院校, m.name AS 专业, r.tuition AS 学费, r.duration AS 学制

用户问「郑州大学计算机专业2025年河南最低分」：
MATCH (s:`院校` {{name: $院校_0}})-[r:OPENS]->(m:`专业` {{name: $专业_0}})
WHERE r.year = 2025 AND r.province = '河南'
RETURN s.name AS 院校, m.name AS 专业, r.min_score AS 最低分, r.min_rank AS 最低位次

用户问「福州大学至诚学院在哪里」：
MATCH (s:`院校` {{name: $院校_0}})-[:LOCATED_IN]->(p:`省份`)
RETURN s.name AS 院校, p.name AS 所在省份

用户问「福州大学至诚学院计算机专业招多少人」：
MATCH (s:`院校` {{name: $院校_0}})-[r:ENROLLS]->(m:`专业` {{name: $专业_0}})
WHERE r.year = 2025
RETURN s.name AS 院校, m.name AS 专业, r.plan_count AS 招生人数

【用户问题】
{question}

【Cypher输出】"""


class CypherGenerator:
    """把「实体列表 + 用户问题」编译成 Cypher。"""

    def __init__(self, llm_chat=None) -> None:
        """
        :param llm_chat: 可调用对象 (prompt, temperature, max_tokens) -> str。
                          依赖倒置：测试时传桩函数即可，不依赖真实 LLM。
                          为 None 时用 `default_llm_chat`（阿里云 OpenAI 兼容通道）。
        """
        self._llm_chat = llm_chat or default_llm_chat

    def generate(self, question: str, entities: List[Dict[str, str]], schema: str) -> str:
        """生成 Cypher；失败返回空串（上层据此返回空图谱结果）。"""
        if not entities:
            return ""

        entity_lines = "\n".join(
            f"  - {e.get('type')}：{e.get('name')}" for e in entities
        )
        prompt = CYPHER_GENERATION_TEMPLATE.format(
            schema=schema,
            entities=entity_lines,
            question=question,
        )
        try:
            raw = self._llm_chat(prompt, temperature=0.0, max_tokens=400)
        except Exception as exc:  # noqa: BLE001
            logger.info("[GRAPH] Cypher 生成失败：%s", exc.__class__.__name__)
            return ""

        cypher = self._clean(raw)
        if not cypher:
            return ""
        # 只读保护：生成的语句必须是 MATCH 开头且不含写操作关键字
        upper = cypher.upper()
        if not upper.startswith("MATCH") or any(
            kw in upper for kw in ("CREATE", "MERGE", "DELETE", "SET ", "DROP", "REMOVE")
        ):
            logger.info("[GRAPH] Cypher 校验不通过，丢弃：%s", cypher[:120])
            return ""
        return cypher

    @staticmethod
    def _clean(cypher: str) -> str:
        """去掉 ```cypher ``` 包裹、首尾空白与多余反引号。"""
        if not cypher:
            return ""
        text = cypher.strip()
        text = re.sub(r"^```(?:cypher)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip().strip("`").strip()
        # 只保留第一条语句（模型偶尔会输出多条）
        text = text.split(";")[0].strip()
        return text

    # ---------------- 参数绑定（实体 → $参数） ----------------

    @staticmethod
    def build_params(entities: List[Dict[str, str]]) -> Dict[str, str]:
        """把实体列表转成 Cypher 参数表：{"院校_0": "福州大学至诚学院", ...}。

        与 Prompt 中约定的 `$类型_序号` 占位符一一对应；即使模型没用占位符，
        调用方也可以用它做二次校验，避免实体名注入。
        """
        params: Dict[str, str] = {}
        counters: Dict[str, int] = {}
        for e in entities:
            etype = str(e.get("type") or "").strip()
            name = str(e.get("name") or "").strip()
            if not etype or not name:
                continue
            idx = counters.get(etype, 0)
            counters[etype] = idx + 1
            params[f"{etype}_{idx}"] = name
        return params

    @staticmethod
    def quote(value: str) -> str:
        """导出给外部的字面量转义工具（复用本体模块，避免重复实现）。"""
        return onto.q(value)
