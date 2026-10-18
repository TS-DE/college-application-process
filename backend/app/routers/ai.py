"""AI 接口：意图解析与推荐理由（Ollama + Qwen3，失败自动降级）。

0.12.0：`/api/ai/chat` 改为**必须登录**，并在 Prompt 中注入用户画像
（`user_profiles.summary_text`）。画像读取失败只记日志，不影响问答。

0.12.1：整体超时改为可配置（`CHAT_TOTAL_TIMEOUT`），超时明确返回 504 并打印
分阶段耗时；意图路由新增主观咨询白名单（不再误拦截「我该去哪」类问题）。
"""
import asyncio
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.routers.auth import get_current_user
from app.schemas.student import (
    ParseIntentIn,
    ParseIntentOut,
    RecommendReasonIn,
    RecommendReasonOut,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])


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
    """志愿问答（可选 RAG + 用户画像个性化）。

    0.7.2：整体链路改为 async + 线程池执行，防止同步 LLM 调用阻塞主事件循环，
    进而拖慢首页、登录等非 AI 接口。整体超时 120 秒，超时返回 504。

    0.12.0：必须登录（画像与历史都挂在 user_id 上）；会话开始前读一次画像总结，
    拼进系统 Prompt。`profile_injected` 字段告诉前端本次是否真的注入了画像。

    0.12.1：整体超时从 120 秒收紧到 `CHAT_TOTAL_TIMEOUT`（默认 100 秒），
    超时明确抛 504 并提示「哪一步慢了」，前端不再无限转圈。
    """
    import time

    _t0 = time.time()
    profile_context = await run_in_threadpool(_load_profile_summary, db, user["id"])
    _t_profile = time.time()
    if profile_context:
        # 便于验证「画像是否真的进了 Prompt」：控制台打印注入摘要。
        # 用 print 而非 logger.info——uvicorn 默认只输出 WARNING 以上的应用日志，
        # 用 logger 会看不到（0.10.0 的 OCR 日志踩过同一个坑）。
        snippet = profile_context[:80].replace("\n", " ")
        print(
            f"[PROFILE] 已注入用户画像 user={user['id']} 长度={len(profile_context)}：{snippet}…",
            flush=True,
        )
    print(
        f"[AI] 阶段耗时 读画像={_t_profile - _t0:.2f}s（画像长度={len(profile_context)}）",
        flush=True,
    )
    try:
        result = await asyncio.wait_for(
            run_in_threadpool(_chat_sync, payload, profile_context),
            timeout=settings.CHAT_TOTAL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print(
            f"[AI] 整体超时 {settings.CHAT_TOTAL_TIMEOUT}s（已耗时 {time.time() - _t0:.2f}s）"
            f" question={(payload.get('question') or '')[:40]}",
            flush=True,
        )
        raise HTTPException(
            status_code=504,
            detail=(
                f"AI 响应超时（>{settings.CHAT_TOTAL_TIMEOUT:.0f} 秒）。"
                "可尝试：关闭知识库增强后重试、缩短问题长度，或稍后再试。"
            ),
        ) from None
    print(
        f"[AI] 阶段耗时 总链路={time.time() - _t0:.2f}s"
        f" source={result.get('source') if isinstance(result, dict) else '?'}",
        flush=True,
    )
    # 附带给前端一个明确标记，便于在界面上提示「已结合你的画像」
    if isinstance(result, dict):
        result.setdefault("profile_injected", bool(profile_context))
    return result


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
