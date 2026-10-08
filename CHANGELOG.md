# 更新日志（CHANGELOG）

## 版本对照表

| 版本 | 日期 | 分块策略 | 检索策略 | 交给 LLM 的上下文 | 状态 |
|---|---|---|---|---|---|
| **v2.0.0** | 2026-10-05 | 定长分块（500 字硬切，重叠 50） | 纯稠密向量检索（Chroma Top-K） | 500 字块（可能被切断） | ✅ Naive RAG 基线（补写） |
| **v2.1.0** | 2026-10-06 | **递归分块** `RecursiveCharacterTextSplitter`（500 / 50） | **混合检索**：稠密 + 稀疏 → **RRF 融合 k=60** | 500 字块（语义完整） | ✅ Advanced RAG |
| **v2.2.0** | 2026-10-07 | **父子块**：父块 500 字；子块 120 字（重叠 20） | 混合检索，**只索引子块**；子块命中 → 回填父块 | **父块**（500 字） | ✅ 已发布 |
| **v2.3.0** | 2026-10-08 | 父子块（不变） | 混合检索 + **Query 路由 + 防幻觉 Prompt** | 父块（经路由筛选） | ✅ 已发布 |
| **v2.3.1** | 2026-10-08 | 父子块（不变） | 混合检索 + **放宽路由 + 修正防幻觉拒答** | 父块（经路由筛选） | ✅ 已发布（热修复） |
| **v2.4.0** | 2026-10-08 | 父子块（不变） | **多路召回**：Query 分解 → 每条子查询混合检索 → 跨路 RRF 累加 → Rerank 精排 | 父块（经多路召回 + 精排） | ✅ 已发布 |
| **v2.4.1** | 2026-10-08 | 父子块（不变） | **检索前预处理**（重写/扩展/子查询）+ **模块化多路召回**（dense/bm25/hybrid 三通道） | 父块（经多路召回 + 精排） | ✅ 本次发布 |
| **v2.5.0** | 计划中 | 父子块 + 语义/标题感知切分 | 检索前 + 多路召回 + **BGE-Reranker 落地** + Text-to-SQL | 父块（经重排筛选） | 🔜 计划 |

---

## [2.4.1] - 2026-10-08 · 检索前预处理 + 模块化多路召回（课堂案例风格重构）

> 主题：按课堂案例（01_混合检索 / 02_多路召回 / 03_多路召回的封装 / 01_查询重写 / 02_查询扩展 / 03_子查询）
> 把「检索前」与「检索中」拆成两个独立模块，面向对象封装，并接入项目检索入口。

---

### 一、原有技术（v2.4.0）及缺陷

| 环节 | v2.4.0 的技术 | 存在的缺陷 |
|---|---|---|
| 检索前 | 只有 Query 分解（MULTI_QUERY_PROMPT），逻辑写在 `rag_service.py` 内部 | ① 缺少「查询重写」「查询扩展（Step-Back）」，口语化问题召回差；<br>② 预处理与检索耦合在一个文件，无法单独复用/替换 |
| 检索中 | 多路召回逻辑内联在 `rag_service.multi_route_search()` | ① 通道（稠密/稀疏）写死，新增数据源要改主文件（违反开闭原则）；<br>② 只有 RRF 一种融合方式；<br>③ 无法单测单个通道 |
| LLM 通道 | 只走本地 Ollama | 未接入 DashScope（课堂案例用的百炼 OpenAI 兼容接口） |

---

### 二、改进技术及对应代码位置

#### 1. 新建 `backend/app/services/retrieval.py`（检索中，模块化）

| 类 | 职责 |
|---|---|
| `ChannelRetriever` | 单路召回抽象基类（接口隔离 + 依赖倒置）：统一 `docs / fields / weight / texts` 与 `search()` 接口 |
| `DenseChannel` | 稠密向量通道：Embedding + 余弦相似度；**支持传入预计算向量**（复用 Chroma 已存向量，避免每次重编码全库） |
| `BM25Channel` | 稀疏关键词通道：jieba 分词 + BM25Okapi；小语料 IDF 为负时降级为「词命中计数」 |
| `HybridSearch` | 单 Query 双路 RRF 融合（对应 01_混合检索.py）；对外暴露 `name / weight / search`，可作为复合通道被 MultiRecall 编排（里氏替换） |
| `MultiRecall` | 多路召回编排：`rrf_fusion`（跨「子查询 × 通道」累加）/ `weight_fusion`（score × weight）/ `round_robin_fusion`（轮询曝光） |
| `get_embedding_model()` | 懒加载：`EMBEDDING_MODEL_PATH` 有值时用 sentence-transformers（课堂案例方式），否则复用项目 Ollama/DashScope embedding（`ProjectEmbedding`） |

设计原则落地：单一职责（每类只做一件事）、开闭（加通道不改编排）、里氏替换（HybridSearch 可当通道用）、
接口隔离（基类只暴露 `search`）、依赖倒置（通道依赖抽象 embedding 接口）、迪米特（编排层不碰通道内部）、
合成复用（MultiRecall 组合通道而非继承）。

#### 2. 新建 `backend/app/services/query_rewrite.py`（检索前）

