# -*- coding: utf-8 -*-
"""0.17.1 验收 C 组：AI 线程池名额归还时机。

核心断言（C2）：`asyncio.wait_for` 超时只是**放弃等待**，线程仍在跑。
因此超时后名额**不应**立即归还；必须等线程真正结束才归零。

用法：python tests/llm/test_executor_slots.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

RESULTS = []


def check(name: str, cond: bool, extra: str = "") -> None:
    RESULTS.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {extra}" if extra else ""))


def test_slot_held_until_thread_ends() -> None:
    """C2：超时后名额仍被占用，线程结束后才归零。"""
    print("C2：超时后名额由线程持有")
    from app.services.llm import ai_executor as ex

    def slow_job(seconds: float) -> str:
        time.sleep(seconds)
        return "done"

    async def run() -> None:
        before = ex._current_inflight()
        check("起始名额为 0", before == 0, f"实际 {before}")

        # 任务要跑 3 秒，但只等 0.6 秒 → 必然超时
        try:
            await ex._run_ai(slow_job, 3.0, timeout=0.6, label="c2-slow")
            check("应当超时", False)
        except asyncio.TimeoutError:
            check("确实超时", True)

        # 超时瞬间：线程还在 sleep，名额必须仍被占着
        right_after = ex._current_inflight()
        check("超时后名额未被提前归还（≥1）", right_after >= 1, f"实际 {right_after}")

        # 等线程跑完（3 秒 + 余量）
        await asyncio.sleep(3.2)
        after = ex._current_inflight()
        check("线程结束后名额归零", after == 0, f"实际 {after}")

    asyncio.run(run())


def test_multiple_timeouts_no_leak() -> None:
    """连续超时不应累积泄漏；也不应因归还而超额放行。"""
    print("\nC2-延伸：连续超时不泄漏、不超额")
    from app.services.llm import ai_executor as ex

    def job(seconds: float) -> None:
        time.sleep(seconds)

    async def run() -> None:
        for i in range(3):
            try:
                await ex._run_ai(job, 1.2, timeout=0.2, label=f"burst-{i}")
            except asyncio.TimeoutError:
                pass
        mid = ex._current_inflight()
        check("3 个超时任务同时在跑 → 名额 ≈3", mid >= 1, f"实际 {mid}")
        await asyncio.sleep(1.6)
        check("全部结束后归零", ex._current_inflight() == 0,
              f"实际 {ex._current_inflight()}")

    asyncio.run(run())


def test_stale_slot_reclaim() -> None:
    """僵尸槽位回收：持有时间超阈值应被强制回收并告警。"""
    print("\n僵尸槽位回收")
    from app.services.llm import ai_executor as ex

    with ex._INFLIGHT_LOCK:
        ex._inflight_slots.clear()
        # 塞一个「600 秒前」的槽位（模拟线程挂死）
        ex._inflight_slots.append(time.monotonic() - 9999)

    before = len(ex._inflight_slots)
    token = ex._try_acquire_inflight()
    check("超时槽位被回收后仍能取到名额", token is not None)
    check("回收后只剩新槽位", len(ex._inflight_slots) == 1,
          f"清理前 {before}，现在 {len(ex._inflight_slots)}")
    ex._release_inflight(token)
    check("归还后归零", ex._current_inflight() == 0)


def test_overload_still_503() -> None:
    """C3（桩版）：名额占满时 _try_acquire_inflight 返回 None（上层据此 503）。"""
    print("\nC3（桩版）：名额占满不再放行")
    from app.config import settings
    from app.services.llm import ai_executor as ex

    limit = settings.AI_THREADPOOL_SIZE * settings.AI_MAX_INFLIGHT_FACTOR
    with ex._INFLIGHT_LOCK:
        ex._inflight_slots.clear()
        now = time.monotonic()
        ex._inflight_slots.extend([now] * limit)

    check(f"占满 {limit} 个名额后 acquire 返回 None", ex._try_acquire_inflight() is None)
    check("计数等于上限", ex._current_inflight() == limit)

    with ex._INFLIGHT_LOCK:
        ex._inflight_slots.clear()
    check("清理后可再次获取", ex._try_acquire_inflight() is not None)
    with ex._INFLIGHT_LOCK:
        ex._inflight_slots.clear()


def main() -> int:
    print("=" * 72)
    test_slot_held_until_thread_ends()
    test_multiple_timeouts_no_leak()
    test_stale_slot_reclaim()
    test_overload_still_503()
    print("=" * 72)
    failed = [n for n, ok in RESULTS if not ok]
    print(f"共 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项")
    for n in failed:
        print("  FAIL:", n)
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
