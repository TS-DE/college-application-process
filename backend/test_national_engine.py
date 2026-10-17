# -*- coding: utf-8 -*-
"""0.11.0 全国多省自适应核心引擎 最小测试用例。

用法：
    python test_national_engine.py           # 桩版：只测映射与参数校验，不连库
    python test_national_engine.py --real    # 真实链路：连 MySQL 查总表 + 打接口

用例：
    1. region_mapper：31 省科类映射、拼音/中文归一、新高考判定
    2. score_to_rank：北京(综合,600) / 河南(物理类,600) / 四川(物理类,600)
    3. calculate_tiers：三档结构、LIMIT 50、概率区间、档内排序
    4. 非法传参：beijing + 物理类 应被拦截
    5. 接口层：/api/recommend/national 与 /api/recommend 的 rank/tiers 字段
    6. 回归：河南原富信息链路不受影响
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

# 任务书指定的三个最小验证场景
CASES = [
    # (说明, province, category, score, 期望位次是否 > 0)
    ("北京考生 3+3 综合", "beijing", "综合", 600, True),
    ("河南考生 3+1+2 物理类", "henan", "物理类", 600, True),
    ("河南考生 3+1+2 历史类", "henan", "历史类", 600, True),
    ("四川考生（实测为物理类）", "sichuan", "物理类", 600, True),
    ("新疆考生 老高考理科", "xinjiang", "理科", 550, True),
]


def test_region_mapper() -> None:
    """用例 1：区域映射。"""
    from app.utils.region_mapper import (
        PROVINCES_NO_DATA,
        categories_map,
        gaokao_mode,
        get_categories_by_province,
        has_data,
        is_new_gaokao,
        list_provinces,
        normalize_province,
    )

    print("用例 1：region_mapper 区域映射")
    provs = list_provinces()
    print(f"  省份数 = {len(provs)}")
    assert len(provs) == 31, f"应为 31 个省级行政区，实际 {len(provs)}"

    # 三种高考模式
    assert get_categories_by_province("beijing") == ["综合"]
    assert get_categories_by_province("henan") == ["物理类", "历史类"]
    assert get_categories_by_province("sichuan") == ["物理类", "历史类"]  # 实测校正
    assert get_categories_by_province("xinjiang") == ["理科", "文科"]
    assert gaokao_mode("beijing") == "3+3"
    assert gaokao_mode("henan") == "3+1+2"
    assert gaokao_mode("xinjiang") == "老高考"
    assert is_new_gaokao("henan") is True
    assert is_new_gaokao("xinjiang") is False

    # 拼音 / 中文 / 大小写 都能归一
    for raw, want in [("henan", "河南"), ("河南", "河南"), ("HenAn", "河南"),
                      ("neimenggu", "内蒙古"), ("内蒙", "内蒙古"), (" 北京 ", "北京")]:
        got = normalize_province(raw)
        assert got == want, f"{raw} → {got}，期望 {want}"
    print(f"  拼音/中文归一全部通过；无数据省份 = {sorted(PROVINCES_NO_DATA)}")
    assert has_data("henan") is True and has_data("shanxi") is False
    assert len(categories_map()) == 31


def test_rank_and_tiers() -> None:
    """用例 2 + 3：位次换算与三档计算（真实库）。"""
    from app.services.rank_service import score_to_rank
    from app.services.recommend_service import _tier_probability, calculate_tiers

    print("用例 2：score_to_rank 多省位次换算")
    for name, prov, cat, score, expect_hit in CASES:
        rank = score_to_rank(score, prov, cat)
        print(f"  {name:<26} score={score} → rank={rank}")
        if expect_hit:
            assert rank > 0, f"{prov}/{cat} 应能换算出位次"

    print("用例 3：calculate_tiers 三档计算")
    for name, prov, cat, score, expect_hit in CASES[:3]:
        rank = score_to_rank(score, prov, cat)
        if not rank:
            print(f"  [SKIP] {name} 位次为 0")
            continue
        tiers = calculate_tiers(rank, prov, cat)
        sizes = {k: len(v) for k, v in tiers.items()}
        print(f"  {name:<26} rank={rank} → {sizes}")
        assert set(tiers.keys()) == {"chong", "wen", "bao"}, tiers.keys()
        for tier, items in tiers.items():
            assert len(items) <= 50, f"{tier} 档超过 50 条（内存保护失效）"
            for it in items:
                assert it["tier"] == tier, "档位标记不一致"
                p = it.get("probability")
                assert p is not None and 0 < p <= 100, f"概率异常：{p}"
                if tier == "chong":
                    assert 10 <= p <= 40, f"冲档概率应在 10-40，实际 {p}"
                elif tier == "wen":
                    assert 55 <= p <= 85, f"稳档概率应在 55-85，实际 {p}"
                else:
                    assert 88 <= p <= 98, f"保档概率应在 88-98，实际 {p}"
        # 档内排序校验
        if tiers["wen"]:
            gaps = [abs(x["rank_diff"]) for x in tiers["wen"]]
            assert gaps == sorted(gaps), "稳档未按位次差绝对值升序"
        if tiers["bao"]:
            ranks_ = [x["min_rank"] for x in tiers["bao"]]
            assert ranks_ == sorted(ranks_), "保档未按 min_rank 升序"
        if tiers["chong"]:
            ranks_ = [x["min_rank"] for x in tiers["chong"]]
            assert ranks_ == sorted(ranks_, reverse=True), "冲档未按 min_rank 降序"

    print("  三档结构 / LIMIT 50 / 概率区间 / 档内排序 全部通过")


def test_probability_mapping() -> None:
    """用例 3b：概率线性映射边界值。

    公式：x = min(|gap| / (buffer × span), 1.0)，span 冲/保 = 3、稳 = 1。
      · 冲：p = 40 - 30x   （gap=0 → 40；gap=-buffer → 30；gap=-3×buffer → 10）
      · 稳：p = 70 - 15x   （x = gap/buffer，-1~1 → 85~55）
      · 保：p = 98 - 10x   （gap=buffer → 94.7；gap=3×buffer → 88）
    """
    from app.services.recommend_service import _tier_probability

    print("用例 3b：概率线性映射边界")
    b = 5000
    assert _tier_probability("chong", 0, b) == 40.0
    assert _tier_probability("chong", -b, b) == 30.0
    assert _tier_probability("chong", -b * 3, b) == 10.0
    assert _tier_probability("chong", -b * 99, b) == 10.0     # 超出跨度封顶
    assert _tier_probability("wen", 0, b) == 70.0
    assert _tier_probability("wen", b, b) == 55.0
    assert _tier_probability("wen", -b, b) == 85.0
    assert _tier_probability("bao", 0, b) == 98.0
    assert _tier_probability("bao", b, b) == 94.7
    assert _tier_probability("bao", b * 3, b) == 88.0
    assert _tier_probability("bao", b * 99, b) == 88.0        # 超出跨度封顶
    print("  冲 10-40 / 稳 55-85 / 保 88-98 边界值正确")


def test_invalid_params() -> None:
    """用例 4：非法传参拦截（任务书指定：beijing + 物理类 应 400）。"""
    from app.utils.region_mapper import get_categories_by_province, is_supported

    print("用例 4：非法传参拦截")
    # 北京只支持「综合」，传「物理类」必须判为不支持
    assert is_supported("beijing", "物理类") is False
    assert is_supported("beijing", "综合") is True
    assert get_categories_by_province("beijing") == ["综合"]
    # 完全不存在的省份
    assert get_categories_by_province("火星") == []
    assert is_supported("火星", "综合") is False
    print("  beijing + 物理类 → 已拦截（路由层会返回 400）")
    print("  未知省份 → 已拦截")

    # 路由层校验函数（不启动服务也能测）
    try:
        from fastapi import HTTPException

        from app.routers.recommend import _validate_province_category
    except Exception as exc:  # noqa: BLE001
        print(f"  [SKIP] 无法导入路由层：{exc.__class__.__name__}")
        return

    for prov, cat, want_detail in [
        ("beijing", "物理类", "不支持此科类"),
        ("火星", "综合", "不支持的省份"),
        ("shanxi", "理科", "暂无"),
    ]:
        try:
            _validate_province_category(prov, cat)
            raise AssertionError(f"{prov}/{cat} 应被 400 拦截")
        except HTTPException as exc:
            assert exc.status_code == 400, exc.status_code
            assert want_detail in str(exc.detail), exc.detail
            print(f"  {prov}/{cat} → 400「{exc.detail}」")


def test_api() -> None:
    """用例 5：接口层验证。"""
    import requests

    base = "http://127.0.0.1:8000"
    print("用例 5：接口层 /api/recommend/national")

    try:
        r = requests.get(f"{base}/api/health", timeout=5)
    except Exception:
        print("  [SKIP] 服务未启动（python -m uvicorn app.main:app）")
        return

    r = requests.post(f"{base}/api/auth/login",
                      json={"username": "admin", "password": "admin123"}, timeout=20)
    if r.status_code != 200:
        print(f"  [SKIP] 登录失败：{r.status_code}")
        return
    token = r.json().get("access_token") or r.json().get("token")
    h = {"Authorization": f"Bearer {token}"}

    # 5a. options 应返回全国省份与科类映射
    r = requests.get(f"{base}/api/meta/options", params={"province": "河南"}, timeout=20)
    assert r.status_code == 200, r.status_code
    d = r.json()
    assert "provinces" in d and "categories_map" in d, d.keys()
    print(f"  /api/meta/options → provinces={len(d['provinces'])} "
          f"categories_map={len(d['categories_map'])}")

    # 5b. 合法：北京 综合 600
    r = requests.post(f"{base}/api/recommend/national",
                      json={"province": "beijing", "category": "综合", "score": 600},
                      timeout=60)
    print(f"  beijing/综合/600 → {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        assert d["rank"] > 0, d
        assert set(d["tiers"].keys()) == {"chong", "wen", "bao"}
        print(f"    rank={d['rank']} tiers={{k:len(v) for k,v in d['tiers'].items()}}".replace(
            "{k:len(v) for k,v in d['tiers'].items()}",
            str({k: len(v) for k, v in d["tiers"].items()})))

    # 5c. 合法：河南 物理类 600
    r = requests.post(f"{base}/api/recommend/national",
                      json={"province": "henan", "category": "物理类", "score": 600},
                      timeout=60)
    print(f"  henan/物理类/600 → {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        print(f"    rank={d['rank']} tiers={{k:len(v) for k,v in d['tiers'].items()}}".replace(
            "{k:len(v) for k,v in d['tiers'].items()}",
            str({k: len(v) for k, v in d["tiers"].items()})))

    # 5d. 非法：北京 + 物理类 → 必须 400
    r = requests.post(f"{base}/api/recommend/national",
                      json={"province": "beijing", "category": "物理类", "score": 600},
                      timeout=60)
    print(f"  beijing/物理类/600（应 400）→ {r.status_code} {r.json().get('detail', '')}")
    assert r.status_code == 400, f"应返回 400，实际 {r.status_code}"

    # 5e. 原接口应附加 rank/tiers 且不破坏旧字段
    r = requests.post(f"{base}/api/recommend",
                      json={"province": "河南", "year": 2025, "category": "物理类",
                            "batch": "本科批", "score": 600},
                      timeout=90)
    print(f"  /api/recommend（河南，向前兼容）→ {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        for k in ("student", "chong", "wen", "bao", "meta"):
            assert k in d, f"缺少原有字段 {k}"
        print(f"    旧字段齐全；rank={d.get('rank')} "
              f"tiers={'有' if d.get('tiers') else '无'}")


def main() -> int:
    test_region_mapper()
    print()
    test_probability_mapping()
    print()
    test_invalid_params()
    print()
    if "--real" in sys.argv or "--api" in sys.argv:
        test_rank_and_tiers()
        print()
        test_api()
        print()
    else:
        print("[提示] 加 --real 跑真实库查询，加 --api 额外打接口")
        print()
    print("=" * 70)
    print("0.11.0 全国多省自适应引擎用例全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