| 类 | 职责 | 参数 |
|---|---|---|
| `QueryRewriter` | 查询重写：把口语化问题改写得更适合检索 | **temperature=0.0** |
| `QueryExpander` | 查询扩展（Step-Back）：生成更宽泛的查询补充背景 | **temperature=0.1** |
| `QueryDecomposer` | 子查询分解：复合问题拆成聚焦子问题 | **temperature=0.2** |
| `QueryPreprocessor` | 统一入口：按需组合三步 → 输出 `QueryBundle(all_queries)`（原始 Query 置顶 + 去重 + 限条数） | `max_queries=4` |

LLM 通道：统一走 DashScope OpenAI 兼容接口（`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`），
Key 从 `DASHSCOPE_API_KEY` 读取（`get_dashscope_key()`：环境变量优先，Windows 下补读注册表 Machine/User 作用域，
因为服务启动后才配置的环境变量 `os.getenv` 读不到）。

#### 3. 修改 `backend/app/services/rag_service.py`（对接）

| 函数 | 说明 |
|---|---|
| `_load_corpus_docs()` | 从 Chroma 取子块语料 + **已存向量**，转成 retrieval 模块需要的 `docs` 结构 |
| `build_multi_recall()` | 构建三通道：`DenseChannel(weight=1.0)` + `BM25Channel(weight=1.2)` + `HybridSearch(weight=1.0)` |
| `_recall()` | 检索中执行：模块化多路召回 → 内置多路召回 → 单路混合检索（逐级回落） |
| `_hit_from_channel()` | 把通道输出转换为项目内部 hit 结构，字段保持一致 |
| `search()` | **① 检索前** `QueryPreprocessor.process()` → **② 检索中** 多路召回 → **③ Rerank** → **④ 父子块回填** |

#### 4. 新增配置（`app/config.py`）

```python
QUERY_REWRITE_ENABLED          = 1     # 查询重写开关
QUERY_EXPANSION_ENABLED        = 1     # 查询扩展（Step-Back）开关
QUERY_DECOMPOSE_ENABLED        = 1     # 子查询分解开关
QUERY_PREPROCESS_MAX           = 4     # 送检索的 Query 条数上限
MULTI_RECALL_FUSION            = "rrf" # 融合策略：rrf / weight / round_robin
MULTI_RECALL_TOPK_PER_CHANNEL  = 20    # 每通道每 Query 候选数
```

#### 5. 降级策略

| 场景 | 处理 |
|---|---|
| 无 `DASHSCOPE_API_KEY` / DashScope 报错（如 403 免费额度用尽） | 自动回落**本地 Ollama** 完成重写/扩展/分解 |
| 本地 Ollama 也不可用 | 返回原始 Query（单路检索），`bundle.source="raw"` |
| 单个通道召回异常 | `MultiRecall` 跳过该通道，其他通道照常 |
| 模块化多路召回整体失败 | 回落内置 `multi_route_search()` → 再回落单路 `HybridRetrieval.search()` |
| 关闭 `MULTI_QUERY_ENABLED` | 直接走单路混合检索，链路不中断 |

---

### 三、验证流程

#### 1. 最小用例

```bash
cd backend
python test_query_preprocess_recall.py
```

实测输出（复合问题：「2025年河南考生报福州大学至诚学院计算机专业，学费和位次大概多少？」）：

```
【1】检索前
  重写后：2025年河南考生报福州大学至诚学院计算机专业学费及位次查询
  后退一步：2025年河南考生报考福州大学至诚学院计算机专业学费及位次情况如何？
  子查询1：2025年河南考生报考福州大学至诚学院计算机专业是否可行？
  子查询2：该专业2025年的学费标准是多少？
  子查询3：该专业在2025年的招生位次大概如何？
  最终送检索（source=ollama）：4 条（原始 Query 置顶）

【2】检索中：三通道（dense, bm25, hybrid），语料 4 条，复用预计算向量：是
  RRF / 加权 / 轮询 三种融合均正常返回 Top3

【3】v2.3.1 单路 vs v2.4.1 预处理 + 多路召回
  覆盖语义侧面数：v2.3.1 = 3/3，v2.4.1 = 3/3   [通过]
  （v2.4.1 三条全部 context_level=parent，学费/位次/学校三个侧面都召回）

【4】降级验证：关闭开关 → 仍返回 3 条 parent 结果    [通过]
```

#### 2. 接口端到端验证

```bash
POST /api/knowledge/upload     # 上传含 学校/学费/位次 三侧面的资料
GET  /api/knowledge/search?query=…&top_k=3
POST /api/ai/chat {"question":"…","use_rag":true,"top_k":3}
```

实测：

```
upload 200 子块 2
  1 parent | file_30_parent_0 | 福州大学至诚学院是独立学院，位于福建省福州市，2025年在河南本…
chat rag+llm | 2025年河南考生报福州大学至诚学院计算机专业，学费为23000元/年，对应位次约112000名。
```

#### 3. 回归验证

```bash
cd backend
python smoke_rag.py   # 登录 → 上传 → 检索 → RAG 问答 → 删除：全链路通过
python smoke_test.py  # 志愿推荐等 14 个业务接口：全部 200
```

