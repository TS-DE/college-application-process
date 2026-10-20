"""本地 Agent 调度层（0.13.0）。

## 为什么要独立成包
0.12.x 的 `/api/ai/chat` 是**写死顺序**的流水线：
「意图路由 → 以文搜图 → 图谱+MySQL+向量三路融合 → 纯向量 → 通用 Prompt」。
这种写法有两个问题：
  1. 每加一路检索就要改 `_chat_sync` 的分支（违反开闭原则）；
  2. 查什么由代码决定，而不是由模型判断，简单闲聊也会走完全部检索。

0.13.0 改为 **Function Calling / Agent 模式**：
把「向量库、MySQL、图谱」封装成三个工具，交给本地 `qwen3:4b` 自主决定调用哪个。

## 模块职责
    base.py         工具抽象（BaseTool / ToolResult）+ 统一返回结构
    tools.py        三个具体工具的实现（向量 / MySQL / 图谱）
    registry.py     工具注册表（注册、查表、生成 OpenAI tools 规格）
    ollama_tools.py 本地 Ollama 的原生 tools 调用客户端（含 JSON 规划兜底）
    prompts.py      Agent 系统提示词
    runner.py       调度器：规划 → 执行 → 再规划 → 生成答案
    agent_result.py 结果数据结构（便于前端展示「AI 用了哪些工具」）

## 依赖方向（DIP）
`AgentRunner` 只依赖 `BaseTool` 抽象与一个「可调用的 LLM 通道协议」，
不 import 具体是 Ollama 还是阿里云；测试时注入桩即可，零网络开销。
"""
from app.services.agent.agent_result import AgentAnswer, ToolTrace
from app.services.agent.base import BaseTool, ToolCall, ToolResult
from app.services.agent.registry import ToolRegistry, build_default_registry
from app.services.agent.runner import AgentRunner, run_agent

__all__ = [
    "AgentAnswer",
    "ToolTrace",
    "BaseTool",
    "ToolCall",
    "ToolResult",
    "ToolRegistry",
    "build_default_registry",
    "AgentRunner",
    "run_agent",
]
