# 高考志愿填报系统（河南 2024-2025）+ RAG 知识库

基于河南 2024-2025 年高考录取数据，构建「冲 / 稳 / 保」三档志愿推荐系统，
并在其上扩展了独立的 **RAG 知识库模块**（Chroma 向量库 + Ali 大模型 + 本地 Ollama 兜底）。

核心分工：

- **规则引擎负责计算**：分数 → 位次换算、分档、筛选过滤、概率估算
- **本地大模型负责理解与表达**：自然语言意图解析、推荐理由生成、知识库问答
- **RAG 负责政策类问答**：上传政策文档 → 递归切片 → 向量化 → 多路召回 → 精排 → 拼进 Prompt
- **物理隔离维度**：所有查询必须带 `province + year + category + batch`

> ℹ️ 本文所有「文件 → 函数 → 参数 → 下一个调用点」均按当前代码实写（0.7.1），
> 行号随版本迭代会漂移，函数名与参数名为准。

---

## 一、项目速览

一段话：**规则引擎算得准，大模型说得清。** 志愿推荐的分档与概率完全由 SQL + Python 规则决定，
AI 只承担「把自然语言翻译成筛选条件」和「把计算结果翻译成人话」两件事；
政策类问答则走完整的 RAG 链路（检索前改写 → 多路召回 → Rerank 精排 → Self-RAG / Corrective RAG → 防幻觉生成）。
任一环节失败都会**静默降级**：推荐理由退化为规则文案、Embedding 退化为本地模型、LLM 退化为本地 Ollama。

### 技术栈一览

> ★ = 该技术的配置项所在位置；★★★ = 需要你手动改的配置文件

| 层次 | 技术 | 说明 | 配置位置 |
|---|---|---|---|
| 前端框架 | Vue 3 + TypeScript + Vite | 组合式 API，`/api` 反向代理到 8000 | ★ `frontend/vite.config.ts` |
| UI 库 | Element Plus | 表单 / 表格 / 上传 / 消息 | ★ `frontend/src/main.ts`（全量注册） |
| 状态管理 | Pinia | `user`（登录态）、`knowledge`（文件与向量库状态） | ★ `frontend/src/stores/*.ts` |
| 图表 | ECharts + 中国地图 GeoJSON | 首页「各省在豫招生专业数」热力地图 | ★ `frontend/src/views/student/Home.vue:116` |
| 后端框架 | FastAPI | 路由按域拆分，全局 `TableNotFound` 处理 | ★ `backend/app/main.py:32-41` |
| 数据访问 | SQLAlchemy Core + PyMySQL | 动态反射表 + `fetch_all()` 返回 dict | ★ `backend/app/database.py:64` |
| 数据库 | MySQL（`gaokao`） | 录取 / 计划 / 一分一段 / 用户 / 知识文件 | ★ `backend/.env`（DB_*） |
| 鉴权 | JWT（python-jose）+ bcrypt（passlib） | `admin` / `student` 两种角色 | ★ `backend/app/utils/security.py` |
| 向量库 | Chroma `PersistentClient` | 集合 `gaokao_knowledge`，落盘 `backend/chroma_db/` | ★ `CHROMA_DB_PATH` / `CHROMA_COLLECTION` |
| 图数据库 | Neo4j + py2neo | 0.9.0 知识图谱通道：院校/专业/专业组/省份/批次/选科/分数段 八类节点 | ★ `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` / `GRAPH_ENABLED` |
| 结构化查询 | SQLAlchemy Core + 参数化绑定 | 0.9.1 MySQL 通道：学费/分数线/位次/选科/招生计划按 intents 分组查询 | ★ `MYSQL_QUERY_ENABLED` / `MYSQL_MAX_ROWS` |
| 图像编码 | Chinese-CLIP（首选）/ 图注向量（兜底） | 0.10.0 以文搜图：图文同空间编码，装不上 CLIP 时用视觉模型生成图注再编码 | ★ `IMAGE_ENCODER` / `IMAGE_COLLECTION` |
| OCR | 阿里云 `qwen-vl-ocr`（回落 VLM） | 0.10.0 扫描件 PDF 预处理：页间并发识别后走文本 RAG | ★ `OCR_ENABLED` / `OCR_MODEL` / `OCR_SCANNED_THRESHOLD` |
| PDF 提图 / 渲染 | pdfplumber + pypdfium2 | 0.10.0 抽嵌图与 PDF 页转图；pypdfium2 自带二进制，无需装 poppler | ★ `MULTIMODAL_MAX_IMAGES` |
| 大语言模型 | **阿里云 OpenAI 兼容接口** | `qwen3.7-flash`，专用工作空间域名 | ★ `Ali_API_KEY` / `ALI_BASE_URL` / `ALI_LLM_MODEL` |
| LLM 兜底 | Ollama `qwen3:1.7b` | Ali 不可用自动降级，离线可跑 | ★ `OLLAMA_FALLBACK_MODEL` / `OLLAMA_URL` |
| Embedding | Ali `text-embedding-v3` | 与 LLM 共用同一个 Key 与 base_url，维度对齐已有集合 | ★ `ALI_EMBED_MODEL` / `ALI_EMBED_DIMENSION` |
| Embedding 兜底 | Ollama `nomic-embed-text` | 768 维，离线可用 | ★ `OLLAMA_EMBED_MODEL` |
| 文档解析 | pypdf / python-docx | PDF / DOCX / TXT 文本提取 | ★ `backend/app/utils/file_utils.py` |

<span style="color:#d32f2f; background-color:#fff3cd">★★★ 配置文件清单 ★★★</span>

| 文件 | 改什么 |
|---|---|
| `backend/.env`（由 `.env.example` 复制） | 数据库连接、<b>Ali_API_KEY</b>、ALI_BASE_URL、模型名、开关 |
| `backend/app/config.py` | 所有配置项的**读取入口**与默认值（`_env()` + 极简 dotenv 加载） |
| `backend/requirements.txt` | Python 依赖（0.7.1 起：`openai>=1.0`，移除 `dashscope`；0.9.0 起新增 `py2neo`） |
| `frontend/vite.config.ts` | 端口 5173、`/api` 代理、别名 `@` |
| `frontend/tsconfig.json` | TS 编译选项、`paths` 别名 |
| `frontend/.npmrc.local` | npm 代理走不通时用 `npm i --userconfig .npmrc.local` |

---

## 二、目录结构与文件职责（★ 醒目标注）

> 图例：
> <span style="color:#d32f2f; background-color:#fff3cd">★★★ 配置文件 ★★★</span>
> <span style="color:#1976d2; background-color:#e3f2fd">🔷 RAG 核心</span>
> <span style="color:#388e3c; background-color:#e8f5e9">🟢 业务核心</span>

### 2.1 仓库总览

```
gaokao_project/
├── backend/                      <span style="color:#888">// FastAPI 服务：业务规则 + RAG + 知识图谱 + AI</span>
├── frontend/                     <span style="color:#888">// Vue3 + TS 单页应用</span>
├── gaokao_data/                  <span style="color:#888">// 原始录取数据（MySQL 建库用）</span>
├── data/                         <span style="color:#888">// 0.8.0：RAG 量化评估数据与报告产出</span>
│   ├── eval/                     <span style="color:#888">// 评估数据集：`question` + `ground_truth`（rag_demo_qa.json / gaokao_qa.json）</span>
│   └── eval_reports/             <span style="color:#888">// 评估报告 JSON（*.md 为同名 Markdown 渲染件，均已 gitignore）</span>
├── CHANGELOG.md                  <span style="color:#888">// 版本迭代记录（每个版本的「原有缺陷 → 改进 → 验证」）</span>
├── README.md                     <span style="color:#888">// 本文</span>
└── 导入数据集.py                  <span style="color:#888">// CSV → MySQL 一次性导入脚本</span>
```

### 2.2 `backend/`

