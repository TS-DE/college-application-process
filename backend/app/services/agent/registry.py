"""工具注册表（0.13.0）。

## 职责
只管「有哪些工具、怎么按名字取、怎么生成给模型的规格」，
不执行调度（`runner.py` 负责），也不实现工具（`tools.py` 负责）。

## 开闭原则
新增一路数据源时：
    1. 在 `tools.py` 里写一个 `BaseTool` 子类；
    2. 在 `build_default_registry()` 里 `register()` 一行。
调度器与路由层零改动。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.services.agent.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具集合（保持注册顺序，便于日志与前端展示稳定）。"""

    def __init__(self, tools: Optional[List[BaseTool]] = None) -> None:
        self._tools: Dict[str, BaseTool] = {}
        for tool in tools or []:
            self.register(tool)

    # ---------------- 注册 / 查询 ----------------

    def register(self, tool: BaseTool) -> "ToolRegistry":
        """注册工具（同名覆盖，便于测试替换）。"""
        if not tool.name:
            raise ValueError("工具必须有 name")
        self._tools[tool.name] = tool
        return self

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return list(self._tools.keys())

    def available(self) -> List[BaseTool]:
        """当前环境下真正可用的工具（Neo4j 未启动时图谱工具会被排除）。"""
        out: List[BaseTool] = []
        for tool in self._tools.values():
            try:
                if tool.is_available():
                    out.append(tool)
            except Exception as exc:  # noqa: BLE001 可用性判断失败按不可用处理
                logger.info("[AGENT] 工具 %s 可用性判断失败：%s", tool.name, exc.__class__.__name__)
        return out

    # ---------------- 给模型看的规格 ----------------

    def specs(self, limit: int = 8) -> List[Dict]:
        """生成 OpenAI / Ollama tools 规格（只含可用工具，最多 limit 个）。"""
        return [t.spec() for t in self.available()[: max(1, int(limit or 8))]]

    def describe(self, limit: int = 8) -> str:
        """工具说明书（纯文本版，用于 JSON 规划兜底 Prompt）。"""
        lines: List[str] = []
        for i, tool in enumerate(self.available()[: max(1, int(limit or 8))], 1):
            params = ", ".join((tool.parameters.get("properties") or {}).keys())
            lines.append(f"{i}. {tool.name}：{tool.description}（参数：{params}）")
        return "\n".join(lines)

    # ---------------- 执行 ----------------

    def execute(self, name: str, query: str, **kwargs) -> ToolResult:
        """按名字执行工具；未知工具返回 ok=False，不抛异常。"""
        tool = self.get(name)
        if tool is None:
            return ToolResult.empty(f"未知工具：{name}")
        return tool.run(query, **kwargs)


def build_default_registry(include_graph: bool = True) -> ToolRegistry:
    """装配默认三路工具（这是唯一需要「知道具体实现」的地方）。"""
    from app.services.agent.tools import (
        GraphSearchTool,
        MySQLSearchTool,
        VectorSearchTool,
    )

    registry = ToolRegistry()
    registry.register(VectorSearchTool())
    registry.register(MySQLSearchTool())
    if include_graph:
        registry.register(GraphSearchTool())
    return registry


__all__ = ["ToolRegistry", "build_default_registry"]
