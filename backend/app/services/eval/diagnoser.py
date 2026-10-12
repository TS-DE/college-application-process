"""自动诊断（对应《企业级 RAG 落地优化与量化评估实战》第四章诊断决策树）。

职责单一：只做「指标 → 问题 → 优化建议 → 可执行参数变更」的映射，
不做任何参数写回（写回交给 AutoTuner，符合单一职责与迪米特法则）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class DiagnosisItem:
    """一条诊断结论。

    suggestion_id ：前端「一键应用」按钮用的标识（用指标名，稳定可读）
    param_changes ：该建议对应的**白名单内**参数变更草案（键=参数名，值=建议值）
    """

    suggestion_id: str
    metric: str
    score: float
    threshold: float
    level: str
    problem: str
    suggestions: List[str] = field(default_factory=list)
    param_changes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "metric": self.metric,
            "score": self.score,
            "threshold": self.threshold,
            "level": self.level,
            "problem": self.problem,
            "suggestions": self.suggestions,
            "param_changes": self.param_changes,
        }


class RAGDiagnoser:
    """指标驱动的诊断器（规则表可增不改，符合开闭原则）。"""

    # 决策树规则表：(指标, 阈值, 级别, 问题描述, 优化建议, 参数变更草案)
    # 参数变更草案里的函数会在运行时结合当前配置算出目标值
    RULES = [
        {
            "metric": "context_precision",
            "threshold": 0.6,
            "level": "high",
            "problem": "召回噪声过多：检索结果里大量片段与标准答案无关",
            "suggestions": ["优化切片策略（减小 CHUNK_SIZE）", "调高重排序权重（开启 RERANK）", "精简 top_k 减少噪声"],
            "params": {"CHUNK_SIZE": "decrease", "RERANK_ENABLED": 1, "MULTI_RECALL_TOPK_PER_CHANNEL": "decrease"},
        },
        {
            "metric": "context_recall",
            "threshold": 0.7,
            "level": "high",
            "problem": "漏召回：标准答案的关键信息没有被检索到",
            "suggestions": ["启用混合检索（多通道召回）", "开启查询扩展", "增加召回数量"],
            "params": {"MULTI_QUERY_ENABLED": 1, "QUERY_EXPANSION_ENABLED": 1, "MULTI_RECALL_TOPK_PER_CHANNEL": "increase"},
        },
        {
            "metric": "mrr",
            "threshold": 0.5,
            "level": "medium",
            "problem": "排序质量差：相关内容没有排在前几位",
            "suggestions": ["接入 cross-encoder 重排序模型", "开启 Rerank 精排"],
            "params": {"RERANK_ENABLED": 1, "RERANK_MODEL": "BAAI/bge-reranker-base"},
        },
        {
            "metric": "faithfulness",
            "threshold": 0.7,
            "level": "high",
            "problem": "存在幻觉：答案内容与召回上下文不一致",
            "suggestions": ["优化提示词（切 strict 版本）", "降低 temperature", "添加答案校验（Self-RAG）"],
            "params": {"ADVANCED_RAG_ENABLED": 1, "PROMPT_VERSION": "strict"},
        },
        {
            "metric": "answer_relevance",
            "threshold": 0.7,
            "level": "medium",
            "problem": "答非所问：答案没有紧扣用户问题",
            "suggestions": ["优化 prompt 指令边界", "开启查询重写", "补充 Few-shot 示例"],
            "params": {"QUERY_REWRITE_ENABLED": 1, "QUERY_DECOMPOSE_ENABLED": 1},
        },
        {
            "metric": "answer_correctness",
            "threshold": 0.6,
            "level": "high",
            "problem": "事实准确性不足：与标准答案偏差较大",
            "suggestions": ["全链路复盘迭代（切片 → 召回 → 精排 → 生成）"],
            "params": {"ADVANCED_RAG_ENABLED": 1, "QUERY_REWRITE_ENABLED": 1},
        },
        {
            "metric": "semantic_similarity",
            "threshold": 0.7,
            "level": "medium",
            "problem": "语义匹配不足：答案整体语义偏离标准答案",
            "suggestions": ["启用混合检索 + 查询改写", "增大 CHUNK_OVERLAP 提升上下文完整度"],
            "params": {"MULTI_QUERY_ENABLED": 1, "QUERY_REWRITE_ENABLED": 1, "CHUNK_OVERLAP": "increase"},
        },
    ]

    def diagnose(self, report: Any) -> List[DiagnosisItem]:
        """输入评估报告（含 aggregate），输出诊断列表（按严重程度排序）。"""
        aggregate: Dict[str, float] = getattr(report, "aggregate", {}) or {}
        items: List[DiagnosisItem] = []
        order = {"high": 0, "medium": 1, "low": 2}

        for rule in self.RULES:
            score = aggregate.get(rule["metric"])
            # 指标缺失（如 LLM 指标未开启）时不诊断，避免给出误导性建议
            if score is None:
                continue
            if score >= rule["threshold"]:
                continue
            if score < rule["threshold"] * 0.6:
                level = "high"
            else:
                level = rule["level"]
            items.append(DiagnosisItem(
                suggestion_id=rule["metric"],
                metric=rule["metric"],
                score=round(float(score), 4),
                threshold=rule["threshold"],
                level=level,
                problem=rule["problem"],
                suggestions=list(rule["suggestions"]),
                param_changes=dict(rule["params"]),
            ))

        items.sort(key=lambda x: order.get(x.level, 3))
        return items

    @staticmethod
    def summarize(items: List[DiagnosisItem]) -> str:
        """给报告用的一句话总结。"""
        if not items:
            return "各项指标均达到阈值，RAG 链路处于健康状态。"
        high = [i.metric for i in items if i.level == "high"]
        return f"发现 {len(items)} 项待优化指标" + (f"，其中高风险 {len(high)} 项：{', '.join(high)}。" if high else "。")