```
backend/
├── app/
│   ├── main.py                   <span style="color:#888">// FastAPI 入口：注册 9 个路由、CORS、SPA 回退、启动时补索引与补列</span>
│   ├── config.py                 <span style="color:#888">// 全局配置：DB / Ollama / Ali / Chroma / JWT / RAG 开关</span>  <span style="color:#d32f2f; background-color:#fff3cd">★★★ 配置文件 ★★★</span>
│   ├── database.py               <span style="color:#888">// 引擎、表反射、`fetch_all/fetch_one/fetch_*_params`、幂等建索引</span>  <span style="color:#388e3c; background-color:#e8f5e9">🟢 业务核心</span>
│   ├── models/                   <span style="color:#888">// 动态表解析 + ORM 模型（与 SQL 表一一对应）</span>
│   │   ├── dataset.py            <span style="color:#888">// 表名拼接 `table_name()`、维度归一 `resolve_batch/category`、选科匹配 `subject_match()`</span>  <span style="color:#388e3c; background-color:#e8f5e9">🟢 业务核心</span>
│   │   ├── knowledge.py          <span style="color:#888">// ORM：knowledge_files（上传文件台账）</span>
│   │   └── user.py               <span style="color:#888">// ORM：users（admin / student）</span>
│   ├── schemas/                  <span style="color:#888">// Pydantic 出入参模型（请求体与响应体的唯一契约）</span>
│   │   ├── student.py            <span style="color:#888">// RecommendIn / RecommendFilters / RecommendItem / ScoreToRankOut …</span>  <span style="color:#388e3c; background-color:#e8f5e9">🟢 业务核心</span>
│   │   ├── knowledge.py          <span style="color:#888">// SearchOut / ChunkHit / KnowledgeFileOut</span>  <span style="color:#1976d2; background-color:#e3f2fd">🔷 RAG 核心</span>
│   │   └── user.py               <span style="color:#888">// 登录注册入参、UserInfo</span>
│   ├── routers/                  <span style="color:#888">// 接口层：只做参数校验与异常映射，业务逻辑一律下沉 service</span>
│   │   ├── ai.py                 <span style="color:#888">// /api/ai/chat（RAG 问答；0.9.0 新增 use_graph 开关，返回 graph_hit/vector_hit/fusion_strategy/graph_cypher）、parse-intent、recommend-reason、status</span>
│   │   ├── auth.py               <span style="color:#888">// /api/auth/login|register|me，JWT 依赖 get_current_user / get_current_admin</span>
│   │   ├── knowledge.py          <span style="color:#888">// /api/knowledge/upload|list|detail|download|delete|search|status（admin 读写，search 全员）</span>  <span style="color:#1976d2; background-color:#e3f2fd">🔷 RAG 核心</span>
│   │   ├── meta.py               <span style="color:#888">// /api/score-table|control-lines|score-check（一分一段 / 批次线）</span>
│   │   ├── recommend.py          <span style="color:#888">// /api/recommend（主链路，0.11.0 全国引擎）、/api/recommend/national（纯全国引擎）、/api/recommend/ai-reasons（批量理由）</span>  <span style="color:#388e3c; background-color:#e8f5e9">🟢 业务核心</span>
│   │   ├── stats.py              <span style="color:#888">// /api/stats/major-count-by-province（首页地图数据）</span>
│   │   ├── student.py            <span style="color:#888">// /api/student/profile、/api/score-to-rank、/api/rank-to-score</span>
│   │   ├── university.py         <span style="color:#888">// /api/universities、/api/majors（复用 recommend_service._probability）</span>
│   │   └── eval.py               <span style="color:#888">// 0.8.0：/api/eval/run|report|reports|apply-suggestion|changes|rollback|datasets（均仅 admin）</span>  <span style="color:#9c27b0; background-color:#f3e5f5">🟣 量化评估</span>
│   ├── services/                 <span style="color:#888">// 业务与算法层（所有计算发生在这里）</span>
│   │   ├── recommend_service.py  <span style="color:#888">// 冲稳保规则引擎：候选拉取 → 位次窗口 → 去重 → 分档 → 概率估算</span>  <span style="color:#388e3c; background-color:#e8f5e9">🟢 业务核心</span>
│   │   ├── rank_service.py       <span style="color:#888">// 一分一段：score_to_rank / rank_to_score / control_lines / score_check</span>  <span style="color:#388e3c; background-color:#e8f5e9">🟢 业务核心</span>
│   │   ├── ai_service.py         <span style="color:#888">// 意图解析、推荐理由、统一 ask() 入口（Ali → Ollama）</span>
│   │   ├── llm_client.py         <span style="color:#888">// LLM/Embedding 通道：AliLLMChannel / AliEmbeddingChannel / Ollama* + 门面降级</span>  <span style="color:#1976d2; background-color:#e3f2fd">🔷 RAG 核心</span>
│   │   ├── rag_service.py        <span style="color:#888">// RAG 主控：Chroma 读写、父子树、search()、rerank()、route_strategy()、answer_with_strategy()、0.9.0 search_with_graph()、0.9.1 answer_with_hybrid() 三路融合（图谱 > MySQL > 向量）</span>  <span style="color:#1976d2; background-color:#e3f2fd">🔷 RAG 核心</span>
│   │   ├── sql_query_engine.py   <span style="color:#888">// 0.9.1 MySQLQueryEngine：按结构化条件查 MySQL（0.11.0 起查 `_all` 总表 + province/category 过滤），参数化查询，异常不抛</span>  <span style="color:#0d47a1; background-color:#e3f2fd">🔵 MySQL 通道</span>
│   │   ├── dataset_access.py     <span style="color:#888">// 0.11.1 数据访问层：resolve_table（全国总表 + school→major 回落）、province/category/batch 条件构造、省份感知的批次归一</span>  <span style="color:#388e3c; background-color:#e8f5e9">🟢 业务核心</span>
│   │   ├── multimodal/            <span style="color:#888">// 0.10.0 以文搜图（5 个类，合成复用；图像独立向量空间 gaokao_images）</span>  <span style="color:#6a1b9a; background-color:#f3e5f5">🟣 多模态</span>
│   │   │   ├── image_extractor.py <span style="color:#888">// ImageExtractor：pdfplumber 抽 PDF 嵌图；扫描件退化为按页渲染（pypdfium2）</span>
│   │   │   ├── image_encoder.py  <span style="color:#888">// BaseImageEncoder 抽象 + ChineseCLIPEncoder / CaptionEncoder + create_image_encoder() 工厂</span>
│   │   │   ├── image_store.py    <span style="color:#888">// ImageStore：Chroma gaokao_images 读写删 + 维度校验 + reset() 重建</span>
│   │   │   ├── vlm_client.py     <span style="color:#888">// VLMClient：qwen3.7-flash 图文输入，多模态问答</span>
│   │   │   └── image_retriever.py <span style="color:#888">// ImageRetriever：合成复用前四者；should_trigger / retrieve / answer / index_pdf / remove_file</span>
│   │   ├── graph/                 <span style="color:#888">// 0.9.0 知识图谱通道（7 个文件，单一职责；与向量通道平级，融合在 rag_service 层）</span>  <span style="color:#0d47a1; background-color:#e3f2fd">🔵 图谱通道</span>
│   │   │   ├── ontology.py       <span style="color:#888">// 本体常量：8 类节点标签 / 8 类关系 / 属性键；中文标签的 Cypher 转义只此一处</span>
│   │   │   ├── graph_store.py    <span style="color:#888">// GraphStore：Neo4j 连接 + execute_cypher + get_schema + get_node_properties；失败抛 GraphConnectionError</span>
│   │   │   ├── entity_extractor.py <span style="color:#888">// EntityExtractor：LLM 抽取 + 词典匹配双路混合（词典优先）+ 简称→全称消歧；default_llm_chat 默认通道</span>
│   │   │   ├── cypher_generator.py <span style="color:#888">// CypherGenerator：实体 + 问题 → Cypher；Schema 动态注入 + 4 条高考 Few-shot + 只读保护 + build_params</span>
│   │   │   ├── graph_query_engine.py <span style="color:#888">// GraphQueryEngine：图谱通道唯一入口（合成复用前三个类）；GraphResult 数据类 + build_default_engine() 工厂</span>
│   │   │   ├── graph_builder.py  <span style="color:#888">// GraphBuilder：MySQL → Neo4j 离线构建，全部 MERGE 幂等；`python -m app.services.graph.graph_builder --year 2025`</span>
│   │   │   └── __init__.py       <span style="color:#888">// 统一导出；GraphBuilder 用 __getattr__ 懒加载（在线问答链路用不到）</span>
│   │   ├── query_rewrite.py      <span style="color:#888">// 检索前：重写 / 扩展(Step-Back) / 子查询分解（线程池并发）</span>  <span style="color:#1976d2; background-color:#e3f2fd">🔷 RAG 核心</span>
│   │   ├── retrieval.py          <span style="color:#888">// 检索中：DenseChannel / BM25Channel / HybridSearch / MultiRecall（三通道 × 多 Query）</span>  <span style="color:#1976d2; background-color:#e3f2fd">🔷 RAG 核心</span>
│   │   ├── reranker.py           <span style="color:#888">// 检索后：CrossEncoder / Embedding 余弦 / Noop 三种精排 + 失败降级</span>  <span style="color:#1976d2; background-color:#e3f2fd">🔷 RAG 核心</span>
│   │   ├── self_rag.py           <span style="color:#888">// Self-RAG：要不要检索 → 上下文有没有用 → 生成 → 自评不合格才反思</span>  <span style="color:#1976d2; background-color:#e3f2fd">🔷 RAG 核心</span>
│   │   └── corrective_rag.py     <span style="color:#888">// Corrective RAG：相关性过滤 → 全部无关则重写 Query 再检索</span>  <span style="color:#1976d2; background-color:#e3f2fd">🔷 RAG 核心</span>
│   │   ├── eval/                 <span style="color:#888">// 0.8.0 RAG 量化评估（8 个类，按单一职责拆分）</span>  <span style="color:#9c27b0; background-color:#f3e5f5">🟣 量化评估</span>
│   │   │   ├── eval_config.py    <span style="color:#888">// RAGEvalConfig：评估配置（阈值 / top_k / 目录），支持前端覆盖</span>
│   │   │   ├── data_builder.py   <span style="color:#888">// BaseRAGRunner(抽象) / ProjectRAGRunner / EvalDataBuilder：构建四字段数据集</span>
│   │   │   ├── metrics_local.py  <span style="color:#888">// LocalMetrics：语义相似度 + context_precision/recall + MRR/NDCG/HitRate（免 LLM）</span>
│   │   │   ├── metrics_llm.py    <span style="color:#888">// LLMMetrics：Faithfulness / Relevance / Correctness（默认关闭）</span>
│   │   │   ├── evaluator.py      <span style="color:#888">// EvalReport / RAGEvaluator：编排 + 聚合（skipna）+ 评级</span>
│   │   │   ├── diagnoser.py      <span style="color:#888">// DiagnosisItem / RAGDiagnoser：决策树 → 问题 + 建议 + 参数变更</span>
│   │   │   ├── report_generator.py <span style="color:#888">// ReportGenerator：Markdown + ECharts 数据 + 落盘</span>
│   │   │   ├── report_store.py   <span style="color:#888">// EvalReportStore：报告读写与倒序列举（趋势图）</span>
│   │   │   └── auto_tuner.py     <span style="color:#888">// AutoTuner：白名单参数写回 .env + 备份 + 回滚 + changes.log</span>
│   └── utils/
│       ├── file_utils.py         <span style="color:#888">// UUID 落盘、类型白名单、PDF/DOCX/TXT 提取（0.10.0 起返回 (文本, ocr_used)）、20MB 限制</span>
│       ├── ocr_utils.py          <span style="color:#888">// 0.10.0 OCRExtractor：扫描件判定 / PDF 转图 / 页间并发 OCR / OCR 兜底入口</span>
│       ├── region_mapper.py      <span style="color:#888">// 0.11.0 全国省份↔科类映射：31 省配置、拼音/中文归一、新高考判定、无数据省份标记</span>
│       ├── data_cleaner.py       <span style="color:#888">// 0.11.2 数据提纯：从 major_note 正则补学费/学制，修「duration 列装学费」的列错位</span>
│       └── security.py           <span style="color:#888">// bcrypt 哈希校验 + JWT 签发/解析</span>
├── sql/
│   ├── 03_knowledge.sql          <span style="color:#888">// 旧版 knowledge_files（历史归档）</span>
│   └── 04_rag_tables.sql         <span style="color:#888">// 新版 users + knowledge_files 建表</span>
├── knowledge_files/              <span style="color:#888">// 上传的原始文件（UUID 重命名，已 gitignore）</span>
├── chroma_db/                    <span style="color:#888">// Chroma 持久化目录（sqlite3 + 向量分片，已 gitignore）</span>
├── .env                          <span style="color:#888">// 本地真实配置（不入库）</span>  <span style="color:#d32f2f; background-color:#fff3cd">★★★ 配置文件 ★★★</span>
├── .env.example                  <span style="color:#888">// 配置模板（含 Ali_* 全部说明）</span>  <span style="color:#d32f2f; background-color:#fff3cd">★★★ 配置文件 ★★★</span>
├── requirements.txt              <span style="color:#888">// Python 依赖清单</span>  <span style="color:#d32f2f; background-color:#fff3cd">★★★ 配置文件 ★★★</span>
├── smoke_test.py                 <span style="color:#888">// 14 个业务接口冒烟</span>
├── smoke_rag.py                  <span style="color:#888">// RAG 全链路冒烟：登录 → 上传 → 检索 → 问答 → 删除</span>
├── test_llm_channel.py           <span style="color:#888">// 0.7.1：LLM/Embedding 通道自检 + 端到端 10 秒验证</span>
├── test_advanced_rag.py          <span style="color:#888">// 0.7.0：精排 + 三条高级链路对比（强制本地兜底）</span>
├── test_graph_rag.py             <span style="color:#888">// 0.9.0：图谱双通道（桩版 6 用例 + --real 真实 Neo4j + --compare 双通道回答对比）</span>
├── test_national_engine.py       <span style="color:#888">// 0.11.0：全国多省自适应引擎（区域映射 + 多省位次 + 三档计算 + 非法传参 + 接口层）</span>
├── test_data_cleaner.py          <span style="color:#888">// 0.11.2：数据提纯（正则边界 + 列错位修复 + 各省填充率 + 接口整数校验）</span>
├── test_multimodal_rag.py        <span style="color:#888">// 0.10.0：OCR 预处理 + 以文搜图（桩版 8 用例 + --real 真实链路）</span>
├── test_hybrid_rag.py            <span style="color:#888">// 0.9.1：三路融合（意图识别 + MySQL 查询 + 优先级分发 + 全空拒答 + 异常降级）</span>
├── test_query_preprocess_recall.py <span style="color:#888">// 0.6.0：检索前预处理 + 多路召回</span>
├── test_multi_query.py           <span style="color:#888">// 0.5.0：Query 分解 + 跨路 RRF</span>
├── test_parent_child.py          <span style="color:#888">// 0.3.0：父子块检索</span>
├── test_hybrid_search.py         <span style="color:#888">// 0.2.0：混合检索 + RRF 融合</span>
└── test_anti_hallucination.py    <span style="color:#888">// v2.3.x：路由 + 防幻觉拒答</span>
```

