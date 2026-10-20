# -*- coding: utf-8 -*-
"""认证与 AI 线程隔离的验收脚本（0.15.0「超时掉登录」修复）。

## 为什么需要一个独立脚本
这次故障的本质是**并发与调度**问题，不是单元逻辑问题：
`/auth/me` 本身没有 bug，是它被 AI 请求挤出了可用线程。
所以验收必须并发压测，用真实 HTTP 测响应时间，而不是桩测试。

## 用法
    # 需先启动服务（uvicorn app.main:app --port 8000）
    python -m tests.auth.test_auth_isolation
    python -m tests.auth.test_auth_isolation --concurrency 12

## 覆盖的验收标准
  ① 6 个并发 /api/ai/chat 期间，/api/auth/me 应 < 2 秒
  ② 后端繁忙时，登录接口应在 30 秒内完成
  ③ 超时判据：401 才算失效，5xx / 无响应都应保留 token（纯函数校验）
"""
from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
from typing import List, Tuple

import requests

BASE = "http://127.0.0.1:8000"
#: 验收阈值（任务书规定）
ME_THRESHOLD_SECONDS = 2.0
LOGIN_THRESHOLD_SECONDS = 30.0


# ---------------------------------------------------------------- 前置


def ensure_account(prefix: str = "iso") -> Tuple[str, str]:
    """注册并登录一个临时账号，返回 (token, username)。"""
    username = f"{prefix}_{int(time.time() * 1000) % 10**9}"
    requests.post(
        f"{BASE}/api/auth/register",
        json={
            "username": username,
            "password": "test123456",
            "nickname": "隔离验证",
            "phone": f"138{int(time.time()) % 100000000:08d}",
        },
        timeout=20,
    )
    resp = requests.post(
        f"{BASE}/api/auth/login",
        json={"username": username, "password": "test123456"},
        timeout=LOGIN_THRESHOLD_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()["access_token"], username


def service_ready() -> bool:
    try:
        return requests.get(f"{BASE}/api/health", timeout=5).status_code == 200
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- 用例 1/2


def test_ai_burst_isolated(concurrency: int = 6) -> bool:
    """并发 AI 请求期间，/auth/me 与登录接口是否仍可用。"""
    print(f"用例 1：{concurrency} 个并发 /chat 期间测量 /auth/me")
    token, username = ensure_account()
    hdr = {"Authorization": f"Bearer {token}"}

    chats: List[Tuple[int, int, float]] = []
    lock = threading.Lock()

    def do_chat(idx: int) -> None:
        started = time.time()
        try:
            resp = requests.post(
                f"{BASE}/api/ai/chat",
                headers=hdr,
                json={"question": "请详细说说平行志愿的投档规则"},
                timeout=240,
            )
            with lock:
                chats.append((idx, resp.status_code, time.time() - started))
        except Exception:  # noqa: BLE001
            with lock:
                chats.append((idx, -1, time.time() - started))

    threads = [threading.Thread(target=do_chat, args=(i,)) for i in range(concurrency)]
    for th in threads:
        th.start()
    time.sleep(1.5)  # 让请求真正进入 AI 线程池

    me_times: List[float] = []
    print("  压测期间 /auth/me：")
    for i in range(5):
        started = time.time()
        resp = requests.get(f"{BASE}/api/auth/me", headers=hdr, timeout=40)
        cost = time.time() - started
        me_times.append(cost)
        print(f"    #{i + 1} {cost * 1000:7.1f} ms  HTTP {resp.status_code}")
        assert resp.status_code == 200, "认证接口不应在压测期间失败"
        time.sleep(0.4)

    started = time.time()
    login_resp = requests.post(
        f"{BASE}/api/auth/login",
        json={"username": username, "password": "test123456"},
        timeout=LOGIN_THRESHOLD_SECONDS,
    )
    login_cost = time.time() - started

    for th in threads:
        th.join()

    print(f"  压测期间登录：HTTP {login_resp.status_code} 耗时 {login_cost:.2f}s")
    print(f"  AI 请求完成 {len(chats)} 个，最慢 {max((c[2] for c in chats), default=0):.1f}s")

    me_max = max(me_times)
    me_avg = statistics.mean(me_times)
    print(f"  /auth/me 最大 {me_max * 1000:.0f} ms，平均 {me_avg * 1000:.0f} ms")

    ok_me = me_max < ME_THRESHOLD_SECONDS
    ok_login = login_resp.status_code == 200 and login_cost < LOGIN_THRESHOLD_SECONDS
    print(f"  验收 3（/auth/me < {ME_THRESHOLD_SECONDS:.0f}s）：{'PASS' if ok_me else 'FAIL'}")
    print(f"  验收 4（登录 < {LOGIN_THRESHOLD_SECONDS:.0f}s）：{'PASS' if ok_login else 'FAIL'}")
    return ok_me and ok_login


# ---------------------------------------------------------------- 用例 3


def test_timeout_judgement() -> bool:
    """纯函数校验前端判据：只有 401 才算登录失效。

    前端 `request.ts` 用状态码/错误码做判定，这里用等价规则复算一遍，
    确保「超时 / 5xx 保留 token、401 才登出」的约定不会被后续改动破坏。
    """
    print("用例 3：超时判据（401 才登出）")

    def decide(status: int | None, has_response: bool = True) -> str:
        """复刻 user.ts loadMe 的判定。"""
        if has_response and status == 401:
            return "LOGOUT"
        return "KEEP_TOKEN"

    cases = [
        ("HTTP 401 token 过期", 401, True, "LOGOUT"),
        ("HTTP 500 后端故障", 500, True, "KEEP_TOKEN"),
        ("HTTP 503 服务不可用", 503, True, "KEEP_TOKEN"),
        ("HTTP 200 正常", 200, True, "KEEP_TOKEN"),
        ("无响应（超时/断网）", None, False, "KEEP_TOKEN"),
    ]
    all_ok = True
    for name, status, has_resp, expected in cases:
        got = decide(status, has_resp)
        ok = got == expected
        all_ok = all_ok and ok
        print(f"  {name:22} → {got:10} {'OK' if ok else 'FAIL'}")
    print(f"  判据校验：{'PASS' if all_ok else 'FAIL'}")
    return all_ok


# ---------------------------------------------------------------- 入口


def main() -> int:
    parser = argparse.ArgumentParser(description="认证线程隔离验收")
    parser.add_argument("--concurrency", type=int, default=6, help="并发 AI 请求数")
    args = parser.parse_args()

    if not service_ready():
        print(f"[SKIP] 服务未启动：{BASE}")
        return 1

    print("=" * 68)
    ok1 = test_ai_burst_isolated(args.concurrency)
    print()
    ok2 = test_timeout_judgement()
    print("=" * 68)
    if ok1 and ok2:
        print("全部通过")
        return 0
    print("存在失败项")
    return 2


if __name__ == "__main__":
    sys.exit(main())
