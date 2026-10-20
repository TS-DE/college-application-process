# -*- coding: utf-8 -*-
"""0.14.0 验证：LangGraph 人机回环（HITL）志愿规划。

用法：
    python test_plan_workflow.py          # 桩版：不连库、不调模型（秒级）
    python test_plan_workflow.py --real   # 真实链路（需服务 + 数据）
"""
from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))  # 0.17.0：指向 backend/


def _item(univ, major, prov, score=600, rank=40000, tuition=None):
    """构造一条志愿条目（字段与 calculate_tiers 产出保持一致）。"""
    return {
        "university_name": univ,
        "major_name": major,
        "school_province": prov,
        "min_score": score,
        "min_rank": rank,
        "tuition": tuition,
        "tier": "wen",
        "tier_label": "稳",
        "probability": 70.0,
        "rank_diff": 0,
    }


# ---------------------------------------------------------------- 用例 1：反馈解析


def test_interpreter() -> None:
    """用例 1：自由文本 → 结构化条件（规则层，0 依赖）。"""
    print("用例 1：反馈解析（规则层）")
    from app.services.agent.plan_builder import FeedbackInterpreter

    interp = FeedbackInterpreter(llm_enabled=False)
    draft = {"wen": [_item("北京大学", "计算机科学与技术", "北京"),
                     _item("吉林大学", "临床医学", "吉林")]}

    # ① 排除省份
    fb = interp.interpret("不想去北京", draft)
    assert "北京" in fb.exclude_provinces, fb.to_dict()
    print(f"  ① 「不想去北京」→ 排除地区 {fb.exclude_provinces}")

    # ② 语义别称：太冷 → 东北/西北
    fb = interp.interpret("我不想去太冷的地方", draft)
    assert "吉林" in fb.exclude_provinces and "黑龙江" in fb.exclude_provinces
    print(f"  ② 「太冷」→ 展开为 {len(fb.exclude_provinces)} 个省份")

    # ③ 偏好地区 + 偏好专业
    fb = interp.interpret("想去江浙沪，想学计算机", draft)
    assert "江苏" in fb.prefer_provinces and "计算机" in fb.prefer_majors
    print(f"  ③ 「江浙沪 + 计算机」→ 偏好地区 {fb.prefer_provinces}，"
          f"专业 {fb.prefer_majors}")

    # ④ 学费上限
    fb = interp.interpret("学费别超过 6000", draft)
    assert fb.max_tuition == 6000, fb.max_tuition
    print(f"  ④ 「学费别超过 6000」→ max_tuition={fb.max_tuition}")

    # ⑤ 具体院校
    fb = interp.interpret("吉林大学不要", draft)
    assert "吉林大学" in fb.exclude_universities
    print(f"  ⑤ 「吉林大学不要」→ 排除院校 {fb.exclude_universities}")

    # ⑥ 空文本不报错
    assert interp.interpret("", draft).is_empty()
    print("  ⑥ 空反馈 → is_empty=True（原稿直接作为终稿）")


# ---------------------------------------------------------------- 用例 2：初稿


