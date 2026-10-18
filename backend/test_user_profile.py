# -*- coding: utf-8 -*-
"""0.12.0 账号体系 + 用户画像（双轨制）最小测试用例。

用法：
    python test_user_profile.py           # 桩版：不连库、不调大模型
    python test_user_profile.py --real    # 真实链路：连 MySQL + 打 HTTP 接口

覆盖：
    1. LLMJsonParser：脏文本（think 块 / 代码围栏 / 尾逗号 / 全角引号）
    2. ReportExtractor / SurveyExtractor：JSON → 结构化特征的归一化
    3. 问卷生成器的内置题库兜底（LLM 不可用时仍有题）
    4. ProfileSummarizer 的规则兜底（LLM 空输出仍产出画像）
    5. ProfileService 全流程（InMemory 仓储）：资料 → 问卷 → 汇总
    6. --real：注册 / 资料 / 报告解析 / 问卷 / 画像注入 端到端
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.services.profile import (
    InMemoryProfileRepository,
    LLMJsonParser,
    ProfileService,
    ProfileSummarizer,
    ReportExtractor,
    SurveyExtractor,
    SurveyQuestionGenerator,
)

# ---------------------------------------------------------------- 桩 LLM


def stub_llm(prompt: str, temperature: float = 0.0, num_predict: int = 800) -> str:
    """按 Prompt 特征返回固定答案，模拟大模型输出。"""
    if "问卷设计专家" in prompt:
        return """```json
[
  {"id": "region", "title": "你希望就读的院校在哪个范围？", "type": "single",
   "options": [{"value": "local", "label": "本省"}, {"value": "any", "label": "全国都行"}],
   "hint": "地域影响可选院校数量"},
  {"id": "tuition", "title": "能接受的学费范围？", "type": "single",
   "options": [{"value": "low", "label": "5000 以内"}, {"value": "high", "label": "1 万以上"}],
   "hint": null},
  {"id": "extra", "title": "还有其他要求吗？", "type": "text", "options": [], "hint": null}
]
```"""
    if "生涯规划师" in prompt:
        return """好的，以下是提取结果：
{
  "mbti": "intj",
  "holland": "IRC",
  "traits": ["逻辑性强", "独立思考", "不喜欢重复性工作"],
  "interests": ["计算机", "科研", "数据分析"],
  "majors": ["计算机科学与技术", "软件工程"],
  "summary": "适合研究型、技术型专业，不宜强社交岗位"
}"""
    if "从考生的问卷作答中提炼" in prompt:
        return """{
  "traits": ["偏好省内", "学费敏感", "倾向计算机"],
  "preferences": {"地域偏好": "河南及邻省", "学费上限": "10000元/年", "专业方向": "计算机类"},
  "summary": "想在省内读计算机，家庭对学费较敏感"
}"""
    if "画像分析师" in prompt:
        return (
            "你是一个逻辑严谨、喜欢独立钻研的同学，对计算机和数据分析方向有明显兴趣，"
            "更适合理工科研究型专业而非强社交岗位。你倾向留在省内或邻近省份，"
            "能接受公办院校为主，对高学费的中外合作项目比较敏感。"
            "建议优先考虑计算机类、电子信息类的公办院校。"
        )
    return ""


def empty_llm(prompt: str, **kwargs) -> str:
    """模拟大模型完全不可用。"""
    return ""


def garbage_llm(prompt: str, **kwargs) -> str:
    """模拟大模型输出无法解析的垃圾文本。"""
    return "抱歉，我无法处理这个请求。#￥%……&*"


# ---------------------------------------------------------------- 用例


def test_json_parser() -> None:
    """用例 1：脏文本解析。"""
    print("用例 1：LLMJsonParser 脏文本解析")
    cases = [
        ('{"a": 1}', {"a": 1}),
        ('<think>思考中…</think>{"a": 2}', {"a": 2}),
        ('```json\n{"a": 3}\n```', {"a": 3}),
        ('好的，结果如下：{"a": 4} 希望有帮助', {"a": 4}),
        ('{"a": 5,}', {"a": 5}),                      # 尾逗号
        ('{“a”: 6}', {"a": 6}),                       # 全角引号
        ('{"a": {"b": [1,2]}}', {"a": {"b": [1, 2]}}),  # 嵌套
        ("不是 JSON", None),
        ("", None),
        (None, None),
    ]
    ok = 0
    for raw, want in cases:
        got = LLMJsonParser.parse_object(raw)
        assert got == want, f"parse_object({raw!r}) = {got!r}，期望 {want!r}"
        ok += 1
    # 数组解析
    arr = LLMJsonParser.parse_array('前导文字 [{"id":"q1"}] 后导文字')
    assert arr == [{"id": "q1"}], arr
    print(f"  {ok} 个对象用例 + 1 个数组用例 全部通过")


def test_extractors() -> None:
    """用例 2：报告 / 问卷提取器的归一化。"""
    print("用例 2：ReportExtractor / SurveyExtractor")
    report = ReportExtractor(llm=stub_llm).extract("霍兰德代码 IRC，MBTI 为 INTJ……")
    assert report["mbti"] == "INTJ", report                 # 小写被归一成大写
    assert report["holland"] == "IRC", report
    assert "逻辑性强" in report["traits"], report
    assert "计算机科学与技术" in report["majors"], report
    print(f"  report: mbti={report['mbti']} holland={report['holland']} "
          f"traits={len(report['traits'])} majors={len(report['majors'])}")

    survey = SurveyExtractor(llm=stub_llm).extract({
        "questions": [{
            "id": "region", "title": "地域", "type": "single",
            "options": [{"value": "local", "label": "本省"}],
        }],
        "answers": {"region": "local"},
    })
    assert survey["traits"], survey
    assert survey["preferences"].get("地域偏好"), survey
    print(f"  survey: traits={survey['traits']} prefs={list(survey['preferences'])}")

    # 空输入 / 垃圾输出都要返回「空但合法」的结构，不能抛异常
    assert ReportExtractor(llm=stub_llm).extract("")["traits"] == []
    assert ReportExtractor(llm=garbage_llm).extract("这是一段足够长的报告文本")["mbti"] == ""
    assert SurveyExtractor(llm=garbage_llm).extract({"questions": [], "answers": {}})["traits"] == []
    print("  空输入 / 垃圾输出 均安全降级")


def test_survey_fallback() -> None:
    """用例 3：问卷生成器的内置题库兜底。"""
    print("用例 3：SurveyQuestionGenerator 兜底")
    gen = SurveyQuestionGenerator(llm=empty_llm)
    questions, fallback = gen.generate(["学费敏感度", "专业与就业偏好"], count=3)
    assert fallback is True, "LLM 不可用时应标记 fallback"
    assert 3 == len(questions), questions
    for q in questions:
        assert q["id"] and q["title"] and q["type"] in {"single", "multiple", "text"}, q
    print(f"  兜底题 {len(questions)} 道：{[q['id'] for q in questions]}")

    # LLM 可用时走大模型
    gen2 = SurveyQuestionGenerator(llm=stub_llm)
    questions2, fallback2 = gen2.generate([], count=3)
    assert fallback2 is False, "LLM 可用时不应标记 fallback"
    assert len(questions2) == 3, questions2
    print(f"  LLM 题 {len(questions2)} 道：{[q['id'] for q in questions2]}")


def test_summary_fallback() -> None:
    """用例 4：汇总器的规则兜底。"""
    print("用例 4：ProfileSummarizer 规则兜底")
    s = ProfileSummarizer(llm=empty_llm)
    text = s.summarize(
        {"province": "河南", "category": "物理类"},
        {"mbti": "INTJ", "traits": ["逻辑性强"], "interests": ["计算机"]},
        {"preferences": {"学费上限": "10000元/年"}},
    )
    assert text and "INTJ" in text, text
    assert "计算机" in text, text
    print(f"  规则画像（{len(text)} 字）：{text[:60]}…")

    # 完全没有数据时给引导话术，而不是空串
    empty = s.summarize({}, {}, {})
    assert empty and len(empty) > 10, empty
    print(f"  空数据引导语：{empty[:40]}…")


def test_service_flow() -> None:
    """用例 5：ProfileService 全流程（内存仓储 + 桩 LLM）。"""
    print("用例 5：ProfileService 全流程（内存仓储）")
    repo = InMemoryProfileRepository()
    repo.update_user(7, username="kaosheng", nickname="小明")
    service = ProfileService(
        repo,
        report_extractor=ReportExtractor(llm=stub_llm),
        survey_extractor=SurveyExtractor(llm=stub_llm),
        survey_generator=SurveyQuestionGenerator(llm=stub_llm),
        summarizer=ProfileSummarizer(llm=stub_llm),
    )

    # ① 空画像
    view = service.get(7)
    assert view["ready"] is False and view["summary_text"] == "", view
    print("  ① 初始无画像 ready=False")

    # ② 完善资料
    view = service.update_basic(7, {"province": "河南", "category": "物理类", "score": 600})
    assert view["basic_info"]["province"] == "河南", view
    print(f"  ② 基础资料：{view['basic_info']}")

    # ③ 走途径 A：报告解析 → 生成画像
    result = service.extract_report(7, "霍兰德代码 IRC，MBTI 为 INTJ，喜欢独立研究……", "霍兰德")
    assert result["ready"] is True and result["summary_text"], result
    assert result["source"] == "report", result
    print(f"  ③ 报告画像 source={result['source']} 长度={len(result['summary_text'])}")
    assert service.get_summary_for_prompt(7), "画像应能被 AI 读取"

    # ④ 走途径 B：问卷 → source 变为 both
    questions, _ = service.generate_survey(["地域倾向"], 3)
    result = service.submit_survey(
        7, questions, {q["id"]: (q["options"][0]["value"] if q["options"] else "无") for q in questions}
    )
    assert result["source"] == "both", result
    print(f"  ④ 问卷后 source={result['source']}（两条轨道已汇合）")

    # ⑤ 重算
    rebuilt = service.rebuild(7)
    assert rebuilt["ready"] is True
    print(f"  ⑤ 重算画像 长度={len(rebuilt['summary_text'])}")

    # ⑥ 清空
    assert service.delete(7) is True
    assert service.get_summary_for_prompt(7) == ""
    print("  ⑥ 清空后 AI 读到的画像为空串")


def test_prompt_injection() -> None:
    """用例 5b：画像确实被拼进了 Prompt（捕获 ask 的入参）。"""
    print("用例 5b：画像注入 Prompt 验证")
    from app.services import ai_service, rag_service

    captured = {}
    original = ai_service.ask

    def spy(prompt, **kwargs):  # noqa: ANN001 - 桩函数
        captured["prompt"] = prompt
        return "（模拟回答）"

    ai_service.ask = spy
    try:
        summary = "你是一个逻辑严谨的同学，对计算机和数据分析有兴趣，家庭对学费比较敏感。"

        # ① 三路融合 Prompt
        hybrid_prompt = rag_service.build_hybrid_prompt(
            priority_hint="测试用优先级声明",
            graph_context="", mysql_context="", vector_context="",
            question="我适合报什么专业？",
            profile_context=summary,
        )
        assert "【考生画像】" in hybrid_prompt, hybrid_prompt[:200]
        assert "逻辑严谨" in hybrid_prompt, "画像正文未进入 Prompt"
        print("  ① 三路融合 Prompt 含【考生画像】段落")

        # ② 防幻觉生成 Prompt（纯向量链路）
        rag_service.generate_answer("我适合报什么专业？", "一些检索上下文", profile_context=summary)
        gen_prompt = captured.get("prompt", "")
        assert "【考生画像】" in gen_prompt, gen_prompt[:200]
        assert "逻辑严谨" in gen_prompt, "画像正文未进入生成 Prompt"
        print("  ② 防幻觉生成 Prompt 含【考生画像】段落")

        # ③ 无画像时不应多出任何段落（向后兼容）
        plain = rag_service.build_hybrid_prompt(
            priority_hint="x", graph_context="", mysql_context="", vector_context="",
            question="q", profile_context="",
        )
        assert "【考生画像】" not in plain, "空画像不应注入段落"
        print("  ③ 空画像时 Prompt 与 0.11.x 完全一致（向后兼容）")
    finally:
        ai_service.ask = original


def test_real() -> None:
    """用例 6：真实链路（需要服务已启动）。"""
    import requests

    base = "http://127.0.0.1:8000"
    print("用例 6：真实链路 HTTP")

    try:
        requests.get(f"{base}/api/health", timeout=5)
    except Exception:
        print("  [SKIP] 服务未启动（python -m uvicorn app.main:app）")
        return

    import time

    uname = f"profile_test_{int(time.time())}"
    # ① 注册
    r = requests.post(f"{base}/api/auth/register", json={
        "username": uname, "password": "test123456",
        "nickname": "测试考生", "phone": f"139{int(time.time()) % 100000000:08d}",
    }, timeout=20)
    print(f"  ① 注册 status={r.status_code}")
    if r.status_code not in (200, 400):
        print(f"     响应：{r.text[:200]}")
    assert r.status_code == 200, r.text

    # ② 登录
    r = requests.post(f"{base}/api/auth/login",
                      json={"username": uname, "password": "test123456"}, timeout=20)
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    print(f"  ② 登录 ok，nickname={r.json()['user'].get('nickname')}")

    # ③ 读空画像
    r = requests.get(f"{base}/api/profile", headers=h, timeout=20)
    assert r.status_code == 200 and r.json()["ready"] is False, r.text
    print("  ③ 初始画像 ready=False")

    # ④ 完善基础资料
    r = requests.put(f"{base}/api/profile/basic", headers=h, json={
        "nickname": "测试考生", "gender": "male", "province": "河南",
        "category": "物理类", "score": 600,
    }, timeout=20)
    assert r.status_code == 200, r.text
    print(f"  ④ 基础资料 basic_info={r.json()['basic_info']}")

    # ⑤ 上传霍兰德报告（真实调用大模型）
    r = requests.post(f"{base}/api/profile/report/upload", headers=h, json={
        "text": (
            "霍兰德职业兴趣测评报告：您的兴趣代码为 IRC（研究型-现实型-常规型）。"
            "MBTI 性格类型为 INTJ（建筑师型）。特质：逻辑性强、独立思考、"
            "喜欢解决复杂问题、不喜欢重复性工作和强社交场合。"
            "推荐专业方向：计算机科学与技术、软件工程、数据科学与大数据技术、数学与应用数学。"
        ),
        "source_hint": "霍兰德 + MBTI",
    }, timeout=120)
    print(f"  ⑤ 报告解析 status={r.status_code}")
    assert r.status_code == 200, r.text
    body = r.json()
    print(f"     source={body['source']} features={body.get('features', {}).get('report')}")
    print(f"     画像：{body['summary_text'][:80]}…")

    # ⑥ 生成问卷
    r = requests.post(f"{base}/api/profile/survey/questions", headers=h, json={
        "domains": ["地域倾向", "学费敏感度", "专业与就业偏好"], "count": 3,
    }, timeout=90)
    assert r.status_code == 200, r.text
    qs = r.json()["questions"]
    print(f"  ⑥ 问卷 {len(qs)} 道 fallback={r.json()['fallback']}：{[q['id'] for q in qs]}")

    # ⑦ 提交问卷
    answers = {}
    for q in qs:
        answers[q["id"]] = [o["value"] for o in q["options"][:2]] if q["type"] == "multiple" \
            else (q["options"][0]["value"] if q["options"] else "无")
    r = requests.post(f"{base}/api/profile/survey/submit", headers=h, json={
        "questions": qs, "answers": answers,
    }, timeout=120)
    assert r.status_code == 200, r.text
    print(f"  ⑦ 问卷提交 source={r.json()['source']}")

    # ⑧ 未登录访问 chat 应 401
    r = requests.post(f"{base}/api/ai/chat", json={"question": "你好", "use_rag": False}, timeout=20)
    print(f"  ⑧ 未登录 chat → {r.status_code}（应为 401）")
    assert r.status_code == 401, r.status_code

    # ⑨ 登录后 chat，应回传 profile_injected=true
    r = requests.post(f"{base}/api/ai/chat", headers=h, json={
        "question": "我适合报什么专业？", "use_rag": True, "use_graph": True,
    }, timeout=150)
    print(f"  ⑨ 登录 chat status={r.status_code} profile_injected={r.json().get('profile_injected')}")
    assert r.status_code == 200, r.text
    assert r.json().get("profile_injected") is True, r.json()
    print(f"     回答：{r.json()['answer'][:80]}…")

    # ⑩ 清空画像
    r = requests.delete(f"{base}/api/profile", headers=h, timeout=20)
    print(f"  ⑩ 清空画像 → {r.status_code} {r.json().get('msg')}")


def main() -> int:
    test_json_parser()
    print()
    test_extractors()
    print()
    test_survey_fallback()
    print()
    test_summary_fallback()
    print()
    test_service_flow()
    print()
    test_prompt_injection()
    print()
    if "--real" in sys.argv:
        test_real()
        print()
    else:
        print("[提示] 加 --real 跑真实链路（需启动服务）")
        print()
    print("=" * 70)
    print("0.12.0 账号体系 + 用户画像用例全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
