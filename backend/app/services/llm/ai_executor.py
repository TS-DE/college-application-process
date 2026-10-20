"""AI 执行基础设施：专用线程池、超时、在途计数、画像读取。

0.17.0 从 `routers/ai.py` 原样搬出。这些能力被 `/chat` 与 `/counselor` 两个**入口**共用，
留在某个 router 里会导致「入口层互相 import」，所以下沉到服务层。
函数名与函数体均未改动。
"""
import asyncio
import functools
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings

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


# ============================================================ 在途计数（0.15.1 过载保护）
#
# ## 为什么线程池还不够
# `ThreadPoolExecutor` 的**队列是无界的**：池子（8 线程）占满后，
# 后续任务会无限排队，直到各自超时才返回 504 —— 用户白等 25-200 秒，
# 期间连接与内存都还占着。对「AI 推理」这种重任务，排队不如直接拒绝。
#
# 上限 = `AI_THREADPOOL_SIZE × AI_MAX_INFLIGHT_FACTOR`（默认 8×2=16），
# 含义是「跑着一批 + 等一批」；再多就说明确实过载，立刻 503 更诚实。
_INFLIGHT_LOCK = threading.Lock()
_inflight_count = 0


def _inflight_limit() -> int:
    return max(1, settings.AI_THREADPOOL_SIZE * settings.AI_MAX_INFLIGHT_FACTOR)


def _try_acquire_inflight() -> bool:
    """尝试占用一个在途名额；超过上限返回 False。"""
    global _inflight_count
    with _INFLIGHT_LOCK:
        if _inflight_count >= _inflight_limit():
            return False
        _inflight_count += 1
        return True


def _release_inflight() -> None:
    """释放名额（`max(0, …)` 防御性下限，避免任何路径把计数压成负数）。"""
    global _inflight_count
    with _INFLIGHT_LOCK:
        _inflight_count = max(0, _inflight_count - 1)


def _current_inflight() -> int:
    """当前在途数（供日志与测试读取）。"""
    with _INFLIGHT_LOCK:
        return _inflight_count


def _reject_if_overloaded(label: str) -> None:
    """请求**入口**的快速预检（0.15.1）。

    与 `_run_ai` 内的检查分工：
      · 这里只读计数、不占名额，作用是「已过载就别再跑读画像等前置步骤」；
      · `_run_ai` 里的 acquire 才是原子的准入控制，负责并发竞态下的最终裁决。

    实测：20 个请求同刻到达时，若等到第一个 `_run_ai` 才发现过载，
    请求已经排过一轮队（约 2 秒）才被拒；入口预检能把这段省掉。
    """
    current = _current_inflight()
    if current >= _inflight_limit():
        print(
            f"[AI] 过载拒绝(入口) {label}：在途 {current}/{_inflight_limit()}",
            flush=True,
        )
        raise HTTPException(status_code=503, detail="AI 服务繁忙，请稍后重试")


async def _run_ai(fn, *args, timeout: float, label: str = "ai") -> Any:
    """把阻塞调用提交到 **AI 专用线程池**，施加超时，并做过载保护。

    与 `run_in_threadpool` 的区别有三点：
      1. 用 `_AI_EXECUTOR` 而非 anyio 默认池 → 不挤占认证/业务接口；
      2. 记录**排队耗时**与执行耗时，超过 `AI_QUEUE_WAIT_WARN_SECONDS` 打告警；
      3. 在途数超过 `AI_THREADPOOL_SIZE × AI_MAX_INFLIGHT_FACTOR` 时
         **立刻 503**，不让请求在无界队列里空等到超时。

    超时后 `wait_for` 会取消 future，但**线程本身无法被强制终止**
    （Python 的已知限制）；被放弃的任务仍会跑完再释放槽位。
    因此 `timeout` 应小于前端 axios 超时，让前端先拿到明确的 504。

    :raises HTTPException: 503（过载）
    """
    if not _try_acquire_inflight():
        print(
            f"[AI] 过载拒绝 {label}：在途 {_current_inflight()}/{_inflight_limit()}"
            f"（池大小 {settings.AI_THREADPOOL_SIZE} × 系数 {settings.AI_MAX_INFLIGHT_FACTOR}）",
            flush=True,
        )
        raise HTTPException(status_code=503, detail="AI 服务繁忙，请稍后重试")

    try:
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
    finally:
        # ★ 必须放在最外层 finally：超时、异常、正常返回都要归零，
        #   否则一次失败就永久吃掉一个名额，最终整个 AI 服务被 503 锁死。
        _release_inflight()


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