> 环境提示：本机 `DASHSCOPE_API_KEY` 存在但**免费额度已用尽**（返回 403 `AllocationQuota.FreeTierOnly`），
> 因此预处理实际走了「DashScope 失败 → 本地 Ollama」的降级路径（实测生效）。
> 额度恢复/充值后无需改代码，会自动切回 DashScope。

---

### 四、后续演进方向（v2.5.0）

| 方向 | 说明 |
|---|---|
| **Rerank 落地** | 接入 BGE-Reranker / Cross-Encoder，在 `rerank()` 中实现二次排序（当前为 no-op） |
| 通道扩展 | 增加「标题通道」「政策条款通道」等数据源级通道，验证开闭原则 |
| 并行召回 | 多通道/多子查询并发执行，降低多路召回时延 |
| 子查询去重 | 语义相近的 Query 合并，避免重复加权 |
| Text-to-SQL 落地 | 把 `extract_sql_filters()` 的条件接到 MySQL |

---

## [2.4.0] - 2026-10-08 · 多路召回（Multi-Query Recall）：Query 分解 + 跨路 RRF 融合

> 主题：把「一条 Query 走一次混合检索」升级为「一条复杂 Query 拆成多条子查询、各走一次混合检索、再跨路 RRF 累加」，
> 解决复合问题（同时问学校 + 学费 + 位次）召回不全的问题。

---

### 一、原有技术（v2.3.1）及缺陷

| 环节 | v2.3.1 的技术 | 存在的缺陷 |
|---|---|---|
| Query 处理 | 用户原始问题**原样**送入混合检索 | ① 复合问题（「XX学校XX专业2025年学费和位次」）语义被平均，各侧面都召回不准；<br>② 一次 embedding 只能表达一个语义方向，多实体问题顾此失彼 |
| 召回路径 | 单条 Query → 稠密 + 稀疏 → 一条 RRF 融合链 | ① 只有 2 条排名列表参与融合，证据单薄；<br>② 只覆盖问题最突出的那一面，其他侧面掉出 Top-K |
| 精排 | 无 | RRF 之后直接取 Top-K，没有二次排序环节 |

---

### 二、改进技术及对应代码位置

#### 1. Query 分解（MULTI_QUERY_PROMPT + decompose_query）

| 项 | 内容 |
|---|---|
| 技术 | 用 LLM 把复杂问题拆成 3-4 条聚焦子查询，覆盖「学校 / 专业 / 年份 / 省份 / 学费 / 位次 / 分数线 / 选科 / 批次」不同语义单元，保留关键实体 |
| 代码位置 | **`backend/app/services/rag_service.py`** → `MULTI_QUERY_PROMPT`、`decompose_query()`、`MAX_SUB_QUERY_LEN` |
| 参数 | **temperature=0.0**（要稳定可复现），`num_predict=120` |
| 输出格式 | 严格 JSON：`{"queries": ["子查询1", ...]}` |
| 完整处理链 | LLM 生成 → JSON 容错解析（截取 `{...}`）→ 去空值 → 去超长（>30 字）→ 去重 → **原始 Query 置顶** → 限条数（默认 4，含原始 Query） |
| **降级** | AI 关闭 / 开关关闭 / LLM 超时 / JSON 解析失败 / 清洗后为空 → 返回 `[原始 Query]`，按单路检索处理 |

#### 2. 多路召回（multi_route_search）

| 项 | 内容 |
|---|---|
| 技术 | 每条子查询**独立**走「稠密(Chroma ANN) + 稀疏(BM25)」两路，共 `2 × 子查询数` 条排名列表；按 doc_id 合并去重，**跨路累加** RRF：`score += 1/(60 + rank)` |
| 代码位置 | **`backend/app/services/rag_service.py`** → `multi_route_search()` |
| 返回 | Top-K 候选池，附带 `rrf_score` / `dense_rank` / `bm25_rank` / `matched_queries`（命中它的子查询）/ `recall_mode="multi_route"` |
| **降级** | 单条子查询检索异常跳过该路；全部失败返回 `[]`，由 `search()` 回落单路混合检索 |

#### 3. Rerank 精排钩子

| 项 | 内容 |
|---|---|
| 技术 | `rerank(query, hits)`：预留 BGE-Reranker / Cross-Encoder 二次排序入口 |
| 代码位置 | **`backend/app/services/rag_service.py`** → `rerank()` |
| 当前行为 | `settings.RERANK_MODEL` 为空 → **no-op 原样返回**（不中断链路）；接入模型后在此实现重排 |

#### 4. search() 串联完整流程

| 项 | 内容 |
|---|---|
| 代码位置 | **`backend/app/services/rag_service.py`** → `search(query, top_k, use_multi_route=True)` |
| 流程 | ① 多路召回 `multi_route_search()` → ② 空结果回落 `HybridRetrieval.search()` 单路 → ③ `rerank()` 精排 → ④ `_expand_to_parents()` 父子块回填 → ⑤ 关键词兜底 |

#### 5. 配置项（`backend/app/config.py` + `.env`）

