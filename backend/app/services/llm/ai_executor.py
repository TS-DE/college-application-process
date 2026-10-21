"""AI 执行基础设施：专用线程池、超时、在途名额。

0.17.0 从 `routers/ai.py` 原样搬出；0.17.1 修正名额归还时机。

## 名词：什么叫「在途名额」
**名额 = 线程占用（任务已提交、且线程尚未结束），不是「请求是否还在等」。**

0.17.0 及以前，`_release_inflight()` 放在 `_run_ai` 的最外层 `finally`：
`asyncio.wait_for` 一旦超时，请求侧立刻归还名额，但**线程还在跑**
（Python 无法强杀线程）—— 于是计数显示空闲、池子其实已满，
新请求照样被放进来，过载保护形同虚设。

0.17.1 起，名额由**工作线程自己在 `finally` 里归还**：
线程真正结束才腾出槽位，与「线程占用」语义一致。
另加僵尸槽位回收（`AI_SLOT_MAX_HOLD_SECONDS`），防止线程永久挂死导致名额泄漏。

## 依赖方向
本模块只依赖 `config` 与 `fastapi.HTTPException`，不 import 任何 `api/` 或业务服务，
保证它可以被任意层级安全复用。
"""
import asyncio
import functools
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

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


def _worker(
    recorder: Dict[str, Any],
    release_token: Optional[float],
    fn,
    args: tuple,
) -> Any:
    """在工作线程内执行任务，**线程结束时才归还名额**（0.17.1 核心修正）。

    与 0.17.0 的 `_timed_call` 相比只多了一件事：`finally` 里归还名额。
    但这一件事决定了过载计数的正确性 —— 请求侧超时后线程仍在占用池子，
    只有线程自己走完才能腾出槽位。
    """
    recorder["started_at"] = time.perf_counter()
    try:
        return fn(*args)
    finally:
        _release_inflight(release_token)


# ============================================================ 在途名额（0.15.1 引入，0.17.1 修正语义）
#
# ## 为什么线程池还不够
# `ThreadPoolExecutor` 的**队列是无界的**：池子（8 线程）占满后，
# 后续任务会无限排队，直到各自超时才返回 504 —— 用户白等 25-200 秒，
# 期间连接与内存都还占着。对「AI 推理」这种重任务，排队不如直接拒绝。
#
# 上限 = `AI_THREADPOOL_SIZE × AI_MAX_INFLIGHT_FACTOR`（默认 8×2=16），
# 含义是「跑着一批 + 等一批」；再多就说明确实过载，立刻 503 更诚实。
#
# 用**列表**而不是计数器：每个槽位记录 `acquired_at`，
# 才能识别「持有时间过长的僵尸槽位」并强制回收。
_INFLIGHT_LOCK = threading.Lock()
_inflight_slots: List[float] = []


def _inflight_limit() -> int:
    return max(1, settings.AI_THREADPOOL_SIZE * settings.AI_MAX_INFLIGHT_FACTOR)


def _reap_stale_slots_locked() -> int:
    """回收僵尸槽位（**必须在持锁时调用**）。

    线程若因死循环 / 阻塞 IO 永久挂死，`_worker` 的 finally 永远不会执行，
    名额就再也收不回来。这里按「持有时间 > AI_SLOT_MAX_HOLD_SECONDS」兜底回收。
    """
    if not _inflight_slots:
        return 0
    now = time.monotonic()
    max_hold = settings.AI_SLOT_MAX_HOLD_SECONDS
    stale = [t for t in _inflight_slots if now - t > max_hold]
    if not stale:
        return 0
    for t in stale:
        _inflight_slots.remove(t)
    print(
        f"[AI] 槽位超时回收 {len(stale)} 个（持有 > {max_hold:.0f}s，"
        f"剩余 {len(_inflight_slots)}/{_inflight_limit()}）",
        flush=True,
    )
    return len(stale)


def _try_acquire_inflight() -> Optional[float]:
    """尝试占用一个名额；成功返回 token（用于精确归还），失败返回 None。"""
    with _INFLIGHT_LOCK:
        _reap_stale_slots_locked()
        if len(_inflight_slots) >= _inflight_limit():
            return None
        token = time.monotonic()
        _inflight_slots.append(token)
        return token


def _release_inflight(token: Optional[float] = None) -> None:
    """归还名额。

    :param token: `_try_acquire_inflight` 返回的令牌；按令牌移除可避免误删他人槽位。
                  传 None（或令牌已不在列表中）时退化为移除最早的一个，保证计数单调正确。
    """
    with _INFLIGHT_LOCK:
        if token is not None and token in _inflight_slots:
            _inflight_slots.remove(token)
        elif _inflight_slots:
            _inflight_slots.pop(0)


def _current_inflight() -> int:
    """当前在途名额数（供日志与测试读取；读取时先做一次僵尸回收）。"""
    with _INFLIGHT_LOCK:
        _reap_stale_slots_locked()
        return len(_inflight_slots)


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
    token = _try_acquire_inflight()
    if token is None:
        print(
            f"[AI] 过载拒绝 {label}：在途 {_current_inflight()}/{_inflight_limit()}"
            f"（池大小 {settings.AI_THREADPOOL_SIZE} × 系数 {settings.AI_MAX_INFLIGHT_FACTOR}）",
            flush=True,
        )
        raise HTTPException(status_code=503, detail="AI 服务繁忙，请稍后重试")

    loop = asyncio.get_running_loop()
    recorder: Dict[str, Any] = {"started_at": 0.0}
    submitted_at = time.perf_counter()

    try:
        future = loop.run_in_executor(
            _AI_EXECUTOR, functools.partial(_worker, recorder, token, fn, args)
        )
    except Exception:
        # 执行器已关闭 / 提交失败：线程不会启动，_worker 的 finally 也不会执行，
        # 必须在这里补还名额，否则每次失败都漏一个槽位。
        _release_inflight(token)
        raise

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
        # 名额归还**不在这里**（已交给 _worker 的 finally）。
        # 唯一例外：线程从未启动 —— 此时 _worker 不会执行，必须补还。
        #
        # 判据用 `recorder["started_at"]` 而不是 `future.cancelled()`：
        # wait_for 超时会把 asyncio 包装的 future 标成 CANCELLED，
        # 但底层线程可能早已在跑（concurrent.futures 无法中断运行中的任务），
        # 用 cancelled() 判断会把「已在跑」误判成「没启动」，导致名额提前归还 ——
        # 这正是 0.17.0 的老问题换了个位置复现。
        if not recorder["started_at"]:
            _release_inflight(token)


# 0.17.1：`_load_profile_summary` 已迁至 `services/chat/chat_orchestrator.py`。
# 本模块保持「纯执行器」定位：只管线程池、超时与在途名额，不参与对话上下文准备。