### 2.3 `frontend/`

```
frontend/
├── src/
│   ├── main.ts                   <span style="color:#888">// 应用入口：createApp + Pinia + Router + ElementPlus + 图标全局注册</span>
│   ├── App.vue                   <span style="color:#888">// 根布局：Navbar + RouterView</span>
│   ├── router/index.ts           <span style="color:#888">// 9 条路由 + 全局守卫（admin 路由校验 role）</span>
│   ├── api/                      <span style="color:#888">// 所有 HTTP 请求集中在此（组件不写 URL）</span>
│   │   ├── request.ts            <span style="color:#888">// axios 实例（baseURL=/api, timeout=60s）+ Token 注入 + 401/403 处理</span>
│   │   ├── recommend.ts          <span style="color:#888">// recommend / scoreCheck / controlLines / listUniversities / listMajors / majorCountByProvince</span>
│   │   ├── knowledge.ts          <span style="color:#888">// upload / list / detail / delete / search / ragStatus</span>  <span style="color:#1976d2; background-color:#e3f2fd">🔷 RAG 核心</span>
│   │   ├── ai.ts                 <span style="color:#888">// chat（timeout 120s，0.9.0 起支持 use_graph 参数）/ aiStatus / parseIntent</span>
│   │   ├── auth.ts               <span style="color:#888">// login / register / fetchMe</span>
│   │   └── eval.ts               <span style="color:#888">// 0.8.0：runEval / getReport / listReports / applySuggestion / listChanges / rollback / datasets</span>  <span style="color:#9c27b0; background-color:#f3e5f5">🟣 量化评估</span>
│   ├── stores/
│   │   ├── user.ts               <span style="color:#888">// token + user（派生 isLogin / role / isAdmin）</span>
│   │   └── knowledge.ts          <span style="color:#888">// files / keyword / backend 状态与动作</span>
│   ├── views/
│   │   ├── Login.vue             <span style="color:#888">// 登录；按 role 跳 `/admin/knowledge` 或 `/`</span>
│   │   ├── student/
│   │   │   ├── Home.vue          <span style="color:#888">// 首页 ECharts 中国地图 + 快捷工具入口</span>
│   │   │   ├── Volunteer.vue     <span style="color:#888">// 志愿填报主页面（分数 → 位次 → 冲稳保）</span>  <span style="color:#388e3c; background-color:#e8f5e9">🟢 业务核心</span>
│   │   │   ├── University.vue    <span style="color:#888">// 查大学 / 查专业（分页表格）</span>
│   │   │   └── AiChat.vue        <span style="color:#888">// AI 问答（可开关知识库增强，展示 sources）</span>  <span style="color:#1976d2; background-color:#e3f2fd">🔷 RAG 核心</span>
│   │   └── admin/
│   │       ├── Dashboard.vue     <span style="color:#888">// 后台首页：文件数 + 向量库状态（RagBackendInfo）+ RAG 量化评估入口</span>
│   │       ├── Knowledge.vue     <span style="color:#888">// 知识库管理：列表 / 搜索 / 上传 / 详情 / 删除</span>  <span style="color:#1976d2; background-color:#e3f2fd">🔷 RAG 核心</span>
│   │       └── RAGEval.vue       <span style="color:#888">// 0.8.0：一键评估 + 指标卡片 + 柱状/雷达/趋势图 + 诊断 + 一键应用建议 + 变更日志</span>  <span style="color:#9c27b0; background-color:#f3e5f5">🟣 量化评估</span>
│   ├── components/
│   │   ├── Navbar.vue            <span style="color:#888">// 顶部导航 + 登录态 + 退出</span>
│   │   ├── UploadModal.vue       <span style="color:#888">// el-upload 直传 /api/knowledge/upload（自带 Bearer）</span>
│   │   └── ChatBubble.vue        <span style="color:#888">// 聊天气泡纯展示组件</span>
│   ├── types/                    <span style="color:#888">// TS 类型：recommend / knowledge / user</span>
│   └── styles/main.css           <span style="color:#888">// 全局样式与 CSS 变量</span>
├── index.html                    <span style="color:#888">// Vite 入口 HTML</span>
├── vite.config.ts                <span style="color:#888">// dev server + /api 代理 + @ 别名</span>  <span style="color:#d32f2f; background-color:#fff3cd">★★★ 配置文件 ★★★</span>
├── tsconfig.json                 <span style="color:#888">// TS 编译配置</span>  <span style="color:#d32f2f; background-color:#fff3cd">★★★ 配置文件 ★★★</span>
├── package.json                  <span style="color:#888">// 依赖与 scripts（dev / build / preview）</span>  <span style="color:#d32f2f; background-color:#fff3cd">★★★ 配置文件 ★★★</span>
├── .npmrc.local                  <span style="color:#888">// npm 本地代理兜底配置</span>  <span style="color:#d32f2f; background-color:#fff3cd">★★★ 配置文件 ★★★</span>
├── dist/                         <span style="color:#888">// 构建产物（生产模式下由 FastAPI 托管）</span>
├── public/china.json             <span style="color:#888">// 中国地图 GeoJSON（首页 `fetch('/china.json')` 加载）</span>
└── _legacy/                      <span style="color:#888">// 旧版原生 JS 前端（已归档，不参与构建）</span>
```

---

## 三、业务模块调用流程（★ 详细到参数级别）

### 3.1 端到端流程图：志愿填报

```mermaid
graph TD
    A["考生填写<br/>province/year/category/batch<br/>score 或 rank / 选科"] -->|"<b>onRecommend() L242</b><br/>POST /api/recommend"| B["routers/recommend.py:recommend() L12"]

    B -->|"payload: <b>RecommendIn</b>"| C["services/recommend_service.py<br/><b>recommend() L318</b>"]

    C -->|"rank 为空<br/>(score, province, year, category, batch)"| D["rank_service.<b>score_to_rank() L66</b>"]
    D --> D1[("score_range_2025_henan<br/>cumulative_count = 位次")]

    C --> E["<b>_plan_index() L38</b><br/>lru_cache(32)<br/>入参 province/year/category/batch"]
    E --> E1[("enrollment_plan_2025_henan<br/>元组 / 学费 / 计划数 / 选科要求")]

    C --> F["<b>_fetch_candidates() L149</b>"]
    F --> F1["_build_filters() L105<br/>AND 条件拼装"]
    F --> F2["dataset.resolve_batch()<br/>dataset.resolve_category()"]
    F --> F3["位次窗口裁剪 L171<br/>rank ± buffer*span ± buffer"]
    F --> F4["_dedupe() L178<br/>院校+专业+专业组去重"]
    F --> F5[("major_admission_2025_henan")]

    C --> G["dataset.<b>subject_match() L181</b><br/>再选科目 Python 侧过滤"]
    C --> H["dataset.<b>split_tiers() L282</b><br/>冲 / 稳 / 保 三档"]
    H --> I["_to_item() L219"]
    I --> I1["_probability() L204<br/>冲 40-30x / 稳 70-15x / 保 98-10x"]
    I --> I2["_reason_of() L258<br/>→ ai_service._rule_reason() L316"]

    C -->|"with_ai=True 且 ai_enabled"| J["ai_service.<b>batch_reasons() L426</b><br/>ThreadPoolExecutor(AI_MAX_WORKERS)"]
    J --> J1["recommend_reason() L398<br/>→ build_reason_context() L374"]
    J1 --> J2["<b>ask() L70</b> → llm_client<br/>Ali → Ollama → 规则兜底"]

    I1 --> K[["RecommendOut<br/>student / chong / wen / bao / meta"]]
    J2 --> K
    K --> L["Volunteer.vue 渲染三栏卡片<br/>含 probability 与 ai_reason"]

    style C fill:#e8f5e9,stroke:#388e3c
    style D fill:#e8f5e9,stroke:#388e3c
    style I fill:#e8f5e9,stroke:#388e3c
    style J2 fill:#e3f2fd,stroke:#1976d2
    style D1 fill:#fff3cd,stroke:#d32f2f
    style F5 fill:#fff3cd,stroke:#d32f2f
    style E1 fill:#fff3cd,stroke:#d32f2f
```

### 3.2 代码级调用树（参数级）

<details>
<summary><b>展开： /api/recommend 完整调用树（文件 → 函数 → 关键参数）</b></summary>

