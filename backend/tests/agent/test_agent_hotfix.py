# -*- coding: utf-8 -*-
"""0.13.1 验证：Fast Mode 降级 / 生成轮短超时兜底 / 环境状态接口 / 答案清洗增强。

用法：
    python test_hotfix_0_13_1.py          # 桩版：零网络
    python test_hotfix_0_13_1.py --real   # 真实链路（需服务 + Ollama）
"""
from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))  # 0.17.0：指向 backend/


# ---------------------------------------------------------------- 用例 1：配置


def test_config() -> None:
    """用例 1：极速模式默认开启，预算按实测调优。"""
    print("用例 1：极速模式与预算配置")
    from app.config import settings

    assert settings.AGENT_FAST_MODE is True, "极速模式应默认开启"
    assert settings.AGENT_PLAN_TOKENS == 350, settings.AGENT_PLAN_TOKENS
    assert settings.AGENT_ANSWER_TOKENS == 300
    assert settings.AGENT_ANSWER_TIMEOUT <= 30, "生成轮必须在 30s 内失败，否则白等"
    assert settings.AGENT_TOTAL_TIMEOUT <= 90
    print(f"  FAST_MODE={settings.AGENT_FAST_MODE} 规划={settings.AGENT_PLAN_TOKENS}token "
          f"生成={settings.AGENT_ANSWER_TOKENS}token")
    print(f"  生成超时={settings.AGENT_ANSWER_TIMEOUT}s 总预算={settings.AGENT_TOTAL_TIMEOUT}s")


# ---------------------------------------------------------------- 用例 2：清洗


def test_clean_answer() -> None:
    """用例 2：旁白必须全程过滤（0.13.0 只过滤开头，尾部会漏）。"""
    print("用例 2：答案清洗（全程过滤）")
    from app.services.agent.runner import clean_answer

    # ① 全旁白 + 引号内才是真答案
    raw1 = (
        "所以我要直接回复，不调用工具。\n"
        "回答要求是只用工具给的事实，但这里没有工具需要调用，所以应该简单回应"
        "“你好！有什么可以帮您的吗？”\n"
        "不过用户要求禁止输出思考过程，所以直接输出"
    )
    out1 = clean_answer(raw1)
    assert "不调用工具" not in out1 and "不过用户" not in out1, out1
    assert "有什么可以帮您的吗" in out1, out1
    print(f"  ① 全旁白 → 抽出答案：{out1[:40]}")

    # ② 旁白 + 正文：正文保留，尾随旁白也过滤
    raw2 = (
        "好的，用户问河南本科批怎么填报，我需要调用工具。\n"
        "河南本科批采用平行志愿，分数优先、遵循志愿、一轮投档。"
    )
    out2 = clean_answer(raw2)
    assert out2.startswith("河南本科批"), out2
    assert "用户问" not in out2
    print(f"  ② 旁白+正文 → 只留正文：{out2[:36]}")

    # ③ 纯正文不能被误删
    raw3 = "河南本科批可填 6 个院校志愿，建议按冲稳保 3:3:2 分配。"
    assert clean_answer(raw3) == raw3
    print("  ③ 纯正文未被误删")

    # ④ 全空时返回原文而不是空
    assert clean_answer("分析一下") != ""
    print("  ④ 极端情况不返回空")

    # ⑤ 只有闭合标签 </think>（token 用尽，开标签被截断）→ 取标签之后的内容
    raw5 = (
        "有什么可以帮您的吗？\n”。\n检查一下是否需要调用工具，这里不需要，所以不调用任何工具。\n"
        "</think>\n你好！\n有什么可以帮您的吗？"
    )
    out5 = clean_answer(raw5)
    assert "</think>" not in out5, out5
    assert "检查一下" not in out5, out5
    assert out5.startswith("你好"), out5
    print(f"  ⑤ </think> 残片 → 只留标签之后：{out5[:24]}")

    # ⑥ 客户端层同样处理（双保险）
    from app.services.agent.ollama_tools import OllamaToolClient

    assert OllamaToolClient._strip_think("推理过程</think>最终答案") == "最终答案"
    assert OllamaToolClient._strip_think("<think>推理</think>答案") == "答案"
    print("  ⑥ OllamaToolClient._strip_think 双保险生效")


# ---------------------------------------------------------------- 用例 3：兜底


def test_fallback_prefix() -> None:
    """用例 3：生成轮失败 → 检索摘要 + 明确的降级提示前缀。"""
    print("用例 3：生成轮失败兜底")

    from app.services.agent.base import BaseTool, ToolResult
    from app.services.agent.registry import ToolRegistry
    from app.services.agent.runner import AgentRunner

    class _Tool(BaseTool):
        name = "tool_search_vector"
        description = "查政策"
        parameters = {"type": "object", "properties": {"query": {"type": "string"}}}

        def run(self, query, **kwargs):
            return ToolResult(
                ok=True,
                summary=(
                    "河南本科批实行平行志愿，分数优先、遵循志愿、一轮投档。\n"
                    "本科一批 6 6 有 平行志愿 2025 2024 2023\n"
                    "建议按冲稳保 3:3:2 分配院校志愿。"
                ),
                sources=["p.pdf"],
            )

    class TimeoutLLM:
        model = "stub-4b"
        tools_supported = True
        timeout = 25

        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools=None, **kwargs):
            from app.services.agent.ollama_tools import LLMReply

            self.calls += 1
            if self.calls == 1:
                from app.services.agent.base import ToolCall

                return LLMReply(tool_calls=[ToolCall(name="tool_search_vector",
                                                     arguments={"query": "平行志愿"})])
            return LLMReply(error="Ollama 超时（>25.0s）")

    ans = AgentRunner(registry=ToolRegistry([_Tool()]), llm=TimeoutLLM(), max_steps=2).run(
        "河南本科批怎么填报"
    )
    assert ans.source == "agent_tool_only", ans.source
    assert ans.answer.startswith("（受限于本地算力"), ans.answer[:40]
    assert "分数优先" in ans.answer, "应包含检索到的正文"
    assert "2025 2024 2023" not in ans.answer, "表格噪声应被 _extract_excerpts 过滤"
    print(f"  source={ans.source}")
    print(f"  前缀正确，正文保留，表格噪声已过滤")
    print(f"  回答：{ans.answer[:70].replace(chr(10), ' ')}…")