```python
MULTI_QUERY_ENABLED       = 1      # 多路召回总开关
MULTI_QUERY_MAX           = 4      # 子查询条数上限（含原始 Query）
MULTI_QUERY_CANDIDATE_N   = 20     # 每条子查询每路召回候选数
RERANK_MODEL              = ""     # 留空表示不启用 Rerank（当前）
```

---

### 三、验证流程

#### 1. 最小用例

```bash
cd backend
python test_multi_query.py
```

实测输出（复杂问题：「2025年河南考生报福州大学至诚学院计算机专业，学费和位次大概多少？」）：

```
【1】Query 分解（MULTI_QUERY_PROMPT, temperature=0.0）
    1. 2025年河南考生报福州大学至诚学院计算机专业，学费和位次大概多少？  (原始 Query)
    2. 2025年河南福州大学至诚学院计算机专业学费
    3. 2025年河南福州大学至诚学院计算机专业位次
    4. 2025年河南福州大学至诚学院计算机专业分数线
  [通过] 原始 Query 保留 + 子查询非空且 ≤30 字

【2】降级验证：开关关闭时返回 [原始 Query]   [通过]

【3】单路检索 vs 多路召回（Top-3）
  -- 单路（v2.3.x）--   RRF 0.03279 / 0.03175 / 0.03175
  -- 多路召回（v2.4.0）-- RRF 0.13088 / 0.12827 / 0.12751（8 条排名列表累加）
  单路覆盖侧面数：3/3    多路覆盖侧面数：3/3   [通过]

【4】完整流程 search()：多路 → RRF → Rerank → 父块回填
  1. [parent] file_9101_parent_2 77 字 | 福州大学至诚学院2025年在河南…（位次）
  2. [parent] file_9101_parent_0 60 字 | …独立学院，位于福建省福州市…（学校）
  3. [parent] file_9101_parent_1 52 字 | …学费标准为23000元/年（学费）
  [通过] 返回父块上下文（小块命中、大块生成）
```

> 关键对照：**同一 Top-3，多路召回的 RRF 分数从 0.032 量级提升到 0.13 量级**（4 条子查询 × 2 条路 = 8 条排名列表累加），
> 被多条子查询共同命中的文档显著胜出。

#### 2. 接口端到端验证

```bash
POST /api/knowledge/upload            # 上传含 学校/学费/位次 三个侧面的资料
GET  /api/knowledge/search?query=2025年河南考生报福州大学至诚学院计算机专业，学费和位次大概多少？&top_k=3
POST /api/ai/chat {"question":"…","use_rag":true,"top_k":3}
```

实测：

```
upload 200 子块 2
  1 parent | RRF 0.1304 | 福州大学至诚学院是独立学院，位于福建省福州市，2025年在河南本科批…
  2 parent | RRF 0.1258 | …
chat rag+llm | …学费标准为23000元/年，投档最低分458分，对应位次…
```

#### 3. 回归验证

```bash
cd backend
python smoke_rag.py              # 登录 → 上传 → 检索 → RAG 问答 → 删除：全链路通过
python smoke_test.py             # 志愿推荐等 14 个业务接口：全部 200
python test_anti_hallucination.py # 路由 + 防幻觉用例：全部通过
python test_parent_child.py       # 父子块用例：全部通过
python test_hybrid_search.py      # 混合检索对比用例：全部通过
```

---

### 四、后续演进方向（v2.5.0）

| 方向 | 说明 |
|---|---|
| **Rerank 落地** | 接入 BGE-Reranker / Cross-Encoder，在 `rerank()` 中实现二次排序（当前为 no-op） |
| 子查询并行化 | 多条子查询的 embedding 与检索改为并发，降低多路召回的时延 |
| 子查询去重优化 | 语义相近的子查询合并，避免同一语义被重复加权 |
| Text-to-SQL 落地 | 把 `extract_sql_filters()` 的条件真正接到 MySQL |
| BM25 索引持久化 | 语料到十万级时改为 pickle 持久化 + 增量更新 |

---

## [2.3.1] - 2026-10-08 · 热修复：修正路由误拦截与防幻觉误拒答

> 主题：v2.3.0 上线后，发现「高考核心业务问题」被过度拦截/拒答
> （如「2025河南在福建招生的院校」「福州大学至诚学院计算机专业学费」均被误判为无关或拒答）。
> 本次热修复放宽路由判定、修正防幻觉 Prompt、调整降级策略与采样参数。

---

### 一、原有技术（v2.3.0）及缺陷

| 环节 | v2.3.0 的技术 | 存在的缺陷 |
|---|---|---|
| Query 路由 | `ROUTER_PROMPT` 关键词列表偏窄，仅含「高考志愿、院校报考、专业选择、分数线、学费、位次」 | ① 跨省招生计划问题（如「2025河南在福建招生的院校」）未命中关键词，被误判为 NO 拦截；<br>② Qwen3-1.7B 对长尾高考问题判定能力弱，容易漏判 |
| 防幻觉 Prompt | `ANTI_HALLUCINATION_PROMPT` 使用「绝对铁律」+ `top_p=0.1` | ① 过度保守，上下文有数据时模型也不敢生成，直接套用拒答话术；<br>② 「找不到就拒答」被过度触发，导致「福州大学至诚学院计算机专业学费」被误拒 |
| 未命中降级 | `ai.py` 中「未检索到资料」时强制返回拒答话术 | ① 用户得不到任何有用信息；<br>② 高考核心问题只要召回失败就一律拒答，体验差 |
| 降级策略 | LLM 调用失败才放行 | 实际故障是「模型判错」而非「调用失败」，拦截逻辑无法兜住 |