```
POST /api/recommend                                     routers/recommend.py:12  recommend()
│   body: RecommendIn(province="河南", year=2025, category="物理类", batch="本科批",
│                     score?, rank?, filters?, buffer?, span_factor?,
│                     limit=60, with_ai=False, ai_limit=8)
│   异常映射 L34-37：ValueError → 400，其它 → 500
└─► services/recommend_service.py:318  recommend(province, year, category, batch,
                                                rank=None, score=None, filters=None,
                                                buffer=None, span_factor=None,
                                                limit=60, with_ai=False, ai_limit=0)
    │
    ├─① services/rank_service.py:66  score_to_rank(province, year, category, batch, score)
    │   └─ _load_score_range(province, year, category, batch=None)  :28
    │       └─ models/dataset.py:64  table_name("score_range", year, province)   → "score_range_2025_henan"
    │           └─ database.py:48  get_table(name)           → 反射 Table（缓存）
    │               └─ database.py:64  fetch_all(select(...)) → List[Dict]
    │   ↳ 返回 {score, rank, segment_count, rank_range, control_score, batch_used, exact, score_diff}
    │
    ├─② _plan_index(province, year, category, batch)   :38   @lru_cache(32)
    │   └─ enrollment_plan_2025_henan → 三级索引 {code / name / school: {tuition, plan_count, duration, subject_req}}
    ├─③ _lookup_plan(idx, uni_code, uni_name, major_code, major_name)  :86   代码 > 名称 > 校名
    │
    ├─④ _fetch_candidates(province, year, category, batch, filters, rank, buffer, span)  :149
    │   ├─ _build_filters(tbl, filters)  :105
    │   │    AND: min_rank IS NOT NULL
    │   │         major_name/major_group/major_note LIKE %major_keyword%
    │   │         不含 exclude_keyword / university_keyword LIKE / school_province=
    │   │         school_nature= / subject_req LIKE / is_985=1 / is_211=1
    │   ├─ models/dataset.py:75/103  resolve_batch() / resolve_category()   ← 2024 表结构特判
    │   ├─ L171-172 位次窗口：min_rank ∈ [rank - buffer*span - buffer, rank + buffer*span + buffer]
    │   └─ _dedupe(rows)  :178   院校+专业+专业组唯一（留 min_rank 最小）
    │
    ├─⑤ models/dataset.py:181  subject_match(subject_req_text, filters.subject_selected)
    │       "不限"/空 → 放行；含"或" → 任一命中；≥2 门或含"必选" → 必须全含
    ├─⑥ filters.tuition_max  Python 侧再过滤  :364-368
    │
    ├─⑦ split_tiers(rows, rank, buffer=settings.RANK_BUFFER, span=settings.RANK_SPAN_FACTOR, limit)  :282
    │       rank-lo ≤ min_rank < rank-buffer        → chong（按 min_rank 降序）
    │       |min_rank - rank| ≤ buffer              → wen （按 |差值| 升序）
    │       rank+buffer < min_rank ≤ rank+lo        → bao （按 min_rank 升序）
    │       池空自动放宽上下界（保证不返回空页）
    │
    ├─⑧ _to_item(row, rank, tier, buffer, span, plan)  :219
    │   ├─ _probability(tier, gap, buffer, span)  :204   → int，钳制 [5,99]
    │   └─ _reason_of(item, rank)  :258 → ai_service.py:316 _rule_reason(ctx)  ← 规则文案，永远可用
    │
    └─⑨ ai_service.py:426  batch_reasons(items, student, limit=ai_limit, workers=AI_MAX_WORKERS)
        └─ ai_service.py:398  recommend_reason(item, student, use_llm=True) → (text, source)
            ├─ build_reason_context(item, student)  :374   组装 17 字段（含 rank_diff、tier_label）
            ├─ _rule_reason(ctx)  :316                     规则兜底（必然可用）
            └─ ask(_REASON_PROMPT, num_predict=180, timeout=min(OLLAMA_TIMEOUT, 40))  :70
                └─ services/llm_client.py  get_llm_client().chat(...)
                    ├─ AliLLMChannel   (OpenAI 兼容，base_url=ALI_BASE_URL)
                    └─ OllamaLLMChannel(settings.OLLAMA_FALLBACK_MODEL)
            ⚠️ 降级三处：AI_ENABLED=0 / ask 返回空 / 长度 <8 或 >220 → 返回 (fallback, "rule")

返回 RecommendOut{ student, chong[], wen[], bao[], meta{total_scanned, buffer, span_factor, table, ai_enabled, ai_generated, elapsed_ms} }
```

</details>

### 3.3 其余业务接口的调用链（一行一个）

```
GET  /api/meta/control-lines     routers/meta.py:198   → rank_service.control_lines(province, year, category)      :148
GET  /api/meta/score-check       routers/meta.py:218   → rank_service.score_check(province, year, category, score) :214
                                                          ├─ control_lines()  :148
                                                          └─ score_to_rank()  :66
GET  /api/meta/score-table       routers/meta.py:184   → rank_service.score_table(province, year, category, batch) :140
GET  /api/score-to-rank          routers/student.py:73 → rank_service.score_to_rank(...)                            :66
GET  /api/rank-to-score          routers/student.py:91 → rank_service.rank_to_score(...)                            :108
POST /api/student/profile        routers/student.py:45 → _ensure_rank(p) :24 → score_to_rank()  （档案仅存内存）
POST /api/ai/parse-intent        routers/ai.py:34      → ai_service.parse_intent(text, province, use_llm=True)      :246
                                                          └─ 规则 _rule_parse_intent() :149 ← AI 失败时的兜底
POST /api/ai/recommend-reason    routers/ai.py:44      → ai_service.recommend_reason(payload, {rank, score})         :398
GET  /api/universities           routers/university.py:36 → recommend_service._probability()（跨模块复用）           :204
GET  /api/majors                 routers/university.py:144 → recommend_service._plan_index()/_lookup_plan()          :38/:86
GET  /api/stats/major-count-by-province  routers/stats.py → 各省在豫招生专业数（首页地图数据源）
```

### 3.4 前端请求表（调用已是二级：Vue → api → URL）

| 前端文件（调用位置） | 方法 | 地址 | 关键参数 |
|---|---|---|---|
| `Volunteer.vue` → `onRecommend()` L242 | POST | `/api/recommend` | `province,year,category,batch,score,rank,filters{subject_selected},use_ai` |
| `Volunteer.vue` → `autoCheck()` L200 | GET | `/api/meta/score-check` | `province,year,category,score` |
| `Volunteer.vue` → `loadLines()` L172 | GET | `/api/meta/control-lines` | `province,year,category` |
| `Home.vue` → `load()` L212 | GET | `/api/stats/major-count-by-province` | `province=河南,year,category,batch` |
| `Home.vue` → `loadGeoJson()` L108 | GET | 静态 `/china.json` | 无（ECharts registerMap） |
| `University.vue` → `load()` L118 | GET | `/api/universities` | `province,year,category,batch,keyword,school_province,rank,page` |
| `University.vue` → `openMajors()` L139 | GET | `/api/majors` | `university_name,category,batch,…` |
| `AiChat.vue` → `send()` L68 | POST | `/api/ai/chat` | `{question, use_rag, top_k, use_graph}`（timeout 120s；0.9.0 起 `use_graph` 默认 true，开启时响应新增 `graph_hit/vector_hit/fusion_strategy/graph_cypher`） |
| `AiChat.vue` → `knowledgeStore.search()` | GET | `/api/knowledge/search` | `query, top_k=3` |
| `Knowledge.vue` → `viewDetail()` L68 | GET | `/api/knowledge/detail/{id}` | path `id` |
| `Knowledge.vue` → `store.remove(id)` L77 | DELETE | `/api/knowledge/delete/{id}` | path `id` |
| `UploadModal.vue`（el-upload action） | POST | `/api/knowledge/upload` | `FormData{file}` + Bearer |
| `Dashboard.vue` → `store.loadBackendInfo()` | GET | `/api/knowledge/status` | 无 |
| `userStore.login()` | POST | `/api/auth/login` | `{username,password}` |
| `router/index.ts` → `beforeEach` 守卫 | GET | `/api/auth/me` | Bearer |

> 说明：`api/*.ts` 是唯一出口（`request.ts` 统一注入 Token、统一处理 401/403），Vue 组件里不出现裸 URL。

---

## 四、RAG 知识库模块调用流程（★ 详细到参数级别）

### 4.1 主链一：管理员上传文档

```mermaid
graph TD
    A["admin/Knowledge.vue<br/>点击上传"] --> B["UploadModal.vue<br/>el-upload action=<br/>/api/knowledge/upload"]
    B -->|"FormData{file} + Bearer"| C["routers/knowledge.py:60<br/><b>upload_knowledge()</b>"]
    C --> C1{"is_allowed(file.filename)?<br/>size ≤ MAX_FILE_SIZE?"}
    C1 -->|否| C2["400 不支持的类型 / 文件过大"]
    C1 -->|是| D["utils/file_utils.py<br/><b>save_upload_file()</b> → UUID 落盘 knowledge_files/"]
    D --> E[("MySQL knowledge_files<br/>status=已上传")]
    E --> F["utils/file_utils.py<br/><b>extract_text()</b><br/>pypdf / python-docx / txt"]
    F --> G["rag_service.<b>split_text()</b><br/>RecursiveCharacterTextSplitter<br/>size=CHUNK_SIZE(500) / overlap=50"]
    G --> H["rag_service.<b>add_documents()</b><br/>chunks, metadata{file_id, filename}, key_fmt"]
    H --> I["<b>put_parents()</b><br/>父块原文写入 parent_store.json"]
    H --> J["<b>split_child_text()</b><br/>120 / 20 → 子块"]
    J --> K["<b>get_embedding()</b> → llm_client<br/>Ali text-embedding-v3 → Ollama nomic"]
    K --> L[("Chroma gaokao_knowledge<br/>add(ids, embeddings, documents, metadatas)")]
    H --> M[("MySQL 回写<br/>chunk_count / status=已向量化")]
    L --> N["返回 {code:200, file_id, data}"]

    style G fill:#e3f2fd,stroke:#1976d2
    style K fill:#e3f2fd,stroke:#1976d2
    style L fill:#fff3cd,stroke:#d32f2f
    style M fill:#fff3cd,stroke:#d32f2f
```

<details>
<summary>展开：上传链参数级调用树</summary>

```
POST /api/knowledge/upload            routers/knowledge.py:60  upload_knowledge(file: UploadFile, db, current_user)
│   权限：Depends(get_current_admin)  第 63 行
│   校验：is_allowed(filename) L66（白名单）／ len(content) > MAX_FILE_SIZE(20MB) L73
├─► utils/file_utils.py  save_upload_file(content, original)   → (stored_filename, file_path)
│       UUID 重命名，落盘 settings.KNOWLEDGE_DIR
├─► db.add(KnowledgeFile(filename, stored_filename, file_path, file_type,
│                        file_size, uploaded_by=current_user["id"], status="已上传"))
│       ORM 模型 models/knowledge.py → 表 knowledge_files
├─► utils/file_utils.py  extract_text(file_path, record.file_type)
│       PDF → pypdf；DOCX → python-docx；其它 → 按 utf-8/gbk 兜底解码
├─► services/rag_service.py  split_text(text, size=settings.CHUNK_SIZE, overlap=settings.CHUNK_OVERLAP)
│       分隔符优先级 ["\n\n", "\n", "。", "，"]；langchain 缺失时退化为定长切分
└─► services/rag_service.py  add_documents(chunks, metadata, key_fmt="file_{id}_chunk_{idx}")
        ├─ put_parents(parents)                父块 docstore（parent_store.json）
        ├─ split_child_text(parent, 120, 20)   子块
        ├─ add_document(child_id, text, meta, embedding=None)
        │   └─ get_embedding(text)  → llm_client.get_llm_client().embed(text, dimensions=_collection_dimension())
        │       ├─ AliEmbeddingChannel  (client.embeddings.create(input=batch, model=ALI_EMBED_MODEL, dimensions=768/128))
        │       └─ OllamaEmbeddingChannel (/api/embeddings, model=nomic-embed-text)
        │   └─ Chroma col.add(ids=[doc_id], embeddings=[vec], documents=[text], metadatas=[metadata])
        └─ 返回写入子块数 → record.chunk_count / status="已向量化"
```

