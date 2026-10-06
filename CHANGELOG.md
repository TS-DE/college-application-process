# 更新日志（CHANGELOG）

## [2.1.0] - 2026-10-06 · RAG 管线进阶：递归分块 + 混合检索（Hybrid Search）

> 主题：让「高考政策 / 志愿填报技巧」类问答从 **Naive RAG** 升级到 **Advanced RAG（混合检索）**。
> 技术栈不变：FastAPI + Vue3 + Chroma + Ollama Qwen3 1.7B。

---

### 一、原有技术及缺陷

| 环节 | 改造前的技术 | 存在的缺陷 |
|---|---|---|
| 文档分块 | **固定大小分块**（定长滑动窗口）：`utils/file_utils.py::split_text`，按 500 字硬切、重叠 50 字 | ① 从句子中间切断，一条政策被劈成两半，两半都不完整；<br>② 忽略 PDF 原有的段落/换行结构，相邻语义被强行拆散；<br>③ 检索时单块语义不完整 → embedding 质量下降、召回不准 |
| 检索召回 | **纯稠密向量检索**：Chroma `collection.query(query_embeddings=...)` 取 Top-K | ① 精确匹配差：专业代码（`080901`）、批次名、`48个志愿` 这类**字面量**查不准；<br>② 短查询（如「婚假几天」「计算机专业代码」）语义信号弱，容易被语义相近但答非所问的块挤掉；<br>③ 实测「计算机专业代码」Top1 命中的是完全无关的「婚假」块 |
| 结果融合 | 无 | 单一路召回，没有互补机制 |
| 可观测性 | 只返回 `text / metadata / distance` | 无法判断某一路召回是否失效，线上难排查 |

---

### 二、改进技术及对应代码位置

#### 1. 递归分块（Recursive Splitting）—— 任务一

| 项 | 内容 |
|---|---|
| 技术 | `langchain_text_splitters.RecursiveCharacterTextSplitter` |
| 参数 | `chunk_size=500`、`chunk_overlap=50`、`separators=["\n\n", "\n", "。", "，"]` |
| 代码位置 | **`backend/app/services/rag_service.py`** → `split_text()`、`SEPARATORS`、`_split_text_fixed()` |
| 调用方 | **`backend/app/routers/knowledge.py`** → 上传接口 `split_text` 的 import 由 `utils.file_utils` 改为 `services.rag_service` |
| 兜底 | `langchain_text_splitters` 未安装时自动退化为定长切分 `_split_text_fixed()`，上传链路不中断 |

> 分隔符优先级含义：段落 `\n\n` → 换行 `\n` → 句号 `。` → 逗号 `，`。
> 递归地用下一级分隔符继续切超长块，直到每块 ≤ 500 字，因此**不会把句子从中间切断**。

#### 2. 混合检索（Hybrid Search）+ RRF 融合 —— 任务二

| 项 | 内容 |
|---|---|
| 稠密路 | Chroma 自带 ANN 向量检索（`nomic-embed-text` 768 维） |
| 稀疏路 | `rank_bm25.BM25Okapi` + `jieba` 中文分词 |
| 融合 | **RRF（倒数排名融合），k = 60** |
| 代码位置 | **`backend/app/services/rag_service.py`** → `class HybridRetrieval`（`dense_search` / `bm25_search` / `rrf` / `search` / `_token_overlap_search`）、常量 `RRF_K = 60`、重写后的 `search()` |
| 结构对照 | 对应《混合检索》文档「代码三：封装成类」：`dense_search≈bgeChou`、`bm25_search≈bm25Xi`、`rrf≈rrf`、`search≈get_rrf` |
| 降级策略 | 只有稠密 → 纯向量；只有 BM25 → 关键词；两路都无 → 老的 `_keyword_fallback`；Chroma 不可用 → 关键词兜底（链路永不中断） |
| 小语料修复 | `rank_bm25` 的 IDF 在语料很小时为负 → 增加 `_token_overlap_search()`（词命中计数）兜底，避免稀疏路整体失效 |
| 接口字段 | **`backend/app/schemas/knowledge.py`** → `ChunkHit` 新增 `rrf_score` / `dense_rank` / `bm25_rank`；**`backend/app/routers/knowledge.py`** → `/api/knowledge/search` 返回这三个字段 |