---

### 二、改进技术及对应代码位置

#### 1. 放宽 Query 路由判定

| 项 | 内容 |
|---|---|
| 技术 | 扩展 `ROUTER_PROMPT`：新增「高考、招生、录取、选科、批次、投档、调剂」等关键词；改为「**满足任意一条即为 YES**」；明确「询问某所学校/专业」「询问某省某年招生计划」也算 YES |
| 代码位置 | **`backend/app/services/rag_service.py`** → `ROUTER_PROMPT` |
| 参数 | 不变（**temperature=0.0**，**max_tokens=5**） |
| 同步 | `OFF_TOPIC_ANSWER` 话术同步为放宽后的口径 |

#### 2. 修正防幻觉 Prompt

| 项 | 内容 |
|---|---|
| 技术 | 「绝对铁律」→「回答规则」：有资料就**直接、完整**回答并原样引用数字；只有上下文**完全没有**相关信息时才拒答；仍禁止编造不存在数字 |
| 代码位置 | **`backend/app/services/rag_service.py`** → `ANTI_HALLUCINATION_PROMPT`、`generate_answer()` |
| 签名 | `generate_answer(query, context, temperature=0.1, top_p=0.3)` |
| 参数 | **temperature=0.1**，**top_p 由 0.1 放宽到 0.3** |

#### 3. 修正未命中降级策略

| 项 | 内容 |
|---|---|
| 技术 | `ai.py` 中「未检索到资料」时**不再强制拒答**，改为让模型基于通用知识给**方向性建议**（查学校官网 / 省教育考试院），但**禁止编造具体数字** |
| 代码位置 | **`backend/app/routers/ai.py`** → `chat()` 未命中分支 |
| 调用 | `rag_service.generate_answer(question, rag_snippets, temperature=0.1, top_p=0.3)` |

---

### 三、验证流程

#### 1. 最小用例

```bash
cd backend
python test_anti_hallucination.py
```

实测输出（修正后）：

```
【1】Query 意图路由（ROUTER_PROMPT, temperature=0.0, max_tokens=5）
  [通过] route_query(婚假几天)                       期望 拦截 → 实际 拦截
  [通过] route_query(今天天气怎么样)                 期望 拦截 → 实际 拦截
  [通过] route_query(2025河南在福建招生的院校)       期望 放行 → 实际 放行   ← v2.3.1 修正
  [通过] route_query(福州大学至诚学院计算机专业学费) 期望 放行 → 实际 放行   ← v2.3.1 修正
  [通过] route_query(河南本科批志愿怎么填报)         期望 放行 → 实际 放行
  [通过] route_query(郑州大学计算机专业学费多少)     期望 放行 → 实际 放行

【2】上下文【有】学费（temperature=0.1, top_p=0.3）
  回答：福州大学至诚学院计算机科学与技术专业2025年在河南本科批物理类招生的学费标准为23000元/年。
  [通过] 回答中出现上下文里的真实学费 23000
  [通过] 没有误触发拒答话术                                                ← v2.3.1 修正

【3】上下文【无】学费 → 拒答/引导，且不编造数字
  回答：根据现有资料，未查询到具体信息，建议查阅学校官方招生简章。
  [通过] 按话术引导    [通过] 没有编造数字

【4】对照：v2.2.0 通用 Prompt（temperature=0.3, top_p=0.85）
  回答：郑州大学计算机科学与技术专业学费一般为**8000元/年**（编造）
【5】结构化提取：{'school_name':'郑州大学','major_name':'计算机科学与技术','year':2025,'province':'河南省'}
```

#### 2. 接口端到端验证

```bash
POST /api/ai/chat {"question":"2025河南在福建招生的院校有哪些？","use_rag":true}
POST /api/ai/chat {"question":"福州大学至诚学院计算机专业学费是多少？","use_rag":true}
POST /api/ai/chat {"question":"婚假几天","use_rag":true}
```

实测：

```
upload 200 子块 1
--- 2025河南在福建招生的院校有哪些？
    rag+llm | （放行，不再被拦截；知识库无该校数据时按规则引导）
--- 福州大学至诚学院计算机专业学费是多少？
    rag+llm | 福州大学至诚学院计算机专业学费标准为23000元/年。
--- 婚假几天
    router_blocked | 抱歉，我是高考志愿填报助手，只回答与【高考、志愿填报、院校…】相关的问题
```

#### 3. 回归验证

```bash
cd backend
python smoke_rag.py    # 登录 → 上传 → 检索 → RAG 问答 → 删除：全链路通过
                       # chat 仍返回 source=rag+llm + sources（相关问题正常放行）
python smoke_test.py   # 志愿推荐等 14 个业务接口：全部 200
```