def test_draft_builder() -> None:
    """用例 2：初稿生成（注入桩引擎，不连库）。"""
    print("用例 2：初稿生成")
    from app.services.agent.plan_builder import PlanDraftBuilder, PlanInputError

    pool = {
        "chong": [_item(f"冲刺大学{i}", "计算机科学与技术", "北京") for i in range(20)],
        "wen": [_item(f"稳妥大学{i}", "软件工程", "江苏") for i in range(20)],
        "bao": [_item(f"保底大学{i}", "数据科学", "湖北") for i in range(20)],
    }

    builder = PlanDraftBuilder(
        rank_fn=lambda s, p, c, y: 40000,
        tiers_fn=lambda r, p, c, y: pool,
        enrich_fn=lambda t, p, c, y: t,
        per_tier={"chong": 3, "wen": 4, "bao": 3},
    )
    res = builder.build("河南", "物理类", 600)
    assert res["rank"] == 40000
    assert len(res["draft_plan"]["chong"]) == 3
    assert len(res["draft_plan"]["wen"]) == 4
    assert len(res["candidate_pool"]["chong"]) == 20, "候选池应保留全量供替换"
    print(f"  rank={res['rank']} 初稿 冲3/稳4/保3，候选池各 20")
    print(f"  摘要：{res['summary'][:50]}…")

    # 非法省份 / 科类 / 查不到位次
    for prov, cat, kw in [("火星", "物理类", "省份"), ("河南", "艺术类", "科类")]:
        try:
            builder.build(prov, cat, 600)
            raise AssertionError(f"{prov}/{cat} 应报错")
        except PlanInputError as exc:
            assert kw in str(exc) or "科类" in str(exc), exc
    print("  非法省份 / 科类 → PlanInputError（路由层转 400）")

    bad = PlanDraftBuilder(
        rank_fn=lambda s, p, c, y: 0, tiers_fn=lambda r, p, c, y: pool,
        enrich_fn=lambda t, p, c, y: t,
    )
    try:
        bad.build("河南", "物理类", 100)
        raise AssertionError("位次为 0 应报错")
    except PlanInputError as exc:
        assert "一分一段表" in str(exc), exc
    print("  位次查不到 → 明确提示（不是静默空结果）")


# ---------------------------------------------------------------- 用例 3：重新规划


def test_refiner() -> None:
    """用例 3：按反馈筛选 + 偏好排序 + 全排除回退。"""
    print("用例 3：重新规划")
    from app.services.agent.plan_builder import PlanFeedback, PlanRefiner

    draft = {
        "chong": [_item("北京大学", "计算机", "北京", tuition=5000)],
        "wen": [_item("吉林大学", "临床医学", "吉林", tuition=6000),
                _item("南京大学", "软件工程", "江苏", tuition=5800)],
        "bao": [_item("民办学院", "工商管理", "广东", tuition=25000)],
    }
    refiner = PlanRefiner(per_tier={"chong": 5, "wen": 5, "bao": 5})

    # ① 排除地区
    fb = PlanFeedback(exclude_provinces=["北京"])
    out = refiner.refine(draft, draft, fb)
    assert not out["final_plan"]["chong"], "北京应被排除"
    assert out["changes"][0]["reason"].startswith("按地区排除")
    print(f"  ① 排除北京 → 冲档清空，记录 {len(out['changes'])} 条调整")

    # ② 学费上限
    fb = PlanFeedback(max_tuition=10000)
    out = refiner.refine(draft, draft, fb)
    assert not out["final_plan"]["bao"], "2.5 万学费应被排除"
    print(f"  ② 学费 >1 万 → 保档被排除（{out['changes'][0]['reason']}）")

    # ③ 偏好排序：江苏优先
    fb = PlanFeedback(prefer_provinces=["江苏"])
    out = refiner.refine(draft, draft, fb)
    assert out["final_plan"]["wen"][0]["school_province"] == "江苏"
    print("  ③ 偏好江苏 → 江苏院校排到稳档首位")

    # ④ 全部被排除 → 回退原稿，不给空表
    fb = PlanFeedback(exclude_provinces=["北京", "吉林", "江苏", "广东"])
    out = refiner.refine(draft, draft, fb)
    assert sum(len(v) for v in out["final_plan"].values()) == 4, out["final_plan"]
    assert "已保留原方案" in out["note"]
    print(f"  ④ 全部排除 → 回退原方案（{out['note'][:24]}…）")

    # ⑤ 空反馈 → 原样返回
    out = refiner.refine(draft, draft, PlanFeedback())
    assert out["final_plan"] == draft
    print("  ⑤ 空反馈 → 原稿即终稿")


# ---------------------------------------------------------------- 用例 4：图结构


def test_graph() -> None:
    """用例 4：LangGraph 图结构（节点 / 中断点 / Checkpointer）。"""
    print("用例 4：图结构")
    from app.services.agent.workflow import LANGGRAPH_AVAILABLE, build_plan_graph

    if not LANGGRAPH_AVAILABLE:
        print("  [SKIP] 未安装 langgraph")
        return

    graph = build_plan_graph()
    assert graph is not None
    nodes = set(graph.get_graph().nodes.keys())
    for name in ("analyze_intent", "generate_draft", "human_review", "refine_plan"):
        assert name in nodes, f"缺少节点 {name}：{nodes}"
    print(f"  节点：{[n for n in nodes if n not in ('__start__', '__end__')]}")
    print("  已挂 MemorySaver Checkpointer + interrupt_before=['human_review']")