</details>

### 4.2 主链二：用户 AI 问答（按提问类型分六个分支）

入口：`AiChat.vue:send()` → `POST /api/ai/chat` → `routers/ai.py:52 chat()`

```mermaid
graph TD
    START["POST /api/ai/chat<br/>payload{question, use_rag, top_k, strategy}"] --> R0{"use_rag?"}
    R0 -->|否| ROUTER0["直接用 replace-背景+question 提示词调 ask()"]
    R0 -->|是| R1{"rag_service.<b>route_query()</b> L1140<br/>ROUTER_PROMPT 二分类"}
    R1 -->|NO 或 LLM 无返回拦截失败| A1["分支 A：OFF_TOPIC_ANSWER L1122<br/>固定话术，不检索"]
    R1 -->|YES| R2{"ADVANCED_RAG_ENABLED?<br/>ai.py L84"}
    R2 -->|否 或 高级链路异常| S["分支 C：标准 RAG<br/>answer_with_strategy(strategy='standard')"]
    R2 -->|是| R3{"<b>route_strategy()</b> L846<br/>纯规则，零 LLM 延迟"}

    R3 -->|"含 是不是/能不能/是否/可否/对不对"| D["分支 D：Self-RAG"]
    R3 -->|"≥2 个复合词 或 len≥18"| E["分支 E：Corrective RAG"]
    R3 -->|其它| S

    S --> S1["search()<br/>①检索前 ②多路召回 ③Rerank ④父块回填"]
    D --> D1["should_retrieve → retrieve → context_useful<br/>→ generate → 自评合格? → 否定才反思"]
    E --> E1["retrieve → 并发相关性过滤<br/>→ 全无关? 重写 Query 重试 N 次 → generate"]

    S1 --> F{"LLM 通道是否可用？"}
    D1 --> F
    E1 --> F
    F -->|Ali 正常| G1["AliLLMChannel<br/>qwen3.7-flash-2026-07-15"]
    F -->|Ali 失败/无 Key| G2["分支 F 降级：<b>OllamaLLMChannel</b><br/>打印 [LLM] Ali 通道失败，降级到 Ollama"]
    F -->|两者都失败| G3["返回空串 → 各判断保守处理<br/>（保留原 Query / 未查询到具体信息）"]

    style D fill:#e3f2fd,stroke:#1976d2
    style E fill:#e3f2fd,stroke:#1976d2
    style G2 fill:#fff3cd,stroke:#d32f2f
    style G3 fill:#ffebee,stroke:#c62828
```

#### 分支 A：无关问题（如「婚假几天」）

| 步骤 | 位置 | 判断 / 参数 | 结果 |
|---|---|---|---|
| ① 路由二分类 | `routers/ai.py:76` → `rag_service.route_query()` L1140 | `ask(ROUTER_PROMPT.format(query=question), temperature=0.0, top_p=1.0, num_predict=5, timeout=20)` | 返回 `"YES" in intent.upper()` |
| ② 拦截 | `routers/ai.py:77-81` | `if use_rag and not route_query(...)` | 直接返回 `rag_service.OFF_TOPIC_ANSWER` L1122，`source="router_blocked"`，**不检索、不调用后续 LLM** |
| ③ 兜底 | `route_query` L1159 | LLM 返回空 → **放行**（避免误伤） | 走主流程 |

#### 分支 B：结构化查询（如「XX 学费多少」→ `SQL_EXTRACT_PROMPT` + MySQL）

`rag_service.extract_sql_filters()` 提供「自然语言 → MySQL 过滤条件」的能力
（`SQL_EXTRACT_PROMPT` 抽出的字段：province / year / category / batch / keyword …），当前版本用于把
可以落到 SQL 的条件从 Query 里抽出来；真正执行 SQL 的仍是「初审四维 + filters」，
即第三章 `recommend_service` 那条链路。因此本分支在实践中表现为：
**AIL聊天里的结构化问句 → `route_query` 放行 → 标准/高级 RAG 用父块上下文回答**，
避免与规则引擎的计算职责重叠（AI 不算概率，只做表达）。

#### 分支 C：一般政策问题（标准 RAG）

```mermaid
graph LR
    Q[query] --> P1["① QueryPreprocessor.process()<br/>query_rewrite.py:227"]
    P1 -->|"len&lt;QUERY_PREPROCESS_MIN_LEN(20)"| P1S["跳过（source=raw(short)）"]
    P1 -->|"否则线程池并发"| P2["rewrite / step_back / decompose"]
    P2 --> P3["QueryBundle.all_queries ≤ QUERY_PREPROCESS_MAX(4)<br/>原始 Query 置顶去重"]
    P3 --> R1["② rag_service.search() L~960<br/>↓ _recall()"]
    R1 --> R2["build_multi_recall(docs, embeddings)<br/>retrieval.py:DenseChannel + BM25Channel + HybridSearch"]
    R2 --> R3["③ rerank() L828 → reranker.Reranker<br/>CrossEncoder / Embedding余弦 / Noop"]
    R3 --> R4["④ _expand_to_parents()<br/>子块命中 → 换父块上下文"]
    R4 --> R5["generate_answer() L1164<br/>ANTI_HALLUCINATION_PROMPT<br/>temperature=0.1 top_p=0.3"]
```

关键参数一览：

| 环节 | 文件:函数 | 关键参数 |
|---|---|---|
| 检索前 | `query_rewrite.py:227 QueryPreprocessor.process(query)` | `use_rewrite/use_expansion/use_decompose`、`max_queries=QUERY_PREPROCESS_MAX`、`min_len=QUERY_PREPROCESS_MIN_LEN` |
| 检索中 | `retrieval.py MultiRecall.search(queries, top_k)` | `MULTI_RECALL_FUSION=rrf`、`MULTI_RECALL_TOPK_PER_CHANNEL`、`RRF_K=60` |
| 检索后 | `rag_service.py:828 rerank(query, hits)` | `RERANK_ENABLED`、`RERANK_MODEL`（留空走 embedding 余弦） |
| 父子回填 | `rag_service._expand_to_parents(hits)` | `CHILD_CHUNK_SIZE=120`、`CHILD_CHUNK_OVERLAP=20`、`PARENT_STORE_FILE` |
| 防幻觉生成 | `rag_service.py:1164 generate_answer(query, context)` | `temperature=0.1`、`top_p=0.3` |

#### 分支 D：Self-RAG（含「是不是 / 能不能 / 是否」）

判断点：`rag_service.py:846 route_strategy()` → `judge_words = ("是不是","能不能","要不要","是否","可否","有没有","对不对")`（L858-862）

```
SelfRAG.run(query)                                   self_rag.py
├─① should_retrieve(query)        → llm(prompt, temperature=0.0, max_tokens=16)
│     NO  → 直接生成，不检索（省一次检索 + 一次 embedding）
├─② retriever(query, top_k)       → rag_service.search()（与分支 C 共用同一条检索链）
├─③ is_context_useful(query, ctx) → YES / NO
│     NO  → 用「通用知识 + 明确说明资料不足」的口径生成（不编造）
├─④ generator(query, context)     → rag_service.generate_answer()
└─⑤ should_continue_generate()    → 合格即结束；不合格才 reflect_and_correct()（省一次 LLM 调用）
返回 SelfRAGResult{answer, used_context, hits, need_retrieve, context_useful, steps}
```

#### 分支 E：Corrective RAG（复合多实体 / ≥18 字）

判断点：`route_strategy()` L863 —— `sum(complex_words 命中数) >= 2 or len(q) >= 18`

```
CorrectiveRAG.run(query, top_k)                      corrective_rag.py:94
├─① retriever(query, k)               → rag_service.search()
├─② _filter_relevant(query, hits, ...) 并发 is_relevant()（max_tokens=16，ThreadPoolExecutor ≤ 4）
│       命中就进 relevant[] / relevant_hits[]
├─③ while not relevant and retry_count < CORRECTIVE_MAX_RETRY:
│       rewrite_query(current_query) → retriever(new_q, k) → 再过滤
├─④ 仍无相关文档 → 返回拒答文案（"根据现有资料，未查询到具体信息…"）
└─⑤ generator(query, relevant)        → rag_service.generate_answer()
返回 CorrectiveRAGResult{answer, used_docs, hits, rewritten_query, retry_count, steps}
```

#### 分支 F：降级路径（Ali 通道失败 → Ollama → 空串保守处理）

| 触发条件 | 处理位置 | 行为 |
|---|---|---|
| `Ali_API_KEY` 为空 | `llm_client.AliLLMChannel.available()` | 直接跳过 Ali 通道，用 Ollama |
| Ali 调用超时 / 403 / 网络错误 | `llm_client.py` `except` → `logger.warning("[LLM] Ali 通道失败，降级到 Ollama")` | 换 `OllamaLLMChannel` 重试一次 |
| Ollama 也不可用 | 同上 → 打日志后返回 `None` | `LLMClient.chat()` 返回 `""`，各判断**保守处理**（"未查询到具体信息" / 保留原始 Query），不抛异常 |
| Embedding 通道失败 | `AliEmbeddingChannel.embed_batch()` → `OllamaEmbeddingChannel` | 单条失败用零向量占位，保证矩阵形状一致 |
| Chroma 维度不匹配 | `rag_service._collection_dimension()` | 优先对齐已有集合维度（历史 768），取不到才用 `ALI_EMBED_DIMENSION` |

### 4.3 RAG 模块的上游 / 下游依赖