**RRF 计算过程（k=60）**

```
score(doc) = Σ 1 / (k + rank_i)
  1) 稠密路、稀疏路各自召回 Top-N（默认 20），得到各自的名次表 {doc: rank}
  2) 取两路并集作为候选池（去重）
  3) 逐文档累加：1/(60+稠密名次) + 1/(60+稀疏名次)
  4) 按总分降序 → 取 Top-K
```
k=60 用来压平前几名的分数差（无 k 时第 1 名 1.0、第 2 名 0.5 差距过大），
让「两路都还行」的文档压过「一路第一、另一路垫底」的文档；
用**排名**而非分数，是因为向量距离与 BM25 得分量纲不同，无需归一化即可融合。

#### 3. 依赖变更

`backend/requirements.txt` 新增：

```
langchain-text-splitters>=0.3
rank-bm25>=0.2.2
jieba>=0.42.1
```

---

### 三、验证流程

#### 1. 分块验证

```bash
cd backend
python -c "
from app.services.rag_service import split_text
text = '第一条 本科批实行平行志愿。\n\n第二条 考生可填报48个院校专业组志愿……'
print(len(split_text(text)), split_text(text))
"
```
结果：单块 ≤ 500 字，且块尾落在「。」等自然断句处，不再从句子中间切断。

#### 2. 混合检索对比（最小用例，脚本已入库）

```bash
cd backend
python test_hybrid_search.py
```

实测输出（查询「计算机专业代码」，知识库 5 个块，只有 1 块含 `080901`）：

| 排名 | 纯向量检索（改造前） | BM25 稀疏路 | 混合检索（RRF k=60） |
|---|---|---|---|
| 1 | ❌ 婚假 10 天（完全无关） | 电子信息工程 | ✅ **计算机科学与技术专业代码 080901** |
| 2 | 计算机科学与技术…080901 | 计算机科学与技术…080901 | 电子信息工程 |
| 3 | 河南招生计划…080901 | 河南招生计划…080901 | 河南招生计划…080901 |

```
纯向量 Top1 命中含专业代码的块：否
混合检索 Top1 命中含专业代码的块：是
```
RRF 分数示例：`稠密第2名 + BM25第2名 → 1/62 + 1/62 = 0.03226`；
`稠密第4名 + BM25第1名 → 1/64 + 1/61 = 0.03202` —— 均衡者胜出，符合 RRF 设计预期。

#### 3. 接口端到端验证（真实服务）

```bash
# 1) 登录取 Token
POST /api/auth/login  {username: admin, password: admin123}
# 2) 上传（自动递归分块 + 向量化）
POST /api/knowledge/upload   →  chunk_count = 1，status = 已向量化
# 3) 检索
GET  /api/knowledge/search?query=计算机专业代码&top_k=3
# 4) 删除
DELETE /api/knowledge/delete/{file_id}
```

实测返回（已带融合信息）：

```
upload 200 chunk_count= 1
--- 查询: 计算机专业代码
   1 RRF 0.03279 | 稠密 1 | BM25 1 | 河南省2025年普通高校招生志愿填报指南…
--- 查询: 婚假几天
   1 RRF 0.03279 | 稠密 1 | BM25 1 | …
delete 删除成功
```

#### 4. 回归验证

```bash
cd backend
python smoke_test.py    # 志愿推荐等 14 个业务接口：全部 200
python smoke_rag.py     # 登录 → 上传 → 向量化 → 检索 → RAG 问答 → 删除：全链路通过
```

- `/api/ai/chat`（`use_rag=true`）仍返回 `source: "rag+llm"` 与 `sources`，混合检索对上层调用**无感替换**
- 权限隔离不变：upload/list/detail/download/delete 仅 admin，search 对登录用户开放

---

### 四、后续可继续演进的方向

| 方向 | 说明 |
|---|---|
| Rerank 重排 | 在 RRF 之后接入 Cross-Encoder / BGE-Reranker 二次排序 |
| 查询改写 | 多轮对话时先让 Qwen3 改写查询再做检索 |
| BM25 索引持久化 | 语料到十万级时改为 pickle 持久化 + 增量更新，避免每次全量 `get()` |
| 父子块 | 小块检索、返回大块上下文，兼顾精度与完整度 |