---

### 四、后续演进方向（v2.4.0）

| 方向 | 说明 |
|---|---|
| **Rerank 重排** | 在 RRF 之后接入 BGE-Reranker 二次排序 |
| **Text-to-SQL 落地** | 把 `extract_sql_filters()` 提取的条件真正接到 MySQL（学费/分数线/位次走结构化查询） |
| 查询改写 | 多轮对话时先让 Qwen3 改写查询再做检索 |
| 表格结构化处理 | 将分数线表格转为自然语言三元组后再切块 |
| BM25 索引持久化 | 语料到十万级时改为 pickle 持久化 + 增量更新 |

---

## [2.3.0] - 2026-10-08 · Query 路由与防幻觉 Prompt：解决无关问答与学费幻觉

> 主题：在 v2.2.0 父子块基础上，增加 Query 意图路由与生成侧强约束，解决「婚假乱答」与「学费编造」两大幻觉问题。

---

### 一、原有技术（v2.2.0）及缺陷

| 环节 | v2.2.0 的技术 | 存在的缺陷 |
|---|---|---|
| Query 处理 | 所有问题直接进入 RAG 检索 | ① 无关问题（如「婚假几天」）强行检索知识库，LLM 生成无关回答；<br>② 没有意图分类，浪费检索资源 |
| 生成约束 | 通用 Prompt「请根据上下文回答」 | ① Qwen3-1.7B 参数量小，指令遵循能力弱；<br>② 上下文中找不到数字时，模型调用预训练常识编造（实测把学费编造成 8000 元/年）；<br>③ 没有拒答机制 |
| 结构化数据 | 学费、分数线等也走 RAG | ① 强结构化数据走 RAG 容易召回失败；<br>② 应优先走 MySQL 查询 |

---

### 二、改进技术及对应代码位置

#### 1. Query 路由与意图分类

| 项 | 内容 |
|---|---|
| 技术 | 在 RAG 检索前，单独调用 LLM 做二分类（YES/NO） |
| 代码位置 | **`backend/app/services/rag_service.py`** → `ROUTER_PROMPT`、`route_query()`、`OFF_TOPIC_ANSWER` |
| 调用位置 | **`backend/app/routers/ai.py`** → `/api/ai/chat` 入口处（`use_rag=true` 时先路由再检索） |
| 参数 | **temperature=0.0**，**max_tokens=5**（`num_predict=5`） |
| 降级策略 | LLM 调用失败 / AI 关闭 / 返回为空 → 默认**放行**（走 RAG），不中断链路 |

#### 2. 防幻觉 Prompt 强约束

| 项 | 内容 |
|---|---|
| 技术 | Prompt 中加入「绝对铁律」：唯一信息源是检索上下文、禁止编造数字、找不到就拒答 |
| 代码位置 | **`backend/app/services/rag_service.py`** → `ANTI_HALLUCINATION_PROMPT`、`generate_answer()` |
| 调用位置 | **`backend/app/routers/ai.py`** → 命中资料后调用；未命中资料时在通用 Prompt 后追加拒答指令 |
| 参数 | **temperature=0.1**，**top_p=0.1** |
| 拒答话术 | “根据现有资料，未查询到具体信息，建议查阅学校官方招生简章。” |
| 返回值 | `source="router_blocked"`（拦截）/ `"rag+llm"`（正常），并新增 `context_level` 标明父块/子块 |

#### 3. 结构化数据提取（预留）

| 项 | 内容 |
|---|---|
| 技术 | Query 含「学费/分数线/位次」等强结构化关键词时，用 LLM 提取 JSON 条件，后续走 MySQL |
| 代码位置 | **`backend/app/services/rag_service.py`** → `SQL_EXTRACT_PROMPT`、`extract_sql_filters()`、`STRUCTURED_KEYWORDS` |
| 参数 | **temperature=0.0** |
| 状态 | 已能正确提取 JSON，实际 Text-to-SQL 查询留到 v2.4.0 落地 |

#### 4. 配套改动

| 文件 | 改动 |
|---|---|
| `backend/app/services/ai_service.py` | `ask()` 增加 `temperature` / `top_p` 可选参数（默认 0.3 / 0.85），支持按场景指定采样策略 |

---

### 三、验证流程

#### 1. 最小用例

```bash
cd backend
python test_anti_hallucination.py
```

实测输出：

```
【1】Query 意图路由（ROUTER_PROMPT, temperature=0.0, max_tokens=5）
  [通过] route_query(婚假几天)              期望 拦截 → 实际 拦截
  [通过] route_query(今天天气怎么样)        期望 拦截 → 实际 拦截
  [通过] route_query(河南本科批志愿怎么填报) 期望 放行 → 实际 放行
  [通过] route_query(郑州大学计算机专业学费多少) 期望 放行 → 实际 放行

【2】上下文【有】学费（temperature=0.1, top_p=0.1）
  回答：…学费标准为5700元/学年。
  [通过] 回答中出现上下文里的真实学费 5700

【3】上下文【无】学费 → 必须拒答
  回答：根据现有资料，未查询到具体信息，建议查阅学校官方招生简章。
  [通过] 按话术拒答   [通过] 没有编造数字

【4】对照：v2.2.0 通用 Prompt（temperature=0.3, top_p=0.85）
  回答：郑州大学计算机科学与技术专业学费一般为**8000元/年**…
  [通过] v2.2.0 会编造数字（说明改造必要性）

【5】结构化提取预留（SQL_EXTRACT_PROMPT, temperature=0.0）
  {'school_name': '郑州大学', 'major_name': '计算机科学与技术', 'year': 2025, 'province': '河南省'}
```