| 模块 | 上游调用者 | 下游被调用者 |
|---|---|---|
| `llm_client.py` | `ai_service.ask`、`query_rewrite.llm_chat`、`self_rag.SelfRAG.llm`、`corrective_rag.CorrectiveRAG.llm`、`rag_service.get_embedding` | `openai.OpenAI`（Ali）、`requests`（Ollama） |
| `query_rewrite.py` | `rag_service.search()` | `llm_client.get_llm_client().chat()` |
| `retrieval.py` | `rag_service.build_multi_recall()` / `_recall()` | `rag_service.get_embeddings_batch()`（经 `ProjectEmbedding.encode`） |
| `reranker.py` | `rag_service.rerank()` | `rag_service.get_embedding()` |
| `self_rag.py` | `rag_service.answer_with_strategy()` | `llm_client` + 注入进来的 `retriever/generator`（= `rag_service.search/generate_answer`） |
| `corrective_rag.py` | `rag_service.answer_with_strategy()` | 同上 |
| `rag_service.py` | `routers/ai.py`、`routers/knowledge.py`、`services/eval/data_builder.py`、`test_*.py` | 上述全部 + Chroma + `parent_store.json` + `services/graph/*` + `services/sql_query_engine.py`（0.9.1 三路） |
| `sql_query_engine.py` | `rag_service.answer_with_hybrid()`（经线程池并行调用）、`test_hybrid_rag.py` | `app.database.SessionLocal` + `app.models.dataset.table_name` |
| `graph/graph_store.py` | `graph/graph_query_engine.py`、`graph/graph_builder.py` | `py2neo.Graph` → Neo4j |
| `graph/entity_extractor.py` | `graph/graph_query_engine.py`、`graph_builder`（不直接） | `ai_service.ask`（经 `default_llm_chat`）+ MySQL 词典 |
| `graph/cypher_generator.py` | `graph/graph_query_engine.py` | 同上 |
| `graph/graph_query_engine.py` | `rag_service._get_graph_engine()`、`test_graph_rag.py` | `EntityExtractor` + `CypherGenerator` + `GraphStore`（合成复用） |
| `graph/graph_builder.py` | 命令行 `python -m app.services.graph.graph_builder` | `GraphStore` + `app.database` + `app.models.dataset` |
| `multimodal/image_retriever.py` | `rag_service.answer_with_multimodal()`、`routers/knowledge.py`、`test_multimodal_rag.py` | `ImageExtractor` + `BaseImageEncoder` + `ImageStore` + `VLMClient`（合成复用） |
| `utils/ocr_utils.py` | `utils/file_utils._maybe_ocr()`、`test_multimodal_rag.py` | `openai.OpenAI`（Ali）+ `pypdfium2` + `pypdf` |

### 4.4 主链三：RAG 量化评估（0.8.0）

入口：`admin/RAGEval.vue` 点击「一键运行评估」→ `api/eval.ts:runEval()` → `POST /api/eval/run`

```mermaid
graph TD
    A["admin/RAGEval.vue<br/>选择数据集 + 配置覆盖"] -->|"POST /api/eval/run<br/>{dataset_id, config_overrides}"| B["routers/eval.py:run_eval()<br/>get_current_admin 鉴权"]
    B --> C["eval/<b>EvalDataBuilder.load_qa_pairs()</b><br/>读 data/eval/*.json|csv"]
    C --> D["<b>ProjectRAGRunner.retrieve()</b><br/>rag_service.search(top_k=TOP_K_FOR_EVAL)"]
    D --> E["<b>ProjectRAGRunner.generate()</b><br/>rag_service.generate_answer()"]
    E --> F["数据集四字段齐备<br/>question / answer / contexts / ground_truth"]
    F --> G["<b>RAGEvaluator.run()</b>"]

    G --> G1["LocalMetrics<br/>semantic_similarity / precision / recall<br/>MRR / NDCG / HitRate"]
    G --> G2["LLMMetrics（默认关闭）<br/>Faithfulness / Relevance / Correctness"]
    G1 --> H["_aggregate() 求均值（skipna）→ _grade() 评级"]
    G2 --> H

    H --> I["<b>RAGDiagnoser.diagnose()</b><br/>决策树规则 → DiagnosisItem<br/>（问题 + 建议 + param_changes）"]
    H --> J["<b>ReportGenerator</b><br/>Markdown + ECharts(bar/radar/trend) + 落盘"]
    J --> K[("data/eval_reports/{report_id}.json|.md")]
    K --> L["EvalReportStore.latest_summary()<br/>历史趋势"]
    L --> M["返回前端：aggregate / grade / details<br/>/ chart_data / diagnoses"]

    M --> N{"管理员点「一键应用」"}
    N -->|"POST /api/eval/apply-suggestion"| O["<b>AutoTuner.plan()</b> → 按白名单解析<br/>decrease/increase → 具体数值"]
    O --> P["备份 .env → .env.bak.{ts}"]
    P --> Q["写回白名单参数 + 追加 changes.log"]
    Q --> R["返回 need_restart=true"]
    N -->|"POST /api/eval/rollback"| S["AutoTuner.rollback()<br/>还原最近备份"]

    style G fill:#f3e5f5,stroke:#9c27b0
    style I fill:#f3e5f5,stroke:#9c27b0
    style O fill:#f3e5f5,stroke:#9c27b0
```

关键数据流（三级闭环）：

| 阶段 | 产物 | 落点 |
|---|---|---|
| ① 评估 | 九项指标 + 综合评级 | `EvalReport.aggregate` / `grade` |
| ② 诊断 | 问题 + 建议 + 参数变更草案 | `DiagnosisItem[]`（随报告持久化） |
| ③ 调优 | 白名单参数实际写回 | `backend/.env` + `services/eval/changes.log` |

> 设计要点：评估器通过 `BaseRAGRunner` 抽象依赖 RAG 系统（依赖倒置），
> 因此用 Mock 跑测试、或将来替换检索引擎，都不需要改评估代码。

### 4.5 主链四：三路融合检索问答（0.9.1）

入口：`student/AiChat.vue` → `api/ai.ts:chat()` → `POST /api/ai/chat`（`use_graph=true`）

```mermaid
graph TD
    A["student/AiChat.vue<br/>发送问题"] -->|"POST /api/ai/chat<br/>{question, use_rag:true, use_graph:true}"| B["routers/ai.py:_chat_sync()<br/>use_graph = payload.use_graph and settings.GRAPH_ENABLED"]
    B -->|"是"| C["rag_service.<b>answer_with_hybrid()</b><br/>0.9.1 三路融合"]
    B -->|"否（向后兼容）"| Z["rag_service.answer_with_strategy()<br/>0.8.0 纯向量链路，行为不变"]

    B -.->|"0.10.0 命中多模态关键词"| MM["rag_service.<b>answer_with_multimodal()</b><br/>以文搜图"]
    MM -->|"未命中图片 / VLM 失败"| C

    C --> S1["<b>Step 1 意图识别</b><br/>detect_structured_intent()"]
    S1 -->|"返回 intents 列表"| S2["<b>Step 2 三路并行</b><br/>ThreadPoolExecutor(max_workers=3)"]

    S2 --> D1["图谱通道<br/>GraphQueryEngine.query()"]
    S2 --> D2["MySQL 通道<br/>MySQLQueryEngine.query_structured()<br/>仅 intents 非空时执行"]
    S2 --> D3["向量通道<br/>rag_service.search()<br/>检索前 + 多路召回 + Rerank"]

    D1 --> E1["EntityExtractor.extract()<br/>LLM 抽取 + 词典匹配（词典优先）"]
    E1 --> E2["canonicalize()<br/>简称 → 词典全称<br/>「计算机」→「计算机科学与技术」"]
    E2 --> E3["GraphStore.get_schema()"]
    E3 --> E4["CypherGenerator.generate()<br/>Schema 注入 + 高考 Few-shot + 只读保护"]
    E4 --> E5["GraphStore.execute_cypher()<br/>build_params() 绑定 $类型_序号 占位符"]
    E5 --> E6["_format_records() → 自然语言上下文"]
    E6 --> G1[("Neo4j<br/>bolt://localhost:7687")]

    D2 --> M1["extract_sql_filters()<br/>LLM 提取 school_name / major_name / year"]
    M1 --> M2["按 intents 拆两组<br/>enrollment_plan(学费/计划)<br/>+ major_admission(分数/位次/选科)"]
    M2 --> M3["参数化查询 :school / :major<br/>LIMIT MYSQL_MAX_ROWS"]
    M3 --> M4["按模板生成中文句子<br/>「…专业2025年学费为23000元/年。」"]
    M4 --> G2[("MySQL<br/>major_admission / enrollment_plan")]

    D3 --> F3["Chroma + BM25 → RRF → Rerank<br/>→ 父子块回填 → vector_context<br/>按 VECTOR_MAX_TOKENS 裁剪"]

    E6 --> H["<b>Step 3 优先级融合</b><br/>图谱 > MySQL > 向量<br/>（不是分数融合）"]
    M4 --> H
    F3 --> H

    H --> I{"三路是否都为空？"}
    I -->|"是"| J1["直接返回拒答话术<br/>不调用大模型"]
    I -->|"否"| J2["<b>Step 5 生成</b><br/>build_hybrid_prompt()<br/>HYBRID_FUSION_PROMPT"]
    J2 --> K["ai_service.ask()<br/>temperature=0.1 / top_p=0.3"]
    K --> L["返回 graph_hit / mysql_hit / vector_hit<br/>/ fusion_strategy / graph_cypher"]

    style S2 fill:#e3f2fd,stroke:#1976d2
    style D1 fill:#e3f2fd,stroke:#0d47a1
    style D2 fill:#e3f2fd,stroke:#0d47a1
    style H fill:#fff3cd,stroke:#d32f2f
    style I fill:#fff3cd,stroke:#d32f2f
```

**为什么不做分数融合（RRF 不适用）**：

| 通道 | 结果形态 | 可排序性 |
|---|---|---|
| 图谱 | **对/错的精确事实**（学费 23000、最低分 512） | 无分数概念，只有命中/未命中 |
| MySQL | **对/错的精确事实**（字段值） | 无分数概念，只有命中/未命中 |
| 向量 | **相似度文本**（"该校学费适中，性价比高"） | 有 0~1 相似度，但不保证数字正确 |

三者量纲不可比，把 0.91 的向量相似度和一条 100% 正确的结构化事实一起排序没有意义。
因此 `rag_service` 扮演「中枢神经」，按 **图谱 > MySQL > 向量** 的顺序排列上下文，
并在 Prompt 里声明权威关系；第一版刻意不做 Level 3 串行筛选，留到 0.10.0。

**降级矩阵**：

| 情况 | `graph_hit` | `mysql_hit` | `vector_hit` | 行为 |
|---|---|---|---|---|
| 三路都命中 | true | true | true | 图谱在前、MySQL 次之，政策文本仅作补充 |
| 仅 MySQL 命中 | false | true | false | 严格基于数据库精确值，禁止编造 |
| 仅向量命中 | false | false | true | 基于政策文本回答，找不到数字就明说 |
| 三路都没命中 | false | false | false | 直接返回预设拒答话术，不调 LLM |
| py2neo 未安装 / Neo4j 未启动 | false | — | — | `graph_error` 记录原因，其余两路照常 |
| MySQL 查询异常 | — | false | — | `mysql_error` 记录原因，其余两路照常 |

**图谱数据来源（离线构建）**：

```bash
cd backend
python -m app.services.graph.graph_builder --year 2025 --batch 本科批
```

