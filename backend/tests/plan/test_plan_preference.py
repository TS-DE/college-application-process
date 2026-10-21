# -*- coding: utf-8 -*-
"""0.19.0 验收：偏好硬过滤 + 双源合并 + 极性修正 + 多轮上限。

覆盖 E1/E2/E5/E6 的**确定性**部分（不依赖真实院校库）：
  E1 偏好省份必须出现在三档里
  E2 「去福建上学」不得被判成排除
  E5 用户显式偏好压过画像推断
  E6 达到轮次上限后自动结束

用法：python tests/plan/test_plan_preference.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

RESULTS = []


def check(name: str, cond: bool, extra: str = "") -> None:
    RESULTS.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {extra}" if extra else ""))


def _item(univ: str, major: str, prov: str, tuition: int = 5000) -> dict:
    return {
        "university_name": univ,
        "major_name": major,
        "school_province": prov,
        "tuition": tuition,
        "probability": 0.5,
    }


def test_polarity() -> None:
    print("E2：极性修正")
    from app.services.agent.plan_builder import FeedbackInterpreter

    i = FeedbackInterpreter(llm_enabled=False)
    fb = i.interpret("去福建上学")
    check("「去福建上学」→ 偏好福建", fb.prefer_provinces == ["福建"], str(fb.to_dict()))
    check("「去福建上学」不排除福建", "福建" not in fb.exclude_provinces)

    fb2 = i.interpret("我想去福建上学")
    check("「我想去福建上学」→ 偏好福建", fb2.prefer_provinces == ["福建"])

    fb3 = i.interpret("不想去北京")
    check("「不想去北京」→ 仍为排除（否定词优先）", "北京" in fb3.exclude_provinces)

    fb4 = i.interpret("北京的不想去")
    check("「北京的不想去」→ 排除（否定词优先）", "北京" in fb4.exclude_provinces)

    fb5 = i.interpret("太冷了")
    check("「太冷了」→ 语义展开排除", len(fb5.exclude_provinces) >= 5)


def test_merge_priority() -> None:
    print("\nE5：用户显式偏好压过画像")
    from app.services.agent.plan_builder import PlanFeedback, PreferenceSource

    merged = PreferenceSource(
        user_explicit=PlanFeedback(prefer_provinces=["福建"]),
        from_profile=PlanFeedback(prefer_provinces=["江苏", "浙江", "上海"]),
    ).merge()
    check("冲突时只保留用户的福建", merged.prefer_provinces == ["福建"],
          str(merged.prefer_provinces))

    merged2 = PreferenceSource(
        user_explicit=PlanFeedback(),
        from_profile=PlanFeedback(prefer_provinces=["江苏"]),
    ).merge()
    check("用户没表态 → 画像补空缺", merged2.prefer_provinces == ["江苏"])

    merged3 = PreferenceSource(
        user_explicit=PlanFeedback(prefer_provinces=["福建"]),
        from_profile=PlanFeedback(exclude_provinces=["福建", "吉林"]),
    ).merge()
    check("用户想去的省不被画像的排除压掉", "福建" not in merged3.exclude_provinces)
    check("画像的其它排除仍然生效", "吉林" in merged3.exclude_provinces)


def test_hard_filter() -> None:
    print("\nE1：偏好硬过滤（候选池里福建排在很后面也要选出来）")
    from app.services.agent.plan_builder import PlanFeedback, PlanRefiner

    # 每档 8 条，福建排在第 7 位 —— 「只加 2 分排序」时永远进不了前 4
    pool = {
        "chong": [_item(f"冲{i}大学", "计算机", "河南") for i in range(1, 7)]
        + [_item("厦门大学", "计算机", "福建"), _item("福州大学", "软件工程", "福建")],
        "wen": [_item(f"稳{i}大学", "计算机", "河南") for i in range(1, 7)]
        + [_item("华侨大学", "计算机", "福建"), _item("集美大学", "计算机", "福建")],
        "bao": [_item(f"保{i}大学", "计算机", "河南") for i in range(1, 7)]
        + [_item("闽江学院", "计算机", "福建"), _item("福建工程学院", "计算机", "福建")],
    }
    refiner = PlanRefiner(per_tier={"chong": 4, "wen": 4, "bao": 4})
    built = refiner.build_with_preference(
        pool, pool, PlanFeedback(prefer_provinces=["福建"]),
        per_tier={"chong": 4, "wen": 4, "bao": 4},
    )
    provinces = {i["school_province"] for v in built["final_plan"].values() for i in v}
    check("三档里都出现了福建院校", "福建" in provinces, str(sorted(provinces)))
    for tier in ("chong", "wen", "bao"):
        got = [i["school_province"] for i in built["final_plan"][tier]]
        check(f"{tier} 档优先放福建", got[0] == "福建", str(got))
    check("每档仍补足到 4 条", all(len(v) == 4 for v in built["final_plan"].values()),
          str({k: len(v) for k, v in built["final_plan"].items()}))


def test_missing_preference_note() -> None:
    print("\nE1-兜底：候选池没有福建时必须明说")
    from app.services.agent.plan_builder import PlanFeedback, PlanRefiner

    pool = {
        "chong": [_item("郑州大学", "计算机", "河南")],
        "wen": [_item("河南大学", "计算机", "河南")],
        "bao": [_item("河南师范大学", "计算机", "河南")],
    }
    built = PlanRefiner(per_tier={"chong": 3, "wen": 3, "bao": 3}).build_with_preference(
        pool, pool, PlanFeedback(prefer_provinces=["福建"]),
        per_tier={"chong": 3, "wen": 3, "bao": 3},
    )
    note = built["note"]
    check("note 写明「候选池中没有位于福建的院校」",
          "候选池中没有位于福建的院校" in note, note)
    check("note 给出放宽建议", "放宽" in note, note)


def test_round_limit() -> None:
    print("\nE6：多轮上限")
    from app.config import settings
    from app.services.agent.plan_builder import (
        FeedbackInterpreter,
        PlanDraftBuilder,
        PlanRefiner,
    )
    from app.services.agent.workflow import LANGGRAPH_AVAILABLE, PlanWorkflow, reset_plan_workflow

    if not LANGGRAPH_AVAILABLE:
        print("  [SKIP] 未安装 langgraph")
        return

    pool = {
        "chong": [_item("厦门大学", "计算机", "福建")],
        "wen": [_item("福州大学", "计算机", "福建")],
        "bao": [_item("闽江学院", "计算机", "福建")],
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
    res = wf.start(user_id=203, user_info={
        "province": "河南", "category": "物理类", "score": 600,
        "preferences": "我想去福建上学",
    })
    tid = res["thread_id"]
    check("初稿第 1 版就有福建", res["review_round"] == 1, f"round={res['review_round']}")

    ended_at = None
    for i in range(1, 8):
        out = wf.resume(tid, 203, {"feedback": "只保留福建的", "action": "revise"})
        if not out["awaiting_feedback"]:
            ended_at = out["review_round"]
            break
    max_rounds = int(settings.PLAN_MAX_REVIEW_ROUNDS)
    check(f"在 {max_rounds} 轮上限处自动结束", ended_at == max_rounds, f"ended_at={ended_at}")
    reset_plan_workflow()


def main() -> int:
    print("=" * 72)
    test_polarity()
    test_merge_priority()
    test_hard_filter()
    test_missing_preference_note()
    test_round_limit()
    print("=" * 72)
    failed = [n for n, ok in RESULTS if not ok]
    print(f"共 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项")
    for n in failed:
        print("  FAIL:", n)
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