# ---------------------------------------------------------------- 用例 4：状态接口


def test_agent_status() -> None:
    """用例 4：/api/meta/agent-status 契约与容错。"""
    print("用例 4：环境状态接口")
    from app.api.recommend import meta_router

    # 接口已注册
    paths = {r.path for r in meta_router.router.routes}
    assert "/api/meta/agent-status" in paths, paths
    print("  已注册 GET /api/meta/agent-status")

    # 直接调用（会真实探测，失败也必须返回结构完整的对象）
    data = meta_router.agent_status(refresh=True)
    for key in ("vector_ready", "graph_ready", "local_model", "agent_mode",
                "vector_count", "graph_error"):
        assert key in data, f"缺少字段 {key}"
    assert isinstance(data["vector_ready"], bool)
    assert isinstance(data["graph_ready"], bool)
    assert data["agent_mode"] in ("fast", "agent")
    print(f"  vector_ready={data['vector_ready']}（{data['vector_count']} 切片）")
    print(f"  graph_ready={data['graph_ready']} 原因={data['graph_error'] or '-'}")
    print(f"  local_model={data['local_model']} agent_mode={data['agent_mode']}")

    # 缓存生效：短时间内第二次不应重新探测。
    # 注意：直接调用时必须显式传 refresh=False——
    # FastAPI 的 `Query(...)` 默认值在函数直调时是个 Query 对象（真值），
    # 会让 `if not refresh` 恒为 False 从而绕过缓存（0.11.1 踩过同类坑）。
    d2 = meta_router.agent_status(refresh=False)
    assert d2["checked_at"] == data["checked_at"], "30 秒内应命中缓存"
    print("  30 秒 TTL 缓存生效")


# ---------------------------------------------------------------- 用例 5：Fast Mode 决策


def test_fast_mode_routing() -> None:
    """用例 5：AGENT_FAST_MODE=1 时不进入 Agent（路由层决策）。"""
    print("用例 5：Fast Mode 路由决策")
    import inspect

    from app.api.chat import chat_router as ai_router

    src = inspect.getsource(ai_router.chat)
    assert "settings.AGENT_FAST_MODE" in src, "路由层必须判断极速模式"
    assert "not settings.AGENT_FAST_MODE" in src, "极速模式下应跳过 Agent"
    print("  路由层：AGENT_FAST_MODE=1 → 跳过 Agent，走 0.12.x 确定性融合链路")
    print("  路由层：AGENT_FAST_MODE=0 → 进入 Agent（演示工具调用）")


# ---------------------------------------------------------------- 真实链路


def test_real() -> None:
    """用例 6：真实 HTTP 延迟与状态接口。"""
    import time

    import requests

    base = "http://127.0.0.1:8000"
    print("用例 6：真实链路")
    try:
        requests.get(f"{base}/api/health", timeout=5)
    except Exception:
        print("  [SKIP] 服务未启动")
        return

    st = requests.get(f"{base}/api/meta/agent-status", timeout=20).json()
    print(f"  状态接口：vector_ready={st['vector_ready']} graph_ready={st['graph_ready']} "
          f"mode={st['agent_mode']}")

    uname = f"speed_{int(time.time())}"
    requests.post(f"{base}/api/auth/register", json={
        "username": uname, "password": "test123456",
        "nickname": "速度验证", "phone": f"135{int(time.time()) % 100000000:08d}",
    }, timeout=20)
    tok = requests.post(f"{base}/api/auth/login",
                        json={"username": uname, "password": "test123456"},
                        timeout=20).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    t = time.time()
    r = requests.post(f"{base}/api/ai/chat", headers=h,
                      json={"question": "河南本科批平行志愿怎么填报"}, timeout=240)
    dt = time.time() - t
    d = r.json()
    print(f"  问答 status={r.status_code} 耗时={dt:.1f}s mode={st['agent_mode']} "
          f"source={d.get('source')}")
    assert r.status_code == 200, r.text
    assert d.get("answer"), "应有回答"

    if st["agent_mode"] == "fast":
        assert dt < 30, f"极速模式应 <30 秒，实际 {dt:.1f}s"
        print(f"  ✅ 极速模式达标：{dt:.1f}s（目标 <30s）")
    else:
        assert dt < 95, f"Agent 模式应 <95 秒，实际 {dt:.1f}s"
        print(f"  Agent 模式：{dt:.1f}s（前端会显示「约需 1 分钟」提示）")


def main() -> int:
    test_config()
    print()
    test_clean_answer()
    print()
    test_fallback_prefix()
    print()
    test_agent_status()
    print()
    test_fast_mode_routing()
    print()
    if "--real" in sys.argv:
        test_real()
        print()
    else:
        print("[提示] 加 --real 跑真实延迟测量（需服务 + Ollama）")
        print()
    print("=" * 72)
    print("0.13.1 桩版全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
