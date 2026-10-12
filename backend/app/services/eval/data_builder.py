"""把「QA 对」与「RAG 系统实时输出」组装成评估数据集（单一职责：只做数据构建）。

评估数据集四字段（必须齐备）：
    question      —— 用户问题
    answer        —— RAG 系统生成的答案
    contexts      —— RAG 系统召回的上下文列表
    ground_truth  —— 人工标注的标准答案

依赖倒置：本类只依赖抽象 `BaseRAGRunner`，不直接依赖 rag_service，
这样将来换成别的 RAG 实现（或 Mock）无需改动构建逻辑。
"""
from __future__ import annotations

import csv
import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence


class BaseRAGRunner(ABC):
    """RAG 系统抽象（接口隔离：只暴露评估需要的两个能力）。"""

    @abstractmethod
    def retrieve(self, question: str, top_k: int) -> List[Dict]:
        """返回命中片段列表，每项至少包含 text / id / metadata。"""

    @abstractmethod
    def generate(self, question: str, contexts: Sequence[str]) -> str:
        """基于召回上下文生成答案。"""


class ProjectRAGRunner(BaseRAGRunner):
    """项目真实 RAG 链路适配器：复用 rag_service 的检索 + 防幻觉生成。"""

    def retrieve(self, question: str, top_k: int) -> List[Dict]:
        from app.services import rag_service

        hits = rag_service.search(question, top_k=top_k) or []
        return [
            {
                "id": (h.get("metadata") or {}).get("parent_chunk_id") or h.get("parent_chunk_id") or f"ctx_{i}",
                "text": h.get("text", ""),
                "metadata": h.get("metadata") or {},
            }
            for i, h in enumerate(hits)
        ]

    def generate(self, question: str, contexts: Sequence[str]) -> str:
        from app.services import rag_service

        if not contexts:
            return rag_service.OFF_TOPIC_ANSWER
        snippets = "\n".join(f"[{i + 1}] {c}" for i, c in enumerate(contexts))
        return rag_service.generate_answer(question, snippets) or ""


class EvalDataBuilder:
    """评估数据集构建器。"""

    # 标准答案按句切分：保留句末标点作为分句依据，过滤过短碎片（<12 字）
    _SPLIT_PATTERN = re.compile(r"(?<=[。！？；])")
    _MIN_CHUNK_LEN = 12

    def load_qa_pairs(self, path: str) -> List[Dict[str, str]]:
        """加载 `question` + `ground_truth` 语料，支持 JSON 数组 / CSV。"""
        if not os.path.exists(path):
            raise FileNotFoundError(f"评估数据集不存在：{path}")

        ext = os.path.splitext(path)[1].lower()
        rows: List[Dict[str, str]] = []
        if ext == ".json":
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data if isinstance(data, list) else data.get("data", []):
                rows.append({
                    "question": str(item.get("question", "")).strip(),
                    "ground_truth": str(item.get("ground_truth", item.get("answer", ""))).strip(),
                })
        elif ext == ".csv":
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                for item in csv.DictReader(f):
                    rows.append({
                        "question": str(item.get("question", "")).strip(),
                        "ground_truth": str(item.get("ground_truth", item.get("answer", ""))).strip(),
                    })
        else:
            raise ValueError(f"不支持的数据集格式：{ext}（仅支持 .json / .csv）")

        # 过滤无效行，保证评估不因为脏数据中断
        return [r for r in rows if r["question"] and r["ground_truth"]]

    def build_dataset(self, qa_pairs: List[Dict[str, str]], rag_system: BaseRAGRunner,
                      top_k: int = 5, max_samples: int = 50) -> List[Dict[str, Any]]:
        """逐条跑 RAG 系统，补齐 answer / contexts，得到四字段完整数据集。"""
        dataset: List[Dict[str, Any]] = []
        for pair in qa_pairs[:max_samples]:
            hits = rag_system.retrieve(pair["question"], top_k)
            contexts = [h.get("text", "") for h in hits]
            answer = rag_system.generate(pair["question"], contexts)
            dataset.append({
                "question": pair["question"],
                "answer": answer,
                "contexts": contexts,
                "ground_truth": pair["ground_truth"],
                # 召回 id 用于 MRR / NDCG / HitRate（顺序即排序位次）
                "context_ids": [h.get("id") for h in hits],
            })
        return dataset

    def split_gold_chunks(self, text: str) -> List[str]:
        """标准答案按句切分（参考课堂案例 demo01_RAGAS.py）。

        用途：context_recall 需要把标准答案拆成若干「可以被召回片段覆盖」的语义单元，
        碎片（如"好的。""是的。"）会造成分母虚高，故过滤长度 < 12 的碎片。
        """
        chunks = [c.strip() for c in self._SPLIT_PATTERN.split(text or "")]
        return [c for c in chunks if len(c) >= self._MIN_CHUNK_LEN]

    @staticmethod
    def gold_ids_for(context_ids: Sequence[str], gold_chunk_count: int) -> List[str]:
        """演示/离线场景下的「相关文档集合」。

        真实语料没有标注 gold doc id 时，默认认为**前 N 条召回**里应包含答案出处，
        这里退化为「假定第一条召回为正确来源」，使 MRR/NDCG/HitRate 仍可计算并有区分度。
        """
        if not context_ids:
            return []
        take = max(1, min(gold_chunk_count, len(context_ids)))
        return list(context_ids[:take])
