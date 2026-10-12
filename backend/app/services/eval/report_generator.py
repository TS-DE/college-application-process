"""报告渲染：把评估产物变成 Markdown / JSON / 前端 ECharts 数据（单一职责：只做渲染）。"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Sequence

from app.services.eval.evaluator import EvalReport

# 三维十二项指标分组（前端雷达图按维度着色）
DIMENSIONS: Dict[str, List[str]] = {
    "检索质量": ["context_precision", "context_recall", "semantic_similarity"],
    "排序质量": ["mrr", "ndcg", "hit_rate"],
    "生成质量": ["faithfulness", "answer_relevance", "answer_correctness"],
}

METRIC_LABELS: Dict[str, str] = {
    "context_precision": "上下文精确率",
    "context_recall": "上下文召回率",
    "mrr": "MRR 首命中倒数",
    "ndcg": "NDCG 排序增益",
    "hit_rate": "Top-K 命中率",
    "semantic_similarity": "答案语义相似度",
    "faithfulness": "忠实度",
    "answer_relevance": "答案相关性",
    "answer_correctness": "答案正确性",
}


class ReportGenerator:
    """渲染 Markdown 报告 + ECharts 图表数据 + 落盘。"""

    # ---------------- Markdown ----------------

    def to_markdown(self, report: EvalReport, diagnoses: Sequence[Any] = ()) -> str:
        lines: List[str] = [
            "# RAG 量化评估报告",
            "",
            f"- 报告 ID：{report.report_id}",
            f"- 生成时间：{report.created_at}",
            f"- 样本数量：{report.dataset_size}",
            f"- 综合评级：**{report.grade}**（综合得分 {report.aggregate.get('overall', 0)}）",
            f"- 耗时：{report.duration_sec:.2f}s",
            "",
            "## 一、指标总览",
            "",
            "| 维度 | 指标 | 得分 |",
            "|---|---|---|",
        ]
        indicators = set(sum(DIMENSIONS.values(), []))
        for dim, metrics in DIMENSIONS.items():
            for metric in metrics:
                if metric not in report.aggregate:
                    continue
                lines.append(f"| {dim} | {METRIC_LABELS.get(metric, metric)} | {report.aggregate[metric]} |")
        for metric, score in report.aggregate.items():
            if metric not in indicators and metric != "overall":
                lines.append(f"| 其他 | {METRIC_LABELS.get(metric, metric)} | {score} |")

        lines += ["", "## 二、自动诊断", ""]
        if not diagnoses:
            lines.append("各项指标均达到阈值，RAG 链路处于健康状态。")
        else:
            for item in diagnoses:
                lines.append(f"### [{item.level}] {METRIC_LABELS.get(item.metric, item.metric)}（{item.score} < {item.threshold}）")
                lines.append(f"- 问题：{item.problem}")
                for sug in item.suggestions:
                    lines.append(f"- 建议：{sug}")
                if item.param_changes:
                    lines.append(f"- 可自动应用的参数：{json.dumps(item.param_changes, ensure_ascii=False)}")
                lines.append("")
        return "\n".join(lines)

    # ---------------- ECharts ----------------

    def to_chart_data(self, report: EvalReport, baseline: EvalReport | None = None,
                      history: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
        """返回前端三种图所需数据：柱状图 / 雷达图 / 趋势图。"""
        core = [
            "context_precision", "context_recall", "mrr", "ndcg",
            "hit_rate", "semantic_similarity", "faithfulness",
            "answer_relevance", "answer_correctness",
        ]
        metrics = [m for m in core if m in report.aggregate]

        # 柱状图：当前报告 vs 上一次报告（优化前后对比）
        bar = {
            "categories": [METRIC_LABELS.get(m, m) for m in metrics],
            "current": [report.aggregate.get(m, 0) for m in metrics],
            "baseline": [ (baseline.aggregate.get(m, 0) if baseline else 0) for m in metrics ],
        }

        # 雷达图：三维十二项全景（缺失指标记 0）
        radar_metrics = [m for m in sum(DIMENSIONS.values(), []) if report.aggregate.get(m) is not None]
        radar = {
            "indicators": [{"name": METRIC_LABELS.get(m, m), "max": 1} for m in radar_metrics],
            "values": [report.aggregate.get(m, 0) for m in radar_metrics],
        }

        # 趋势图：历史报告综合得分 / 关键指标
        trend = {
            "dates": [h.get("created_at", "")[:10] for h in history],
            "overall": [h.get("aggregate", {}).get("overall", 0) for h in history],
            "precision": [h.get("aggregate", {}).get("context_precision", 0) for h in history],
            "recall": [h.get("aggregate", {}).get("context_recall", 0) for h in history],
        }
        return {"bar": bar, "radar": radar, "trend": trend}

    # ---------------- 落盘 ----------------

    def save(self, report: EvalReport, output_dir: str, diagnoses: Sequence[Any] = ()) -> Dict[str, str]:
        """把报告落盘为 JSON + Markdown，返回文件路径。"""
        os.makedirs(output_dir, exist_ok=True)
        base = os.path.join(output_dir, report.report_id)
        json_path = f"{base}.json"
        md_path = f"{base}.md"

        payload = report.to_dict()
        payload["diagnoses"] = [d.to_dict() if hasattr(d, "to_dict") else d for d in diagnoses]
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self.to_markdown(report, diagnoses))
        return {"json": json_path, "md": md_path}

    @staticmethod
    def new_report_id() -> str:
        """报告 ID：时间戳，天然支持按字典序排序拿趋势。"""
        return datetime.now().strftime("%Y%m%d_%H%M%S")
