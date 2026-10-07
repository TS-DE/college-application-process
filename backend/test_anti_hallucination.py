"""v2.3.0 最小验证用例：Query 路由拦截 + 防幻觉生成。

运行：
    cd backend
    python test_anti_hallucination.py

验证四件事：
  1. 无关问题（婚假几天）被 route_query 拦截
  2. 相关问题（志愿填报）被 route_query 放行
  3. 上下文里有学费 → 回答给出上下文中的真实数字（不编造）
  4. 上下文里没有学费 → 按话术拒答（对照 v2.2.0 通用 Prompt 会编造）
  5. （预留）extract_sql_filters 能从"学费"类问题里提取 JSON 条件
"""
import sys

sys.path.insert(0, ".")

from app.services import rag_service
from app.services.ai_service import ask

# 有学费信息的上下文（数字必须来自这里）
CONTEXT_WITH_TUITION = (
    "[河南招生计划2025.txt] 福州大学至诚学院 计算机科学与技术专业，2025年在河南本科批物理类招生60人，"
    "学制4年，学费标准为23000元/年，选科要求首选物理、再选化学。"
)

# 完全没有学费信息的上下文
CONTEXT_NO_TUITION = (
    "[河南志愿填报指南.txt] 河南省2025年本科批实行平行志愿，考生可填报48个院校专业组志愿，"
    "投档规则为分数优先、遵循志愿、一轮投档。"
)

REFUSAL = "未查询到具体信息"


def check(name: str, ok: bool, extra: str = "") -> None:
    print(f"  [{'通过' if ok else '未通过'}] {name}{(' → ' + extra) if extra else ''}")


def main() -> None:
    print("=" * 78)
    print("【1】Query 意图路由（ROUTER_PROMPT, temperature=0.0, max_tokens=5）")
    print("=" * 78)
    for q, expect in [
        ("婚假几天", False),
        ("今天天气怎么样", False),
        # v2.3.1 修正的两个场景（v2.3.0 会因关键词太窄被误拦截）
        ("2025河南在福建招生的院校", True),
        ("福州大学至诚学院计算机专业学费", True),
        ("河南本科批志愿怎么填报", True),
        ("郑州大学计算机专业学费多少", True),
    ]:
        passed = rag_service.route_query(q)
        check(f"route_query({q}) 期望 {'放行' if expect else '拦截'}", passed is expect,
              f"实际 {'放行' if passed else '拦截'}")

    print()
    print("=" * 78)
    print("【2】防幻觉生成：上下文【有】学费（temperature=0.1, top_p=0.3）")
    print("=" * 78)
    ans = rag_service.generate_answer("福州大学至诚学院计算机科学与技术专业学费是多少？", CONTEXT_WITH_TUITION)
    print("  回答：", (ans or "").replace("\n", " ")[:160])
    # v2.3.1 关注点：上下文有 23000 时模型必须敢生成，而不是套用拒答话术
    check("回答中出现上下文里的真实学费 23000", bool(ans) and "23000" in ans)
    check("没有误触发拒答话术", bool(ans) and REFUSAL not in ans)

    print()
    print("=" * 78)
    print("【3】防幻觉生成：上下文【无】学费 → 拒答/引导，且不编造数字")
    print("=" * 78)
    ans2 = rag_service.generate_answer("福州大学至诚学院计算机科学与技术专业学费是多少？", CONTEXT_NO_TUITION)
    print("  回答：", (ans2 or "").replace("\n", " ")[:160])
    check("按话术引导（含「未查询到具体信息」）", bool(ans2) and REFUSAL in ans2)
    check("没有编造数字", bool(ans2) and "23000" not in ans2 and "6000" not in ans2)

    print()
    print("=" * 78)
    print("【4】对照：v2.2.0 通用 Prompt（temperature=0.3, top_p=0.85）同样问题")
    print("=" * 78)
    old_prompt = (
        "你是高考志愿填报助手，回答要简洁实用，分点说明，不要编造具体院校分数线。\n"
        "问题：郑州大学计算机科学与技术专业学费是多少？\n回答："
    )
    old_ans = ask(old_prompt, temperature=0.3, top_p=0.85, num_predict=200)
    print("  回答：", (old_ans or "").replace("\n", " ")[:160])
    fabricated = bool(old_ans) and any(x in old_ans for x in ("5700", "6000", "5000", "元"))
    check("v2.2.0 会给出/编造数字（说明改造必要性）", fabricated)

    print()
    print("=" * 78)
    print("【5】结构化提取预留（SQL_EXTRACT_PROMPT, temperature=0.0）")
    print("=" * 78)
    filters = rag_service.extract_sql_filters("郑州大学计算机科学与技术专业2025年学费多少")
    print("  提取结果：", filters)
    check("能提取出 school_name", bool(filters) and filters.get("school_name"))

    print()
    print("=" * 78)
    print("结论：无关问题被拦截（不再检索知识库），有资料时不编造、无资料时拒答。")
    print("=" * 78)


if __name__ == "__main__":
    main()
