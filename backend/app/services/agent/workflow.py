"""人机回环（HITL）的志愿生成工作流 —— LangGraph 编排层（0.14.0）。

## 这个模块只做三件事
1. 定义 **State**（`PlanState`）——图里流转的数据契约；
2. 把四个 Node 连成图，并在 `human_review` **之前** 挂中断点；
3. 用 `MemorySaver` 保存暂停时的状态，对外暴露 `start()` / `resume()`。

业务逻辑（查位次、算冲稳保、解析反馈、重新筛选）全部在
`plan_builder.py` 里，本文件不写一行 SQL、不调一次 LLM ——
这样既满足单一职责，也让核心逻辑可以脱离 langgraph 单独测试。

## 图长什么样

```
START → analyze_intent → generate_draft → ⏸ human_review → refine_plan → END
                                          ↑
                              第一次 invoke 会停在这里
                              前端拿到 draft_plan 给用户改
                              update_state 注入 user_feedback 后 resume
```

## 与现有链路的关系
**完全独立**：不复用 `/api/ai/chat` 的 AgentRunner，也不改动 `rag_service`。
RAG 问答、心理师、报告上传的行为一行都没变。

## 依赖缺失时的降级
`langgraph` 未安装时模块仍可 import（`LANGGRAPH_AVAILABLE=False`），
路由层据此返回 503 并提示安装命令，而不是让整个应用启动失败。
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, TypedDict

from app.services.agent.plan_builder import (
    FeedbackInterpreter,
    PlanDraftBuilder,
    PlanFeedback,
    PlanInputError,
    PlanRefiner,
    PreferenceSource,
)

logger = logging.getLogger(__name__)

# ---------------- langgraph 可选依赖 ----------------
try:  # pragma: no cover - 取决于环境是否安装
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    # 0.19.0：节点内中断与恢复都用这两个（interrupt / Command）
    from langgraph.types import Command, interrupt

    LANGGRAPH_AVAILABLE = True
    LANGGRAPH_IMPORT_ERROR = ""
except Exception as exc:  # noqa: BLE001 缺依赖不能拖垮整个应用
    Command = None  # type: ignore[assignment]
    interrupt = None  # type: ignore[assignment]
    MemorySaver = None  # type: ignore[assignment]
    StateGraph = None  # type: ignore[assignment]
    END = START = None  # type: ignore[assignment]
    LANGGRAPH_AVAILABLE = False
    LANGGRAPH_IMPORT_ERROR = f"{exc.__class__.__name__}: {exc}"


# ============================================================ State


class PlanState(TypedDict, total=False):
    """图的全局状态。

    `total=False` 让节点可以只返回自己改动的字段（LangGraph 会做增量合并），
    不必每个节点都把整个状态回传。
    """

    # ---- 输入 ----
    user_id: int
    user_info: Dict[str, Any]       # province / category / score / rank / year / preferences
    profile_context: str            # 用户画像总结（可为空）

    # ---- Node 1 分析意图 ----
    intent: Dict[str, Any]          # 结构化的筛选偏好（省份/专业/学费上限）

    # ---- Node 2 生成初稿 ----
    rank: int
    draft_plan: Dict[str, List[Dict[str, Any]]]
    candidate_pool: Dict[str, List[Dict[str, Any]]]
    summary: str

    # ---- Node 3 人工干预（0.19.0：多轮） ----
    user_feedback: str
    review_round: int               # 当前第几版方案（从 1 开始）
    review_action: str              # revise / accept
    history: List[Dict[str, Any]]   # 每轮 {round, feedback, changes, note}

    # ---- Node 4 重新规划 ----
    feedback_parsed: Dict[str, Any]
    final_plan: Dict[str, List[Dict[str, Any]]]
    changes: List[Dict[str, str]]
    note: str

    # ---- 元信息 ----
    stage: str
    elapsed_ms: int


# ============================================================ 图构建


def _build_checkpointer():
    """按配置创建 Checkpointer（0.19.0）。

    · `sqlite`：落盘到 `backend/data/plan_checkpoints.db`，**服务重启后仍能恢复**；
      缺 `langgraph-checkpoint-sqlite` 时自动回落 memory 并打警告（不能让服务起不来）。
    · `memory`：进程内，重启即丢（0.14.0 的行为）。

    用 `check_same_thread=False`：FastAPI 的同步端点跑在线程池里，
    sqlite 连接会被不同线程使用。
    """
    from app.config import settings

    kind = (settings.PLAN_CHECKPOINTER or "sqlite").lower()
    if kind == "sqlite":
        try:
            import sqlite3
            from pathlib import Path

            from langgraph.checkpoint.sqlite import SqliteSaver

            backend_dir = Path(__file__).resolve().parents[3]
            db_path = backend_dir / settings.PLAN_CHECKPOINT_DB
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            print(f"[PLAN] Checkpointer=sqlite，落盘 {db_path}", flush=True)
            return SqliteSaver(conn)
        except Exception as exc:  # noqa: BLE001 依赖缺失/写盘失败 → 回落内存
            logger.warning(
                "[PLAN] sqlite checkpointer 不可用（%s），回落 MemorySaver：重启会丢失会话",
                exc.__class__.__name__,
            )
    return MemorySaver()


def build_plan_graph(
    draft_builder: Optional[PlanDraftBuilder] = None,
    interpreter: Optional[FeedbackInterpreter] = None,
    refiner: Optional[PlanRefiner] = None,
    checkpointer: Any = None,
):
    """编译带 Checkpoint 的 HITL 图；langgraph 不可用时返回 None。

    ## 0.19.0：从「静态中断」改为「节点内 interrupt()」
    0.14.0 用 `interrupt_before=["human_review"]` + 空节点：
    图在节点**之前**停下，用户意见靠 `update_state` 塞进状态，节点本身什么都没消费。
    现在 `human_review` 内部调用 `interrupt(payload)`，图在该节点**中间**挂起，
    恢复时用 `Command(resume=...)` 把用户的决定**作为 interrupt() 的返回值**交给节点 ——
    这才是真正的人机回环，也是多轮循环（回到同一个节点再中断）的前提。

    :param checkpointer: 默认按 `settings.PLAN_CHECKPOINTER` 创建（sqlite/memory）
    """
    if not LANGGRAPH_AVAILABLE:
        logger.warning("[PLAN] langgraph 不可用，HITL 工作流停用：%s", LANGGRAPH_IMPORT_ERROR)
        return None

    from app.config import settings

    draft_n = max(1, int(settings.PLAN_DRAFT_PER_TIER or 8))
    final_n = max(1, int(settings.PLAN_FINAL_PER_TIER or 8))
    max_rounds = max(1, int(settings.PLAN_MAX_REVIEW_ROUNDS or 5))

    builder = draft_builder or PlanDraftBuilder(
        per_tier={"chong": draft_n, "wen": draft_n, "bao": draft_n}
    )
    interp = interpreter or FeedbackInterpreter(llm_timeout=settings.PLAN_LLM_TIMEOUT)
    refiner_svc = refiner or PlanRefiner(
        per_tier={"chong": final_n, "wen": final_n, "bao": final_n}
    )

    # ---------------- Node 1：分析意图 ----------------
    def analyze_intent(state: PlanState) -> Dict[str, Any]:
        """把「用户显式偏好」与「画像推断」**分别**解析，再按权重合并。

        0.19.0 拆成两次解析的理由：拼成一个字符串后无法区分来源，
        冲突时（画像说江浙沪、用户说福建）会两边都进 prefer_provinces，
        硬过滤时互相稀释——用户会觉得「我说的话没被听」。
        """
        _t = time.time()
        info = state.get("user_info") or {}
        user_pref = str(info.get("preferences") or "").strip()
        profile = state.get("profile_context") or ""

        user_fb = interp.interpret(user_pref, draft=None) if user_pref else PlanFeedback()
        profile_fb = interp.interpret(profile, draft=None) if profile else PlanFeedback()
        merged = PreferenceSource(user_explicit=user_fb, from_profile=profile_fb).merge()
        intent = merged.to_dict()
        intent["user"] = user_fb.to_dict()
        intent["profile"] = profile_fb.to_dict()
        intent["merged"] = merged.to_dict()

        print(
            f"[PLAN] Node1 分析意图 {time.time() - _t:.2f}s "
            f"用户侧 偏好地区={user_fb.prefer_provinces} 排除地区={user_fb.exclude_provinces} | "
            f"画像侧 偏好地区={profile_fb.prefer_provinces} 排除地区={profile_fb.exclude_provinces} | "
            f"合并后 偏好={intent.get('prefer_provinces')} 排除={intent.get('exclude_provinces')}",
            flush=True,
        )
        return {"intent": intent, "stage": "intent_done"}

    # ---------------- Node 2：生成初稿 ----------------
    def generate_draft(state: PlanState) -> Dict[str, Any]:
        """生成冲稳保初稿，并对偏好做**硬过滤**（不再清空偏好）。"""
        _t = time.time()
        info = state.get("user_info") or {}
        result = builder.build(
            province=str(info.get("province") or ""),
            category=str(info.get("category") or ""),
            score=float(info.get("score") or 0),
            year=int(info.get("year") or 2025),
            rank=int(info.get("rank") or 0) or None,
            profile_context=state.get("profile_context") or "",
        )

        intent_dict = state.get("intent") or {}
        draft = result["draft_plan"]
        note = ""
        try:
            fb = PlanFeedback.from_dict(intent_dict.get("merged") or intent_dict)
            built = refiner_svc.build_with_preference(
                draft, result["candidate_pool"], fb,
                per_tier={"chong": draft_n, "wen": draft_n, "bao": draft_n},
            )
            draft = built["final_plan"]
            note = built["note"]
        except Exception as exc:  # noqa: BLE001 偏好应用失败不能阻断初稿
            logger.info("[PLAN] 偏好应用失败，使用原始初稿：%s", exc.__class__.__name__)

        print(
            f"[PLAN] Node2 生成初稿 {time.time() - _t:.2f}s "
            f"rank={result['rank']} 冲{len(draft.get('chong', []))} "
            f"稳{len(draft.get('wen', []))} 保{len(draft.get('bao', []))}"
            + (f" | {note}" if note else ""),
            flush=True,
        )
        return {
            "rank": result["rank"],
            "draft_plan": draft,
            "final_plan": draft,          # 前端统一读 final_plan 展示当前版本
            "candidate_pool": result["candidate_pool"],
            "summary": result["summary"],
            "note": note,
            "review_round": 1,
            "review_action": "revise",
            "history": [],
            "stage": "draft_ready",
            "elapsed_ms": int((time.time() - _t) * 1000),
        }

    # ---------------- Node 3：人工复核（节点内中断） ----------------
    def human_review(state: PlanState) -> Dict[str, Any]:
        """在这里**挂起**，等用户说话（0.19.0 改为节点内 interrupt）。

        `interrupt(payload)` 会把 payload 交给调用方，并让图停在本节点中间；
        恢复时 `Command(resume={...})` 的值就是这个函数的返回值。
        """
        current_round = int(state.get("review_round") or 1)
        decision = interrupt({
            "type": "plan_review",
            "round": current_round,
            "max_rounds": max_rounds,
            "plan": state.get("final_plan") or state.get("draft_plan") or {},
            "hint": "可以直接说要改什么，例如：只保留福建的、学费别超 6000、太远的不想去",
        })
        decision = decision or {}
        action = str(decision.get("action") or "revise")
        print(
            f"[PLAN] Node3 收到用户决定：第 {current_round} 轮 action={action} "
            f"feedback={str(decision.get('feedback') or '')[:40]}",
            flush=True,
        )
        return {
            "user_feedback": str(decision.get("feedback") or ""),
            "review_action": action,
            "stage": "reviewed",
        }

    # ---------------- Node 4：根据反馈重新规划 ----------------
    def refine_plan(state: PlanState) -> Dict[str, Any]:
        """把「当前版本 + 用户意见」变成下一版。

        `action=accept` 时直接透传（定稿不改方案，也不占用轮次），
        否则 `review_action` **不能被重置** —— 条件边要靠它判断是否结束。
        """
        _t = time.time()
        if str(state.get("review_action") or "revise") == "accept":
            print("[PLAN] Node4 用户定稿，跳过重新规划", flush=True)
            return {"stage": "final_ready", "elapsed_ms": int((time.time() - _t) * 1000)}

        draft = state.get("final_plan") or state.get("draft_plan") or {}
        pool = state.get("candidate_pool") or draft
        feedback_text = state.get("user_feedback") or ""
        current_round = int(state.get("review_round") or 1)

        parsed = interp.interpret(feedback_text, draft=draft)
        intent_dict = state.get("intent") or {}
        if intent_dict.get("prefer_provinces") or intent_dict.get("prefer_majors"):
            parsed.prefer_provinces = list(dict.fromkeys(
                parsed.prefer_provinces + list(intent_dict.get("prefer_provinces") or [])
            ))
            parsed.prefer_majors = list(dict.fromkeys(
                parsed.prefer_majors + list(intent_dict.get("prefer_majors") or [])
            ))

        result = refiner_svc.refine(draft, pool, parsed)
        next_round = current_round + 1
        history = list(state.get("history") or [])
        history.append({
            "round": current_round,
            "feedback": feedback_text,
            "changes": result["changes"],
            "note": result["note"],
        })
        print(
            f"[PLAN] Node4 第 {current_round} 轮调整 {time.time() - _t:.2f}s "
            f"调整{len(result['changes'])}条 → 第 {next_round} 版 冲"
            f"{len(result['final_plan'].get('chong', []))} "
            f"稳{len(result['final_plan'].get('wen', []))} "
            f"保{len(result['final_plan'].get('bao', []))}",
            flush=True,
        )
        return {
            "feedback_parsed": parsed.to_dict(),
            "final_plan": result["final_plan"],
            "changes": result["changes"],
            "note": result["note"],
            "review_round": next_round,
            "history": history,
            "stage": "final_ready",
            "elapsed_ms": int((time.time() - _t) * 1000),
        }

    def needs_more_review(state: PlanState) -> str:
        """条件边：定稿 / 到轮次上限 → 结束；否则回到 human_review 再中断一次。"""
        if str(state.get("review_action") or "revise") == "accept":
            return END
        if int(state.get("review_round") or 1) >= max_rounds:
            return END
        return "human_review"

    # ---------------- 组装 ----------------
    graph = StateGraph(PlanState)
    graph.add_node("analyze_intent", analyze_intent)
    graph.add_node("generate_draft", generate_draft)
    graph.add_node("human_review", human_review)
    graph.add_node("refine_plan", refine_plan)

    graph.add_edge(START, "analyze_intent")
    graph.add_edge("analyze_intent", "generate_draft")
    graph.add_edge("generate_draft", "human_review")
    graph.add_edge("human_review", "refine_plan")
    graph.add_conditional_edges(
        "refine_plan",
        needs_more_review,
        {"human_review": "human_review", END: END},
    )

    # ★ 不再用 interrupt_before：中断发生在 human_review 节点内部（interrupt()）
    return graph.compile(checkpointer=checkpointer or _build_checkpointer())


# ============================================================ 对外门面


class PlanWorkflow:
    """HITL 工作流的门面：start / resume / get_state。

    路由层只跟这个类打交道，不碰 langgraph 的 API（迪米特法则）。
    """

    def __init__(
        self,
        draft_builder: Optional[PlanDraftBuilder] = None,
        interpreter: Optional[FeedbackInterpreter] = None,
        refiner: Optional[PlanRefiner] = None,
        checkpointer: Any = None,
        graph: Any = None,
    ) -> None:
        self._graph = graph if graph is not None else build_plan_graph(
            draft_builder, interpreter, refiner, checkpointer
        )

    @property
    def available(self) -> bool:
        return self._graph is not None

    # ---------------- 内部工具 ----------------

    @staticmethod
    def _config(thread_id: str) -> Dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    def _require_graph(self):
        if self._graph is None:
            raise RuntimeError(
                "HITL 工作流不可用：请先安装 langgraph"
                "（pip install \"langgraph>=1.0\"）。"
                f"原始错误：{LANGGRAPH_IMPORT_ERROR or '未知'}"
            )
        return self._graph

    def _check_owner(self, thread_id: str, user_id: int) -> Dict[str, Any]:
        """校验线程归属：别人的方案不能读也不能改（隐私隔离）。"""
        snapshot = self._require_graph().get_state(self._config(thread_id))
        values = dict(snapshot.values or {})
        if not values:
            raise LookupError(f"会话不存在或已过期：{thread_id}")
        if int(values.get("user_id") or 0) != int(user_id):
            raise PermissionError("无权访问该规划会话")
        return values

    # ---------------- 对外接口 ----------------

    def start(
        self,
        user_id: int,
        user_info: Dict[str, Any],
        profile_context: str = "",
    ) -> Dict[str, Any]:
        """创建会话并跑到中断点，返回 thread_id + 初稿。"""
        graph = self._require_graph()
        thread_id = uuid.uuid4().hex
        cfg = self._config(thread_id)

        t = time.time()
        try:
            graph.invoke(
                {
                    "user_id": int(user_id),
                    "user_info": dict(user_info),
                    "profile_context": profile_context or "",
                    "user_feedback": "",
                },
                cfg,
            )
        except PlanInputError:
            raise
        except Exception as exc:  # noqa: BLE001 图内异常统一转业务异常
            logger.warning("[PLAN] 生成初稿失败：%s %s", exc.__class__.__name__, str(exc)[:200])
            raise

        values = dict(graph.get_state(cfg).values or {})
        elapsed = int((time.time() - t) * 1000)
        print(
            f"[PLAN] 会话 {thread_id[:8]} 已暂停在 human_review，"
            f"耗时 {elapsed}ms，等待用户反馈",
            flush=True,
        )
        return {
            "thread_id": thread_id,
            "rank": values.get("rank"),
            "draft_plan": values.get("draft_plan") or {},
            "final_plan": values.get("final_plan") or values.get("draft_plan") or {},
            "summary": values.get("summary") or "",
            "intent": values.get("intent") or {},
            "note": values.get("note") or "",
            "review_round": int(values.get("review_round") or 1),
            "history": values.get("history") or [],
            "stage": values.get("stage") or "draft_ready",
            "elapsed_ms": elapsed,
        }

    def resume(
        self, thread_id: str, user_id: int, payload: Any
    ) -> Dict[str, Any]:
        """把用户的决定送进 `interrupt()` 并继续执行（0.19.0 改为 Command 恢复）。

        :param payload: 兼容两种形态
            · dict → `{"feedback": str, "action": "revise"|"accept"}`
            · str  → 视为 `{"feedback": str, "action": "revise"}`（0.14.0 的旧调用）
        """
        graph = self._require_graph()
        self._check_owner(thread_id, user_id)
        cfg = self._config(thread_id)

        if isinstance(payload, dict):
            feedback = str(payload.get("feedback") or payload.get("user_feedback") or "")
            action = str(payload.get("action") or "revise")
        else:
            feedback, action = str(payload or ""), "revise"

        t = time.time()
        # ★ 0.19.0：恢复值就是 human_review 里 interrupt() 的返回值
        graph.invoke(Command(resume={"feedback": feedback, "action": action}), cfg)

        values = dict(graph.get_state(cfg).values or {})
        snapshot = graph.get_state(cfg)
        elapsed = int((time.time() - t) * 1000)
        print(
            f"[PLAN] 会话 {thread_id[:8]} 第 {values.get('review_round')} 版完成，"
            f"action={action}，耗时 {elapsed}ms，"
            f"{'等待下一轮' if snapshot.next else '已结束'}",
            flush=True,
        )
        return {
            "thread_id": thread_id,
            "final_plan": values.get("final_plan") or {},
            "changes": values.get("changes") or [],
            "feedback_parsed": values.get("feedback_parsed") or {},
            "note": values.get("note") or "",
            "rank": values.get("rank"),
            "review_round": int(values.get("review_round") or 1),
            "review_action": str(values.get("review_action") or action),
            "history": values.get("history") or [],
            "awaiting_feedback": bool(snapshot.next),
            "stage": values.get("stage") or "final_ready",
            "elapsed_ms": elapsed,
        }

    def get_state(self, thread_id: str, user_id: int) -> Dict[str, Any]:
        """读取会话当前状态（前端刷新页面后可以恢复现场）。"""
        graph = self._require_graph()
        values = self._check_owner(thread_id, user_id)
        snapshot = graph.get_state(self._config(thread_id))
        return {
            "thread_id": thread_id,
            "stage": values.get("stage") or "",
            "rank": values.get("rank"),
            "draft_plan": values.get("draft_plan") or {},
            "final_plan": values.get("final_plan") or {},
            "changes": values.get("changes") or [],
            "note": values.get("note") or "",
            "intent": values.get("intent") or {},
            "review_round": int(values.get("review_round") or 1),
            "review_action": str(values.get("review_action") or "revise"),
            "history": values.get("history") or [],
            # next 非空表示还停在中断点，等着用户反馈
            "awaiting_feedback": bool(snapshot.next),
        }

    def drop(self, thread_id: str) -> None:
        """释放会话（MemorySaver 目前靠 GC；保留此方法便于将来换持久化 Checkpointer）。"""
        logger.info("[PLAN] 会话 %s 释放", thread_id[:8])


# ---------------------------------------------------------------- 单例


_workflow: Optional[PlanWorkflow] = None


def get_plan_workflow() -> PlanWorkflow:
    """进程内单例（MemorySaver 必须复用同一个实例，否则读不到历史状态）。"""
    global _workflow
    if _workflow is None:
        _workflow = PlanWorkflow()
    return _workflow


def reset_plan_workflow() -> None:
    """重置单例（测试用）。"""
    global _workflow
    _workflow = None


__all__ = [
    "PlanState",
    "PlanWorkflow",
    "build_plan_graph",
    "get_plan_workflow",
    "reset_plan_workflow",
    "LANGGRAPH_AVAILABLE",
    "LANGGRAPH_IMPORT_ERROR",
]
