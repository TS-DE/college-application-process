"""AI 接口。

## 两个角色，两条链路

| 接口 | 模型 | 用途 |
|---|---|---|
| `POST /api/ai/chat` | **本地** `qwen3:4b`（Agent / Function Calling） | 政策、分数、院校查询 |
| `POST /api/ai/counselor` | **云端** `qwen3.7-flash` | 心理疏导、多轮谈心、画像采集 |

0.13.0 变更：
  · `/chat` 默认走 **Agent 模式**——把「向量库 / MySQL / 图谱」封装成工具，
    由本地模型自主决定查哪一路，不再由代码写死检索顺序；
  · 前端不再有「RAG 增强」开关，进页面即默认启用；
  · 新增 `/counselor`，**强制云端通道**（本地 4b 的情感推理不足，不降级）。

0.12.1 保留：整体超时可配置、超时返回 504、分阶段耗时日志。
"""
import asyncio
import functools
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.routers.auth import get_current_user
from app.schemas.ai import CounselorIn, CounselorOut
from app.schemas.student import (
    ParseIntentIn,
    ParseIntentOut,
    RecommendReasonIn,
    RecommendReasonOut,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])

# ============================================================ AI 专用线程池（0.15.0）
#
# ## 为什么必须拆出来
# FastAPI 的同步 `def` 端点与 `run_in_threadpool` 共用 anyio 默认线程池（上限 40）。
# `/chat` 单次可占用 100-200 秒，几个并发请求就能把池子占满，
# 此时同步的 `/auth/me`、`/api/students/*` 全部排队，
# 前端 10 秒超时后误判为「登录失效」→ 清 token → 用户被踢出登录。
#
# 拆出独立池后，**AI 再忙也不会挤占认证与普通查询的线程**。
# 池大小取 `AI_THREADPOOL_SIZE`（默认 8）：本机 CPU 推理并发过高只会互相拖慢。
_AI_EXECUTOR = ThreadPoolExecutor(
    max_workers=settings.AI_THREADPOOL_SIZE,
    thread_name_prefix="ai-worker",
)


def _timed_call(recorder: Dict[str, Any], fn, args: tuple) -> Any:
    """在线程内记录「真正开始执行」的时刻，用于算排队时间。"""
    recorder["started_at"] = time.perf_counter()
    return fn(*args)


async def _run_ai(fn, *args, timeout: float, label: str = "ai") -> Any:
    """把阻塞调用提交到 **AI 专用线程池**，并施加超时。

    与 `run_in_threadpool` 的区别只有两点，但都很关键：
      1. 用 `_AI_EXECUTOR` 而非 anyio 默认池 → 不挤占认证/业务接口；
      2. 记录**排队耗时**与执行耗时，超过 `AI_QUEUE_WAIT_WARN_SECONDS` 打告警，
         这样「池子被占满」在生产日志里是可见的，而不是靠猜。

    超时后 `wait_for` 会取消 future，但**线程本身无法被强制终止**
    （Python 的已知限制）；被放弃的任务仍会跑完再释放槽位。
    因此 `timeout` 应小于前端 axios 超时，让前端先拿到明确的 504。
    """
    loop = asyncio.get_running_loop()
    recorder: Dict[str, Any] = {"started_at": 0.0}
    submitted_at = time.perf_counter()

    future = loop.run_in_executor(
        _AI_EXECUTOR, functools.partial(_timed_call, recorder, fn, args)
    )
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        waited = time.perf_counter() - submitted_at
        print(
            f"[AI] {label} 超时 {timeout:.0f}s（已等待 {waited:.2f}s，"
            f"排队 {recorder['started_at'] - submitted_at if recorder['started_at'] else -1:.2f}s）",
            flush=True,
        )
        raise
    finally:
        if recorder["started_at"]:
            queue_wait = recorder["started_at"] - submitted_at
            if queue_wait > settings.AI_QUEUE_WAIT_WARN_SECONDS:
                print(
                    f"[AI] 线程池排队告警 {label} 等待 {queue_wait:.2f}s"
                    f"（阈值 {settings.AI_QUEUE_WAIT_WARN_SECONDS:.0f}s，"
                    f"池大小 {settings.AI_THREADPOOL_SIZE}）",
                    flush=True,
                )