| 步骤 | 数据来源 | 写入 |
|---|---|---|
| 院校 / 专业 / 专业组 / 省份 / 批次 / 选科 / 分数段 节点 | `major_admission_2025_henan`、`enrollment_plan_2025_henan` 的 DISTINCT 列 | `MERGE`（幂等） |
| `OPENS` / `ADMITS` | `major_admission` 的 min_score / min_rank | 边上带 year / province / batch / category |
| `TUITION` / `ENROLLS` | `enrollment_plan` 的 tuition / plan_count / duration / subject_req | 同上 |
| `RANKS` | `school_admission` 的院校投档线 | 院校 → 分数段 |
| `LOCATED_IN` / `BELONGS_TO` / `REQUIRES` | `school_province` 列 / `major_group` / `subject_req` | 结构关系 |

### 4.6 主链五：多模态「以文搜图」问答（0.10.0）

入口：`student/AiChat.vue` → `api/ai.ts:chat()` → `POST /api/ai/chat`（问题命中触发关键词时）

```mermaid
graph TD
    A["student/AiChat.vue<br/>发送问题"] -->|"POST /api/ai/chat"| B["routers/ai.py:_chat_sync()"]
    B --> C{"rag_service.should_use_multimodal()<br/>命中「图/课程/培养方案/校园」等关键词？"}
    C -->|"未命中"| Z["回落 0.9.1 三路融合<br/>图谱 + MySQL + 向量"]
    C -->|"命中"| D["rag_service.answer_with_multimodal()"]

    D --> E["ImageRetriever.retrieve()<br/>编码问题 → 查 Chroma gaokao_images"]
    E --> F["BaseImageEncoder.encode_text()<br/>ChineseCLIPEncoder / CaptionEncoder"]
    F --> G["ImageStore.search_by_text()<br/>独立向量空间，与文本集合分开"]
    G --> H{"是否命中图片？"}
    H -->|"否"| Z
    H -->|"是"| I["VLMClient.generate_with_images()<br/>qwen3.7-flash 图文输入"]
    I --> J{"VLM 是否返回内容？"}
    J -->|"否"| Z
    J -->|"是"| K["返回 answer + images<br/>source = multimodal:image<br/>image_hit = true"]

    style C fill:#fff3cd,stroke:#d32f2f
    style H fill:#fff3cd,stroke:#d32f2f
    style J fill:#fff3cd,stroke:#d32f2f
```

**图像入库（上传时）**：`routers/knowledge.py` 文本向量化成功后 → `ImageExtractor.extract_images()` 抽嵌图（扫描件按页渲染兜底）→ `ImageEncoder.encode_image()` 编码 → `ImageStore.add_images()` 写入 `gaokao_images` → 回写 `knowledge_files.image_count`。删除文件时同步清理。

**OCR 预处理（上传时前置）**：`utils/file_utils.extract_text()` 对 PDF 先按页平均字符数判定是否扫描件 → 是则 `OCRExtractor` 用 `qwen-vl-ocr`（不可用回落 `qwen3.7-flash`）页间并发识别 → 识别结果再走原有 `split_text()` 切片流程，并回写 `knowledge_files.ocr_used`。

**为什么图像用独立集合**：图像编码器与文本编码器不同（Chinese-CLIP 512 维 / 图注向量 768 维），语义空间也不同；混在一个集合会维度报错，且检索结果互相干扰。切换编码器前必须调用 `ImageStore.reset()` 重建集合并重新上传文件。

### 4.7 主链六：志愿填报推荐（0.11.0 全国多省自适应）

入口：`student/Volunteer.vue` → `api/recommend.ts` → `POST /api/recommend`（或 `/api/recommend/national`）

```mermaid
graph TD
    A["student/Volunteer.vue<br/>选省份 / 科类 / 填分数"] -->|"POST /api/recommend<br/>{province, category, score}"| B["routers/recommend.py<br/>_validate_province_category()"]
    B -->|"省份不存在"| E1["400 不支持的省份"]
    B -->|"科类不支持"| E2["400 该省份不支持此科类"]
    B -->|"该省无数据"| E3["400 该省暂无 2025 年数据"]
    B -->|"校验通过"| C["rank_service.score_to_rank()<br/>score → 位次（查 score_range_2025_all）"]
    C -->|"返回 0"| E4["400 未在当年一分一段表中找到该分数"]
    C -->|"得到位次"| D["recommend_service.calculate_tiers()<br/>位次 → 冲稳保（查 major_admission_2025_all）"]
    D --> D1["每档 LIMIT 50<br/>位次缓冲按省份动态取值"]
    D1 --> D2["recommend_service.enrich_with_plan()<br/>查 enrollment_plan_2025_all 补学费/计划数/学制"]
    D2 --> F["返回 student / chong / wen / bao<br/>+ rank + tiers（向前兼容）"]

    style B fill:#fff3cd,stroke:#d32f2f
    style D fill:#e3f2fd,stroke:#1976d2
    style D2 fill:#e3f2fd,stroke:#1976d2
```

**省份 / 科类参数传递路径**（★ 0.11.0 核心，0.11.1 打通全链路）：

| 环节 | 位置 | 做什么 |
|---|---|---|
| ⓪ 前端级联 | `Volunteer.vue` / `University.vue` / `Home.vue` | 省份下拉取自 `metaOptions().provinces`；选省份后 `category` 重置为 `categories_map[省份][0]`（0.11.1） |
| ① 前端取选项 | `GET /api/meta/options` | 一次返回 `provinces`（31 省）+ `categories_map`（省→科类）+ `province_modes`（高考模式），前端做「选省份 → 联动科类」 |
| ② 归一化 | `region_mapper.normalize_province()` | 入参可传中文名（`河南`）或拼音（`henan`），统一归一成数据库 `province` 列的中文取值 |
| ③ 合法性校验 | `routers/recommend._validate_province_category()` | 省份不存在 / 科类不在该省列表 / 该省无数据 → 分别返回明确 400 |
| ④ 表解析 | `dataset_access.resolve_table(kind, year)` | 统一反射 `{kind}_{year}_all`；`school_admission` 无总表时回落 `major_admission`（0.11.1） |
| ⑤ 条件构造 | `dataset_access.scope_conditions()` | 一次生成 `province` + `category` + `batch` 三组条件；批次按**该省真实写法**归一（本科批A/B/C段等）（0.11.1） |
| ⑥ 位次换算 | `rank_service.score_to_rank(score, prov, cat, year)` | 查 `score_range_{year}_all`，WHERE 带 `province` + `category`；查不到返回 0 |
| ⑦ 三档计算 | `recommend_service.calculate_tiers(rank, prov, cat, year)` | 查 `major_admission_{year}_all`，WHERE 带 `province` + `category` + `year` + `min_rank BETWEEN`；每档 LIMIT 50 |
| ⑧ 富化 | `recommend_service.enrich_with_plan()` | 复用 `_plan_index` / `_lookup_plan` 三级匹配补学费 / 计划数 / 学制（0.11.2 重写，原先精确匹配会让广西等省全部落空） |
| ⑨ 提纯 | `utils/data_cleaner.clean_item()` | 计划表仍缺学费/学制时，从 `major_note` 正则提取；并修「四川把学费写进 `duration` 列」的列错位（0.11.2） |

**数据表只有一套，省份靠条件区分**（0.11.1 定案）：`major_admission_2025_all` / `enrollment_plan_2025_all` / `score_range_2025_all` 三张总表承载全国 30+ 省数据，`school_admission` 未参与合并、由投档表按院校聚合替代。路由层不再拼表名，漏传省份最多查出全量，不会因表名拼错直接 500。

**科类差异处理**：三种高考模式的科类名不同，`region_mapper` 已按实测数据配置——3+3 六省只有「综合」；3+1+2 二十省为「物理类 / 历史类」（含四川、云南、陕西、宁夏，任务书原归老高考，实测为 3+1+2）；老高考仅新疆、西藏为「理科 / 文科」。山西 / 内蒙古 / 青海暂无数据，会在第 ③ 步被明确拦截。

**内存与性能保护**：总表单表 43 万行（`enrollment_plan` 80 万行），所有查询都带 `LIMIT`（三档各 50 条、富化各 20 条），绝不 `SELECT *` 全量拉取；列类型收紧与索引脚本见 `backend/sql/05_national_tables_perf.sql`。

---

## 五、接口清单

> 「调用链」列 = 该接口在前端的发起位置（Vue 文件 → 方法 → api 函数）

| 方法 | 路径 | 说明 | 权限 | 调用链（前端） |
|---|---|---|---|---|
| GET | `/api/health` | 服务 + DB + Ollama + RAG 状态 | 公开 | 运维自检 |
| GET | `/api/ai/status` | AI 开关与 Ollama 健康 | 公开 | `api/ai.ts:aiStatus()`（预留） |
| POST | `/api/ai/chat` | **志愿问答**（`use_rag=true` 走完整 RAG 链路；0.9.1 起 `use_graph=true` 走三路融合，响应新增 `graph_hit/mysql_hit/vector_hit/fusion_strategy/graph_cypher`；0.10.0 起命中多模态关键词则走以文搜图，响应新增 `image_hit/images`） | 需登录 | `AiChat.vue:send()` → `api/ai.ts:chat()` |
| POST | `/api/ai/parse-intent` | 自然语言 → 筛选条件 | 需登录 | `api/ai.ts:parseIntent()`（预留） |
| POST | `/api/ai/recommend-reason` | 单条志愿推荐理由 | 需登录 | 预留（批量走 `/recommend` 的 `with_ai`） |
| POST | `/api/recommend` | **冲稳保推荐主链路**（0.11.0 起走全国总表引擎，响应新增 `rank` / `tiers`；省份+科类非法返回 400） | 公开 | `Volunteer.vue:onRecommend()` → `recommendApi()` |
| POST | `/api/recommend/national` | 0.11.0 纯全国引擎版：只返回 `{rank, province, category, year, tiers}` | 公开 | 预留（只要结构化结果的场景） |
| POST | `/api/recommend/ai-reasons` | 批量生成 AI 理由 | 公开 | 预留 |
| GET | `/api/meta/options` | 年份/科类/批次下拉 + `provinces` / `categories_map` / `province_modes`（0.11.1 起前端三处页面均用它做省份→科类级联） | 公开 | `Volunteer.vue` / `University.vue` / `Home.vue` → `metaOptions()` |
| GET | `/api/score-to-rank` | 分数 → 位次 | 公开 | 预留（页面走 score-check） |
| GET | `/api/rank-to-score` | 位次 → 分数 | 公开 | 预留 |
| POST | `/api/student/profile` | 保存考生信息并返回换算位次 | 公开 | 预留 |
| GET | `/api/student/profile/{id}` | 读取内存档案 | 公开 | 预留 |
| GET | `/api/score-table` | 一分一段表 | 公开 | 预留 |
| GET | `/api/control-lines` | 各省控线与可填分数区间 | 公开 | `Volunteer.vue:loadLines()` → `controlLines()` |
| GET | `/api/score-check` | 分数体检（批次线 + 位次） | 公开 | `Volunteer.vue:autoCheck()` → `scoreCheck()` |
| GET | `/api/universities` | 查大学（分页 / 筛选 / 概率） | 公开 | `University.vue:load()` → `listUniversities()` |
| GET | `/api/majors` | 查专业 | 公开 | `University.vue:openMajors()` → `listMajors()` |
| GET | `/api/stats/major-count-by-province` | 各省在豫招生专业数 | 公开 | `Home.vue:load()` → `majorCountByProvince()` |
| POST | `/api/auth/login` | 登录（JSON / form），返回 JWT | 公开 | `userStore.login()` → `api/auth.ts:login()` |
| POST | `/api/auth/register` | 注册（默认 student） | 公开 | `userStore.register()`（预留） |
| GET | `/api/auth/me` | 当前用户信息 | 需登录 | `router/index.ts` 守卫 → `userStore.loadMe()` |
| POST | `/api/knowledge/upload` | 上传并向量化 | admin | `UploadModal.vue` el-upload 直传 |
| GET | `/api/knowledge/list` | 文件列表 | admin | `Knowledge.vue` → `store.loadList()` |
| GET | `/api/knowledge/detail/{id}` | 文件详情 | admin | `Knowledge.vue:viewDetail()` |
| GET | `/api/knowledge/download/{id}` | 下载原文件 | admin | `api/knowledge.ts:downloadUrl()`（拼接） |
| DELETE | `/api/knowledge/delete/{id}` | 删除文件 + 向量 + 记录 | admin | `Knowledge.vue:removeFile()` → `store.remove()` |
| GET | `/api/knowledge/search` | **向量检索**（所有登录用户） | 需登录 | `AiChat.vue` → `knowledgeStore.search()` |
| GET | `/api/knowledge/status` | 向量库 / embedding 后端状态 | admin | `Dashboard.vue` → `store.loadBackendInfo()` |

