"""RAG 量化评估模块（0.8.0）。

模块内类一览（每个类单一职责，可独立测试 / 替换）：

| 文件 | 类 | 职责 |
|---|---|---|
| eval_config.py      | RAGEvalConfig     | 评估配置（默认值来自 settings，支持前端覆盖） |
| data_builder.py     | BaseRAGRunner     | RAG 系统抽象（依赖倒置，评估不依赖具体实现） |
| data_builder.py     | ProjectRAGRunner  | 项目真实 RAG 链路适配器 |
| data_builder.py     | EvalDataBuilder   | 构建 question/answer/contexts/ground_truth 四字段数据集 |
| metrics_local.py    | LocalMetrics      | 本地指标（相似度 / 上下文精确率召回率 / MRR / NDCG / HitRate） |
| metrics_llm.py      | LLMMetrics        | LLM 打分指标（默认关闭，规避 API 报错） |
| evaluator.py        | EvalReport        | 评估报告数据结构 |
| evaluator.py        | RAGEvaluator      | 评估流程编排 + 聚合 + 评级 |
| diagnoser.py        | DiagnosisItem     | 单条诊断结论（含可自动应用的参数变更） |
| diagnoser.py        | RAGDiagnoser      | 指标 → 问题 → 建议（决策树规则表） |
| report_generator.py | ReportGenerator   | Markdown / ECharts 数据 / 落盘 |
| report_store.py     | EvalReportStore   | 报告读写与列举（趋势图数据源） |
| auto_tuner.py       | AutoTuner         | 白名单参数自动调优 + 备份 + 回滚 |

调用链：
    routers/eval.py → EvalDataBuilder.load_qa_pairs()
                    → ProjectRAGRunner（检索 + 生成）
                    → RAGEvaluator.run()（组合 LocalMetrics + LLMMetrics）
                    → RAGDiagnoser.diagnose()
                    → ReportGenerator.save() / EvalReportStore
                    → AutoTuner.plan()/apply()（一键参数自调优）
"""
from app.services.eval.auto_tuner import PARAM_SPECS, ApplyResult, AutoTuner, ParamChange
from app.services.eval.data_builder import BaseRAGRunner, EvalDataBuilder, ProjectRAGRunner
from app.services.eval.diagnoser import DiagnosisItem, RAGDiagnoser
from app.services.eval.eval_config import RAGEvalConfig
from app.services.eval.evaluator import EvalReport, RAGEvaluator
from app.services.eval.metrics_llm import LLMMetrics
from app.services.eval.metrics_local import LocalMetrics
from app.services.eval.report_generator import DIMENSIONS, METRIC_LABELS, ReportGenerator
from app.services.eval.report_store import EvalReportStore

__all__ = [
    "RAGEvalConfig",
    "BaseRAGRunner",
    "ProjectRAGRunner",
    "EvalDataBuilder",
    "LocalMetrics",
    "LLMMetrics",
    "EvalReport",
    "RAGEvaluator",
    "DiagnosisItem",
    "RAGDiagnoser",
    "ReportGenerator",
    "EvalReportStore",
    "AutoTuner",
    "ParamChange",
    "ApplyResult",
    "PARAM_SPECS",
    "DIMENSIONS",
    "METRIC_LABELS",
]
