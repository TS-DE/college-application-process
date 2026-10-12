"""评估编排器：串起「样本 → 指标 → 聚合 → 评级」。

合成复用：RAGEvaluator **组合** LocalMetrics（本地必算）+ LLMMetrics（可选），
自身不实现任何指标算法，符合单一职责与合成复用原则。
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.eval.data_builder import EvalDataBuilder
from app.services.eval.eval_config import RAGEvalConfig
from app.services.eval.metrics_llm import LLMMetrics
from app.services.eval.metrics_local import LocalMetrics


@dataclass
class EvalReport:
    """一次完整评估的产物。"""

    report_id: str = ""
    created_at: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    aggregate: Dict[str, float] = field(default_factory=dict)
    grade: str = ""
    dataset_size: int = 0
    duration_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "created_at": self.created_at,
            "config": self.config,
            "rows": self.rows,
            "aggregate": self.aggregate,
            "grade": self.grade,
            "dataset_size": self.dataset_size,
            "duration_sec": round(self.duration_sec, 2),
        }


class RAGEvaluator:
    """三维十二项指标的落地编排（本地指标必算，LLM 指标可选）。"""

    def __init__(self, config: RAGEvalConfig, builder: Optional[EvalDataBuilder] = None) -> None:
        self.config = config
        self.builder = builder or EvalDataBuilder()
        self.local = LocalMetrics(threshold=config.SIM_THRESHOLD)
        # 依赖倒置：通过开关决定是否启用 LLM 打分，默认关闭，失败不影响本地指标
        self.llm = LLMMetrics(enabled=config.LLM_METRICS_ENABLED, model=config.LLM_MODEL)

    def run(self, dataset: List[Dict[str, Any]], config: Optional[RAGEvalConfig] = None) -> EvalReport:
        config = config or self.config
        started = time.time()
        rows: List[Dict[str, Any]] = []

        for sample in dataset:
            rows.append(self._evaluate_sample(sample, config))

        aggregate = self._aggregate(rows)
        report = EvalReport(
            config=config.to_dict(),
            rows=rows,
            aggregate=aggregate,
            grade=self._grade(aggregate),
            dataset_size=len(rows),
            duration_sec=time.time() - started,
        )
        return report

    # ---------------- 单样本计算 ----------------

    def _evaluate_sample(self, sample: Dict[str, Any], config: RAGEvalConfig) -> Dict[str, Any]:
        question = sample.get("question", "")
        answer = sample.get("answer", "")
        contexts = sample.get("contexts") or []
        ground_truth = sample.get("ground_truth", "")
        context_ids = sample.get("context_ids") or []
        # 无 gold doc 标注时，用前 N 条召回充当相关集合，保证排序指标可计算
        gold_ids = sample.get("gold_ids") or EvalDataBuilder.gold_ids_for(
            context_ids, max(1, len(self.builder.split_gold_chunks(ground_truth)))
        )

        row: Dict[str, Any] = {
            "question": question,
            "answer": answer,
            "ground_truth": ground_truth,
            "context_precision": self.local.calc_context_precision(contexts, ground_truth, config.SIM_THRESHOLD),
            "context_recall": self.local.calc_context_recall(contexts, ground_truth, config.SIM_THRESHOLD),
            "mrr": self.local.calc_mrr(context_ids, gold_ids),
            "ndcg": self.local.calc_ndcg(context_ids, gold_ids, k=config.TOP_K_FOR_EVAL),
            "hit_rate": self.local.calc_hit_rate(context_ids, gold_ids),
            "semantic_similarity": self.local.semantic_similarity(answer, ground_truth),
        }

        # LLM 打分指标（默认关闭；任一返回 None 表示跳过，不参与均值）
        faith = self.llm.calc_faithfulness(answer, contexts)
        rel = self.llm.calc_answer_relevance(question, answer)
        corr = self.llm.calc_answer_correctness(answer, ground_truth)
        if faith is not None:
            row["faithfulness"] = round(faith, 4)
        if rel is not None:
            row["answer_relevance"] = round(rel, 4)
        if corr is not None:
            row["answer_correctness"] = round(corr, 4)
        return row

    # ---------------- 聚合与评级 ----------------

    def _aggregate(self, rows: List[Dict[str, Any]]) -> Dict[str, float]:
        """按指标求均值（skipna：某行的 LLM 指标缺失时不参与该指标均值）。"""
        numeric_keys = [
            "context_precision", "context_recall", "mrr", "ndcg", "hit_rate",
            "semantic_similarity", "faithfulness", "answer_relevance", "answer_correctness",
        ]
        aggregate: Dict[str, float] = {}
        for key in numeric_keys:
            values = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
            if not values:
                continue
            aggregate[key] = round(statistics.fmean(values), 4)

        # 综合得分 = 各维度均值（三大维度：检索质量 / 排序质量 / 生成质量）
        if aggregate:
            aggregate["overall"] = round(statistics.fmean(list(aggregate.values())), 4)
        return aggregate

    def _grade(self, aggregate: Dict[str, float]) -> str:
        """综合评级：≥0.85 优秀 / ≥0.75 良好 / ≥0.65 合格 / <0.65 需优化。"""
        score = aggregate.get("overall", 0.0)
        if score >= 0.85:
            return "优秀"
        if score >= 0.75:
            return "良好"
        if score >= 0.65:
            return "合格"
        return "需优化"