---

## 六、环境准备与启动

### 6.1 依赖

| 组件 | 版本要求 | 备注 |
|---|---|---|
| Python | 3.11+ | 后端 |
| Node.js | 18+ | 前端 |
| MySQL | 5.7+ / 8.0 | 数据库 `gaokao` |
| Ollama | 最新版 | 本地兜底 LLM + Embedding |

### 6.2 后端

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate     # 可选
pip install -r requirements.txt                     # 含 openai>=1.0

# 1) 配置 LLM / Embedding 通道（0.7.1）
copy .env.example .env
```

`.env` 关键段落（**重点是变量名和 base_url**）：

```ini
# ★ Key 的变量名是 Ali_API_KEY（也可直接配 Windows 系统环境变量，代码会自动补读注册表）
Ali_API_KEY=sk-xxxxxxxxxxxxxxxx

# ★ 必须是「工作空间专属域名」，不能用通用 dashscope 域名，也不能用 dashscope SDK
ALI_BASE_URL=https://ws-66jxf85tc3oa6b98.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
ALI_LLM_MODEL=qwen3.7-flash

# 向量模型与大语言模型共用同一个 Key 和同一个 base_url
ALI_EMBED_MODEL=text-embedding-v3
ALI_EMBED_DIMENSION=128     # 实际会优先对齐已有 Chroma 集合维度
ALI_TIMEOUT=30
ALI_ENABLE_THINKING=0       # 思考模式关掉：同一请求实测 9.7s → 2.6s

# 本地兜底
OLLAMA_URL=http://localhost:11434
OLLAMA_FALLBACK_MODEL=qwen3:1.7b
OLLAMA_EMBED_MODEL=nomic-embed-text
```

```bash
# 2) 拉取本地兜底模型
ollama pull qwen3:1.7b
ollama pull nomic-embed-text

# 3) 建表 + 导入数据
mysql -u root -p gaokao < backend/sql/04_rag_tables.sql
cd gaokao_data && python import_to_mysql.py

# 4) 启动
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

启动后自检：

```bash
curl http://127.0.0.1:8000/api/health
# rag.embedding_provider = "ali"、llm_provider = "ali(openai-compatible)" 表示线上通道已生效
```

### 6.3 前端

```bash
cd frontend
npm install                       # 代理异常时用 npm install --userconfig .npmrc.local
npm run dev                       # http://127.0.0.1:5173
npm run build                     # 产物 dist/，生产模式下由 FastAPI 托管
```

### 6.4 验证脚本

```bash
cd backend
python test_llm_channel.py   # 0.7.1：通道自检 + 端到端 10 秒验证（推荐首先跑）
python smoke_test.py         # 14 个业务接口
python smoke_rag.py          # 登录 → 上传 → 检索 → RAG 问答 → 删除
```

---

## 七、常见问题排查

| 症状 | 原因 | 处理 |
|---|---|---|
| **AI 问答全部超时 / 等半天才返回** | 0.7.0 用的是通用域名 `dashscope.aliyuncs.com` + 裸 HTTP，限时模型不在该域名上，每次都要等满超时才降级 | 0.7.1 已修正：统一用 `openai.OpenAI` + `ALI_BASE_URL`（工作空间专属域名）。排查：`GET /api/health` 看 `llm_provider` 是否为 `ali(openai-compatible)`；再看 `.env` 的 `ALI_BASE_URL` 与 Key 变量名是否写成 `Ali_API_KEY` |
| **首页地图/登录提示 `timeout of 60000ms exceeded`，登录按钮一直转圈** | 0.7.1 把 AI 通道收敛后，启动阶段/健康检查仍同步探测 Ollama，前端 axios 默认超时 60s 又把所有接口一视同仁；AI 通道一旦阻塞，登录和首页统计也被拖住 | 0.7.2 已修正：① `main.py` startup 改为后台任务；② `/api/health` 限时 2s 缓存；③ AI 路由全部 `async` + 线程池；④ 前端默认超时降到 10s，AI 接口单独使用 120s。排查：刷新首页后 F12 看 `/api/health` 是否 <500ms；登录接口是否 <5s |
| Key 配了但读不到 | 系统环境变量是在**服务进程启动之后**配置的，`os.getenv` 读不到 | 代码已兜底读 Windows 注册表（`llm_client.get_api_key()`）；或重启终端/服务 |
| 回答很慢（>10s） | 检索前预处理、多路召回、相关性判断各自一次网络往返 | 已做：关思考（9.7s→2.6s）、ThreadPool 并发、embedding 批量 + 缓存、短问句跳过预处理。仍慢可设 `ALI_ENABLE_THINKING=0`、`QUERY_PREPROCESS_MIN_LEN` 调大、`ADVANCED_RAG_STRATEGY=standard` |
| Chroma 报维度不匹配 | 新写入向量维度与历史集合不一致 | `get_embedding()` 会自动用 `_collection_dimension()` 对齐已有维度；若换了集合需重建 |
| 上传成功但检索为空 | Ollama / Ali embedding 都失败，或 `status=失败` | 看 `GET /api/knowledge/status` 与后端日志 `[LLM]` 开头的告警 |
| 回答没有引用知识库 | `/api/ai/chat` 需传 `use_rag=true` 且已登录 | 前端 `AiChat.vue` 的「知识库增强」开关需打开 |
| `npm install` 报 `ECONNREFUSED 127.0.0.1:7890` | `~/.npmrc` 里的代理未启动 | `npm install --userconfig .npmrc.local` |
| `AttributeError: module 'bcrypt'` / passlib 报错 | bcrypt 版本过高 | 安装 `bcrypt==4.0.1` |
| 推荐结果为空 | 科类 / 批次与年份不匹配 | 2024 用理科/文科，2025 用物理类/历史类 |
| `/admin/knowledge` 刷新后 404 | 未构建 dist 或未启用 SPA 回退 | 开发模式请用 5173 端口 |

---

## 八、RAG 版本演进对照

| 版本 | 分块策略 | 检索策略 | 交给 LLM 的上下文 | 关键改进一句话 |
|---|---|---|---|---|
| 0.1.0 | 定长 500/50 | 纯稠密 Top-K | 500 字块（可能切断） | Naive RAG 基线 |
| 0.2.0 | 递归分块 500/50 | 稠密 + 稀疏 → **RRF(k=60)** | 语义完整的 500 字 | 混合检索，召回率上来 |
| 0.3.0 | **父子块**（父 500 / 子 120） | 只索引子块，命中后回填父块 | 父块 | 检索粒度与上下文粒度解耦 |
| 0.4.0 | 父子块 | + Query 路由 + 防幻觉 Prompt | 父块（路由筛选） | 无关问题不再浪费检索 |
| 0.4.1 | 父子块 | 放宽路由 + 修正误拒答 | 父块 | 热修复：该答的答得出来 |
| 0.5.0 | 父子块 | **多路召回**：Query 分解 → 跨路 RRF 累加 | 父块（多路融合） | 复合问题不再只召回一面 |
| 0.6.0 | 父子块 | 检索前预处理 + 模块化三通道 | 父块 | 检索前/中拆成两个可复用模块 |
| 0.7.0 | 父子块 | + **Rerank 精排落地** + Self-RAG / Corrective RAG | 父块（精排后） | 检索之后还能「再排一次」「自我反思」「纠偏重试」 |
| **0.7.1** | 父子块（不变） | 同 0.7.0，**LLM/Embedding 通道修正 + 提速 34 倍** | 父块（不变） | Ali OpenAI 兼容通道正确落地，问答从 198s → 5.7s |

> 每个版本的「原有技术缺陷 → 改进技术与代码位置 → 降级策略 → 验证流程」详见 [CHANGELOG.md](./CHANGELOG.md)。

---

### 设计原则落点速查

| 原则 | 本项目落点 |
|---|---|
| 单一职责 | `llm_client.py` 只管「怎么调模型 + 怎么降级」；Prompt 全部留在各业务模块 |
| 开闭原则 | 新增 LLM 通道只需加一个 `BaseLLMChannel` 子类，`LLMClient` 一行不改 |
| 里氏替换 | `HybridSearch` 既是编排组合又能被 `MultiRecall` 当普通通道使用 |
| 依赖倒置 | `SelfRAG / CorrectiveRAG` 依赖注入的 `retriever / generator / llm` 抽象，不依赖具体实现 |
| 接口隔离 | LLM 通道只有 `chat()`，Embedding 通道只有 `embed()/embed_batch()` |
| 迪米特法则 | `ai_service.ask()` 只知道 `llm_client`，不知道背后是 Ali 还是 Ollama |
| 合成复用 | `LLMClient` **组合**主通道 + 兜底通道；`MultiRecall` **组合**多个通道，而非继承 |