# ---------------------------------------------------------------- 用例 5：HITL 闭环


def test_hitl_flow() -> None:
    """用例 5：start 暂停 → resume 恢复 → 终稿（全桩，不连库）。"""
    print("用例 5：HITL 三步闭环")
    from app.services.agent.plan_builder import (
        FeedbackInterpreter,
        PlanDraftBuilder,
        PlanRefiner,
    )
    from app.services.agent.workflow import PlanWorkflow, reset_plan_workflow

    pool = {
        "chong": [_item("北京大学", "计算机", "北京")],
        "wen": [_item("南京大学", "软件工程", "江苏"),
                _item("吉林大学", "临床医学", "吉林")],
        "bao": [_item("河南大学", "汉语言文学", "河南")],
    }
    wf = PlanWorkflow(
        draft_builder=PlanDraftBuilder(
            rank_fn=lambda s, p, c, y: 40000,
            tiers_fn=lambda r, p, c, y: pool,
            enrich_fn=lambda t, p, c, y: t,
            per_tier={"chong": 5, "wen": 5, "bao": 5},
        ),
        interpreter=FeedbackInterpreter(llm_enabled=False),
        refiner=PlanRefiner(per_tier={"chong": 5, "wen": 5, "bao": 5}),
    )
    assert wf.available, "图应可构建"

    res = wf.start(user_id=101, user_info={
        "province": "河南", "category": "物理类", "score": 600},
    )
    tid = res["thread_id"]
    assert res["draft_plan"]["wen"], res
    print(f"  ① start → thread={tid[:8]} rank={res['rank']} "
          f"初稿 {sum(len(v) for v in res['draft_plan'].values())} 条")

    st = wf.get_state(tid, 101)
    assert st["awaiting_feedback"] is True, "应停在 human_review 等待用户"
    print("  ② get_state → awaiting_feedback=True（图已暂停）")

    out = wf.resume(tid, 101, "不想去北京和吉林")
    provs = {i["school_province"] for i in out["final_plan"]["wen"]}
    assert "北京" not in {i["school_province"] for v in out["final_plan"].values() for i in v}
    assert "吉林" not in provs
    print(f"  ③ resume → 终稿 {sum(len(v) for v in out['final_plan'].values())} 条，"
          f"稳档地区={sorted(provs)}")

    st2 = wf.get_state(tid, 101)
    assert st2["awaiting_feedback"] is False
    assert st2["stage"] == "final_ready"
    print("  ④ 完成后 awaiting_feedback=False，stage=final_ready")

    # 越权
    try:
        wf.get_state(tid, 999)
        raise AssertionError("他人访问应报错")
    except PermissionError:
        print("  ⑤ 他人访问同一 thread → PermissionError（路由层转 403）")

    # 不存在的 thread
    try:
        wf.resume("not-exist", 101, "x")
        raise AssertionError("不存在的 thread 应报错")
    except LookupError:
        print("  ⑥ 不存在的 thread → LookupError（路由层转 404）")

    reset_plan_workflow()


# ---------------------------------------------------------------- 用例 6：路由


def test_routes() -> None:
    """用例 6：路由契约与入参校验。"""
    print("用例 6：路由契约")
    from pydantic import ValidationError

    from app.api.plan import plan_router
    from app.schemas.plan import PlanStartIn

    paths = {r.path for r in plan_router.router.routes}
    for p in ("/api/plan/start", "/api/plan/resume", "/api/plan/state/{thread_id}"):
        assert p in paths, f"缺少路由 {p}"
    print(f"  路由：{sorted(paths)}")

    # 分数与位次至少一个
    try:
        PlanStartIn(province="河南", category="物理类")
        raise AssertionError("应校验失败")
    except ValidationError:
        print("  缺分数/位次 → 422（model_validator）")

    ok = PlanStartIn(province="河南", category="物理类", score=600)
    assert ok.score == 600
    print("  正常入参通过")