> 关键对照：同一问题「学费多少」，v2.2.0 编造 **8000 元/年**，v2.3.0 有资料时给 **5700 元/学年**（真实值）、无资料时拒答。

#### 2. 接口端到端验证

```bash
POST /api/ai/chat {"question":"婚假几天","use_rag":true}
POST /api/knowledge/upload            # 上传含学费的招生资料
POST /api/ai/chat {"question":"郑州大学计算机科学与技术专业学费是多少？","use_rag":true,"top_k":3}
```

实测：

```
health 200
婚假几天 -> 200 router_blocked | 抱歉，我是高考志愿填报助手，只回答与【高考志愿…】相关的问题
upload 200 子块 1
学费提问 -> rag+llm parent | 根据现有资料，郑州大学计算机科学与技术专业2025年在河南本科批物理类招生的学费标准为5700元/学年。
sources ['河南招生计划2025.txt']
```

#### 3. 回归验证

```bash
cd backend
python smoke_rag.py    # 登录 → 上传 → 检索 → RAG 问答 → 删除：全链路通过
                       # chat 仍返回 source=rag+llm + sources（相关问题正常放行）
python smoke_test.py   # 志愿推荐等 14 个业务接口：全部 200
```

---

### 四、后续演进方向（v2.4.0）

| 方向 | 说明 |
|---|---|
| **Rerank 重排** | 在 RRF 之后接入 BGE-Reranker 二次排序 |
| 查询改写 | 多轮对话时先让 Qwen3 改写查询再做检索 |
| **Text-to-SQL 落地** | 把 `extract_sql_filters()` 提取的条件真正接到 MySQL（学费/分数线/位次走结构化查询） |
| 表格结构化处理 | 将分数线表格转为自然语言三元组后再切块 |
| BM25 索引持久化 | 语料到十万级时改为 pickle 持久化 + 增量更新 |
| docstore 入 MySQL | 父块量大时把 JSON docstore 换成 `knowledge_parent_chunks` 表 |

---

## [2.2.0] - 2026-10-07 · 父子块检索（Parent-Child Chunking）：小块命中、大块生成

> 主题：在 v2.1.0 的「递归分块 + BM25/RRF 混合检索」基础上叠加父子块结构。
> 检索单元从 500 字缩小到 120 字（更聚焦），生成上下文仍用 500 字父块（更完整）。

---

### 一、原有技术（v2.1.0）及缺陷

| 环节 | v2.1.0 的技术 | 存在的缺陷 |
|---|---|---|
| 分块与索引 | 递归分块得到的 500 字块**直接**进向量库，检索单元 = 生成单元 | ① **检索粒度粗**：500 字块里塞了多个话题，短查询（「婚假几天」）的语义被无关内容稀释；<br>② **两难困境**：块调小 → 检索准但喂给 LLM 的上下文不完整；块调大 → 上下文全但召回不准；<br>③ 命中块里可能缺少答案的补充条件（如「需提前 5 个工作日申请」） |
| 检索召回 | 稠密(Chroma) + 稀疏(BM25) → RRF 融合 k=60 | 混合检索已解决"字面量查不准"，但对"同一块内多话题稀释"无能为力 |
| 上下文完整度 | 直接用命中块 | 若缩小块以提升精度，上下文必然被截断；二者不可兼得 |

---

### 二、改进技术及对应代码位置

#### 1. 父子块结构（Parent-Child Chunking）

| 项 | 内容 |
|---|---|
| 父块 | 递归分块得到的 **500 字**块（语义完整，**只存 docstore，不进向量库**） |
| 子块 | 父块内部再切一次的 **120 字**小块（重叠 20），**只有子块进向量库** |
| ID 关联 | 父块 `file_{file_id}_parent_{父块序号}`；子块 `file_{file_id}_chunk_{父块序号}_{子块序号}`，子块 metadata 带 `parent_chunk_id` |
| 检索流程 | 子块参与混合检索（BM25 + RRF 路径完全沿用 v2.1.0）→ 命中子块 → 按 `parent_chunk_id` 从 docstore 取回父块 → 父块交给 LLM |
| 代码位置 | **`backend/app/services/rag_service.py`** |
| - 常量 | `CHILD_CHUNK_SIZE=120`、`CHILD_CHUNK_OVERLAP=20`、`PARENT_STORE_FILE="parent_store.json"` |
| - 子块切分 | `split_child_text()`（递归分块，依赖缺失时退化为定长切分） |
| - docstore | `_load_parent_store()` / `_save_parent_store()` / `put_parents()` / `get_parent()` / `drop_parents_by_file()`（JSON 落盘在 `backend/chroma_db/parent_store.json`，已在 .gitignore） |
| - 写入 | `add_documents()`：入参 chunks 视为父块 → 父块写 docstore + 子块写向量库（返回子块数） |
| - 删除 | `delete_by_file()`：先 `drop_parents_by_file()` 清父块，再删向量库子块，避免孤儿数据 |
| - 回填 | `_expand_to_parents()`：子块 → 父块，**同一父块的多个子块去重合并** |
| - 检索入口 | `search()`：混合检索结果经 `_expand_to_parents()` 后再返回（含关键词兜底路径） |
| 降级策略 | 父块缺失 / docstore 损坏 / 旧数据无 `parent_chunk_id` → 直接返回子块并标记 `context_level="child"`，**链路不中断** |

