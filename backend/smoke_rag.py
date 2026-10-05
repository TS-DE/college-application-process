"""RAG 链路冒烟测试：登录 → 上传 → 列表 → 检索 → AI 问答 → 删除。"""
import os
import requests

B = "http://127.0.0.1:8000"


def login(u, p):
    r = requests.post(B + "/api/auth/login", json={"username": u, "password": p})
    r.raise_for_status()
    return r.json()["access_token"]


def hdr(t):
    return {"Authorization": "Bearer " + t}


admin = login("admin", "admin123")
student = login("student01", "student123")
print("login: admin & student ok")

# 权限：未登录 / 学生
print("no token search:", requests.get(B + "/api/knowledge/search", params={"query": "志愿"}).status_code)
print("student list:", requests.get(B + "/api/knowledge/list", headers=hdr(student)).status_code)
print("student search:", requests.get(B + "/api/knowledge/search", params={"query": "志愿"}, headers=hdr(student)).status_code)

# 上传
doc = (
    "河南省2025年普通高校招生志愿填报指南。\n"
    "本科批实行平行志愿，考生可填报48个院校专业组志愿，每个志愿包含1个院校专业组和若干专业。\n"
    "投档规则为分数优先、遵循志愿、一轮投档。考生位次是志愿填报最重要的参考指标。\n"
    "填报策略建议采用冲稳保梯度：冲的志愿选择录取位次略高于自己的院校，稳的志愿选择与自己位次相当，"
    "保的志愿选择录取位次明显低于自己的院校，确保不掉档。\n"
    "专科批同样实行平行志愿，建议把最想去的院校专业组放在前面。\n"
)
open("_rag_test.txt", "w", encoding="utf-8").write(doc * 3)
with open("_rag_test.txt", "rb") as f:
    r = requests.post(
        B + "/api/knowledge/upload",
        headers=hdr(admin),
        files={"file": ("河南志愿填报指南.txt", f, "text/plain")},
    )
print("upload:", r.status_code, r.json().get("msg"), "chunk_count =", r.json().get("data", {}).get("chunk_count"))
fid = r.json()["file_id"]

# 列表 / 详情
print("list total:", requests.get(B + "/api/knowledge/list", headers=hdr(admin)).json()["total"])
print("detail:", requests.get(B + f"/api/knowledge/detail/{fid}", headers=hdr(admin)).json()["status"])

# 检索（学生可调用）
hits = requests.get(B + "/api/knowledge/search", params={"query": "平行志愿怎么填报", "top_k": 3}, headers=hdr(student)).json()
print("search hits:", hits["total"] if "total" in hits else len(hits["data"]))
for h in hits["data"][:2]:
    print("   -", h["metadata"].get("filename"), "|", h["text"][:40].replace("\n", " "))

# AI 问答（带 RAG）
r = requests.post(B + "/api/ai/chat", json={"question": "河南本科批平行志愿怎么填报？", "use_rag": True, "top_k": 3})
print("chat:", r.status_code, "source =", r.json().get("source"), "sources =", r.json().get("sources"))
print("answer:", r.json().get("answer", "")[:120].replace("\n", " "))

# 删除
print("delete:", requests.delete(B + f"/api/knowledge/delete/{fid}", headers=hdr(admin)).json())
print("list after delete:", requests.get(B + "/api/knowledge/list", headers=hdr(admin)).json()["total"])
print("search after delete:", len(requests.get(B + "/api/knowledge/search", params={"query": "平行志愿"}, headers=hdr(student)).json()["data"]))

os.remove("_rag_test.txt")
print("RAG SMOKE DONE")
