# -*- coding: utf-8 -*-
"""0.9.1 三路融合（图谱 + MySQL + 向量）最小测试用例。

用法：
    python test_hybrid_rag.py           # 桩版：不连 Neo4j、不调 LLM，秒级跑完
    python test_hybrid_rag.py --real    # 真实链路：连 MySQL（图谱/向量视环境而定）

用例：
    1. detect_structured_intent 意图识别（含多意图与空意图）
    2. MySQLQueryEngine.query_structured 结构化查询（桩 Session）
    3. 三路融合：仅 MySQL 命中 → 走 hybrid:priority_quota
    4. 三路融合：三路全空 → hybrid_empty + 拒答话术
    5. 降级：MySQL 路异常只跳过该路，其他路照常
    6. 兼容别名：answer_with_graph 仍可调用
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List

sys.path.insert(0, ".")

QUESTION = "福州大学至诚学院计算机专业学费是多少？选科要求是什么？"
QUESTION_FAKE = "福州大学至诚学院计算机专业在冥王星星球 3025 年的量子学费是多少？"

_FAKE_ROWS: List[Dict[str, Any]] = [
    {
        "university_name": "福州大学至诚学院",
        "major_name": "计算机科学与技术",
        "tuition": 23000,
        "subject_req": "首选物理再选化学",
    }
]


class _StubResult:
    """模拟 SQLAlchemy Result.mappings() 的返回。"""

    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self):
        return [_Row(r) for r in self._rows]


class _Row(dict):
    pass


class _StubSession:
    """桩 Session：记录收到的 SQL 与参数，返回预置数据。"""

    def __init__(self, rows: List[Dict[str, Any]] | None = None, boom: bool = False) -> None:
        self.rows = _FAKE_ROWS if rows is None else rows
        self.boom = boom
        self.calls: List[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, params=None):
        self.calls.append((str(statement), dict(params or {})))
        if self.boom:
            raise RuntimeError("connection refused")
        return _StubResult(self.rows)


def _session_factory(rows=None, boom=False):
    return lambda: _StubSession(rows=rows, boom=boom)


# ------------------------------------------------------------ 用例


def test_intent() -> None:
    """用例 1：结构化意图识别。"""
    from app.services.rag_service import detect_structured_intent

    got = detect_structured_intent(QUESTION)
    assert got == ["tuition", "subject_req"], got

    assert detect_structured_intent("河南本科批志愿怎么填报？") == []
    assert detect_structured_intent("郑州大学计算机2025年最低分和位次") == ["min_score", "min_rank"]
    assert detect_structured_intent("") == []

    print("用例 1：结构化意图识别")
    print(f"  {QUESTION}")
    print(f"  → {got}")
    print(f"  非结构化问题 → {detect_structured_intent('河南本科批志愿怎么填报？')}")


def test_mysql_engine() -> None:
    """用例 2：MySQLQueryEngine 结构化查询（桩 Session，不连真库）。"""
    from app.services.sql_query_engine import MySQLQueryEngine

    engine = MySQLQueryEngine(session_factory=_session_factory())
    res = engine.query_structured({
        "school_name": "福州大学至诚学院",
        "major_name": "计算机",
        "year": 2025,
        "intents": ["tuition", "subject_req"],
    })
    assert res["hit"] is True, res
    assert "23000" in res["context"], res["context"]
    assert "首选物理再选化学" in res["context"], res["context"]

    sql, params = engine.query_structured.__self__ and (None, None)  # 占位，避免误用
    session = _StubSession()
    MySQLQueryEngine(session_factory=lambda: session).query_structured({
        "school_name": "福州大学至诚学院",
        "major_name": "计算机",
        "intents": ["tuition", "subject_req"],
    })
    # 按真实 schema 拆成两张表查询：tuition 走 enrollment_plan，subject_req 走 major_admission
    assert len(session.calls) == 2, [c[0] for c in session.calls]
    sql_plan, params_plan = session.calls[0]
    sql_adm, params_adm = session.calls[1]
    assert "enrollment_plan_2025_henan" in sql_plan, sql_plan
    assert "major_admission_2025_henan" in sql_adm, sql_adm
    # 参数化查询：条件必须走绑定，不能字符串拼接进 SQL
    for sql_text in (sql_plan, sql_adm):
        assert "LIKE :school" in sql_text and "LIKE :major" in sql_text, sql_text
        assert "福州大学至诚学院" not in sql_text, "院校名不应拼接进 SQL"
        assert "tuition" in sql_text or "subject_req" in sql_text, sql_text
    assert params_plan["school"] == "%福州大学至诚学院%", params_plan
    assert params_plan["major"] == "%计算机%", params_plan
    assert params_plan["limit"] == 5, params_plan

    print("用例 2：MySQLQueryEngine.query_structured")
    print(f"  hit={res['hit']}")
    for line in res["context"].splitlines():
        print(f"    {line}")
    print(f"  参数化校验通过：school={params_plan['school']} major={params_plan['major']} limit={params_plan['limit']}")
    print(f"  两表拆分：enrollment_plan(学费/计划) + major_admission(分数线/位次/选科)")

    # 无意图 / 无条件时不查库
    empty = MySQLQueryEngine(session_factory=_session_factory()).query_structured({"intents": []})
    assert empty["hit"] is False, empty
    print(f"  无意图 → hit={empty['hit']} error={empty['error']}")


def test_hybrid_mysql_only(monkeypatch=None) -> None:
    """用例 3：仅 MySQL 命中 → 走 hybrid:priority_quota。

    把图谱路与向量路都打成空，只留 MySQL 路，验证优先级分发与返回结构。
    """
    from app.services import rag_service
    from app.services.sql_query_engine import MySQLQueryEngine

    rag_service._graph_engine = False          # 图谱引擎不可用
    monkeypatch_search(rag_service, [])        # 向量路无命中

    orig = MySQLQueryEngine.query_structured

    def _stub(self, filters):
        return {
            "hit": True,
            "context": "福州大学至诚学院计算机科学与技术专业2025年学费为23000元/年。\n"
                       "福州大学至诚学院计算机科学与技术专业选科要求：首选物理再选化学。",
            "raw": _FAKE_ROWS,
            "error": "",
        }

    MySQLQueryEngine.query_structured = _stub
    # extract_sql_filters 走 LLM，测试里替换成确定性词典提取
    rag_service.rag_service_extract_sql_filters = lambda q: {
        "school_name": "福州大学至诚学院", "major_name": "计算机科学与技术", "year": 2025
    }
    try:
        out = rag_service.answer_with_hybrid(QUESTION, top_k=5)
    finally:
        MySQLQueryEngine.query_structured = orig

    assert out["source"] == "hybrid:priority_quota", out["source"]
    assert out["mysql_hit"] is True, out
    assert out["graph_hit"] is False and out["vector_hit"] is False, out
    assert out["fusion_strategy"] == "priority_quota", out
    assert "MySQL 招生数据" in out["sources"], out["sources"]
    assert "23000" in out["answer"], out["answer"]

    print("用例 3：仅 MySQL 命中（三路融合）")
    print(f"  source={out['source']} graph_hit={out['graph_hit']} "
          f"mysql_hit={out['mysql_hit']} vector_hit={out['vector_hit']}")
    print(f"  sources={out['sources']}")
    print(f"  answer={out['answer'][:120]}")


def test_hybrid_all_empty(monkeypatch=None) -> None:
    """用例 4：三路全空 → hybrid_empty + 拒答话术，不调大模型。"""
    from app.services import rag_service

    rag_service._graph_engine = False
    monkeypatch_search(rag_service, [])

    def _stub(self, filters):
        return {"hit": False, "context": "", "raw": [], "error": ""}

    from app.services.sql_query_engine import MySQLQueryEngine

    orig = MySQLQueryEngine.query_structured
    MySQLQueryEngine.query_structured = _stub
    rag_service.rag_service_extract_sql_filters = lambda q: {"school_name": "X", "major_name": "Y"}
    try:
        out = rag_service.answer_with_hybrid(QUESTION_FAKE, top_k=5)
    finally:
        MySQLQueryEngine.query_structured = orig

    assert out["source"] == "hybrid_empty", out["source"]
    assert out["graph_hit"] is False and out["mysql_hit"] is False and out["vector_hit"] is False, out
    assert "未查询到具体信息" in out["answer"], out["answer"]
    assert out["sources"] == [], out["sources"]

    print("用例 4：三路全空（hybrid_empty）")
    print(f"  source={out['source']}")
    print(f"  answer={out['answer']}")


def test_mysql_channel_failure() -> None:
    """用例 5：MySQL 路异常只跳过该路，不影响其他路。"""
    from app.services.sql_query_engine import MySQLQueryEngine

    engine = MySQLQueryEngine(session_factory=_session_factory(boom=True))
    res = engine.query_structured({
        "school_name": "福州大学至诚学院", "major_name": "计算机", "intents": ["tuition"],
    })
    assert res["hit"] is False, res
    assert "查询异常" in res["error"], res
    print("用例 5：MySQL 路异常降级")
    print(f"  hit={res['hit']} error={res['error']}")


def test_compat_alias() -> None:
    """用例 6：0.9.0 兼容别名仍可用。"""
    from app.services import rag_service

    assert callable(rag_service.answer_with_graph)
    assert rag_service.answer_with_graph.__doc__ and "answer_with_hybrid" in rag_service.answer_with_graph.__doc__
    print("用例 6：兼容别名 answer_with_graph → answer_with_hybrid")


def monkeypatch_search(rag_service, hits) -> None:
    """把 rag_service.search 换成确定性桩（避免依赖 Chroma / embedding）。"""
    rag_service.search = lambda *a, **k: hits


def test_real() -> None:
    """真实链路：连 MySQL；图谱与向量视环境可用性自动降级。"""
    from app.services import rag_service

    engine = rag_service._get_graph_engine()
    print(f"  图谱引擎：{'可用' if engine else '不可用（将自动降级）'}")
    rag_service.rag_service_extract_sql_filters = lambda q: {
        "school_name": "福州大学至诚学院", "major_name": "计算机", "year": 2025
    }
    out = rag_service.answer_with_hybrid(QUESTION, top_k=5)
    print(f"  source={out['source']} graph_hit={out['graph_hit']} "
          f"mysql_hit={out['mysql_hit']} vector_hit={out['vector_hit']}")
    print(f"  sources={out['sources']}")
    if out.get("mysql_error"):
        print(f"  mysql_error={out['mysql_error']}")
    if out.get("graph_error"):
        print(f"  graph_error={out['graph_error'][:100]}")
    print(f"  answer={out['answer'][:200]}")


def main() -> int:
    test_intent()
    print()
    test_mysql_engine()
    print()
    test_hybrid_mysql_only()
    print()
    test_hybrid_all_empty()
    print()
    test_mysql_channel_failure()
    print()
    test_compat_alias()
    print()
    if "--real" in sys.argv:
        print("真实链路：answer_with_hybrid")
        test_real()
        print()
    print("=" * 70)
    print("0.9.1 三路融合用例全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
