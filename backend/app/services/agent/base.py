"""工具抽象层（0.13.0）。

## 设计要点

**单一职责**：`BaseTool` 只描述「一个工具叫什么、能干什么、参数是什么、怎么执行」，
不关心调度顺序（那是 `runner.py` 的事），也不关心 HTTP（那是路由层的事）。

**开闭原则（OCP）**：新增一路数据源（比如「招生计划 Excel 检索」）只需继承
`BaseTool` 并在 `registry.build_default_registry()` 里注册一行，
`AgentRunner` 与路由层**一行都不用改**。

**里氏替换（LSP）**：所有工具对 `run()` 的契约完全一致——必定返回 `ToolResult`，
绝不抛异常（失败也返回 `ok=False`），因此调度器可以无差别地遍历执行。

**依赖倒置（DIP）**：工具的构造函数接受可调用的检索函数（默认懒加载真实实现），
测试时注入桩函数即可验证调度逻辑，不需要启动 MySQL / Chroma / Neo4j。
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolResult:
    """工具执行结果（调度器与模型都消费这个结构）。"""

    #: 是否拿到了可用内容（False 表示「没查到」或「执行失败」，模型据此换工具）
    ok: bool = False
    #: 给模型看的文本（已是精简后的中文句子，不含原始 JSON 噪声）
    summary: str = ""
    #: 原始结构化数据（前端调试 / 二次处理用，不喂给模型）
    data: Any = None
    #: 数据来源标签（文件名、表名等），用于前端展示「参考了什么」
    sources: List[str] = field(default_factory=list)
    #: 失败原因（为空表示无错误）
    error: str = ""
    #: 执行耗时（毫秒），用于分阶段日志
    elapsed_ms: int = 0
    #: 该工具是否被判定为「不适用」（例如问题里没有院校名，MySQL 工具跳过）
    skipped: bool = False

    @classmethod
    def empty(cls, reason: str = "", skipped: bool = False) -> "ToolResult":
        return cls(ok=False, summary="", error=reason, skipped=skipped)

    def to_model_text(self, limit: int = 1500) -> str:
        """转成喂回模型的文本（限制长度，防止小模型上下文被撑爆）。"""
        text = (self.summary or "").strip()
        if not text:
            return f"（无结果）{self.error}".strip()
        return text[:limit]


@dataclass
class ToolCall:
    """模型发起的一次工具调用请求。"""

    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    #: Ollama 原生 tool_calls 会带 id，用于回填 tool 消息（JSON 规划兜底时为空）
    call_id: str = ""


class BaseTool(ABC):
    """工具抽象基类。

    子类只需实现三样东西：
      · `name` / `description` / `parameters`：给模型看的说明书；
      · `run()`：真正执行；
      · `is_available()`（可选）：当前环境下该工具是否可用（如 Neo4j 未启动）。
    """

    #: 工具名（模型按这个名字调用，只能是英文/下划线）
    name: str = ""
    #: 一句话说明「什么时候该用我」，写得越具体小模型选得越准
    description: str = ""
    #: JSON Schema 形式的参数定义
    parameters: Dict[str, Any] = {"type": "object", "properties": {}}

    @abstractmethod
    def run(self, query: str, **kwargs: Any) -> ToolResult:
        """执行工具。**必须**返回 ToolResult，不允许抛异常。"""

    # ---------------- 可选覆写 ----------------

    def is_available(self) -> bool:
        """当前环境是否可用（默认可用）。"""
        return True

    def spec(self) -> Dict[str, Any]:
        """转成 OpenAI / Ollama 的 tools 规格。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    # ---------------- 供子类复用的执行包装 ----------------

    def _timed(self, func: Callable[[], ToolResult]) -> ToolResult:
        """统一的耗时统计与异常兜底包装（模板方法，避免每个子类重复写 try）。"""
        start = time.time()
        try:
            result = func()
        except Exception as exc:  # noqa: BLE001 工具异常绝不允许冒泡到调度器
            result = ToolResult.empty(f"{exc.__class__.__name__}: {str(exc)[:150]}")
        if result.elapsed_ms == 0:
            result.elapsed_ms = int((time.time() - start) * 1000)
        return result


__all__ = ["BaseTool", "ToolResult", "ToolCall"]
