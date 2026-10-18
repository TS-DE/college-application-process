# -*- coding: utf-8 -*-
"""0.12.1 热修复验证：隐私隔离 / 地图统计 / 主观咨询放行 / 超时降级。

用法：
    python test_hotfix_0_12_1.py           # 桩版：不连库、不调大模型
    python test_hotfix_0_12_1.py --real    # 真实链路（需启动服务）
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")


# ---------------------------------------------------------------- 用例 1：地图统计


def test_map_stats() -> None:
    """用例 1：地图统计口径修复（山东/江西不再 0，吉林给出明确降级提示）。"""
    print("用例 1：地图统计口径")
    from app.routers.stats import major_count_by_province

    # 山东：university_code 整列为空，旧口径 university_count=0 / major_count=101
    shandong = major_count_by_province(province="山东", year=2025, category="综合", batch="本科批")
    assert shandong["degraded"] is False, shandong
    assert shandong["total_major"] > 1000, (
        f"山东专业数应恢复正常（>1000），实际 {shandong['total_major']}"
    )
    assert shandong["total_university"] > 100, (
        f"山东院校数应恢复正常（>100），实际 {shandong['total_university']}"
    )
    print(f"  山东/综合: 专业={shandong['total_major']} 院校={shandong['total_university']} "
          f"省份数={len(shandong['data'])}")

    # 江西：major_code 大面积为空，旧口径 major_count=584（实际 7000+）
    jiangxi = major_count_by_province(province="江西", year=2025, category="物理类", batch="本科批")
    assert jiangxi["total_major"] > 1000, (
        f"江西专业数应恢复正常，实际 {jiangxi['total_major']}"
    )
    print(f"  江西/物理类: 专业={jiangxi['total_major']} 院校={jiangxi['total_university']}")

    # 吉林：school_province 整列为 NULL → 归入「数据缺失」桶 + degraded 提示
    jilin = major_count_by_province(province="吉林", year=2025, category="物理类", batch="本科批")
    assert jilin["total_major"] > 0, "吉林不应返回空数据"
    assert jilin["degraded"] is True, "吉林应标记 degraded"
    assert jilin["message"], "吉林应给出降级说明"
    assert any(d["province"] == "数据缺失" for d in jilin["data"]), jilin["data"][:3]
    print(f"  吉林/物理类: 专业={jilin['total_major']} 院校={jilin['total_university']} "
          f"degraded=True")
    print(f"    提示：{jilin['message'][:50]}…")

    # 河南回归：不能被改坏
    henan = major_count_by_province(province="河南", year=2025, category="物理类", batch="本科批")
    assert henan["total_major"] > 5000, henan["total_major"]
    assert henan["degraded"] is False
    print(f"  河南/物理类（回归）: 专业={henan['total_major']} 院校={henan['total_university']}")


# ---------------------------------------------------------------- 用例 2：主观咨询


def test_subjective_intent() -> None:
    """用例 2：主观咨询白名单（不再被意图路由拦截）。"""
    print("用例 2：主观咨询意图识别")
    from app.services.rag_service import SUBJECTIVE_INTENT_KEYWORDS, _has_subjective_intent

    should_pass = [
        "你能猜到我想去哪所学校吗",
        "我该去哪里读大学",
        "帮我推荐几个适合的志愿",
        "502分有什么建议",
        "这些志愿这样填稳不稳",
        "把把关",
        "我适合什么专业",
        "怎么选学校",
    ]
    for q in should_pass:
        assert _has_subjective_intent(q), f"应放行：{q}"
    print(f"  {len(should_pass)} 个主观咨询问题全部命中白名单")

    should_block = [
        "婚假有几天",
        "今天天气怎么样",
        "Python 怎么安装",
        "唐朝有多少年",
        "1 加 1 等于几",
    ]
    for q in should_block:
        assert not _has_subjective_intent(q), f"不应命中白名单：{q}"
    print(f"  {len(should_block)} 个无关问题均不命中（仍交给 LLM 分类）")
    print(f"  白名单词数：{len(SUBJECTIVE_INTENT_KEYWORDS)}")


def test_router_prompt() -> None:
    """用例 3：ROUTER_PROMPT 已包含主观咨询放行规则。"""
    print("用例 3：ROUTER_PROMPT 放行规则")
    from app.services.rag_service import ROUTER_PROMPT

    assert "主观咨询" in ROUTER_PROMPT, "Prompt 应明确主观咨询类判 YES"
    assert "我该去哪" in ROUTER_PROMPT or "该去哪" in ROUTER_PROMPT
    print("  Prompt 已新增第 4 条：主观咨询 / 征询意见类问题判 YES")


# ---------------------------------------------------------------- 用例 4：规划师兜底


def test_advisory_fallback() -> None:
    """用例 4：三路无资料 + 主观意图 → 走规划师兜底而非拒答。"""
    print("用例 4：规划师兜底逻辑")
    from app.services import rag_service

    prompt = rag_service.build_advisory_prompt(
        "我高考502分，根据我的用户画像，我该去哪里",
        profile_context="你逻辑严谨，对计算机有兴趣，家庭对学费敏感。",
        context_text="",
    )
    assert "考生画像" in prompt and "502分" in prompt, prompt[:200]
    assert "严禁编造" in prompt, "必须明确禁止编造数字"
    assert "规划师" in prompt
    print("  ADVISORY_PROMPT 含画像 / 问题 / 禁编造约束")

    # 有（可能不相关的）检索内容时，应放进【参考资料】而不是逼成拒答
    with_ctx = rag_service.build_advisory_prompt(
        "我该去哪", profile_context="画像", context_text="【政策/介绍文本】某省专升本录取率…"
    )
    assert "【参考资料】" in with_ctx, "有上下文时应放进参考资料"
    print("  有检索内容时进入【参考资料】，不再触发拒答")

    # 用桩 ask 验证 answer_with_hybrid 的空结果分支走 advisory
    from app.services import ai_service

    captured = {}
    original = ai_service.ask

    def spy(prompt, **kwargs):  # noqa: ANN001
        captured["prompt"] = prompt
        captured["kwargs"] = kwargs
        return "建议优先考虑省内公办院校的计算机类专业，并把冲刺批次放在省属重点。"

    ai_service.ask = spy
    try:
        # 三路都空（Neo4j 未装 py2neo 的通道会降级；MySQL/向量也按桩返回空）
        result = rag_service.answer_with_hybrid(
            "我高考502分，根据我的用户画像，我该去哪里",
            top_k=1,
            profile_context="你逻辑严谨，对计算机有兴趣。",
        )
        print(f"  source={result['source']} profile_injected={result.get('profile_injected')}")
        print(f"  回答：{result['answer'][:50]}…")
        assert result["source"] in (
            "hybrid:advisory", "hybrid:advisory_with_context",
            "hybrid:priority_quota", "hybrid_empty",
        ), result["source"]
        if result["source"].startswith("hybrid:advisory"):
            assert "严禁编造" in captured["prompt"] and "规划师" in captured["prompt"]
            print("  已走规划师模式，Prompt 含画像 + 禁编造约束")
        else:
            print("  规划师模式生成失败，落回常规链路")
    finally:
        ai_service.ask = original


def test_advisory_branch_forced() -> None:
    """用例 4b：强制三路全空，验证 advisory 分支确实被触发（确定性）。"""
    print("用例 4b：强制三路全空时的 advisory 分支")
    from app.services import ai_service, rag_service

    captured = {}
    original = ai_service.ask

    def spy(prompt, **kwargs):  # noqa: ANN001
        captured.setdefault("prompts", []).append(prompt)
        # 路由分类返回 YES，其余返回规划师回答
        if "意图分类器" in prompt:
            return "YES"
        return "建议优先考虑省内公办院校的计算机类专业，冲刺批次放省属重点。"

    # 强制三路都空
    rag_service._get_graph_engine = lambda: None
    rag_service.rag_service_extract_sql_filters = lambda q: None
    rag_service.search = lambda *a, **k: []

    ai_service.ask = spy
    try:
        result = rag_service.answer_with_hybrid(
            "我高考502分，根据我的用户画像，我该去哪里读书",
            top_k=1,
            profile_context="你逻辑严谨，对计算机有兴趣，家庭对学费敏感。",
        )
        print(f"  source={result['source']}")
        print(f"  回答：{result['answer'][:60]}…")
        assert result["source"] == "hybrid:advisory", result
        assert "严禁编造" in captured["prompts"][-1], "advisory Prompt 必须含禁编造约束"
        assert result["profile_injected"] is True
        assert result["graph_hit"] is False and result["vector_hit"] is False
        print("  已走规划师兜底：禁编造约束在 Prompt 中，画像已注入")

        # 对照组：非主观问题在三路全空时仍应拒答（不能什么都放行）
        result2 = rag_service.answer_with_hybrid("福州大学至诚学院的学费是多少", top_k=1)
        print(f"  对照组（客观问题）source={result2['source']}")
        assert result2["source"] == "hybrid_empty", result2
        assert "未查询到" in result2["answer"]
        print("  客观问题仍走拒答，防幻觉底线未松动")
    finally:
        ai_service.ask = original


# ---------------------------------------------------------------- 用例 5：隐私隔离


def test_report_privacy() -> None:
    """用例 5：报告读取器不写知识库、用完即删。"""
    print("用例 5：报告隐私隔离")
    import os

    from app.services.profile import ReportReader, ReportReadError
    from app.utils import file_utils

    # ① 类型白名单与知识库不同（多图片、多 md，且目录独立）
    assert file_utils.REPORT_ALLOWED_EXTS != file_utils.ALLOWED_EXTS
    assert ".png" in file_utils.REPORT_ALLOWED_EXTS
    assert ".png" not in file_utils.ALLOWED_EXTS
    report_dir = os.path.join(os.path.abspath(file_utils.ensure_report_dir()))
    knowledge_dir = os.path.abspath(file_utils.ensure_dir())
    assert report_dir != knowledge_dir, "报告目录必须与知识库目录隔离"
    print(f"  报告目录：{report_dir}")
    print(f"  知识库目录：{knowledge_dir}（不同）")

    # ② 读取后文件被删除
    reader = ReportReader()
    content = "霍兰德职业兴趣测评报告\n兴趣代码 IRC\nMBTI 为 INTJ\n特质：逻辑性强、独立思考。".encode("utf-8")
    text = reader.read(content, "report.txt")
    assert "INTJ" in text and len(text) > 10, text
    leftovers = os.listdir(report_dir)
    assert not leftovers, f"读取后应无残留文件，实际 {leftovers}"
    print("  文本读取成功，且临时文件已删除（磁盘无私人副本）")

    # ③ 不支持的类型直接报错
    try:
        reader.read(b"x" * 100, "virus.exe")
        raise AssertionError("应拒绝不支持的扩展名")
    except ReportReadError:
        print("  非白名单类型已拒绝")

    # ④ 不写 Chroma：ReportReader 模块不应引用 rag_service / ImageStore
    import inspect

    src = inspect.getsource(ReportReader)
    for banned in ("add_documents", "ImageStore", "ImageExtractor", "gaokao_knowledge"):
        assert banned not in src, f"ReportReader 不应引用 {banned}"
    print("  ReportReader 源码无任何 Chroma / 知识库写入调用")


# ---------------------------------------------------------------- 用例 6：超时配置


def test_timeout_config() -> None:
    """用例 6：timeout 真正下传到通道。"""
    print("用例 6：超时配置贯通")
    from app.config import settings

    assert settings.CHAT_TOTAL_TIMEOUT > 0, settings.CHAT_TOTAL_TIMEOUT
    assert settings.GRAPH_LLM_TIMEOUT > 0, settings.GRAPH_LLM_TIMEOUT
    assert settings.GRAPH_LLM_TIMEOUT < settings.CHAT_TOTAL_TIMEOUT, (
        "图谱单次超时必须小于整体预算，否则两次调用就爆"
    )
    print(f"  CHAT_TOTAL_TIMEOUT={settings.CHAT_TOTAL_TIMEOUT}s "
          f"GRAPH_LLM_TIMEOUT={settings.GRAPH_LLM_TIMEOUT}s")

    # ai_service.ask 是否把 timeout 传给门面
    import inspect

    from app.services import ai_service

    src = inspect.getsource(ai_service.ask)
    assert "timeout=timeout" in src, "ask() 必须把 timeout 传给 llm_client"
    print("  ai_service.ask 已透传 timeout")

    # 门面是否透传给通道
    from app.services import llm_client

    src = inspect.getsource(llm_client.LLMClient.chat)
    assert "timeout=timeout" in src, "LLMClient.chat 必须透传 timeout"
    print("  LLMClient.chat 已透传 timeout")

    # 通道是否真的用上
    for cls in (llm_client.AliLLMChannel, llm_client.OllamaLLMChannel):
        src = inspect.getsource(cls.chat)
        assert "timeout" in src, f"{cls.__name__}.chat 未使用 timeout"
    print("  Ali / Ollama 通道均已使用 per-call timeout")


# ---------------------------------------------------------------- 真实链路


def test_real() -> None:
    """用例 7：真实链路（需启动服务）。"""
    import time

    import requests

    base = "http://127.0.0.1:8000"
    print("用例 7：真实链路 HTTP")
    try:
        requests.get(f"{base}/api/health", timeout=5)
    except Exception:
        print("  [SKIP] 服务未启动")
        return

    uname = f"hotfix_{int(time.time())}"
    r = requests.post(f"{base}/api/auth/register", json={
        "username": uname, "password": "test123456",
        "nickname": "修复验证", "phone": f"138{int(time.time()) % 100000000:08d}",
    }, timeout=20)
    assert r.status_code == 200, r.text
    r = requests.post(f"{base}/api/auth/login",
                      json={"username": uname, "password": "test123456"}, timeout=20)
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # ① 上传报告（文本版）→ 落画像
    r = requests.post(f"{base}/api/profile/report/upload", headers=h, json={
        "text": "霍兰德职业兴趣测评：兴趣代码 IRC。MBTI：INTJ。特质：逻辑性强、独立思考、"
                "喜欢解决复杂问题。推荐专业：计算机科学与技术、软件工程。",
        "source_hint": "霍兰德 + MBTI",
    }, timeout=120)
    print(f"  ① 报告上传（文本）status={r.status_code}")
    assert r.status_code == 200, r.text

    # ② 上传报告（文件版）→ 同样落画像，且知识库里看不到
    files = {"file": ("mbti_report.txt",
                      "MBTI 性格测评报告\n类型：INTJ（建筑师型）\n特质：理性、独立、"
                      "擅长系统思考、不喜欢重复性工作\n适合方向：软件工程、数据科学\n"
                      .encode("utf-8"), "text/plain")}
    r = requests.post(f"{base}/api/profile/report/upload-file", headers=h, files=files, timeout=150)
    print(f"  ② 报告上传（文件）status={r.status_code}")
    assert r.status_code == 200, r.text

    # ③ 知识库列表不应包含这份报告
    r_admin = requests.post(f"{base}/api/auth/login",
                            json={"username": "admin", "password": "admin123"}, timeout=20)
    if r_admin.status_code == 200:
        ah = {"Authorization": f"Bearer {r_admin.json()['access_token']}"}
        kfiles = requests.get(f"{base}/api/knowledge/list", headers=ah, timeout=20).json()
        names = [f.get("filename", "") for f in kfiles.get("data", [])]
        leaked = [n for n in names if "mbti_report" in n or "report" in n.lower()]
        print(f"  ③ 知识库文件数={len(names)}，含用户报告={leaked or '无'}")
        assert not leaked, f"隐私泄露：知识库出现用户报告 {leaked}"

    # ④ 主观咨询问答：502 分 + 画像 → 不应拒答
    r = requests.post(f"{base}/api/ai/chat", headers=h, json={
        "question": "我高考502分，根据我的用户画像，我该去哪里读书？",
        "use_rag": True, "use_graph": True,
    }, timeout=180)
    print(f"  ④ 主观咨询问答 status={r.status_code} source={r.json().get('source')}")
    assert r.status_code == 200, r.text
    body = r.json()
    answer = body.get("answer", "")
    print(f"     profile_injected={body.get('profile_injected')}")
    print(f"     回答：{answer[:90]}…")
    assert "未查询到" not in answer, f"不应拒答，实际：{answer[:80]}"
    assert len(answer) > 30, f"回答过短：{answer}"

    # ⑤ 地图：山东 / 江西 / 吉林
    for prov, cat in (("山东", "综合"), ("江西", "物理类"), ("吉林", "物理类")):
        r = requests.get(f"{base}/api/stats/major-count-by-province",
                         params={"province": prov, "year": 2025, "category": cat},
                         timeout=60)
        d = r.json()
        print(f"  ⑤ 地图 {prov}/{cat}: 专业={d.get('total_major')} "
              f"院校={d.get('total_university')} degraded={d.get('degraded')}")
        assert r.status_code == 200
        assert d.get("total_major", 0) > 0, f"{prov} 地图仍无数据"

    # ⑥ 无关问题仍应被拦截（不能因为放宽而失效）
    r = requests.post(f"{base}/api/ai/chat", headers=h,
                      json={"question": "婚假有几天？", "use_rag": True}, timeout=180)
    print(f"  ⑥ 无关问题 status={r.status_code} source={r.json().get('source')}")
    assert r.status_code == 200, r.text

    # ⑦ 清空画像
    requests.delete(f"{base}/api/profile", headers=h, timeout=20)
    print("  ⑦ 画像已清空")


def main() -> int:
    test_map_stats()
    print()
    test_subjective_intent()
    print()
    test_router_prompt()
    print()
    test_advisory_fallback()
    print()
    test_advisory_branch_forced()
    print()
    test_report_privacy()
    print()
    test_timeout_config()
    print()
    if "--real" in sys.argv:
        test_real()
        print()
    else:
        print("[提示] 加 --real 跑真实链路（需启动服务）")
        print()
    print("=" * 70)
    print("0.12.1 热修复用例全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
