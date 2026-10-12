"""评估报告持久化（单一职责：只负责报告的读写与列举，供趋势图使用）。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from app.services.eval.evaluator import EvalReport


class EvalReportStore:
    """以 `data/eval_reports/*.json` 为存储，按文件名（时间戳）倒序列举。"""

    def __init__(self, output_dir: str) -> None:
        self.output_dir = output_dir

    def latest_summary(self, limit: int = 20) -> List[Dict[str, Any]]:
        """返回历史报告摘要列表（倒序），用于趋势图与报告列表。"""
        if not os.path.isdir(self.output_dir):
            return []
        files = sorted(
            [f for f in os.listdir(self.output_dir) if f.endswith(".json")],
            reverse=True,
        )
        summaries: List[Dict[str, Any]] = []
        for name in files[:limit]:
            path = os.path.join(self.output_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:  # noqa: BLE001 单个文件损坏不影响列表
                continue
            summaries.append({
                "report_id": data.get("report_id", os.path.splitext(name)[0]),
                "created_at": data.get("created_at", ""),
                "grade": data.get("grade", ""),
                "dataset_size": data.get("dataset_size", 0),
                "aggregate": data.get("aggregate", {}),
            })
        return summaries

    def load(self, report_id: str) -> Dict[str, Any]:
        """读取完整报告（含 rows / diagnoses）。"""
        # 防目录穿越：report_id 只允许文件名字符
        safe = os.path.basename(report_id)
        path = os.path.join(self.output_dir, f"{safe}.json")
        if not os.path.exists(path):
            raise FileNotFoundError(f"报告不存在：{safe}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_report_object(self, report_id: str) -> EvalReport:
        """把持久化 JSON 还原为 EvalReport 对象（供 ReportGenerator.to_chart_data 对比基线用）。"""
        data = self.load(report_id)
        report = EvalReport(
            report_id=data.get("report_id", report_id),
            created_at=data.get("created_at", ""),
            config=data.get("config", {}),
            rows=data.get("rows", []),
            aggregate=data.get("aggregate", {}),
            grade=data.get("grade", ""),
            dataset_size=data.get("dataset_size", 0),
            duration_sec=data.get("duration_sec", 0.0),
        )
        return report
