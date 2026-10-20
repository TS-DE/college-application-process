"""Agent 结果结构（0.13.0）。

单独一个文件是为了让「数据契约」与「执行逻辑」解耦：
路由层、前端、测试都依赖这里的字段名，改执行逻辑不会牵动契约。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ToolTrace:
    """一次工具调用的轨迹（前端可据此展示「AI 查了什么」）。"""

    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    ok: bool = False
    skipped: bool = False
    elapsed_ms: int = 0
    error: str = ""
    #: 结果摘要（截断，便于前端折叠展示）
    preview: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "ok": self.ok,
            "skipped": self.skipped,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "preview": self.preview,
        }


@dataclass
class AgentAnswer:
    """Agent 最终产出。"""

    answer: str = ""
    #: 回答来源标记：agent / agent_no_tool / agent_fallback / agent_empty
    source: str = "agent"
    #: 去重后的数据来源（文件名 / 表名 / 图谱）
    sources: List[str] = field(default_factory=list)
    #: 本次用到的工具轨迹
    traces: List[ToolTrace] = field(default_factory=list)
    #: 实际执行的轮数（1 表示模型直接回答，没调工具）
    steps: int = 0
    #: 总耗时（毫秒）
    elapsed_ms: int = 0
    #: 是否注入了用户画像
    profile_injected: bool = False
    #: 本地模型名（便于前端/日志确认走的是 qwen3:4b）
    model: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "source": self.source,
            "sources": self.sources,
            "tool_trace": [t.to_dict() for t in self.traces],
            "steps": self.steps,
            "elapsed_ms": self.elapsed_ms,
            "profile_injected": self.profile_injected,
            "model": self.model,
            "tools_used": [t.name for t in self.traces if t.ok],
        }


__all__ = ["AgentAnswer", "ToolTrace"]
