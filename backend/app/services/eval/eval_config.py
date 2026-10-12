"""评估全局配置（单一职责：只负责「评估这件事」的参数存取）。

设计要点（开闭 + 依赖倒置）：
- 默认值统一从 `app.config.settings` 读取，保证与项目其他模块同源；
- 支持前端传参覆盖（dict 覆盖），不修改源码即可调整评估行为。
"""
from typing import Any, Dict

from app.config import settings


class RAGEvalConfig:
    """RAG 量化评估的配置对象。

    关键字段：
    - LLM_MODEL          ：评估用的 LLM（仅 LLM 打分指标启用时生效）
    - EMBED_MODEL        ：评估用的 embedding 模型（语义相似度 / context 指标均依赖它）
    - SIM_THRESHOLD      ：判定「召回片段命中标准答案」的相似度阈值，默认 0.65
    - TOP_K_FOR_EVAL     ：评估时每条样本检索多少条上下文
    - MAX_SAMPLES        ：单次评估最大样本数（防止接口超时）
    - LLM_METRICS_ENABLED：是否启用 LLM 打分指标，默认关闭（规避 API 报错 / 额度耗尽）
    - EVAL_DATA_DIR      ：评估数据集目录
    - REPORT_OUTPUT_DIR  ：评估报告输出目录
    """

    def __init__(self, overrides: Dict[str, Any] | None = None) -> None:
        self.LLM_MODEL: str = settings.ALI_LLM_MODEL
        self.EMBED_MODEL: str = settings.ALI_EMBED_MODEL
        self.SIM_THRESHOLD: float = settings.EVAL_SIM_THRESHOLD
        self.TOP_K_FOR_EVAL: int = settings.EVAL_TOP_K
        self.MAX_SAMPLES: int = settings.EVAL_MAX_SAMPLES
        self.LLM_METRICS_ENABLED: bool = settings.EVAL_LLM_METRICS_ENABLED
        self.EVAL_DATA_DIR: str = settings.EVAL_DATA_DIR
        self.REPORT_OUTPUT_DIR: str = settings.EVAL_REPORT_DIR

        # 前端传入覆盖（只接受已知字段，避免任意属性注入）
        for key, value in (overrides or {}).items():
            if not hasattr(self, key):
                continue
            current = getattr(self, key)
            setattr(self, key, self._cast(current, value))

    @staticmethod
    def _cast(current: Any, value: Any) -> Any:
        """按现有字段类型做安全转换，避免字符串 "0" 变成 True。"""
        if isinstance(current, bool):
            return str(value) not in {"0", "false", "False", ""}
        if isinstance(current, int):
            return int(value)
        if isinstance(current, float):
            return float(value)
        return value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "LLM_MODEL": self.LLM_MODEL,
            "EMBED_MODEL": self.EMBED_MODEL,
            "SIM_THRESHOLD": self.SIM_THRESHOLD,
            "TOP_K_FOR_EVAL": self.TOP_K_FOR_EVAL,
            "MAX_SAMPLES": self.MAX_SAMPLES,
            "LLM_METRICS_ENABLED": self.LLM_METRICS_ENABLED,
            "EVAL_DATA_DIR": self.EVAL_DATA_DIR,
            "REPORT_OUTPUT_DIR": self.REPORT_OUTPUT_DIR,
        }