@router.get("/status")
async def status() -> dict:
    """AI 状态探测：限时完成，避免阻塞前端。"""
    from app.services.ai_service import ai_enabled, ollama_health

    try:
        ok, msg = await asyncio.wait_for(
            run_in_threadpool(ollama_health), timeout=3.0
        )
    except asyncio.TimeoutError:
        ok, msg = False, "AI 状态探测超时"
    return {
        "ai_enabled": ai_enabled(),
        "ollama": ok,
        "message": msg,
        "model": _model_name(),
    }


def _model_name() -> str:
    from app.config import settings

    return settings.OLLAMA_MODEL


@router.post("/parse-intent", response_model=ParseIntentOut)
async def parse_intent(payload: ParseIntentIn) -> ParseIntentOut:
    """把「我想找个离家近、计算机强、学费便宜的学校」转成筛选条件。"""
    from app.services.ai_service import parse_intent as _parse

    data = await asyncio.wait_for(
        run_in_threadpool(_parse, payload.text, province=payload.province),
        timeout=30.0,
    )
    raw = data.pop("raw", None)
    return ParseIntentOut(**data, raw=raw)


@router.post("/recommend-reason", response_model=RecommendReasonOut)
async def recommend_reason(payload: RecommendReasonIn) -> RecommendReasonOut:
    """为单条志愿生成推荐理由。"""
    from app.services.ai_service import recommend_reason as _reason

    text, source = await asyncio.wait_for(
        run_in_threadpool(
            _reason,
            payload.model_dump(),
            {"rank": payload.student_rank, "score": payload.student_score},
        ),
        timeout=30.0,
    )
    return RecommendReasonOut(reason=text, source=source)