#### 2. 接口字段

| 文件 | 改动 |
|---|---|
| `backend/app/schemas/knowledge.py` | `ChunkHit` 新增 `parent_chunk_id`（命中子块所属父块 ID）、`context_level`（`parent`=父块 / `child`=子块降级） |
| `backend/app/routers/knowledge.py` | `/api/knowledge/search` 透出 `parent_chunk_id` 与 `context_level` |

#### 3. 依赖

无新增依赖（复用 v2.1.0 的 `langchain-text-splitters` / `rank-bm25` / `jieba`）。

---

### 三、验证流程

#### 1. 最小用例（脚本已入库）

```bash
cd backend
python test_parent_child.py
```

实测输出（查询「婚假几天」，语料：招生政策 / 假期制度（干扰项） / 考勤办法（正确答案被无关内容包围））：

```
【v2.1.0】向量库 = 3 个 500 字大块（无父子结构）
  1. [RRF 0.03279] 上下文 159 字 | 学校教职工考勤管理办法…

【v2.2.0】向量库 = 6 个 120 字子块，docstore = 3 个父块
  -- 命中的子块（仅用于检索）--
    1. 116 字 | 学校教职工考勤管理办法：…教职工婚假为10天…
    2. 43 字  | 。婚假申请流程：需在休假前5个工作日提交书面申请…
  -- 回填父块后交给 LLM 的上下文 --
    1. [parent] file_9002_parent_2 上下文 159 字
    2. [parent] file_9002_parent_1 上下文 123 字

对比结果（查询「婚假几天」）
  A) v2.1.0 直接用大块检索     → Top1 159 字，命中「婚假」=是
  B) v2.2.0 命中的子块（检索用）→ Top1 116 字，命中「婚假」=是，含审批条件「5个工作日」=否
  C) v2.2.0 回填父块（交给LLM）→ Top1 159 字，粒度=parent，命中「婚假」=是，含审批条件「5个工作日」=是

  关键差异：B 只看到「婚假10天」这 116 字，C 通过父块拿回了同一段落里的
           「5个工作日提交申请」等完整条件 —— 即『小块命中、大块生成』。
  去重收益：3 个命中子块中有多个属于同一父块，回填后合并为 2 条，避免上下文重复。

降级验证：清空 docstore 后，应直接返回子块且不报错
  1. [child] 116 字   2. [child] 43 字   3. [child] 84 字
  降级后仍返回 3 条，链路未中断 ✅
```

#### 2. 接口端到端验证（真实服务）

```bash
# 1) 登录
POST /api/auth/login {username: admin, password: admin123}
# 2) 上传（父块写 docstore + 子块写向量库）
POST /api/knowledge/upload
# 3) 检索 → 返回父块上下文
GET  /api/knowledge/search?query=婚假几天&top_k=3
# 4) 删除（子块 + 父块一起清）
DELETE /api/knowledge/delete/{file_id}
```

实测：

```
upload 200 child_chunk_count= 3        # 3 个子块进向量库（父块另存 docstore）
  1 | parent | file_17_parent_0 | 上下文 225 字 | 学校教职工考勤管理办法…
delete 删除成功
docstore 残留 file_17：[]              # 父块随文件一并清理
```

#### 3. 回归验证

```bash
cd backend
python smoke_test.py    # 志愿推荐等 14 个业务接口：全部 200
python smoke_rag.py     # 登录 → 上传 → 检索 → RAG 问答 → 删除：全链路通过
                        # chat 仍返回 source: "rag+llm" + sources
```

- 权限隔离不变：upload/list/detail/download/delete 仅 admin，search 对登录用户开放
- v2.1.0 之前上传的历史数据没有 `parent_chunk_id` → 自动走降级分支返回子块，**不会报错**

---

### 四、后续演进方向（v2.3.0）

| 方向 | 说明 |
|---|---|
| **Rerank 重排** | 在 RRF 之后接入 Cross-Encoder / BGE-Reranker 二次排序，进一步提精 |
| 查询改写 | 多轮对话时先让 Qwen3 改写查询再做检索 |
| 语义/标题感知切分 | 父块按 Markdown 标题或语义相似度切分，而非纯递归字符切分 |
| BM25 索引持久化 | 语料到十万级时改为 pickle 持久化 + 增量更新 |
| docstore 入 MySQL | 父块量大时把 JSON docstore 换成 `knowledge_parent_chunks` 表 |

---

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
