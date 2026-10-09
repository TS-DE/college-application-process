"""v2.5.1 最小用例：验证 LLM / Embedding 通道是否修正。

① Ali LLM 通道（OpenAI 兼容）能否在秒级返回
② Ali Embedding 通道能否按指定维度返回向量（对齐已有集合维度）
③ 关掉 Key 之后能否自动降级到本地 Ollama
④ /api/ai/chat 端到端：回答「学费是多少」是否在 10 秒内返回
"""
import sys
import time
from typing import List, Optional

sys.path.insert(0, ".")

from app.config import settings
from app.services import llm_client, rag_service


def probe_channels() -> None:
    print("=" * 72)
    print("【1】通道自检")
    print("=" * 72)
    key = llm_client.get_api_key()
    print(f"  Ali_API_KEY：{llm_client.mask(key)}（来源：系统环境变量/注册表）")
    client = llm_client.get_llm_client()
    print(f"  LLM 通道顺序：{client.llm_channel_names}")
    print(f"  Embedding 通道顺序：{client.embed_channel_names}")
    print(f"  ALI_BASE_URL = {settings.ALI_BASE_URL}")
    print(f"  ALI_LLM_MODEL = {settings.ALI_LLM_MODEL}")

    t = time.time()
    out = client.chat("", "只回复两个字：你好", temperature=0.0, max_tokens=16)
    print(f"\n【2】Ali LLM 调用：{out!r}   耗时 {time.time() - t:.2f}s")

    dim = rag_service._collection_dimension() or settings.ALI_EMBED_DIMENSION
    print(f"\n【3】已有集合维度：{rag_service._collection_dimension()}，本次请求维度：{dim}")
    t = time.time()
    vec = rag_service.get_embedding("福州大学至诚学院计算机专业学费")
    print(f"  embedding 返回：{'None' if vec is None else f'{len(vec)} 维'}   耗时 {time.time() - t:.2f}s")

    print("\n【4】关闭 Key 后的降级（模拟线上通道故障）")
    original_key_fn = llm_client.get_api_key  # 先留底，稍后还原
    llm_client.get_api_key = lambda: ""
    llm_client.reset_client()
    client = llm_client.get_llm_client()
    t = time.time()
    out = client.chat("", "只回复两个字：你好", temperature=0.0, max_tokens=16)
    print(f"  Ollama 兜底返回：{out!r}   耗时 {time.time() - t:.2f}s")

    # 还原现场（Key 读取函数 + 单例），避免影响后续用例
    llm_client.get_api_key = original_key_fn
    llm_client.reset_client()


TEST_COLLECTION = "test_v251"
TEST_FILE_ID = 9311
DOCS = [
    "福州大学至诚学院是经教育部批准设立的独立学院，位于福建省福州市，2025年在河南省本科批物理类招生。",
    "福州大学至诚学院计算机科学与技术专业，学制4年，学费标准为23000元/年，选科要求首选物理、再选化学。",
    "福州大学至诚学院2025年在河南本科批物理类投档最低分为458分，对应全省位次约为112000名。",
]


def _build_temp_kb() -> int:
    """临时搭一个小知识库（独立集合 + 独立 file_id），跑完即删，不污染真实数据。"""
    rag_service.settings.CHROMA_COLLECTION = TEST_COLLECTION
    rag_service._collection = None
    rag_service._collection_dim_cache = None
    rag_service.collection()
    parents: List[str] = []
    for d in DOCS:
        parents.extend(rag_service.split_text(d))
    return rag_service.add_documents(parents, {"file_id": TEST_FILE_ID, "filename": "福大至诚招生.txt"},
                                     key_fmt=f"file_{TEST_FILE_ID}_chunk_{{idx}}")


def _cleanup_temp_kb() -> None:
    try:
        rag_service._client.delete_collection(TEST_COLLECTION)
    except Exception:  # noqa: BLE001
        pass
    rag_service.drop_parents_by_file(TEST_FILE_ID)
    rag_service._collection = None
    rag_service.settings.CHROMA_COLLECTION = _ORIG_COLLECTION
    rag_service._collection_dim_cache = None


_ORIG_COLLECTION = rag_service.settings.CHROMA_COLLECTION


def probe_chat() -> None:
    print("\n" + "=" * 72)
    print("【5】端到端问答（与 POST /api/ai/chat 同一条链路）")
    print("=" * 72)
    cnt = _build_temp_kb()
    print(f"  临时知识库：{len(DOCS)} 个父块 → {cnt} 个子块")
    try:
        q = "福州大学至诚学院计算机专业学费是多少"
        t = time.time()
        res = rag_service.answer_with_strategy(q, top_k=3, strategy="auto")
        cost = time.time() - t
        print(f"  问题：{q}")
        print(f"  strategy = {res['strategy']}")
        print(f"  steps    = {res['steps']}")
        print(f"  answer   = {res['answer'][:120]}")
        print(f"  sources  = {res['sources']}")
        hit = "23000" in res["answer"]
        print(f"  答案含正确数字(23000)：{'是' if hit else '否'}")
        print(f"  耗时 {cost:.2f}s → {'[通过] 10 秒内返回' if cost < 10 else '[超时] 需继续排查'}")
    finally:
        _cleanup_temp_kb()
        print("  已清理临时集合与测试父块")


if __name__ == "__main__":
    probe_channels()
    probe_chat()