def _load_profile_summary(db: Session, user_id: int) -> str:
    """读取用户画像总结（供 Prompt 注入）。

    单独抽成函数是为了让异常处理集中在一处：
    画像只是「锦上添花」，任何失败都必须静默降级为空串，绝不能让问答 500。
    """
    try:
        from app.services.profile import ProfileRepository, ProfileService

        return ProfileService(ProfileRepository(db)).get_summary_for_prompt(user_id)
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).info(
            "[PROFILE] 读取画像失败，按无画像处理：%s", exc.__class__.__name__
        )
        return ""


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
        except Exception as exc:  # noqa: BLE001 Agent 任何异常都不应让问答失败
            print(f"[AI] Agent 异常 {exc.__class__.__name__}，回落三路融合链路", flush=True)

    # ---- ② 回落：0.12.1 融合链路 ----
    try:
        result = await _run_ai(
            _chat_sync,
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


@router.post("/counselor", response_model=CounselorOut)
async def counselor(
    body: CounselorIn,
    user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CounselorOut:
    """云端「心理师 / 画像构建师」多轮对话（0.13.0）。

    ## 与 /chat 的分工
    · `/chat`   本地 qwen3:4b + 工具，查政策与数据，毫秒级，数据不出本机；
    · `/counselor` 云端 qwen3.7-flash，谈心、疏导、采集画像，**不降级到本地**。

    ## 为什么必须登录
    画像与历史都挂在 `user_id` 上；同时把 `summary_text` 注入 system prompt，
    让云端模型知道「这个考生已经说过什么」，避免反复问同样的问题。
    """
    from app.services.counselor import CounselorService

    _t0 = time.time()
    # 0.15.0：读画像与云端生成都走 AI 专用线程池，不挤占认证接口
    profile_summary = await _run_ai(
        _load_profile_summary,
        db,
        user["id"],
        timeout=settings.AUTH_TIMEOUT_SECONDS,
        label="read-profile",
    )
    _t_profile = time.time()

    service = CounselorService()
    result = await _run_ai(
        service.chat,
        [m.model_dump() for m in body.messages],
        profile_summary,
        timeout=settings.COUNSELOR_TIMEOUT,
        label="counselor",
    )
    if result.get("error"):
        print(f"[COUNSELOR] 失败 user={user['id']}：{result['error']}", flush=True)
        raise HTTPException(status_code=503, detail=result["error"])

    print(
        f"[COUNSELOR] user={user['id']} 读画像={_t_profile - _t0:.2f}s "
        f"生成={result.get('elapsed_ms', 0)}ms model={result.get('model')} "
        f"画像注入={result.get('profile_injected')}",
        flush=True,
    )
    return CounselorOut(
        answer=result["answer"],
        source=result["source"],
        model=result.get("model"),
        elapsed_ms=result.get("elapsed_ms", 0),
        profile_injected=result.get("profile_injected", False),
        error=None,
    )


def _chat_sync(payload: dict, profile_context: str = "") -> dict:
    """原 /chat 同步实现，独立出来便于在线程池中运行。

    0.9.0：新增 `use_graph` 开关（默认 true）。开启且 `GRAPH_ENABLED=1` 时走
    「图谱 + 向量」双通道优先级融合（`rag_service.answer_with_graph`），
    任一路失败都会自动降级；`use_graph=false` 时保持 0.8.0 的纯向量行为不变。

    0.9.1：图谱分支升级为「图谱 + MySQL + 向量」三路融合
    （`rag_service.answer_with_hybrid`），按「图谱 > MySQL > 向量」优先级分发，
    响应新增 `mysql_hit` 字段。

    0.12.0：`profile_context` 由调用方（已登录态）传入，逐层注入 Prompt；
    为空串时所有链路行为与 0.11.x 完全一致。
    """
    from app.services import rag_service
    from app.services.ai_service import ai_enabled, ask

    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")
    if not ai_enabled():
        raise HTTPException(status_code=503, detail="AI 未启用")
    # 0.7.2：不再强制探测 Ollama；Ali 通道可用时即可正常问答，Ollama 只作为兜底。
    # 真正不可用的情况由 ask() / rag_service 返回空值后抛出 504。

    # ---- 0.4.0 ① Query 意图路由：无关问题直接拦截，不走检索 ----
    use_rag = bool(payload.get("use_rag"))
    if use_rag and not rag_service.route_query(question):
        return {
            "answer": rag_service.OFF_TOPIC_ANSWER,
            "source": "router_blocked",   # 前端可据此展示"该问题不在服务范围内"
            "sources": [],
        }

    # ---- 0.10.0 ② 多模态「以文搜图」：命中关键词才走，未命中/未命中图都回落三路融合 ----
    # 只做以文搜图（文字问题 → 检索图片 → VLM 解读），不做以图搜文与图文混合融合
    if use_rag and rag_service.should_use_multimodal(question):
        mm = rag_service.answer_with_multimodal(question)
        if mm:
            return {
                "answer": mm["answer"],
                "source": mm["source"],
                "sources": mm["sources"],
                "image_hit": mm["image_hit"],
                "images": mm["images"],
            }

    # ---- 0.9.1 ③ 三路融合：use_graph=true 时走「图谱 + MySQL + 向量」优先级分发 ----
    # 与下面的纯向量链路完全隔离：use_graph=false 时行为与 0.8.0 一致（向后兼容）
    use_graph = bool(payload.get("use_graph", True)) and rag_service.settings.GRAPH_ENABLED
    if use_rag and use_graph:
        try:
            hybrid = rag_service.answer_with_hybrid(
                question,
                top_k=int(payload.get("top_k") or 5),
                profile_context=profile_context,
            )
            return {
                "answer": hybrid["answer"],
                "source": hybrid["source"],
                "sources": hybrid["sources"],
                # 三路调试/统计字段（前端可展示「图谱命中 / 数据库命中 / 向量命中 / 实际 Cypher」）
                "graph_hit": hybrid["graph_hit"],
                "mysql_hit": hybrid["mysql_hit"],
                "vector_hit": hybrid["vector_hit"],
                "fusion_strategy": hybrid["fusion_strategy"],
                "graph_cypher": hybrid.get("graph_cypher", ""),
                "graph_error": hybrid.get("graph_error", ""),
                "mysql_error": hybrid.get("mysql_error", ""),
            }
        except Exception:  # noqa: BLE001 三路链路异常 → 回落下面的纯向量流程
            pass

    # ---- 0.7.0 ② Modular RAG：按 Query 特征走 Self-RAG / Corrective RAG / 标准 RAG ----
    if use_rag and rag_service.settings.ADVANCED_RAG_ENABLED:
        try:
            adv = rag_service.answer_with_strategy(
                question,
                top_k=int(payload.get("top_k") or 5),
                strategy=str(payload.get("strategy") or "auto"),
            )
            return {
                "answer": adv["answer"],
                "source": f"advanced:{adv['strategy']}",
                "sources": adv["sources"],
                "strategy": adv["strategy"],
                "steps": adv["steps"],
                "rewritten_query": adv.get("rewritten_query", ""),
            }
        except Exception:  # noqa: BLE001 高级链路异常 → 回落原有流程
            pass

    background = payload.get("context") or ""
    sources: list[str] = []
    rag_snippets = ""
    context_levels: list[str] = []

    if use_rag:
        hits = rag_service.search(question, int(payload.get("top_k") or 5))
        if hits:
            parts = []
            for h in hits:
                meta = h.get("metadata") or {}
                name = meta.get("filename") or "知识库"
                sources.append(name)
                context_levels.append(h.get("context_level") or "child")
                parts.append(f"[{name}] {h['text']}")
            rag_snippets = "\n".join(parts[:5])

    # ---- 0.4.0 ② 防幻觉生成：命中资料时用强约束 Prompt（temperature=0.1, top_p=0.1）----
    if use_rag and rag_snippets:
        # 0.4.1：top_p 从 0.1 放宽到 0.3，避免模型在极端保守采样下放弃生成
        answer = rag_service.generate_answer(
            question,
            rag_snippets,
            temperature=0.1,
            top_p=0.3,
            profile_context=profile_context,
        )
        if not answer:
            raise HTTPException(status_code=504, detail="大模型响应超时")
        return {
            "answer": answer,
            "source": "rag+llm",
            "sources": sorted(set(sources)),
            "context_level": "parent" if "parent" in context_levels else "child",
        }

    # 未开启 RAG 或没检索到资料：走通用 Prompt（不编造具体数字，仅给通用建议）
    prompt_parts = [
        "你是高考志愿填报助手，回答要简洁实用，分点说明，不要编造具体院校分数线。",
    ]
    # 0.12.0：画像优先于用户临时填的 background（画像是长期档案，更权威）
    if profile_context:
        prompt_parts.append(
            f"【考生画像】{profile_context}\n"
            "请结合上述画像给出个性化建议，但不得据此编造分数线、学费、位次等数字。"
        )
    if background:
        prompt_parts.append(f"考生背景：{background}")
    if rag_snippets:
        prompt_parts.append(
            "以下是知识库检索到的参考资料，优先依据它们回答；资料不足时再结合常识，并说明这是通用建议：\n"
            + rag_snippets
        )
    if use_rag and not rag_snippets:
        # 0.4.1 修正：不再直接拒答，而是让模型基于通用知识给方向性建议，
        # 但明确禁止编造具体数字（学费 / 分数线 / 位次）
        prompt_parts.append(
            "注意：知识库中未检索到直接相关的资料。请基于你的通用知识给出**方向性建议**"
            "（如建议查阅学校官网、省教育考试院），"
            "但**禁止编造具体的学费、分数线、位次数字**。"
            "如果用户问的是具体数字，请明确说明“建议查阅官方招生简章获取准确数字”。"
        )
    prompt_parts.append(f"问题：{question}")
    prompt_parts.append("回答：")

    answer = ask("\n".join(prompt_parts), num_predict=400)
    if not answer:
        raise HTTPException(status_code=504, detail="大模型响应超时")
    return {
        "answer": answer,
        "source": "rag+llm" if rag_snippets else "llm",
        "sources": sorted(set(sources)),
    }
