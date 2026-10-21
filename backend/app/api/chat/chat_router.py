"""AI 问答入口：POST /chat（0.17.1 精简为「只做入口」）。

职责：解析 payload → 读画像 → 调编排层 → 转响应。
其余端点已拆到：
  · /status                    → status_router.py
  · /parse-intent、/recommend-reason → intent_router.py
  · 五层回落编排               → services/chat/chat_orchestrator.py
"""
import asyncio
import time
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.api.account.auth_router import get_current_user
from app.services.chat.chat_orchestrator import _load_profile_summary, run_chat
from app.services.llm.ai_executor import _reject_if_overloaded, _run_ai

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/chat")
async def chat(
    payload: dict,
    user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """志愿问答：**本地 Agent 模式**（默认）+ 用户画像个性化。

    0.13.0 核心变更：
      不再由代码写死「先查向量库再查 SQL」，而是把三路数据源包装成工具
      （`tool_search_vector` / `tool_search_mysql` / `tool_search_graph`）
      交给本地 `qwen3:4b`，由模型自己决定调用哪个。
      模型判断不需要工具（闲聊）时直接回答，省掉全部检索开销。

    降级：Agent 不可用（模型未启动 / 协议异常）→ 回落 0.12.x 的融合链路
    `_chat_sync()`，保证「再差也能答」。

    0.12.0：必须登录（画像与历史都挂在 user_id 上）。
    0.12.1：整体超时 `CHAT_TOTAL_TIMEOUT`，超时明确抛 504。
    """
    _t0 = time.time()
    # 0.15.1：入口预检，过载时立刻拒绝，不跑读画像等前置步骤
    _reject_if_overloaded("chat")

    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")

    # 0.15.0：读画像也走 AI 专用池（它持有 db 会话，属于阻塞 IO）
    profile_context = await _run_ai(
        _load_profile_summary,
        db,
        user["id"],
        timeout=settings.AUTH_TIMEOUT_SECONDS,
        label="read-profile",
    )
    if profile_context:
        snippet = profile_context[:80].replace("\n", " ")
        print(
            f"[PROFILE] 已注入用户画像 user={user['id']} 长度={len(profile_context)}：{snippet}…",
            flush=True,
        )
    print(
        f"[AI] 阶段耗时 读画像={time.time() - _t0:.2f}s（画像长度={len(profile_context)}）",
        flush=True,
    )

    # ---- ① 本地 Agent（0.13.1 起默认让位给极速模式）----
    # 决策顺序：
    #   1) 请求显式 use_agent=false → 不用 Agent
    #   2) AGENT_ENABLED=0          → 不用 Agent
    #   3) AGENT_FAST_MODE=1        → 不用 Agent（默认，走 0.12.x 快速链路，6-15s）
    #   4) 其余情况                 → 走 Agent（演示工具调用时把 AGENT_FAST_MODE 设为 0）
    use_agent = (
        bool(payload.get("use_agent", True))
        and settings.AGENT_ENABLED
        and not settings.AGENT_FAST_MODE
    )
    if not use_agent and settings.AGENT_FAST_MODE and settings.AGENT_ENABLED:
        print(
            "[AI] 极速模式：跳过 Agent 两轮推理，直接走确定性融合链路"
            "（设 AGENT_FAST_MODE=0 可启用 Agent 演示）",
            flush=True,
        )
    if use_agent:
        try:
            # ★ 用 AGENT_TOTAL_TIMEOUT（200s）而不是 CHAT_TOTAL_TIMEOUT（100s）：
            #   Agent 要跑「规划 + 工具 + 生成」两轮本地推理，实测 110-155 秒，
            #   沿用 100 秒会在生成轮前就被掐断（0.13.0 首次联调的真实故障）。
            agent_out = await _run_ai(
                _run_agent_sync,
                question,
                profile_context,
                payload.get("province") or "",
                payload.get("category") or "",
                int(payload.get("top_k") or 5),
                timeout=settings.AGENT_TOTAL_TIMEOUT,
                label="agent",
            )
            if agent_out.get("answer"):
                print(
                    f"[AI] 阶段耗时 总链路={time.time() - _t0:.2f}s "
                    f"mode=agent tools={agent_out.get('tools_used')}",
                    flush=True,
                )
                return agent_out
            print("[AI] Agent 未产出答案，回落三路融合链路", flush=True)
        except asyncio.TimeoutError:
            # 已经等满 200 秒，再回落旧链路只会让用户多等 40 秒。
            # 直接 504 并说明原因，比「看起来卡死」更诚实。
            print(f"[AI] Agent 超时 {settings.AGENT_TOTAL_TIMEOUT}s，直接返回 504", flush=True)
            raise HTTPException(
                status_code=504,
                detail=(
                    f"AI 思考超时（>{settings.AGENT_TOTAL_TIMEOUT:.0f} 秒）。"
                    "本地模型在 CPU 上推理较慢，可稍后重试或把问题问得更具体。"
                ),
            ) from None
        except HTTPException:
            # 0.15.1：过载 503 必须**直接透传**，不能被下面的「回落融合链路」吞掉。
            # 否则池子满了还会继续排一次队，过载保护形同虚设。
            raise
        except Exception as exc:  # noqa: BLE001 Agent 任何异常都不应让问答失败
            print(f"[AI] Agent 异常 {exc.__class__.__name__}，回落三路融合链路", flush=True)

    # ---- ② 回落：0.12.1 融合链路 ----
    try:
        result = await _run_ai(
            run_chat,
            payload,
            profile_context,
            timeout=settings.CHAT_TOTAL_TIMEOUT,
            label="chat-hybrid",
        )
    except asyncio.TimeoutError:
        print(
            f"[AI] 整体超时 {settings.CHAT_TOTAL_TIMEOUT}s（已耗时 {time.time() - _t0:.2f}s）"
            f" question={question[:40]}",
            flush=True,
        )
        raise HTTPException(
            status_code=504,
            detail=(
                f"AI 响应超时（>{settings.CHAT_TOTAL_TIMEOUT:.0f} 秒）。"
                "请稍后重试，或缩短问题长度。"
            ),
        ) from None
    print(
        f"[AI] 阶段耗时 总链路={time.time() - _t0:.2f}s"
        f" source={result.get('source') if isinstance(result, dict) else '?'}",
        flush=True,
    )
    if isinstance(result, dict):
        result.setdefault("profile_injected", bool(profile_context))
    return result




def _run_agent_sync(
    question: str,
    profile_context: str,
    province: str,
    category: str,
    top_k: int,
) -> dict:
    """线程池里执行 Agent（同步阻塞，不能占用事件循环）。"""
    from app.services.agent import run_agent

    answer = run_agent(
        question,
        profile_context=profile_context,
        province=province,
        category=category,
        top_k=top_k,
    )
    out = answer.to_dict()
    out["profile_injected"] = bool(profile_context)
    return out


