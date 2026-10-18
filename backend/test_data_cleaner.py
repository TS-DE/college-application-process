# -*- coding: utf-8 -*-
"""0.11.2 数据提纯（data_cleaner）最小测试用例。

用法：
    python test_data_cleaner.py           # 桩版：纯正则单测，不连库
    python test_data_cleaner.py --real    # 真实链路：连库验证广西/四川/北京等省

覆盖：
    1. extract_tuition / extract_duration 的正则边界（真实 note 样本）
    2. clean_item：缺字段补全 + 「列错位」修复（四川 duration 里装学费）
    3. 真实链路：各省招生计划索引的学费/学制填充率
    4. 真实链路：推荐接口返回的 tuition 是整数且 0 表示免学费
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.utils.data_cleaner import clean_item, extract_duration, extract_tuition

# (note, 期望学费, 期望学制) —— 全部取自 2025 总表的真实文本
NOTE_CASES = [
    # ---- 广西：`(4年,5000元/年,...)` ----
    ("(4年,5000元/年,要求外语语种为英语)", 5000, "4年"),
    ("(4年,5000元/年)", 5000, "4年"),
    ("[4年,6000元/年,包含专业:西班牙语(欧洲研究)、法语(法国研究)]", 6000, "4年"),
    ("(国家公费师范生,师范类,4年,免费,在北京校区办学)", 0, "4年"),
    # ---- 安徽：`(6000元/年;...)` ----
    ("(6000元/年;报名参加综合评价招生的考生,须参加北外组织的测试)", 6000, None),
    ("(6000元/年；报名参加综合评价招生)", 6000, None),
    # ---- 万 单位 ----
    ("（中外合作办学）（学费9.5万元/年；外语单科高考成绩不得低于110分）", 95000, None),
    # ---- 暂定 / 约 / 多段 ----
    ("（学费暂定49000元/年，最终以发改委批复为准；大庆校区）", 49000, None),
    ("（国内学费6480元/年，第四、五学年须赴昆士兰大学学习，学费约53000澳元/年）", 6480, None),
    # ---- 免收学费 ----
    ("(航空飞行与指挥)(免收学费,只招男生,只招英语、俄语考生)", 0, None),
    ("(师范)(免收学费，加试体育)", 0, None),
    # ---- 学制边界：不能把「第1~3年」「第4年」「2025年」当学制 ----
    ("（第1~3年在本校学习（学费68000元/年），第4年在美国学习）", 68000, None),
    ("(学制4年)", None, "4年"),
    ("(3年制)", None, "3年"),
    ("(2025年招生)", None, None),
    # ---- 无信息 ----
    ("（师范类）（师范类）", None, None),
    ("（办学地点：龙湖东校区）", None, None),
    ("", None, None),
    (None, None, None),
]

# clean_item 的「列错位」用例：(输入 dict, 期望 tuition, 期望 duration)
SHIFT_CASES = [
    # 四川：duration 列里装的是学费
    ({"duration": "5000", "tuition": None, "major_note": ""}, 5000, None),
    ({"duration": "5500年", "tuition": None, "major_note": ""}, 5500, None),
    ({"duration": "免费", "tuition": None, "major_note": ""}, 0, None),
    # 广西：真实的 9 年制不能被当成学费（关键回归点）
    ({"duration": "9年", "tuition": None, "major_note": ""}, None, "9年"),
    ({"duration": "4", "tuition": None, "major_note": ""}, None, "4年"),
    # 正常省份：已有学费不动，只补学制
    ({"duration": None, "tuition": 6000, "major_note": "(4年,5000元/年)"}, 6000, "4年"),
    # 金额整数化：Decimal / float → int
    ({"duration": "4年", "tuition": 5500.0, "major_note": ""}, 5500, "4年"),
]


def test_regex() -> None:
    """用例 1：正则提取的单测。"""
    print("用例 1：extract_tuition / extract_duration")
    ok = fail = 0
    for note, want_t, want_d in NOTE_CASES:
        got_t = extract_tuition(note)
        got_d = extract_duration(note)
        if (got_t, got_d) == (want_t, want_d):
            ok += 1
        else:
            fail += 1
            print(f"  [FAIL] note={(note or '<None>')[:50]!r} "
                  f"期望({want_t},{want_d}) 实际({got_t},{got_d})")
    print(f"  {ok} 通过 / {fail} 失败")
    assert fail == 0, "正则提取用例存在失败"


def test_clean_item() -> None:
    """用例 2：clean_item 的补全与列错位修复。"""
    print("用例 2：clean_item 补全 / 列错位修复")
    ok = fail = 0
    for src, want_t, want_d in SHIFT_CASES:
        item = dict(src)
        clean_item(item)
        if (item.get("tuition"), item.get("duration")) == (want_t, want_d):
            ok += 1
        else:
            fail += 1
            print(f"  [FAIL] 输入={src} 期望({want_t},{want_d}) "
                  f"实际({item.get('tuition')},{item.get('duration')})")
    print(f"  {ok} 通过 / {fail} 失败")
    assert fail == 0, "clean_item 用例存在失败"


def test_real() -> None:
    """用例 3 + 4：真实库验证各省填充率与接口返回。"""
    from app.services.rank_service import score_to_rank
    from app.services.recommend_service import _plan_index, calculate_tiers, enrich_with_plan

    print("用例 3：各省招生计划索引填充率（提纯前后对比的关键指标）")
    expect = {
        # 省份: (最低学费填充率, 最低学制填充率) —— 提纯前广西/四川/安徽均为 0
        ("广西", "物理类"): (0.80, 0.80),
        ("四川", "物理类"): (0.70, 0.0),   # 四川无学制信息
        ("安徽", "物理类"): (0.70, 0.0),   # 安徽无学制信息
        ("河南", "物理类"): (0.80, 0.80),  # 原始数据完整，不能被改坏
    }
    for (prov, cat), (min_t, min_d) in expect.items():
        idx = _plan_index(prov, 2025, cat, "本科批")
        infos = list(idx["name"].values())
        if not infos:
            print(f"  [SKIP] {prov} 索引为空")
            continue
        t_ratio = sum(1 for i in infos if i.get("tuition") not in (None, "")) / len(infos)
        d_ratio = sum(1 for i in infos if i.get("duration")) / len(infos)
        print(f"  {prov}: 索引 {len(infos)} 条 | 学费 {t_ratio:.0%} | 学制 {d_ratio:.0%}")
        assert t_ratio >= min_t, f"{prov} 学费填充率 {t_ratio:.0%} 低于预期 {min_t:.0%}"
        assert d_ratio >= min_d, f"{prov} 学制填充率 {d_ratio:.0%} 低于预期 {min_d:.0%}"

    print("用例 4：推荐结果的 tuition 必须是整数，0 表示免学费")
    for prov, cat in (("广西", "物理类"), ("四川", "物理类"), ("河南", "物理类")):
        rank = score_to_rank(600, prov, cat)
        if not rank:
            print(f"  [SKIP] {prov} 位次为 0")
            continue
        tiers = enrich_with_plan(calculate_tiers(rank, prov, cat), prov, cat)
        items = [it for v in tiers.values() for it in v]
        filled = [it for it in items if it.get("tuition") not in (None, "")]
        bad = [it["tuition"] for it in items
               if isinstance(it.get("tuition"), float) and not float(it["tuition"]).is_integer()]
        print(f"  {prov}: 条目 {len(items)} | 有学费 {len(filled)} | 非整数学费 {len(bad)}")
        assert not bad, f"{prov} 存在非整数学费：{bad[:5]}"
        # 学费要么是 None，要么是合理整数（0 或 >=100）
        for it in items:
            t = it.get("tuition")
            if t is None:
                continue
            assert isinstance(t, int), f"{prov} 学费类型应为 int，实际 {type(t)}"
            assert t == 0 or t >= 100, f"{prov} 学费值异常：{t}"


def main() -> int:
    test_regex()
    print()
    test_clean_item()
    print()
    if "--real" in sys.argv:
        test_real()
        print()
    else:
        print("[提示] 加 --real 跑真实库验证")
        print()
    print("=" * 70)
    print("0.11.2 数据提纯用例全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
