"""对话编排层：把一次问答分派到正确的 RAG 链路（0.17.1 从 chat_router 迁入）。

## 职责边界
本模块**只做编排**：判断走哪条链路、按顺序调用 `services/rag` 与 `services/llm`。
不内联 Prompt 文本、不写 SQL —— 那些属于各自的 service。

## 五层回落顺序（与 0.17.0 完全一致）
    ① 意图路由（无关问题直接拦截）
    ② 多模态以文搜图
    ③ 三路融合（图谱 + MySQL + 向量）
    ④ 进阶 RAG（Self-RAG / Corrective / 标准）
    ⑤ 基础 RAG + 通用问答

## 为什么 `_load_profile_summary` 也在这里
它原本在 `services/llm/ai_executor.py`，但那个模块只管「线程池 / 超时 / 过载」。
读画像属于**对话上下文准备**，放在编排层职责更单一：
`ai_executor` 保持为纯执行器，编排层负责「准备输入 → 派发」。
"""
from typing import Dict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings


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


def run_chat(payload: dict, profile_context: str = "") -> dict:
    """对话编排唯一入口：等价于 0.17.0 的 `_chat_sync`。

    函数体逐行搬迁，未做任何逻辑改动（含异常映射与日志文案）。
    """
def run_chat(payload: dict, profile_context: str = "") -> dict:
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
    from app.services.rag import rag_service
    from app.services.llm.ai_service import ai_enabled, ask
    from app.services.rag.prompt_utils import build_history_section, sanitize_history

    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")
    if not ai_enabled():
        raise HTTPException(status_code=503, detail="AI 未启用")

    # ---- 0.17.1 多轮上文：先清洗（不可信输入），再渲染成 Prompt 片段 ----
    # 只用于消解「那学费呢」里的「那」，不进【检索上下文】，因此不会成为事实来源。
    turns = sanitize_history(
        payload.get("history"),
        max_turns=settings.CHAT_HISTORY_MAX_TURNS,
        max_chars=settings.CHAT_HISTORY_MAX_CHARS,
    )
    history_section = build_history_section(turns)
    history_used = bool(history_section)
    # 0.7.2：不再强制探测 Ollama；Ali 通道可用时即可正常问答，Ollama 只作为兜底。
    # 真正不可用的情况由 ask() / rag_service 返回空值后抛出 504。

    # ---- 0.4.0 ① Query 意图路由：无关问题直接拦截，不走检索 ----
    use_rag = bool(payload.get("use_rag"))
    if use_rag and not rag_service.route_query(question):
        return {
            "answer": rag_service.OFF_TOPIC_ANSWER,
            "source": "router_blocked",   # 前端可据此展示"该问题不在服务范围内"
            "sources": [],
            "history_used": history_used,
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
                "history_used": history_used,
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
                history_section=history_section,
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
                "history_used": history_used,
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
                history_section=history_section,
            )
            return {
                "answer": adv["answer"],
                "source": f"advanced:{adv['strategy']}",
                "sources": adv["sources"],
                "strategy": adv["strategy"],
                "steps": adv["steps"],
                "rewritten_query": adv.get("rewritten_query", ""),
                "history_used": history_used,
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
            history_section=history_section,
        )
        if not answer:
            raise HTTPException(status_code=504, detail="大模型响应超时")
        return {
            "answer": answer,
            "source": "rag+llm",
            "sources": sorted(set(sources)),
            "context_level": "parent" if "parent" in context_levels else "child",
            "history_used": history_used,
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
    if history_section:
        # 0.17.1：通用分支同样需要上文，否则「那退档呢」会被当成全新问题
        prompt_parts.append(history_section.strip())
    prompt_parts.append(f"问题：{question}")
    prompt_parts.append("回答：")

    answer = ask("\n".join(prompt_parts), num_predict=400)
    if not answer:
        raise HTTPException(status_code=504, detail="大模型响应超时")
    return {
        "answer": answer,
        "source": "rag+llm" if rag_snippets else "llm",
        "sources": sorted(set(sources)),
        "history_used": history_used,
    }
