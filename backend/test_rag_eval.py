"""0.8.0 最小用例：跑一次 RAG 量化评估 → 输出 aggregate + grade + diagnoses + 参数变更计划。

两种运行模式：

    cd backend
    python test_rag_eval.py              # 桩版：不联网，验证评估链路本身（秒级）
    python test_rag_eval.py --real       # 真实版：走项目真实 RAG 链路（会调 Ali / Ollama）

之所以能做「桩版」，是因为 RAGEvaluator / EvalDataBuilder 只依赖 `BaseRAGRunner` 抽象，
不依赖具体检索实现（依赖倒置带来的可测性）。
"""
import argparse
import json
import os
import sys
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.eval.auto_tuner import PARAM_SPECS, AutoTuner
from app.services.eval.data_builder import BaseRAGRunner, EvalDataBuilder, ProjectRAGRunner
from app.services.eval.diagnoser import RAGDiagnoser
from app.services.eval.eval_config import RAGEvalConfig
from app.services.eval.evaluator import RAGEvaluator
from app.services.eval.report_generator import ReportGenerator

DATASET = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "eval", "gaokao_qa.json"
)

# 桩召回语料：故意留一部分噪声，让 context_precision 偏低、从而触发诊断规则
STUB_CORPUS = [
    "一分一段表把每个分数段的考生人数和累计人数列出来，考生可以据此换算出自己在全省的位次。",
    "位次是考生高考成绩在全省同科类考生中的排名位置，因此填报志愿主要看位次而不是分数。",
    "本校图书馆开放时间为周一至周日 8:00-22:00，节假日另行通知。",  # 噪声：与问题无关
]


class StubRAGRunner(BaseRAGRunner):
    """桩 RAG 系统：用于**离线**验证评估链路（实现 BaseRAGRunner 即插即用）。"""

    def retrieve(self, question: str, top_k: int) -> List[Dict]:
        # 简单加权：问题里出现关键词的片段排前面，噪声片段垫底
        scored = sorted(STUB_CORPUS, key=lambda t: -sum(w in t for w in question))
        return [{"id": f"ctx_{i}", "text": t, "metadata": {}} for i, t in enumerate(scored[:top_k])]

    def generate(self, question: str, contexts) -> str:
        return " ".join(contexts)[:200]


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 量化评估最小用例")
    parser.add_argument("--real", action="store_true", help="走真实 RAG 链路（会调用 Ali / Ollama）")
    parser.add_argument("--samples", type=int, default=4, help="评估样本数")
    parser.add_argument("--dataset", default=DATASET, help="评估数据集路径")
    args = parser.parse_args()

    print("=" * 78)
    print("【1】加载评估数据集")
    print("=" * 78)
    builder = EvalDataBuilder()
    qa_pairs = builder.load_qa_pairs(args.dataset)[: args.samples]
    print(f"  数据集：{os.path.basename(args.dataset)}")
    print(f"  样本数：{len(qa_pairs)}（question + ground_truth）")

    print()
    print("=" * 78)
    print(f"【2】运行 RAG 系统（{'真实链路 ProjectRAGRunner' if args.real else '桩 StubRAGRunner'}）")
    print("=" * 78)
    config = RAGEvalConfig({"TOP_K_FOR_EVAL": 3, "LLM_METRICS_ENABLED": False})
    runner = ProjectRAGRunner() if args.real else StubRAGRunner()
    dataset = builder.build_dataset(qa_pairs, runner, top_k=config.TOP_K_FOR_EVAL)
    sample = dataset[0]
    print("  四字段校验：", {
        "question": bool(sample["question"]),
        "answer": bool(sample["answer"]),
        "contexts": len(sample["contexts"]),
        "ground_truth": bool(sample["ground_truth"]),
    })

    print()
    print("=" * 78)
    print("【3】计算指标（本地指标，不调用 LLM 打分）")
    print("=" * 78)
    report = RAGEvaluator(config, builder).run(dataset, config)
    for key, value in report.aggregate.items():
        print(f"  {key:<22} = {value}")
    print(f"  综合评级：{report.grade}（{report.dataset_size} 条样本，耗时 {report.duration_sec:.2f}s）")

    print()
    print("=" * 78)
    print("【4】自动诊断")
    print("=" * 78)
    diagnoses = RAGDiagnoser().diagnose(report)
    print(f"  {RAGDiagnoser.summarize(diagnoses)}")
    for item in diagnoses:
        print(f"  - [{item.level}] {item.metric}={item.score} < {item.threshold}")
        print(f"     问题：{item.problem}")
        print(f"     建议：{'；'.join(item.suggestions)}")
        print(f"     参数草案：{json.dumps(item.param_changes, ensure_ascii=False)}")

    print()
    print("=" * 78)
    print("【5】参数自调优计划（dry_run，不写文件）")
    print("=" * 78)
    tuner = AutoTuner()
    changes = tuner.plan(diagnoses, report_id="min-case")
    if not changes:
        print("  无需变更的参数")
    for change in changes:
        allowed = "yes" if change.name in PARAM_SPECS and change.name in tuner.whitelist else "no"
        print(f"  - {change.name}: {change.old_value} -> {change.new_value} (whitelist={allowed})")
    result = tuner.apply(changes, dry_run=True)
    print(f"  dry_run 结果：applied={result.applied} need_restart={result.need_restart} msg={result.message}")

    print()
    print("=" * 78)
    print("【6】报告渲染")
    print("=" * 78)
    generator = ReportGenerator()
    report.report_id = generator.new_report_id()
    from datetime import datetime

    report.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    chart = generator.to_chart_data(report)
    print(f"  柱状图类目：{chart['bar']['categories']}")
    print(f"  雷达图指标数：{len(chart['radar']['indicators'])}")
    print(f"  Markdown 报告行数：{len(generator.to_markdown(report, diagnoses).splitlines())}")
    print()
    print("最小用例结束。")


if __name__ == "__main__":
    main()