# ---------------------------------------------------------------- 真实链路


def test_real() -> None:
    """用例 7：真实 HTTP 全流程。"""
    import time

    import requests

    base = "http://127.0.0.1:8000"
    print("用例 7：真实 HTTP")
    try:
        h = requests.get(f"{base}/api/plan/health", timeout=5).json()
    except Exception:
        print("  [SKIP] 服务未启动")
        return
    if not h.get("available"):
        print(f"  [SKIP] langgraph 不可用：{h.get('error')}")
        return
    print(f"  plan/health → {h}")

    uname = f"plan_{int(time.time())}"
    requests.post(f"{base}/api/auth/register", json={
        "username": uname, "password": "test123456", "nickname": "HITL",
        "phone": f"134{int(time.time()) % 100000000:08d}",
    }, timeout=20)
    tok = requests.post(f"{base}/api/auth/login",
                        json={"username": uname, "password": "test123456"},
                        timeout=20).json()["access_token"]
    auth = {"Authorization": f"Bearer {tok}"}

    t = time.time()
    r = requests.post(f"{base}/api/plan/start", headers=auth, json={
        "province": "河南", "category": "物理类", "score": 600,
    }, timeout=90)
    print(f"  ① start status={r.status_code} 耗时={time.time()-t:.1f}s")
    assert r.status_code == 200, r.text
    d = r.json()
    tid = d["thread_id"]
    assert d["awaiting_feedback"] is True
    assert sum(len(v) for v in d["draft_plan"].values()) > 0
    print(f"     thread={tid[:8]} rank={d['rank']} "
          f"初稿={sum(len(v) for v in d['draft_plan'].values())} 条")

    r = requests.get(f"{base}/api/plan/state/{tid}", headers=auth, timeout=30)
    assert r.json()["awaiting_feedback"] is True
    print("  ② state → awaiting_feedback=True")

    t = time.time()
    r = requests.post(f"{base}/api/plan/resume", headers=auth, json={
        "thread_id": tid, "user_feedback": "不想去北京，想学计算机，学费别太贵",
    }, timeout=120)
    print(f"  ③ resume status={r.status_code} 耗时={time.time()-t:.1f}s")
    assert r.status_code == 200, r.text
    f = r.json()
    all_provs = {i["school_province"] for v in f["final_plan"].values() for i in v}
    assert "北京" not in all_provs, f"仍含北京：{all_provs}"
    print(f"     解析={f['feedback_parsed'].get('exclude_provinces')} "
          f"调整={len(f['changes'])} 条 终稿={sum(len(v) for v in f['final_plan'].values())} 条")
    print(f"     地区={sorted(all_provs)}")

    # 越权
    uname2 = f"other_{int(time.time())}"
    requests.post(f"{base}/api/auth/register", json={
        "username": uname2, "password": "test123456", "nickname": "他人",
        "phone": f"133{int(time.time()) % 100000000:08d}",
    }, timeout=20)
    tok2 = requests.post(f"{base}/api/auth/login",
                         json={"username": uname2, "password": "test123456"},
                         timeout=20).json()["access_token"]
    r = requests.get(f"{base}/api/plan/state/{tid}",
                     headers={"Authorization": f"Bearer {tok2}"}, timeout=30)
    print(f"  ④ 他人访问 status={r.status_code}（应 403）")
    assert r.status_code == 403

    # 未登录
    r = requests.post(f"{base}/api/plan/start", json={
        "province": "河南", "category": "物理类", "score": 600}, timeout=30)
    print(f"  ⑤ 未登录 status={r.status_code}（应 401）")


def main() -> int:
    test_interpreter()
    print()
    test_draft_builder()
    print()
    test_refiner()
    print()
    test_graph()
    print()
    test_hitl_flow()
    print()
    test_routes()
    print()
    if "--real" in sys.argv:
        test_real()
        print()
    else:
        print("[提示] 加 --real 跑真实 HTTP（需服务已启动）")
        print()
    print("=" * 72)
    print("0.14.0 桩版全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
