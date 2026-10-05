"""接口冒烟测试：先把后端跑起来（python main.py），再执行 python smoke_test.py。

覆盖：健康检查、维度选项、分数转位次、位次转分数、冲稳保推荐、
查大学、查专业、AI 意图解析、AI 推荐理由。
"""
import json
import time

import requests

BASE = "http://127.0.0.1:8000"
PROVINCE = "河南"


def get(path: str, **params):
    t = time.time()
    r = requests.get(BASE + path, params=params, timeout=60)
    return r, time.time() - t


def post(path: str, payload: dict):
    t = time.time()
    r = requests.post(BASE + path, json=payload, timeout=180)
    return r, time.time() - t


def show(title: str, resp: requests.Response, cost: float, limit: int = 300) -> dict:
    ok = 200 <= resp.status_code < 300
    print(f"\n[{title}] status={resp.status_code} {cost:.2f}s")
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        print("  非 JSON 响应：", resp.text[:limit])
        return {}
    text = json.dumps(data, ensure_ascii=False)
    print("  " + (text[:limit] + (" ..." if len(text) > limit else "")))
    if not ok:
        print("  !! 请求失败")
    return data if isinstance(data, dict) else {}


def main() -> None:
    show("健康检查", *get("/api/health"))
    show("维度选项", *get("/api/meta/options", province=PROVINCE))
    show("AI 状态", *get("/api/ai/status"))

    rank_info = show(
        "分数转位次 611/物理类/本科批",
        *get("/api/score-to-rank", province=PROVINCE, year=2025,
             category="物理类", batch="本科批", score=611),
    )
    rank = rank_info.get("rank") or 34569

    show("位次转分数", *get("/api/rank-to-score", province=PROVINCE, year=2025,
                           category="物理类", batch="本科批", rank=rank))

    show("考生档案", *post("/api/student/profile", {
        "province": PROVINCE, "year": 2025, "category": "物理类",
        "batch": "本科批", "score": 611,
    }))

    rec = show("推荐（不带 AI）", *post("/api/recommend", {
        "province": PROVINCE, "year": 2025, "category": "物理类",
        "batch": "本科批", "score": 611, "limit": 6,
    }))
    for tier in ("chong", "wen", "bao"):
        items = rec.get(tier, [])
        print(f"  {tier}: {len(items)} 条", end="")
        if items:
            it = items[0]
            print(f" | 示例：{it.get('university_name')} {it.get('major_name')} "
                  f"位次 {it.get('min_rank')} 概率 {it.get('probability')}%")
        else:
            print()

    show("推荐（带筛选：计算机 + 学费<=6000）", *post("/api/recommend", {
        "province": PROVINCE, "year": 2025, "category": "物理类",
        "batch": "本科批", "rank": rank, "limit": 3,
        "filters": {"major_keyword": "计算机", "tuition_max": 6000},
    }))

    show("查大学", *get("/api/universities", province=PROVINCE, year=2025,
                       category="物理类", batch="本科批", rank=rank, page_size=3))
    show("查专业（郑州大学）", *get("/api/majors", province=PROVINCE, year=2025,
                                 category="物理类", batch="本科批",
                                 university_name="郑州大学", page_size=3))
    show("省份分布", *get("/api/meta/province-stats", province=PROVINCE))
    show("热门院校", *get("/api/meta/hot-schools", province=PROVINCE, limit=3))

    show("AI 意图解析", *post("/api/ai/parse-intent", {
        "text": "我想找个离家近、计算机强、学费便宜的学校", "province": PROVINCE,
    }))
    show("AI 推荐理由", *post("/api/ai/recommend-reason", {
        "university_name": "郑州大学", "major_name": "计算机科学与技术",
        "min_rank": 34569, "min_score": 611, "student_rank": 34418,
        "tier": "wen", "school_province": "河南", "tuition": 5700,
    }))
    print("\n冒烟测试结束。")


if __name__ == "__main__":
    main()
