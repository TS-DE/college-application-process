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
)

logger = logging.getLogger(__name__)

# ---------------- langgraph 可选依赖 ----------------
try:  # pragma: no cover - 取决于环境是否安装
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
    LANGGRAPH_IMPORT_ERROR = ""
except Exception as exc:  # noqa: BLE001 缺依赖不能拖垮整个应用
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

    # ---- Node 3 人工干预 ----
    user_feedback: str

    # ---- Node 4 重新规划 ----
    feedback_parsed: Dict[str, Any]
    final_plan: Dict[str, List[Dict[str, Any]]]
    changes: List[Dict[str, str]]
    note: str

    # ---- 元信息 ----
    stage: str
    elapsed_ms: int


# ============================================================ 图构建


def build_plan_graph(
    draft_builder: Optional[PlanDraftBuilder] = None,
    interpreter: Optional[FeedbackInterpreter] = None,
    refiner: Optional[PlanRefiner] = None,
    checkpointer: Any = None,
):
    """编译带 Checkpoint 的 HITL 图；langgraph 不可用时返回 None。

    :param checkpointer: 默认 `MemorySaver()`（进程内）。
                         将来换 SQLite/Redis 只需在这里注入，业务代码不动（DIP）。
    """
    if not LANGGRAPH_AVAILABLE:
        logger.warning("[PLAN] langgraph 不可用，HITL 工作流停用：%s", LANGGRAPH_IMPORT_ERROR)
        return None

    from app.config import settings

    draft_n = max(1, int(settings.PLAN_DRAFT_PER_TIER or 8))
    final_n = max(1, int(settings.PLAN_FINAL_PER_TIER or 8))

    builder = draft_builder or PlanDraftBuilder(
        per_tier={"chong": draft_n, "wen": draft_n, "bao": draft_n}
    )
    interp = interpreter or FeedbackInterpreter(llm_timeout=settings.PLAN_LLM_TIMEOUT)
    refiner_svc = refiner or PlanRefiner(
        per_tier={"chong": final_n, "wen": final_n, "bao": final_n}
    )

    # ---------------- Node 1：分析意图 ----------------
    def analyze_intent(state: PlanState) -> Dict[str, Any]:
        """读分数与画像，把「想去江浙沪、不想太冷」这类偏好变成筛选条件。

        这里复用 `FeedbackInterpreter` 的规则层（0 延迟）：
        用户画像里的偏好文字、以及 start 请求里显式传的 preferences，
        都按同一种方式解析成结构化的 `PlanFeedback`。
        """
        _t = time.time()
        info = state.get("user_info") or {}
        profile = state.get("profile_context") or ""
        preference_text = " ".join(
            x for x in [str(info.get("preferences") or ""), profile] if x
        )
        parsed = interp.interpret(preference_text, draft=None)
        intent = parsed.to_dict()
        print(
            f"[PLAN] Node1 分析意图 {time.time() - _t:.2f}s "
            f"排除地区={intent.get('exclude_provinces')} "
            f"偏好地区={intent.get('prefer_provinces')} "
            f"偏好专业={intent.get('prefer_majors')}",
            flush=True,
        )
        return {"intent": intent, "stage": "intent_done"}

    # ---------------- Node 2：生成初稿 ----------------
    def generate_draft(state: PlanState) -> Dict[str, Any]:
        """调用规则引擎生成冲稳保初稿，并按 Node1 的意图做一次预筛。"""
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

        # 意图预筛：把画像里的偏好也应用一次（候选池保留全量供后续替换）
        intent_dict = state.get("intent") or {}
        draft = result["draft_plan"]
        if any(intent_dict.get(k) for k in (
            "exclude_provinces", "exclude_universities", "exclude_keywords", "max_tuition"
        )):
            try:
                fb = PlanFeedback.from_dict(intent_dict)
                # 只取排除类条件做预筛，偏好留到 Node4 再排序
                fb.prefer_provinces = []
                fb.prefer_majors = []
                draft = refiner_svc.refine(draft, result["candidate_pool"], fb)["final_plan"]
            except Exception as exc:  # noqa: BLE001 预筛失败用原稿
                logger.info("[PLAN] 意图预筛失败：%s", exc.__class__.__name__)

        print(
            f"[PLAN] Node2 生成初稿 {time.time() - _t:.2f}s "
            f"rank={result['rank']} 冲{len(draft.get('chong', []))} "
            f"稳{len(draft.get('wen', []))} 保{len(draft.get('bao', []))}",
            flush=True,
        )
        return {
            "rank": result["rank"],
            "draft_plan": draft,
            "candidate_pool": result["candidate_pool"],
            "summary": result["summary"],
            "stage": "draft_ready",
            "elapsed_ms": int((time.time() - _t) * 1000),
        }

    # ---------------- Node 3：人工复核（中断点） ----------------
    def human_review(state: PlanState) -> Dict[str, Any]:
        """空节点 —— 唯一的职责是给 `interrupt_before` 一个挂载点。

        真正的「等待用户」发生在图外面：`invoke()` 到这里之前就返回，
        前端拿到 `draft_plan` 展示，用户改完再 `update_state` + `resume`。
        """
        print("[PLAN] Node3 人工复核（恢复执行）", flush=True)
        return {"stage": "reviewed"}

    # ---------------- Node 4：重新规划 ----------------
    def refine_plan(state: PlanState) -> Dict[str, Any]:
        """把「初稿 + 用户意见」变成终稿。"""
        _t = time.time()
        draft = state.get("draft_plan") or {}
        pool = state.get("candidate_pool") or draft
        feedback_text = state.get("user_feedback") or ""

        parsed = interp.interpret(feedback_text, draft=draft)
        # 意图里的偏好（画像）也带上，不影响排除逻辑
        intent_dict = state.get("intent") or {}
        if intent_dict.get("prefer_provinces") or intent_dict.get("prefer_majors"):
            parsed.prefer_provinces = list(dict.fromkeys(
                parsed.prefer_provinces + list(intent_dict.get("prefer_provinces") or [])
            ))
            parsed.prefer_majors = list(dict.fromkeys(
                parsed.prefer_majors + list(intent_dict.get("prefer_majors") or [])
            ))

        result = refiner_svc.refine(draft, pool, parsed)
        print(
            f"[PLAN] Node4 重新规划 {time.time() - _t:.2f}s "
            f"排除{len(result['changes'])}条 最终冲{len(result['final_plan'].get('chong', []))} "
            f"稳{len(result['final_plan'].get('wen', []))} "
            f"保{len(result['final_plan'].get('bao', []))}",
            flush=True,
        )
        return {
            "feedback_parsed": parsed.to_dict(),
            "final_plan": result["final_plan"],
            "changes": result["changes"],
            "note": result["note"],
            "stage": "final_ready",
            "elapsed_ms": int((time.time() - _t) * 1000),
        }

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
    graph.add_edge("refine_plan", END)

    return graph.compile(
        checkpointer=checkpointer or MemorySaver(),
        # ★ HITL 的关键：在 human_review **之前** 停下，把控制权交回前端
        interrupt_before=["human_review"],
    )


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
            "summary": values.get("summary") or "",
            "intent": values.get("intent") or {},
            "stage": values.get("stage") or "draft_ready",
            "elapsed_ms": elapsed,
        }

    def resume(
        self, thread_id: str, user_id: int, user_feedback: str
    ) -> Dict[str, Any]:
        """注入用户意见并恢复执行，返回终稿。"""
        graph = self._require_graph()
        self._check_owner(thread_id, user_id)
        cfg = self._config(thread_id)

        t = time.time()
        # ① 把反馈写进 State（挂在 human_review 上，语义上就是「用户在这一步提交了意见」）
        graph.update_state(cfg, {"user_feedback": user_feedback or ""}, as_node="human_review")
        # ② 继续执行
        graph.invoke(None, cfg)

        values = dict(graph.get_state(cfg).values or {})
        elapsed = int((time.time() - t) * 1000)
        print(
            f"[PLAN] 会话 {thread_id[:8]} 完成重新规划，耗时 {elapsed}ms",
            flush=True,
        )
        return {
            "thread_id": thread_id,
            "final_plan": values.get("final_plan") or {},
            "changes": values.get("changes") or [],
            "feedback_parsed": values.get("feedback_parsed") or {},
            "note": values.get("note") or "",
            "rank": values.get("rank"),
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
