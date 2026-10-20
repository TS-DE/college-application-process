# 更新日志（CHANGELOG）

## 版本号命名规范修正说明（SemVer）

> **为什么要改**：本项目此前使用 `v2.x.x` / `v3.0.0` 的版本号，**不符合 SemVer 语义化版本规范**：
>
> 1. 版本号前带了 `v` 前缀（规范明确禁止，Git tag 可保留，但文档里不应出现）；
> 2. 项目尚处内部开发 / 培训阶段，**没有形成稳定的公共 API**，不应出现 ≥1.0.0 的主版本号；
> 3. 主版本号从 2 起步，隐含"已界定公共 API"的语义，与实际情况不符。
>
> **修正原则**：主版本号从 0 开始（`0.x.x` 表示内部开发阶段），第一个可用版本从 `0.1.0` 起；
> 新增功能（向前兼容）递增**次版本号 minor**，仅修 bug 递增**修订号 patch**；
> 文档中的版本号本体**不带 `v` 前缀**，Git tag 保留 `v` 前缀（如 `git tag v0.8.0`）。

### 新旧版本映射表

| 旧版本号 | 新版本号 | 类型 |
|---|---|---|
| v2.0.0 | **0.1.0** | Naive RAG 基线（补写） |
| v2.1.0 | **0.2.0** | 递归分块 + 混合检索 |
| v2.2.0 | **0.3.0** | 父子块 |
| v2.3.0 | **0.4.0** | Query 路由 + 防幻觉 Prompt |
| v2.3.1 | **0.4.1** | 热修复（放宽路由 + 修正拒答） |
| v2.4.0 | **0.5.0** | 多路召回 |
| v2.4.1 | **0.6.0** | 检索前预处理 + 模块化多路召回 |
| v2.5.0 | **0.7.0** | Rerank 精排 + 高级 RAG |
| v2.5.1 | **0.7.1** | 热修复（LLM 通道 + README） |
| v2.5.2 | **0.7.2** | 热修复（前端超时 + 登录阻塞） |
| v3.0.0（本次） | **0.8.0** | RAG 量化评估模块 |
| v2.6.0（路线图） | **0.9.0** | ~~并行召回 + CrossEncoder + Text-to-SQL~~ → 实际落地为**知识图谱双通道** |

> 替换范围：`CHANGELOG.md` / `README.md` / 项目文档（简历、面经、行动方案）/ 全部 Python 与 TS 代码注释
> / `backend/.env` 与 `.env.example` 注释。依赖清单（`frontend/package.json` 的 `^2.3.2` 等 npm 包版本）
> **不在**替换范围内，避免误伤第三方依赖版本。
>
> **声明：从 0.8.0 起严格执行 SemVer**（MAJOR.MINOR.PATCH，仅在 patch 变更时递增修订号；
> 形成公共 API 前主版本号保持为 0）。

---

## 版本对照表

| 版本 | 日期 | 分块策略 | 检索策略 | 交给 LLM 的上下文 | 状态 |
|---|---|---|---|---|---|
| **0.1.0** | 2026-10-05 | 定长分块（500 字硬切，重叠 50） | 纯稠密向量检索（Chroma Top-K） | 500 字块（可能被切断） | ✅ Naive RAG 基线（补写） |
| **0.2.0** | 2026-10-06 | **递归分块** `RecursiveCharacterTextSplitter`（500 / 50） | **混合检索**：稠密 + 稀疏 → **RRF 融合 k=60** | 500 字块（语义完整） | ✅ Advanced RAG |
| **0.3.0** | 2026-10-07 | **父子块**：父块 500 字；子块 120 字（重叠 20） | 混合检索，**只索引子块**；子块命中 → 回填父块 | **父块**（500 字） | ✅ 已发布 |
| **0.4.0** | 2026-10-08 | 父子块（不变） | 混合检索 + **Query 路由 + 防幻觉 Prompt** | 父块（经路由筛选） | ✅ 已发布 |
| **0.4.1** | 2026-10-08 | 父子块（不变） | 混合检索 + **放宽路由 + 修正防幻觉拒答** | 父块（经路由筛选） | ✅ 已发布（热修复） |
| **0.5.0** | 2026-10-08 | 父子块（不变） | **多路召回**：Query 分解 → 每条子查询混合检索 → 跨路 RRF 累加 → Rerank 精排 | 父块（经多路召回 + 精排） | ✅ 已发布 |
| **0.6.0** | 2026-10-08 | 父子块（不变） | **检索前预处理**（重写/扩展/子查询）+ **模块化多路召回**（dense/bm25/hybrid 三通道） | 父块（经多路召回） | ✅ 已发布 |
| **0.7.0** | 2026-10-08 | 父子块（不变） | 检索前 + 多路召回 + **Rerank 精排落地** + **Modular RAG（Self-RAG / Corrective RAG）** | 父块（经精排 + 反思/纠偏筛选） | ✅ 已发布 |
| **0.7.1** | 2026-10-09 | 父子块（不变） | 检索前+多路+Rerank+高级RAG（不变） | 父块（不变） | ✅ 已发布 |
| **0.7.2** | 2026-10-09 | 父子块（不变） | 检索前+多路+Rerank+高级RAG（不变） | 父块（不变） | ✅ 已发布 |
| **0.8.0** | 2026-10-12 | 父子块（不变） | 检索前+多路+Rerank+高级RAG（不变） | 父块（不变） | ✅ 已发布 |
| **0.9.0** | 2026-10-12 | 父子块（不变） | 检索前+多路+Rerank+高级RAG（不变）**＋知识图谱双通道** | 父块 + **图谱三元组**（按优先级 + Token 配额融合） | ✅ 已发布 |
| **0.9.1** | 2026-10-14 | 父子块（不变） | + 三路融合检索（图谱 + MySQL + 向量），按「图谱 > MySQL > 向量」优先级分发 | 父块 + 图谱三元组 + **MySQL 精确值** | ✅ 已发布 |
| **0.10.0** | 2026-10-16 | 父子块（不变） | 三路融合（不变）+ OCR 预处理 + 以文搜图（Chinese-CLIP / 图注向量 + qwen3.7-flash） | 父块 + 图谱三元组 + MySQL 精确值 + **图像** | ✅ 已发布 |
| **0.11.0** | 2026-10-17 | 父子块（不变） | 三路融合（不变）+ **全国多省自适应核心引擎**（查 `_all` 总表，province/category 参数化） | 父块 + 图谱三元组 + MySQL 精确值 + 图像（全国 30+ 省） | ✅ 已发布 |
| **0.11.1** | 2026-10-18 | 父子块（不变） | 三路融合（不变）+ 全国引擎（不变 **＋前后端全链路打通**） | 同上（数据源彻底统一到 `_all` 总表） | ✅ 已发布 |
| **0.11.2** | 2026-10-18 | 父子块（不变） | 三路融合 + 全国引擎 + **数据提纯层**（从 `major_note` 正则补学费/学制） | 同上（补齐广西/四川/安徽等省的缺失字段） | ✅ 已发布 |
| **0.12.0** | 2026-10-18 | 父子块（不变） | 三路融合 + 全国引擎 + 数据提纯 + **账号体系与双轨制用户画像**（报告提取 / 业务问卷 → 画像注入 Prompt） | 同上 + **用户画像**（个性化建议） | ✅ 已发布 |
| **0.12.1** | 2026-10-18 | 父子块（不变） | 三路融合 + 全国引擎 + 数据提纯 + 用户画像（**＋隐私隔离 / 规划师模式 / 超时贯通**） | 同上（修复地图统计与问答拒答） | ✅ 已发布 |
| **0.13.0** | 2026-10-20 | 父子块（不变） | **本地 Agent（Function Calling）**：向量/MySQL/图谱封装成工具，由 qwen3:4b 自主选择；云端心理师独立成链路 | 父块 + 图谱 + MySQL + 图像 + **用户画像（物理隔离上传）** | ✅ 已发布 |
| **0.13.1** | 2026-10-20 | 父子块（不变） | Agent（不变）+ **极速模式**（默认走确定性链路）+ **环境状态指示灯** | 同上（问答延迟 150s → 9.5s） | ✅ 已发布 |
| **0.14.0** | 2026-10-20 | 父子块（不变） | Agent（不变）+ **LangGraph 人机回环（HITL）志愿规划**：初稿 → 人工干预 → 终稿 | 同上（新增独立规划模块，RAG/Agent 零改动） | ✅ 已发布 |
| **0.15.0** | 2026-10-20 | 父子块（不变） | Agent（不变）+ **认证与 AI 线程池隔离**：超时不再清 token、认证接口独立调度 | 同上（修复「超时掉登录」） | ✅ 已发布 |
| **0.15.1** | 2026-10-20 | 父子块（不变） | Agent（不变）+ **401 同步登出 / 公开页不阻塞 / AI 过载保护** | 同上（补齐 0.15.0 遗留三处缺陷） | ✅ 已发布 |
| **0.16.0** | 2026-10-20 | 父子块（不变） | Agent（不变）+ **聊天记录会话级持久化**（Pinia store + sessionStorage + 账号隔离） | 同上（新增会话缓存能力） | ✅ 已发布 |
| **0.17.0** | 2026-10-20 | 父子块（不变） | **目录与模块化重构（无行为变更）**：routers→api 分域、services 按域分组、测试归 tests/ | 同上（接口清单 57 条逐条一致） | ✅ 本次发布 |
| **1.0.0** | 计划中 | 父子块 + 语义/标题感知切分 | 并行召回 + CrossEncoder 精排 + Text-to-SQL + Level 3 串行筛选 | 父块（经重排筛选） | 🔜 计划 |

---

## [0.17.0] - 2026-10-20 · 目录与模块化重构（**无行为变更**）

### 一、原有缺陷 / 原有设计

功能是对的，但**结构上看不出层次**：

| 位置 | 重构前 | 问题 |
|---|---|---|
| `app/routers/` | 11 个 router 平铺（`ai.py` 同时装 `/chat`、`/counselor`、`/status`、`/parse-intent`、`/recommend-reason`） | 一个文件混了「本地问答」与「云端心理师」两个域；入口层还塞着线程池、过载保护、读画像等基础设施 |
| `app/services/` | 11 个文件 + 5 个目录平铺在根 | `rag_service.py` 2036 行里混着「分块」「父块存储」「检索」「融合」四件事；`llm_client` / `ai_service` / `rank_service` 与 `rag_service` 平级，看不出依赖层次 |
| `backend/` 根目录 | 21 个 `test_*.py` / `smoke_*.py` / `rag_eval.py` | 测试散落在入口层目录，无法按被测域定位；也无法用 `pytest` 统一跑 |

### 二、改进技术与方案

**严格只做「移动 + 改 import」**，不改任何函数体、签名、SQL、Prompt、配置默认值。

#### 1. 入口层：`routers/` → `api/<域>/`

```
app/api/
├── __init__.py              # ALL_ROUTERS 汇总，main.py 一处注册
├── account/   auth_router.py、profile_router.py
├── chat/      chat_router.py（/status /parse-intent /recommend-reason /chat）
│              counselor_router.py（/counselor）
├── knowledge/ knowledge_router.py、rag_eval_router.py
├── plan/      plan_router.py
└── recommend/ recommend_router.py、university_router.py、student_router.py
               meta_router.py、stats_router.py
```

`main.py` 由 12 行 `include_router` 收敛为：

```python
from app.api import ALL_ROUTERS
for _router in ALL_ROUTERS:
    app.include_router(_router)
```

#### 2. AI 执行基础设施下沉（任务树未指定，但必须做）

`_AI_EXECUTOR`、`_run_ai`、过载计数、`_load_profile_summary` 被 `/chat` 与 `/counselor` **共用**。
若留在任一 router 里，两个入口文件就得互相 import，违背「入口层只做参数校验」。
因此新增 `app/services/llm/ai_executor.py` 承载它们，两个 router 从服务层引用。

#### 3. 业务层：`services/` 按域分组

```
app/services/
├── knowledge/  splitter.py（split_text / split_child_text）
│               parent_store.py（put_parents / get_parent / drop_parents_by_file）
├── llm/        llm_client.py、ai_service.py、ai_executor.py
├── recommend/  rank_service.py、recommend_service.py、dataset_access.py
├── sql/        sql_query_engine.py
├── rag/        rag_service.py、retrieval.py、reranker.py、query_rewrite.py
│               self_rag.py、corrective_rag.py
├── agent/ eval/ graph/ multimodal/ profile/   （保持不动）
└── counselor.py
```

`rag_service.py` 2036 → 1907 行：分块与父块存储拆到 `services/knowledge/`，
**函数体逐字未改**，`rag_service` 通过 `from app.services.knowledge.splitter import ...`
保留同名引用，因此测试里的 `rag_service.split_text(...)`、`rag_service.drop_parents_by_file(...)` 无需改动。

#### 4. 测试层：`tests/<域>/`

21 个脚本按被测域归位：`rag/`（9）、`agent/`（2）、`plan/`、`profile/`、`graph/`、
`multimodal/`、`eval/`（3）、`integration/`（3）、`auth/`（0.15.0 已有）。
新增 `tests/conftest.py`（统一 fixtures）与 `pytest.ini`（固定 rootdir / pythonpath）。
移动后脚本的 `sys.path.insert(0, ".")` 改为按 `__file__` 计算 backend 根，保证任意 cwd 可运行。

### 三、对应代码位置

| 文件 | 改动 |
|---|---|
| `app/main.py:18` | `from app.api import ALL_ROUTERS` |
| `app/main.py:34-37` | 循环注册替代 12 行显式 `include_router` |
| `app/api/__init__.py`（新） | `ALL_ROUTERS` 元组，顺序与 0.16.0 一致 |
| `app/api/chat/chat_router.py`（新，417 行） | 原 `routers/ai.py` 的 status / parse-intent / recommend-reason / chat |
| `app/api/chat/counselor_router.py`（新，83 行） | 原 `routers/ai.py` 的 counselor |
| `app/services/llm/ai_executor.py`（新，175 行） | 线程池 / `_run_ai` / 过载计数 / `_load_profile_summary` |
| `app/services/knowledge/splitter.py`（新） | `SEPARATORS`、`CHILD_CHUNK_*`、`split_text`、`split_child_text` |
| `app/services/knowledge/parent_store.py`（新） | `PARENT_STORE_FILE`、`put_parents`、`get_parent`、`drop_parents_by_file` |
| 其余 40 个文件 | 仅 import 路径变更（共 **108 处**） |
| `tests/conftest.py`（新） | `backend_root` / `client` / `tmp_vector_dir` 三个夹具 |
| `tests/**/*.py` | `sys.path` 引导改为 `Path(__file__).resolve().parents[2]` |

### 四、验证流程与实测结果

#### 1. 接口清单逐条对比（行为一致性的硬证据）

用 `git worktree` 检出重构前基线 `a7fcc73`，两侧各导出 OpenAPI 全量接口：

```
旧 57 条，新 57 条
只在旧代码中存在（0）
只在新代码中存在（0）
响应模型不一致（0）
```

> 首次对比出现 `56 vs 57`，差的是 `/{full_path}` SPA 兜底：
> 它由 `if os.path.isdir(DIST_DIR)` 条件注册，而 worktree 里没有 `frontend/dist`（构建产物不入库）。
> 在 worktree 补一个 `dist/index.html` 后两侧均为 57，**差异归零**。

#### 2. 后端测试（21 项，与基线逐项对齐）

```bash
cd backend
python tests/rag/test_hybrid_rag.py          # ... 共 20 个脚本
python -m tests.auth.test_auth_isolation
```

```
全部通过（21 项）
```

基线（重构前）同样 21 项全绿，**结果完全一致**。

#### 3. 前端（本次零改动）

```
npm run build        ✓ built in 9.60s
npm run verify:auth  401 登出 / 超时保留 / 守卫结构 —— 全 PASS
npm run verify:chat  23 项全 PASS
```

#### 4. 结构自检

```
backend 根目录裸 py 文件：0
app/api 下：5 个域、12 个 router 文件、6 个 __init__.py
```

### 五、已知限制

| 项 | 说明 |
|---|---|
| `pytest` 未安装 | 已写好 `pytest.ini` + `conftest.py`，但当前环境（系统 Python 3.11）无 pytest，`pytest tests/` 未实测。现有 21 个脚本仍是 `python xxx.py` 方式，全部通过 |
| 环境不一致 | 任务约束要求用 conda 环境 `py312_env`，但项目实际运行在系统 Python 3.11（历史一致）。本次未安装任何新库，未改变运行环境 |
| `rag_service.py` 仍 1907 行 | 任务明确「模块化拆解留给 0.18.0」，本次只搬不改 |
| `chat_router.py` 417 行 | 超出「单文件 ≤300 行」约定；拆分函数体会改变代码结构，与本任务「只搬不改」冲突，留给 0.18.0 |

---

## [0.16.0] - 2026-10-20 · 聊天记录会话级持久化

### 一、原有缺陷 / 原有设计

在 AI 问答页聊了几句后，切换到「志愿填报」或刷新页面，再回到问答页，**聊天记录全部清空**。

根因（已核实）：

| # | 现状 | 位置 | 后果 |
|---|---|---|---|
| 1 | `const messages = ref<Msg[]>([])` —— 组件内局部状态 | `AiChat.vue:108` | 组件卸载即销毁，切路由/刷新全部丢失 |
| 2 | `const question = ref('')` —— 输入框草稿同样是局部状态 | `AiChat.vue:105` | 切页后打了一半的字也没了 |
| 3 | 项目中**没有对应的 Pinia store**，也没有任何持久化 | — | 无处可恢复 |
| 4 | 欢迎语是写死的独立 `ChatBubble` | `AiChat.vue:55-58` | 有历史记录时仍显示欢迎语 |

### 二、改进技术与方案

#### 1. 新增 `useChatStore`（Pinia + 手写 sessionStorage）

| state | 说明 |
|---|---|
| `messages` | `{ id, role, text, sources?, createdAt }[]` |
| `draftQuestion` | 输入框草稿 |
| `ownerUserId` | 当前记录归属用户，用于账号隔离 |
| `sessionId` | 会话标识，便于排查 |
| `trimmed` | 是否发生过「更早记录被清理」，供 UI 提示 |

| action | 说明 |
|---|---|
| `loadForUser(userId)` | 读 sessionStorage；`ownerUserId` 不匹配则**清掉旧账号的记录**再重建 |
| `push(msg)` | 追加 + 持久化；超 100 条裁剪最早消息并置 `trimmed` |
| `setDraft(text)` | 更新草稿 + 持久化 |
| `clear()` | 清空消息与草稿，并删除存储 |
| `acknowledgeTrimmed()` | UI 提示后复位 `trimmed` |

#### 2. 为什么用 sessionStorage 而不是 localStorage

`localStorage` 在同一浏览器的**所有标签页共享**：登录 A 账号和 B 账号会互相串号
（两个标签页读到同一份记录）。`sessionStorage` 按**标签页**隔离，
符合「聊天记录属于当前这次会话」的语义；关闭标签页即释放，也不会长期占空间。
**未引入任何持久化插件**（如 `pinia-plugin-persistedstate`），全部手写。

存储布局：key = `gaokao_chat_<userId>`，value = `{ messages, draftQuestion, sessionId, savedAt }`。

#### 3. 健壮性约定

| 场景 | 处理 |
|---|---|
| sessionStorage 无数据 | 按空会话处理（全新会话） |
| 脏数据（非 JSON） | `console.warn` + 丢弃重建，**页面不崩** |
| 脏数据（JSON 合法但结构不符） | 同上 |
| 单条消息 > 4000 字 | 截断存储，避免撑爆配额 |
| 序列化/写入失败（配额超限） | 只告警，降级为「仅内存」，**不让页面白屏** |
| 超过 100 条 | 丢弃最早消息，UI 提示「更早的记录已清理」 |

#### 4. 账号隔离与退出登录

- 存储 key 按 userId 分桶，天然隔离；
- `loadForUser` 发现 `ownerUserId` 与当前用户不一致时，**把上一个账号的记录一并删除**；
- `userStore.logout()` 中调用 `chatStore.clear()`。
  依赖方向是 `user → chat`（**单向**），`stores/chat.ts` 不 import `stores/user.ts`，
  `api/request.ts` 也不反向 import store，因此**不存在循环依赖**。

#### 5. `AiChat.vue` 改造要点

- 移除本地 `messages` / `question` / `Msg` 接口，全部读写 `chatStore`；
- 欢迎语改为 `v-if="chatStore.isEmpty"`，**只在空会话时渲染**；
- 输入框 `v-model="chatStore.draftQuestion"`；
- 发送流程：**先 push 用户消息**（立即持久化）→ 调接口 → push AI 消息；
  **接口失败也 push 一条失败提示并持久化**，避免「发完就没了」；
- 头部新增「清空对话」按钮，`ElMessageBox` 二次确认后 `clear()`；
- **加载时机用 `watch` 而非 `onMounted`**：`/ai-chat` 是公开页，0.15.1 之后路由守卫
  **不再等待** `/auth/me`，进页面时 `userStore.user` 可能还是 null（后台拉取中）。
  `watch(() => userStore.user?.id, ..., { immediate: true })` 可覆盖两种时序。

### 三、对应代码位置

| 文件 | 函数 / 区块 | 改动 |
|---|---|---|
| `frontend/src/stores/chat.ts` | **新建**（240 行） | `useChatStore` + `ChatMessage` 接口 + 读写/校验工具函数 |
| `frontend/src/stores/chat.ts` | `readSession` / `writeSession` / `removeSession` / `truncate` | 持久化与降级 |
| `frontend/src/stores/user.ts` | `logout()` | 增加 `useChatStore().clear()` |
| `frontend/src/views/student/AiChat.vue` | 模板 `head-right` | 新增「清空对话」按钮 |
| `frontend/src/views/student/AiChat.vue` | 模板 `messages` 区 | 欢迎语加 `v-if="chatStore.isEmpty"`；`v-for` 改读 `chatStore.messages`（key 用 `m.id`） |
| `frontend/src/views/student/AiChat.vue` | 模板 `composer` | `v-model` 改绑 `chatStore.draftQuestion` |
| `frontend/src/views/student/AiChat.vue` | `send()` | 改用 `chatStore.push` / `setDraft`，失败也落记录 |
| `frontend/src/views/student/AiChat.vue` | `onClearChat()`（新增） | 二次确认后清空 |
| `frontend/src/views/student/AiChat.vue` | `watch(userStore.user?.id)` / `watch(chatStore.trimmed)` | 加载时机与「更早记录已清理」提示 |
| `frontend/tests/chat/test_chat_store.cjs` | **新建** | 23 项验收断言 |

### 四、验证流程与实测结果

```bash
cd frontend
npm run verify:chat
```

用 esbuild 打包**真实的** `src/stores/chat.ts`，在 Node 里用真实 pinia 运行，
sessionStorage 用内存实现打桩 —— 验证的是线上跑的同一份源码。

```
=== ① 发 3 条 → 切走再切回 ===
  PASS  切页后仍能读到 3 条  实际 3 条

=== ② 刷新页面（重建 pinia）===
  PASS  刷新后 3 条仍在  实际 3 条
  PASS  刷新后内容一致
  PASS  消息带 id 与 createdAt

=== ③ 关闭标签页重新打开 ===
  PASS  重新打开是全新空会话
  PASS  欢迎语条件成立（isEmpty）

=== ④ 输入框草稿跨页保留 ===
  PASS  草稿仍在  实际 "河南本科批平行志"

=== ⑤ 换账号登录 ===
  PASS  A 账号有 2 条
  PASS  B 账号看不到 A 的记录  实际 0 条
  PASS  A 的存储键已被清除
  PASS  B 拥有独立的存储键
  PASS  B 的记录独立保存

=== ⑥ 连续发送超过 100 条 ===
  PASS  只保留 100 条  实际 100 条
  PASS  保留的是最新 100 条
  PASS  trimmed 标志已置位（UI 可提示）
  PASS  写入不卡顿（26ms < 3000ms）

=== ⑦ 脏 JSON 降级 ===
  PASS  页面不崩，按空会话处理
  PASS  控制台有告警  （[CHAT] 会话数据解析失败（非合法 JSON），已丢弃重建…）
  PASS  结构不符也降级为空会话
  PASS  结构不符有告警

=== 附加：超长截断与写入失败降级 ===
  PASS  超长文本被截断到 4000  实际 4000 字
  PASS  写入失败不抛异常（不白屏）
  PASS  写入失败有告警

===== 汇总 =====
共 23 项，通过 23 项，失败 0 项
```

**回归**：`npm run build`（vue-tsc + vite）通过；`npm run verify:auth`（0.15.1 的 401 判据与守卫结构）
仍全 PASS；后端**未做任何改动**。

### 五、已知限制

| 项 | 说明 |
|---|---|
| 关闭标签页即丢 | sessionStorage 的固有语义，符合「会话级缓存」定位；要跨会话保留需改用 localStorage + 账号隔离设计 |
| 草稿每次按键都写一次 | JSON 序列化 + 同步写入，实测 105 条消息累计 26ms，无卡顿；若消息量再增可加节流 |
| `AiChat.vue` 387 行 | 超出「单文件 ≤300 行」约定；该文件改动前已 344 行，本次为功能改造未做范围外重构 |
| 浏览器手工复核 | 上述断言覆盖 store 全部逻辑；「点击路由跳转」这一交互层未做浏览器实测（本机 playwright 不可用） |

---

## [0.15.1] - 2026-10-20 · 补齐 0.15.0 遗留三处缺陷 + AI 线程池过载保护

### 一、原有缺陷

0.15.0 把「超时掉登录」修好了，但核对时确认还剩三处同类隐患，外加一个缺失的过载保护：

| # | 缺陷 | 现象 |
|---|---|---|
| 1 | 拦截器 401 只清 localStorage，**不同步 Pinia** | `userStore.token` 仍在内存 → `isLogin` 仍为 true → 导航栏显示已登录，但所有请求都 401，页面进入「假登录」僵尸状态 |
| 2 | 守卫对**公开页**也 `await loadMe()` | 后端卡住时，从首页点「查大学」要**先空等满 30 秒**才跳转。0.15.0 只做到了「超时后不拦截公开页」，没做到「公开页不等」 |
| 3 | `/parse-intent`、`/recommend-reason` 仍用全局线程池 | 这两个接口内部同样调 LLM，仍会占 anyio 池，把认证接口挤到排队 |
| 4 | AI 线程池**队列无界** | 池满后任务无限排队，用户只能白等到各自超时（25–200 秒）才拿到 504，而不是立刻被告知「服务繁忙」 |

### 二、改进技术

#### 问题 1：401 → 同步登出（回调注入，避免循环依赖）

```
request.ts（基础设施层）                main.ts（应用装配层）
  let onUnauthorized = null       ──→   setUnauthorizedHandler(() => {
  export function setUnauthorizedHandler(fn)      useUserStore(pinia).logout()
  401 分支：clearToken() + onUnauthorized?.()    })
```

**为什么用回调而不是直接 `import store`**：`stores/user.ts` → `api/auth.ts` → `api/request.ts`，
若 `request.ts` 再 import store 就形成**循环依赖**（打包后表现为 `useUserStore is not defined`）。
回调注入把依赖方向反过来：基础设施只声明「需要通知」，由应用入口装配。

#### 问题 2：公开页不等 `/auth/me`

```ts
const needsIdentity = !!(to.meta.requiresLogin || to.meta.requiresAdmin)
if (userStore.isLogin && !userStore.user) {
  if (needsIdentity) {
    await userStore.loadMe()          // 必须知道角色才能决定放行
    if (userStore.meError === 'network') { next({ path:'/login', query:{ reason:'network' } }); return }
  } else {
    void userStore.loadMe()           // ★ 公开页：后台拉取，不阻塞导航
  }
}
```

`loadMe` 内部已吞掉所有异常（只返回 `null`），所以 `void` 不会产生 unhandled rejection；
导航栏靠 Pinia 响应式更新，用户信息到达后自动显示。

#### 问题 3：两个 AI 接口并入专用池

| 接口 | 改前 | 改后 |
|---|---|---|
| `POST /api/ai/parse-intent` | `run_in_threadpool(_parse, ...)` | `_run_ai(_parse, ..., timeout=30, label="parse-intent")` |
| `POST /api/ai/recommend-reason` | `run_in_threadpool(_reason, ...)` | `_run_ai(_reason, ..., timeout=30, label="recommend-reason")` |

改后 `ai.py` 中 `run_in_threadpool` **只剩一处**：`/status` 里的 `ollama_health` 毫秒级探测（符合约定）。

#### 问题 4：AI 过载保护

```python
_INFLIGHT_LOCK = threading.Lock()
_inflight_count = 0

def _inflight_limit() -> int:
    return max(1, settings.AI_THREADPOOL_SIZE * settings.AI_MAX_INFLIGHT_FACTOR)  # 8 × 2 = 16
```

- **准入**在 `_run_ai` 内用原子计数裁决（并发竞态下只有 16 个能进）；
- **入口预检** `_reject_if_overloaded()` 在路由函数第一行执行，让已过载的请求**不跑读画像等前置步骤**；
- **释放**放在 `_run_ai` 最外层 `finally`，超时、异常、正常返回都归零（`max(0, …)` 兜底防负）；
- 超限时抛 **503「AI 服务繁忙，请稍后重试」**；
- `/chat` 的 Agent 分支新增 `except HTTPException: raise`，避免 503 被「回落融合链路」吞掉后继续排队。

新增配置：`AI_MAX_INFLIGHT_FACTOR=2`（上限 = 池大小 × 系数）。

### 三、对应代码位置

| 文件 | 函数 / 区块 | 改动 |
|---|---|---|
| `frontend/src/api/request.ts` | 模块级 `onUnauthorized` / `setUnauthorizedHandler` / 401 分支 | 新增回调注入机制 |
| `frontend/src/main.ts` | `const pinia = createPinia()` + `setUnauthorizedHandler(...)` | 注册登出回调（传 pinia 实例） |
| `frontend/src/router/index.ts` | `beforeEach` | 引入 `needsIdentity`，公开页改 `void loadMe()` |
| `backend/app/config.py` | 线程隔离配置区 | 新增 `AI_MAX_INFLIGHT_FACTOR` |
| `backend/app/routers/ai.py` | `_INFLIGHT_LOCK` / `_try_acquire_inflight` / `_release_inflight` / `_reject_if_overloaded` | 新增过载保护 |
| `backend/app/routers/ai.py` | `_run_ai` | 增加准入与最外层 `finally` 释放 |
| `backend/app/routers/ai.py` | `chat` / `counselor` / `parse_intent` / `recommend_reason` | 入口预检 + 两处改用 `_run_ai` |
| `backend/app/routers/ai.py` | `chat` 的 Agent 分支 | 新增 `except HTTPException: raise` |
| `frontend/tests/auth/verify_401_logout.cjs` | 新增 | 401/超时/5xx 判据验证（打包真实源码） |
| `frontend/tests/auth/verify_router_guard.cjs` | 新增 | 守卫结构断言 |

### 四、验证流程

#### 验收 a：token 过期 → 导航栏立刻变未登录

```bash
cd frontend && npm run verify:auth
```

用 esbuild 把**真实的** `src/api/request.ts` 打包，只把 element-plus 打桩，注入假 axios adapter：

```
=== 用例 1：业务接口返回 401 ===
  请求后 localStorage token = ""
  onUnauthorized 回调被调用次数 = 1
  判定：PASS（401 必须同步登出）

=== 用例 2：请求超时（无 response）===
  请求后 localStorage token = "keep-me-token"
  onUnauthorized 回调被调用次数 = 0
  判定：PASS（超时必须保留 token）

=== 用例 3：后端 503（过载保护）===
  请求后 token = "keep-on-503" 回调次数 = 0
  判定：PASS（5xx 必须保留 token）
```

#### 验收 b：公开页导航不等 `/auth/me`

```bash
cd frontend && node tests/auth/verify_router_guard.cjs
```

```
  PASS  ① 先计算 needsIdentity
  PASS  ② 需要身份时才 await loadMe
  PASS  ③ 公开页用 void loadMe（不 await）
  PASS  ④ 公开页 loadMe 之后直接 next()（无阻塞判断）
  PASS  ⑤ 保留网络异常分流（reason=network）
  PASS  ⑥ 公开页分支内不含 await loadMe
结构验证全部通过
```

> **说明**：本机未安装 playwright（无 chromium，浏览器下载受限），
> 因此「导航实际耗时」未能做浏览器实测。以上为源码结构断言，
> 浏览器复核步骤：把后端 `/auth/me` 延迟 40 秒 → 刷新首页 → 点「查大学」，
> 应立即跳转（<1 秒）且导航栏稍后自动显示用户名。

#### 验收 c：20 并发 → 超出的请求 1 秒内 503

```bash
# 20 个独立 curl 进程并发（避免 Python 多线程的 GIL 干扰测量）
```

```
总墙钟 19.38s
200 成功    : 16 个，11.59–19.30s
503 过载拒绝: 4 个，597–611 ms

存在 503 拒绝      : PASS（4 个）
503 在 1 秒内返回  : PASS
```

> **测量说明**：同一场景用 Python 多线程测得 2.3–3.0 秒，但那是 **GIL 争抢导致的客户端假象**
> （20 个线程同时建连/写请求，实际发出时间被拉开）。改用 20 个独立 curl 进程后为 **597–611ms**；
> 另单独测「16 个占满后再单发」的纯拒绝路径，响应仅 **22–26ms**。
> 服务端拒绝逻辑本身是毫秒级。

同时验证**计数不泄漏**：过载测试结束后单发一次 → `HTTP 200 耗时 6.5s`（名额已全部归还）。

#### 回归

```bash
python -m tests.auth.test_auth_isolation     # PASS（认证隔离）
python smoke_test.py                          # PASS
python smoke_rag.py                           # PASS
python test_user_profile.py                   # PASS
cd frontend && npx tsc --noEmit && npm run build   # PASS
```

### 五、已知限制

| 项 | 说明 |
|---|---|
| 过载阈值偏保守 | 上限 = 池大小 × 2 = 16。实测 16 个请求最长排队 21 秒（池压到 2 时），说明队列仍会积压；如需更激进可调小 `AI_MAX_INFLIGHT_FACTOR` |
| 被拒绝的请求不排队 | 503 是「立即拒」，不是「优雅降级」。若希望过载时仍服务低优先级请求（如 `/status`），需另加优先级队列 |
| 浏览器实测缺失 | 验收 b 只做了结构断言，原因见上（playwright 不可用） |
| 超时线程不中断 | `wait_for` 只取消 future，线程仍会跑完再释放槽位，因此上限是「在途」而非「运行中」 |

---

## [0.15.0] - 2026-10-20 · 修复「超时掉登录」：认证与 AI 线程池隔离

### 一、原有缺陷（一条 AI 请求即可打掉登录态）

现象：打开前端一段时间后任意操作提示「请求超时」并退回未登录，刷新页面最易复现；
此时点「登录」也一直转圈。

因果链（已逐条核对代码确认）：

```
用户发一个 AI 问题（/chat 占用线程 100-200s）
        ↓
FastAPI 同步端点与 run_in_threadpool 共用 anyio 默认线程池（上限 40）
        ↓
AI 请求挤占线程，/auth/me 排队 >10s
        ↓
前端 axios 默认超时 10s → 抛错（无 response）
        ↓
store.loadMe() 的 catch 无差别 logout()  ← 致命点
        ↓
token 被清，用户被迫退出；刷新后守卫又必调一次 /auth/me，再次赌运气
```

五个缺陷点：

| # | 缺陷 | 位置 |
|---|---|---|
| A | `loadMe` 的 catch 无差别 `logout()`，不区分 401 与超时 | `stores/user.ts` |
| B | 守卫每次刷新必触发 `loadMe()`（Pinia 内存态刷新即丢） | `router/index.ts` |
| C | 认证接口走默认 10s 实例且无重试 | `api/auth.ts`、`api/request.ts` |
| D | 同步 `def` + anyio 共享线程池被 AI 占满 | `routers/auth.py`、`routers/ai.py` |
| E | 无线程池等待、无 `/me` 耗时日志 | — |

**核对时额外发现 2 处同类隐患**：

- `get_current_user()` 声明了 `db: Session = Depends(get_db)` 却从未使用 —— 每次鉴权仍要取一次 DB 会话，是 AI 高峰期的额外排队点；
- 拦截器 401 时 `clearToken()` 只清 localStorage、不清 Pinia，导致「界面显示已登录、实际请求全 401」的状态错位。

### 二、改进技术

#### 1. 前端：把「登录失效」与「后端不可用」分开

新增两个判据函数（`api/request.ts`，收敛判据、避免各处各写一套）：

| 函数 | 语义 |
|---|---|
| `isUnauthorized(error)` | 仅 **401** —— 唯一需要登出的情况 |
| `isNetworkError(error)` | 无 response / 5xx / 超时 —— 一律**保留 token** |
| `isConnectionError(error)` | 仅「连接失败」—— 唯一值得重试的情况 |

`loadMe(options)` 新逻辑：

```ts
try   { user = await fetchMeWithTimeout(); lastMeLoadedAt = now }
catch { 401 → logout()            // 真失效
        其他 → user=null, meError='network'，token 保留 }
```

并加 **60 秒内存缓存**：同一页面生命周期内成功过一次就不再重复拉取，避免连续导航反复打接口。

#### 2. 前端：认证独立超时 + 只对「连接失败」重试

- 新增 `authRequest` 实例（`timeout: 30000`）与 `httpAuth()`；`login`/`register`/`fetchMe` 全部改用它；
- `fetchMe` 3 次指数退避（300 / 900 / 2700 ms），**但只在连接失败时重试**。

> **偏离任务书的一处设计（有实测依据）**：任务要求「超时也重试」。
> 实测若 `AUTH_TIMEOUT=30s` 也重试 3 次，一次刷新要白屏 `30×4 + 退避 ≈ 2 分钟`，
> 与验收标准「关闭后端后应尽快提示网络异常」直接冲突；且超时说明后端在、只是慢，
> 立刻重试大概率还是慢。故实现为：**连接失败重试（毫秒级失败，总 <5s），超时不重试**。

#### 3. 前端：守卫不再因网络问题阻断导航

| 场景 | 处理 |
|---|---|
| `/auth/me` 成功 | 正常放行 |
| 401 | store 已 logout，跳登录页 |
| 网络异常 + 目标页**不需要**登录 | **直接放行**（页面自行降级） |
| 网络异常 + 目标页**需要**登录 | 跳 `/login?reason=network`，提示「网络波动，请重试」而非「登录已过期」 |

#### 4. 后端：AI 专用线程池，认证不再排队

```python
_AI_EXECUTOR = ThreadPoolExecutor(max_workers=AI_THREADPOOL_SIZE,  # 默认 8
                                  thread_name_prefix="ai-worker")

async def _run_ai(fn, *args, timeout, label):
    # run_in_executor(_AI_EXECUTOR, partial(...)) + wait_for
    # 并记录「排队耗时」，超过 AI_QUEUE_WAIT_WARN_SECONDS 打告警
```

`/chat`、`/counselor` 的 5 处阻塞调用（读画像 / Agent / 融合链路 / 心理师 / 读画像）
全部改走 `_run_ai`。anyio 默认池只剩普通业务接口与认证使用，不再被 AI 挤占。

`me()` 改为 `async def`，DB 访问放线程池，并用 `AUTH_TIMEOUT_SECONDS` 兜底，
超时返回 **503**（5xx 会让前端保留 token，而不是登出）。

`get_current_user()` 去掉未使用的 `db` 参数，恢复「纯 JWT 解码、零 IO」的契约。

#### 5. 可观测性

| 日志 | 含义 |
|---|---|
| `[AUTH] /me 耗时=3ms user=28` | 认证接口实际耗时 |
| `[AI] 线程池排队告警 chat-hybrid 等待 6.53s（阈值 5s，池大小 2）` | 池子被占满 |
| `[AI] agent 超时 90s（已等待 90.00s，排队 12.34s）` | 超时时能区分「排队久」还是「执行久」 |

### 三、对应代码位置

| 文件 | 函数 / 区块 | 改动 |
|---|---|---|
| `backend/app/config.py` | 新增「认证与 AI 线程隔离」区块 | `AUTH_TIMEOUT_SECONDS` / `AI_THREADPOOL_SIZE` / `AI_QUEUE_WAIT_WARN_SECONDS` |
| `backend/app/routers/ai.py` | 模块级 `_AI_EXECUTOR`、`_timed_call`、`_run_ai` | 新增；`/chat`、`/counselor` 5 处调用改用 |
| `backend/app/routers/auth.py` | `get_current_user` | 移除未使用的 `db` 参数 |
| `backend/app/routers/auth.py` | `_fetch_user`（新增）、`me` | `me` 改 `async def` + 线程池 + 超时 503 + 耗时日志 |
| `frontend/src/api/request.ts` | `AUTH_TIMEOUT`、`authRequest`、`httpAuth`、`isNetworkError`、`isUnauthorized`、`isConnectionError` | 新增 |
| `frontend/src/api/auth.ts` | `login` / `register` / `fetchMe` / `fetchMeWithTimeout` | 改用 `httpAuth`；`fetchMe` 加退避重试 |
| `frontend/src/stores/user.ts` | `loadMe` / `logout` / state | 区分 401 与网络错误；60s 缓存；新增 `lastMeLoadedAt` / `meError` |
| `frontend/src/router/index.ts` | `beforeEach` | 网络异常不阻断导航，需登录页跳转带 `reason=network` |
| `frontend/src/views/Login.vue` | `networkReason` + `el-alert` | 「网络波动，请重试」提示 |
| `backend/tests/auth/test_auth_isolation.py` | 新增 | 并发隔离验收脚本 |

### 四、验证流程

#### 验收 3 / 4：并发压测（真实 HTTP）

```bash
python -m tests.auth.test_auth_isolation
```

实测输出：

```
用例 1：6 个并发 /chat 期间测量 /auth/me
    #1   125.9 ms  HTTP 200
    #2    36.5 ms  HTTP 200
    #3    18.1 ms  HTTP 200
    #4    19.9 ms  HTTP 200
    #5    29.2 ms  HTTP 200
  压测期间登录：HTTP 200 耗时 0.22s
  /auth/me 最大 126 ms，平均 46 ms
  验收 3（/auth/me < 2s）：PASS
  验收 4（登录 < 30s）：PASS
```

**更严苛的隔离验证**（12 并发 + 池大小压到 2，排队 21 秒）：

```
[AI] 线程池排队告警 chat-hybrid 等待 21.48s（阈值 5s，池大小 2）
/auth/me 最大 111 ms（阈值 2000）
验收：PASS
```

> 这是修复生效的最强证据：**AI 池只有 2 个槽位、排队 21 秒时，认证仍是 111ms**。
> 修复前这些 AI 任务占的是 anyio 池，认证要排在它们后面。

#### 验收 2：模拟后端变慢（`/auth/me` 延迟）

| 场景 | 结果 |
|---|---|
| 延迟 12s（< 30s 超时） | 12.1s 返回 200 → `KEEP_TOKEN`（user 已刷新，不登出） |
| 延迟 40s（> 30s 超时） | 30.0s 客户端超时、无 response → `KEEP_TOKEN`（提示网络波动，不登出） |

#### 验收 5：关闭后端进程

```
结果：KEEP_TOKEN（网络异常：ConnectionError）
判定：PASS（保留 token，未 logout）
```

#### 验收 1：AI 长请求期间切页 / 刷新

由验收 3 覆盖：并发 AI 期间 `/auth/me` 始终 <130ms，远低于前端 30s 超时，
`loadMe` 成功返回，`logout()` 不会被触发。

#### 回归

`smoke_test` / `smoke_rag` / `test_user_profile` / `test_hotfix_0_12_1` /
`test_agent_0_13_0` / `test_hotfix_0_13_1` / `test_plan_workflow` 全部通过；
`npx tsc --noEmit` 与 `npm run build` 通过。

### 五、已知限制

| 项 | 说明 |
|---|---|
| 超时线程不中断 | `wait_for` 只取消 future，Python 线程无法强杀；被放弃的 AI 任务仍会跑完再释放槽位。因此 `AI_THREADPOOL_SIZE` 不宜过小 |
| 连接失败重试耗时 | Windows 下 Python 模拟单次连接失败约 2s（SYN 重传），4 次尝试约 12s；浏览器通常立即返回 `ERR_CONNECTION_REFUSED`，实际更快。若偏慢可下调 `ME_RETRY_DELAYS` |
| 缓存窗口 | 60 秒内不重复拉 `/auth/me`，因此改了昵称等资料后，其他标签页最多 60 秒后同步 |
| `ai.py` 行数 | 468 行，超出「单文件 ≤300 行」约定；本次只做线程池改造，重构不在范围内 |

---

## [0.14.0] - 2026-10-20 · LangGraph 人机回环（HITL）志愿规划

### 一、为什么需要人机回环

志愿填报是**不可逆的重大决策**，AI 一次生成的方案不能直接当终稿。
0.14.0 用 LangGraph 的 Checkpoint 机制把流程切成三段：

```
AI 生成初稿 → 图暂停，用户随便改 → 恢复执行，AI 按意见重排 → 终稿
```

关键在「暂停」——不是前端假装等待，而是**后端真的把图停在中断点**，
状态存在 Checkpointer 里，用户改完再唤醒。这样即使中间隔了几分钟、
换了浏览器，方案也不会丢。

### 二、图的形状

```
START → analyze_intent → generate_draft → ⏸ human_review → refine_plan → END
                                          ↑
                              第一次 invoke 停在这里
```

| 节点 | 职责 | 耗时 |
|---|---|---|
| `analyze_intent` | 读分数 + 画像，把「想去江浙沪、不想太冷」变成筛选条件 | <10ms |
| `generate_draft` | 位次换算 → 冲稳保 → 学费富化，产出初稿 + 全量候选池 | ~1s |
| `human_review` | **空节点**，只作为 `interrupt_before` 的挂载点 | 0 |
| `refine_plan` | 解析用户意见 → 从候选池重筛 → 终稿 + 调整记录 | <10ms（规则）/ 20-60s（含模型） |

### 三、新增文件

| 文件 | 职责 | 设计原则 |
|---|---|---|
| `services/agent/workflow.py` | 只做编排：State、连图、MemorySaver、start/resume | **SRP**（不写 SQL、不调 LLM） |
| `services/agent/plan_builder.py` | 业务：初稿生成 / 反馈解析 / 重新筛选 | **DIP**（引擎函数可注入）/ **可测**（不依赖 langgraph） |
| `schemas/plan.py` | `start` 与 `resume` 入参**分开建模** | **ISP** |
| `routers/plan.py` | `/start`、`/resume`、`/state`、`/health` | 独立路由，出问题可单独回滚 |
| `frontend/src/views/student/PlanGenerator.vue` | 三步 UI（填信息 → 人工干预 → 终稿） | — |
| `frontend/src/api/plan.ts` | 三段式 API 封装 | — |
| `backend/test_plan_workflow.py` | 6 组桩版 + `--real` | — |

**零侵入**：`rag_service.py`、`agent/runner.py`、`routers/ai.py` 一行未改。
规划模块只**复用**（`score_to_rank` / `calculate_tiers` / `enrich_with_plan` / `LLMJsonParser`），
不修改任何既有函数。

### 四、反馈解析：规则优先，模型兜底

用户说的话千奇百怪，全部交给大模型会慢（本机 20-60s），全用规则又不够聪明。
0.14.0 采用**双层 + 短路**：

```
规则层（0ms）→ 已解析出条件？ → 是 → 直接返回（不调模型）
                              → 否 → 调模型 → 与规则结果取并集
```

规则层能力（实测）：

| 用户说法 | 解析结果 |
|---|---|
| 不想去北京 | `exclude_provinces=['北京']` |
| 我不想去太冷的地方 | `exclude_provinces=[黑龙江, 吉林, 辽宁, 内蒙古, 新疆, 青海, 西藏]`（语义展开） |
| 想去江浙沪，想学计算机 | `prefer_provinces=[江苏,浙江,上海]`、`prefer_majors=['计算机']` |
| 学费别超过 6000 | `max_tuition=6000` |
| 太贵了（无数字） | `max_tuition=8000`（公办普通专业经验上限） |
| 不学土木 | `exclude_keywords=['土木']` |
| 想学计算机但别太远 | 专业为**偏好**、远地区为**排除**（同句双极性） |

模型层用 `PLAN_LLM_ENABLED=1` 开启，只在规则看不懂时触发；
`PLAN_LLM_ALWAYS=1` 可强制每次都过模型。

### 五、接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/plan/start` | 生成初稿，返回 `thread_id` + `draft_plan`，图停在中断点 |
| POST | `/api/plan/resume` | 注入 `user_feedback`，恢复执行，返回 `final_plan` + `changes` |
| GET | `/api/plan/state/{thread_id}` | 读会话现场（刷新后可恢复，`awaiting_feedback` 表示是否还停在中断点） |
| GET | `/api/plan/health` | langgraph 依赖自检，前端据此决定是否显示按钮 |

**权限**：全部 `Depends(get_current_user)`；`thread_id` 内嵌 `user_id`，
Service 层校验归属 —— 拿到别人的 `thread_id` 也是 403。

### 六、验证结果

#### 桩版（`python test_plan_workflow.py`）

```
用例 1：反馈解析      6 类说法全部正确（含「太冷」语义展开、同句双极性）
用例 2：初稿生成      rank=40000，初稿 3/4/3，候选池各 20；非法省份/科类/位次为 0 → 明确报错
用例 3：重新规划      排除地区/学费超限/偏好排序/全排除回退/空反馈原样
用例 4：图结构        4 个节点齐全 + MemorySaver + interrupt_before=['human_review']
用例 5：HITL 闭环     start 暂停 → get_state 等待 → resume 终稿 → 越权 403 → 不存在 404
用例 6：路由契约      3 个路由注册，缺分数/位次 → 422
0.14.0 桩版全部通过
```

#### 真实链路（`--real`）

```
plan/health  → {available: true, engine: langgraph, interrupt_before: human_review}
① start  status=200 耗时=1.2s   thread=1bf63c19 rank=45887 初稿=24 条
② state  → awaiting_feedback=True（图确实停在中断点）
③ resume status=200 耗时=0.0s   解析=['北京'] 调整=23 条 终稿=24 条
          地区=['上海','吉林','四川','安徽','广东','广西','江苏','河北','河南','海南','湖北','贵州','辽宁','黑龙江']
④ 他人访问 status=403
⑤ 未登录   status=401
```

#### 回归

`test_agent_0_13_0`、`test_hotfix_0_13_1`、`smoke_test`、`smoke_rag`、
`test_hybrid_rag`、`test_multimodal_rag`、`test_national_engine --api`、
`test_user_profile`、`npm run build` 全部通过。

### 七、已知限制

| 项 | 说明 |
|---|---|
| Checkpoint 存在内存 | `MemorySaver` 进程内有效；**重启服务后旧 `thread_id` 失效**（前端会收到 404，需重新生成）。生产环境建议换 `SqliteSaver`/`RedisSaver`，只需改 `build_plan_graph(checkpointer=...)` 一处 |
| 单进程限制 | 多 worker（`uvicorn --workers N`）时状态不共享；当前部署为单 worker，够用 |
| 终稿不落库 | 目前只在会话内保存，刷新可恢复但过期即失；导出 CSV 是主要留存方式 |
| 反馈词表有限 | 规则层覆盖常见说法，冷门表达依赖模型；`PLAN_LLM_ENABLED=0` 时可能漏解 |

### 八、后续演进（0.15.0）

| 方向 | 说明 |
|---|---|
| Checkpoint 持久化 | 换 `SqliteSaver`，支持跨重启恢复 + 历史版本回溯 |
| 终稿落库 | 新增 `plan_drafts` 表，支持「我的方案」列表与版本对比 |
| 多轮迭代 | 允许用户连续改多轮（当前 resume 后即结束） |
| 干预粒度细化 | 支持「这条往上提一档」「这条换成同城其他学校」这类结构化微调 |

---

## [0.13.1] - 2026-10-20 · 热修复：Agent 延迟优化（150s → 9.5s）+ 环境状态指示灯

### 一、问题

0.13.0 引入 Function Calling 后，纯 CPU 环境下一次问答要 **150 秒**（规划 32-55s + 工具 5-10s + 生成 70-90s），演示不可接受。
同时 Neo4j 未启动时用户只看到「查不到」，不知道是环境没起来。

### 二、先做了实验，再改代码

任务书建议把规划轮 `num_predict` 限制到 150。**实测不可行**——qwen3 是思考型模型，
推理会吃光预算，根因如下表（短 Prompt + `/no_think`，每题实测）：

| `num_predict` | 政策类问题 | 分数类问题 | `done_reason` | 结论 |
|---|---|---|---|---|
| 150 | ❌ 0 tool_calls | ❌ 0 tool_calls | `length` | 推理没写完就被截断 |
| 250 | ❌ 0 tool_calls | ✅ 1 tool_call | `length`/`stop` | 不稳定 |
| **350** | ✅ 1 tool_call（26.6s） | ✅ 1 tool_call（20.1s） | `stop` | **可靠下限** |

因此取 **350**，并把「缩短 Prompt」作为主要优化手段：系统提示词从 400+ 字压到约 120 字。

### 三、修改内容

#### 1. 极速模式（默认开启）

```python
# config.py
AGENT_FAST_MODE: bool = _env("AGENT_FAST_MODE", "1")
```

路由层决策顺序：

```python
use_agent = (
    payload.use_agent            # 请求显式指定
    and settings.AGENT_ENABLED   # 全局开关
    and not settings.AGENT_FAST_MODE   # 极速模式下跳过 Agent
)
```

- `AGENT_FAST_MODE=1`（默认）→ 走 0.12.x 确定性融合链路，最终生成走 Ali 通道，**实测 9.5 秒**；
- `AGENT_FAST_MODE=0` → 走 Agent 两轮推理，用于**演示工具调用能力**。

启动日志会明确打印当前模式：

```
[AI] 极速模式：跳过 Agent 两轮推理，直接走确定性融合链路（设 AGENT_FAST_MODE=0 可启用 Agent 演示）
```

#### 2. Prompt 精简

| 位置 | 0.13.0 | 0.13.1 |
|---|---|---|
| 系统提示词长度 | ~420 字（6 条工具规则 + 4 条回答规则） | **~120 字**（工具→场景 四行 + 一行回答要求） |
| 首句 | 「你是高考志愿填报助手，可以调用工具查询本地资料后再回答」 | 「你是高考助手。如需调用工具，直接输出工具名和参数，**禁止输出任何思考过程**」 |

#### 3. 生成轮短超时 + 明确降级

| 参数 | 0.13.0 | 0.13.1 | 理由 |
|---|---|---|---|
| `AGENT_PLAN_TOKENS` | 768 | **350** | 实测可靠下限 |
| `AGENT_ANSWER_TOKENS` | 768 | **300** | 回答 200-300 字够用 |
| `AGENT_ANSWER_TIMEOUT` | 110s | **25s** | 0.13.0 实测 110s 仍超时，白等 1 分半 |
| `AGENT_TOTAL_TIMEOUT` | 200s | **90s** | 规划 27 + 工具 10 + 生成 25 ≈ 62，留余量 |

同时**删掉了「轮数耗尽后再发一轮强制收尾」**的第三次 LLM 调用（0.13.0 会多等 25-60 秒），
改为直接用已获取的工具结果作答。

降级答案现在有明确前缀：

```
（受限于本地算力，已为你直接提取检索结果）

1. 河南本科批实行平行志愿，分数优先、遵循志愿、一轮投档。
   建议按冲稳保 3:3:2 分配院校志愿。
```

#### 4. 答案清洗增强（顺带修的质量问题）

0.13.0 只过滤「开头」的推理旁白，一旦首句是正文，后面的旁白又会漏回来。
0.13.1 改为**全程过滤**，并新增两种判定：

| 判定 | 例子 |
|---|---|
| 以思考连接词开头 | 「所以我要直接回复…」「不过用户要求…」「回答要求是…」 |
| 含元叙述短语 | 「不调用工具」「这里没有工具」「简单回应」 |
| 全旁白时从引号里捞答案 | 模型写「所以应该简单回应"你好！…"」→ 抽 `你好！…` |

实测修复前：`所以我要直接回复，不调用工具。…` → 修复后：`有什么可以帮您的吗？`

#### 5. 环境状态接口 + 前端指示灯

新增 `GET /api/meta/agent-status`（30 秒 TTL 缓存）：

```json
{
  "vector_ready": true,
  "vector_count": 195,
  "graph_ready": false,
  "graph_error": "Neo4j 未启动",
  "local_model": "qwen3:4b",
  "agent_mode": "fast"
}
```

`AiChat.vue` 标题栏新增两个指示灯：

| 指示灯 | 绿灯 | 红灯 + 悬浮提示 |
|---|---|---|
| 政策库 | 知识库有文档（显示切片数） | 「政策库暂无内容，政策类问题可能答不上来」 |
| 图谱 | Neo4j 可连接 | 「图数据库未启动，无法查询开设专业和选科要求」 |

思考动画也按耗时升级：<6s「AI 正在思考…」→ <15s「判断需要查哪些资料」→
<30s「检索政策与录取数据」→ <45s「整理答案」→ **>45s「本地模型正在深度推理，约需 1 分钟（已等待 N 秒）」**。

### 四、实测对比

| 场景 | 0.13.0 | 0.13.1（Fast Mode） |
|---|---|---|
| 「河南本科批平行志愿怎么填报」 | **150.3s** | **9.5s**（↓ 94%） |
| 「你好」 | 13.9s | 2.3s |
| 「郑州大学计算机专业多少分」 | — | 约 8s |

Agent 模式（`AGENT_FAST_MODE=0`，含工具调用）约 60-90 秒，前端有「约需 1 分钟」明确提示。

### 五、验证

```bash
python test_hotfix_0_13_1.py          # 5 组桩版用例
用例 1：极速模式与预算配置      FAST_MODE=True 规划=350token 生成=300token
用例 2：答案清洗（全程过滤）    全旁白→抽引号答案；旁白+正文→只留正文；纯正文不误删
用例 3：生成轮失败兜底          source=agent_tool_only，前缀正确，表格噪声已过滤
用例 4：环境状态接口            字段完整、bool 类型、30s TTL 缓存生效
用例 5：Fast Mode 路由决策      路由层含 AGENT_FAST_MODE 判断
0.13.1 桩版全部通过

python test_hotfix_0_13_1.py --real
  状态接口：vector_ready=True graph_ready=False mode=fast
  问答 status=200 耗时=9.5s mode=fast
  ✅ 极速模式达标：9.5s（目标 <30s）
```

回归：`test_agent_0_13_0`（桩版 7 组）、`smoke_test`、`smoke_rag`、`test_hybrid_rag`、
`test_multimodal_rag`、`test_national_engine --api`、`test_data_cleaner --real`、
`test_user_profile`、`test_hotfix_0_12_1`、`npm run build` 全部通过。

### 六、与任务书的偏差

| 项 | 任务书建议 | 实际处理 | 原因 |
|---|---|---|---|
| 规划轮 token | 150 | **350** | 150 实测 3/3 拿不到 `tool_calls`（推理吃光预算） |
| 极速链路耗时 | 「约 40s」 | 实测 **9.5s** | 最终生成走 Ali 通道，不是本地模型 |
| 前端超时 | 「比如 40s」 | 后端 25s（生成轮）/ 前端 200s（axios） | 后端先超时并降级，前端只需等一次 |

### 七、后续演进（0.13.2）

| 方向 | 说明 |
|---|---|
| 规划轮热点缓存 | 同类问题复用上次的工具选择，可再省 20-27s |
| 换非思考模型 | `qwen2.5:3b-instruct` 无推理开销，Agent 模式可望降到 20-30s |
| 状态接口扩展 | 增加 Ollama / Ali 通道健康，指示灯扩到三个 |
| 流式输出 | Agent 模式边生成边显示，消除长等待感 |

---

## [0.13.0] - 2026-10-20 · UI 重构 + 本地 Agent 调度（Function Calling）+ 报告物理隔离

### 一、四个改动与动机

| # | 改动 | 为什么 |
|---|---|---|
| 1 | 去掉「RAG 增强」开关，进页面即默认检索 | 普通考生不理解 RAG 是什么，开关只会增加决策负担；检索能力应默认开启 |
| 2 | 新增「想让我更了解你吗？」→ 独立心理与画像空间 | 志愿查询与心理疏导是两种完全不同的对话，混在一个聊天框会让本地小模型「既查数据又谈心」 |
| 3 | 用户报告改走 `POST /api/profile/report-upload` | 0.12.x 虽然已从知识库剥离，但路径仍在 `/report/upload-file` 下，语义上仍与知识库纠缠；新路径从命名到实现完全独立 |
| 4 | 本地模型 1.7b → **qwen3:4b** + Function Calling | 1.7b 无法稳定输出 `tool_calls`；4b 在实测中 3/3 稳定返回 |

### 二、核心架构变化：从「写死流水线」到「模型自主调度」

**0.12.x（旧）** —— 检索顺序由代码决定：

```python
# ai.py:_chat_sync() 里的分支链
if 多模态关键词: 以文搜图
elif use_graph: 图谱 + MySQL + 向量 三路并行 → 融合
elif use_rag:   纯向量检索
else:           通用 Prompt
```

问题：每加一路数据源都要改这个函数（违反开闭原则）；简单闲聊也要跑完所有检索。

**0.13.0（新）** —— 把数据源变成工具，由模型决定：

```python
# services/agent/runner.py
reply = llm.chat(messages, tools=registry.specs())   # 模型返回 tool_calls
for call in reply.tool_calls:
    result = registry.execute(call.name, call.arguments["query"])
    messages.append({"role": "tool", "content": result.to_model_text()})
answer = llm.chat(messages, tools=None)              # 基于工具结果作答
```

新增文件（`backend/app/services/agent/`，7 个）：

| 文件 | 职责 | 对应设计原则 |
|---|---|---|
| `base.py` | `BaseTool` 抽象 + `ToolResult` / `ToolCall` 统一契约 | **LSP**（所有工具返回结构一致）/ **DIP**（依赖抽象） |
| `tools.py` | `VectorSearchTool` / `MySQLSearchTool` / `GraphSearchTool` | **SRP**（只管执行 + 转人话） |
| `registry.py` | 工具注册、按名取用、生成 tools 规格 | **OCP**（加工具只改一行） |
| `ollama_tools.py` | Ollama `/api/chat` 原生 tools 客户端 + 降级 | **SRP**（只负责一次带工具的对话） |
| `prompts.py` | Agent 系统提示词 / JSON 规划兜底 / 最终生成 | 策略与机制分离 |
| `runner.py` | 调度器：规划 → 执行 → 再规划 → 生成 | **LoD**（不关心工具内部） |
| `agent_result.py` | `AgentAnswer` / `ToolTrace` 数据契约 | **ISP**（路由/前端只依赖需要的字段） |

### 三、三处必须知道的技术细节（都是实测踩出来的）

#### 1. `think: false` 对 qwen3 无效，只有 `/no_think` 能用

```python
# 实测（Ollama 0.6+ / qwen3:4b）
{"think": False}                      → tool_calls 恒为空，推理全写进 content
system 末尾加 "/no_think"              → 正确返回 tool_calls ✅
```

处理位置：`ollama_tools._with_no_think()`——**在传输层统一注入**，不污染 `prompts.py`。

#### 2. 推理会吃掉 token 预算，规划轮必须给到 768

| `num_predict` | done_reason | tool_calls | 结论 |
|---|---|---|---|
| 300 | `length` | 0 | 推理没写完就被截断 |
| 400 | `length` | 1/2（不稳定） | 时好时坏 |
| **768** | `stop` | **3/3** | 稳定 |

#### 3. 本机 CPU 推理约 10 token/s，两轮 Agent 需要 110-155 秒

| 阶段 | 实测耗时 |
|---|---|
| 规划轮（选工具） | 32-55s |
| 工具执行（向量检索） | 5-10s |
| 生成轮（基于结果作答） | 70-90s |

因此：
- `AGENT_TOTAL_TIMEOUT=200`、前端 axios 超时 200s；
- 前端加「AI 正在思考…」动画，文案随阶段切换（判断→检索→整理）；
- **生成轮失败时用工具结果兜底**（`source=agent_tool_only`），而不是让用户等两分钟后拿到空白。

### 四、云端心理师：本地查数据，云端谈心事

| 维度 | 志愿助手 `/api/ai/chat` | 心理师 `/api/ai/counselor` |
|---|---|---|
| 模型 | 本地 `qwen3:4b` | 云端 `qwen3.7-flash` |
| 能力 | Function Calling 查政策/分数 | 多轮对话、情感推理 |
| 数据 | 不出本机 | 传输到云端 |
| 降级 | 失败回落确定性融合链路 | **不降级**（本地 4b 谈心会说教，宁可报错） |

`CounselorService`（`services/counselor.py`）：

- 强制使用 `AliLLMChannel.chat_messages()`（0.13.0 新增的多轮方法，保留 system/user/assistant 轮次结构）；
- 注入 `user_profiles.summary_text` 到 system prompt，标注「不要直接念给考生听」；
- `_trim()` 过滤非法的 `system` 角色 —— **防止前端注入覆盖人设**。

### 五、报告隐私：从「逻辑隔离」升级为「物理解耦」

| 维度 | 知识库（Admin） | 用户报告（User） |
|---|---|---|
| 接口 | `POST /api/knowledge/upload` | `POST /api/profile/report-upload` |
| 处理函数 | `upload_knowledge` | `upload_report_file`（**不同函数**） |
| 落盘 | `KNOWLEDGE_DIR/` | `{UPLOAD_ROOT}/reports/`（读后即删） |
| 台账 | `knowledge_files` | 无 |
| 向量库 | `gaokao_knowledge` + `gaokao_images` | **不写** |

测试用 **AST 静态检查**验证：解析 `upload_report_file` 的函数体，断言不存在
`add_documents` / `ImageStore` / `ImageExtractor` 调用，也不存在 `knowledge_files` 的
`INSERT/UPDATE` 语句字符串。（用 AST 而不是字符串匹配，是因为 docstring 里会
正当地提到 `gaokao_knowledge`。）

### 六、顺手修掉的一个长期配置 bug

`config._load_dotenv()` 只读 `app/.env`，而项目真实配置在 `backend/.env`——
**README 让用户改的配置从来没生效过**，一直走 `config.py` 的硬编码默认值。
0.13.0 改为按顺序读 `backend/.env` → `app/.env`，并用 `setdefault`
（真实环境变量优先级最高，Windows 系统环境变量里的 `Ali_API_KEY` 不受影响）。

> 这个 bug 极难排查：配置看起来改了、日志却还是旧值。0.13.0 之前
> `OLLAMA_TIMEOUT` 一直是代码里的 60，改 `.env` 到 120 完全无效。

### 七、Neo4j 启动提示

`main.py` 启动时后台检测 Neo4j（限时 8 秒，不阻塞启动），失败时红字输出：

```
[WARN] Neo4j 未启动！知识图谱功能将不可用。
       请执行："E:\Neo4j_NOSQL\neo4j-community-2026.02.2\bin\neo4j.bat" console
       连接串：bolt://localhost:7687  原因：GraphConnectionError
```

路径由 `_find_neo4j_bat()` 自动探测（扫 `E:\Neo4j_NOSQL` 等常见目录），
换机器也能给出可直接复制的命令。

### 八、验证结果

```
python test_agent_0_13_0.py          # 桩版：零网络零数据库
用例 1：配置检查            OLLAMA_MODEL=qwen3:4b，规划/生成超时分离
用例 2：工具注册表          3 个工具 + 规格合法 + 不可用工具自动剔除
用例 3：工具执行            向量/MySQL 正常；无院校名 skipped；异常吞并为 ok=False
用例 4：Agent 调度          4a 调工具后作答 / 4b 闲聊不调工具 / 4c 生成失败兜底 / 4d 首轮失败
用例 5：答案清洗            剥掉「用户问/我需要」旁白，保留正文
用例 6：云端心理师          画像注入 system、过滤非法 system、不可用时不降级
用例 7：报告隐私隔离        AST 检查无 Chroma/台账写入，处理函数与知识库不同
0.13.0 桩版全部通过
```

真实链路（`--real`）实测：

| 验收标准 | 结果 |
|---|---|
| 1. AI 助手无 RAG 开关，问「河南本科批怎么填报」自动调政策库工具 | ✅ `tools_used=['tool_search_vector']`，`sources=['高考志愿录取顺序.pdf']` |
| 2. 心理空间上传 PDF 能解析出画像 | ✅ `POST /api/profile/report-upload` 200，画像 `ready=true` |
| 3. 后台知识库看不到这份 PDF | ✅ 知识库文件列表无 `mbti` 记录 |
| 4. 个人主页能看到画像 | ✅ `GET /api/profile` → `ready=true` |

### 九、已知限制（本机硬件决定）

| 项 | 说明 |
|---|---|
| 问答需 110-155 秒 | CPU 推理约 10 token/s。换 GPU 或换更小的非思考模型可显著改善 |
| 生成轮偶发超时 | 超时后走 `agent_tool_only`，返回检索到的原文而非自然语言总结 |
| qwen3 无法真正关闭思考 | `/no_think` 只能抑制「选工具」时的推理，自由作答仍会有旁白（已用 `clean_answer` 剥离） |
| 图谱工具需 Neo4j | 未启动时 `tool_search_graph` 自动从候选列表剔除，模型只会在剩下两个工具里选 |

### 十、后续演进方向（0.14.0）

| 方向 | 说明 |
|---|---|
| 流式输出 | 边生成边显示，把「等待 2 分钟」变成「逐步看到结果」 |
| 规划轮缓存 | 同类问题复用上次的工具选择，省掉 32-55 秒 |
| 心理师画像回写 | 从对话中自动抽取兴趣/偏好，写回 `user_profiles` |
| 换非思考模型 | 如 qwen2.5:3b-instruct，无推理开销，延迟可降到 20-30 秒 |

---

## [0.12.1] - 2026-10-18 · 热修复：隐私隔离 / 地图统计 / 规划师模式 / 超时贯通

### 一、四个线上问题与根因

| # | 现象 | 真实根因 |
|---|---|---|
| 1 | 普通用户的私人报告进了「知识库管理」，管理员与其他用户都能检索 | 0.12.0 抽屉里写着「请先在知识库管理上传」，把用户报告导流到了 Admin 的公共政策库；报告因此写入 Chroma `gaokao_knowledge` 与 `knowledge_files` 台账 |
| 2 | 吉林、山东地图「暂无数据」，江西「0 个专业 / 17 所院校」 | ① 统计口径用 `university_code`/`major_code` 做 DISTINCT，而山东 `university_code` **33861/33861 全空**、江西 `major_code` **9660/11725 为空**，`CONCAT(code,'-',code)` 为 NULL → `COUNT(DISTINCT NULL)=0`；② 吉林 `school_province` **整列为 NULL**，被 `IS NOT NULL` 过滤掉 → 返回空数组 |
| 3 | AI 一直转圈 / 超时 504 | `ai_service.ask(timeout=…)` **收了参数却从未下传**给 `llm_client`，所有调用实际用通道构造时的 `ALI_TIMEOUT(30)`/`OLLAMA_TIMEOUT(45)`；链路最多串 3 次 LLM 调用，叠加后越过 120 秒上限 |
| 4 | 「我 502 分该去哪」被拒答；「你能猜到我想去哪所学校吗」被拦截 | ① 向量通道命中了**无关文档**（MBTI 报告、专升本录取率），`contexts` 非空 → 走融合路径 → 被防幻觉规则逼成拒答；② `ROUTER_PROMPT` 只认「院校/专业/分数线」等硬词，规划类问法被误判为闲聊 |

### 二、修复内容

#### 1. 隐私隔离：报告与知识库彻底分家

| 位置 | 改动 |
|---|---|
| `utils/file_utils.py` | 新增 `REPORT_ALLOWED_EXTS`（多 `png/jpg/md`）、`ensure_report_dir()`、`save_report_file()`；落盘在 `{UPLOAD_ROOT}/reports/`，与 `KNOWLEDGE_DIR` **物理隔离** |
| `services/profile/report_reader.py` | **新增** `ReportReader`：文件 → 文本，`finally` 块里**立即删除**文件（磁盘不留私人副本） |
| `routers/profile.py` | **新增** `POST /api/profile/report/upload-file`：读文件 → 提文本 → `ProfileService.extract_report`；全链路**不调** `add_documents` / `ImageStore` / 不写 `knowledge_files` |
| `utils/ocr_utils.py` | 新增 `ocr_image_file()`：支持直接上传图片（复用 `_ocr_one` 的模型选择与重试） |
| `AiChat.vue` | 抽屉内改为 `el-upload` 直接上传（PDF/图片/TXT/MD/DOCX），删除「请先在知识库管理上传」的提示，增加隐私说明 |
| `Knowledge.vue` | 保持仅管理员可见（路由 `requiresAdmin` + Navbar `v-if`） |

**隐私保证**：报告只进当前用户的 `user_profiles`，不进 Chroma、不进台账、不留磁盘。

#### 2. 地图统计修复

```sql
-- 旧（错误）：任一 code 为空 → CONCAT 为 NULL → COUNT(DISTINCT NULL) = 0
COUNT(DISTINCT university_code), COUNT(DISTINCT CONCAT(university_code,'-',major_code))

-- 新（正确）：改用名称列，各省都有值
COUNT(DISTINCT university_name),
COUNT(DISTINCT CONCAT_WS('||', university_name, major_name))
```

同时不再过滤 `school_province IS NOT NULL`：缺失值归入 `数据缺失` 桶，
接口返回 `degraded=True` + `message`，前端显示明确说明而不是「暂无数据」。

#### 3. 规划师模式（解决「拒绝回答规划类问题」）

新增 `ADVISORY_PROMPT` + `build_advisory_prompt(question, profile_context, context_text)`。

关键改动：**只要命中主观咨询意图，无论有没有检索到内容都走规划师 Prompt**。
- 有检索内容 → 作为【参考资料】放进 Prompt，要求「有数据就引用」；
- 无检索内容 → 基于画像 + 通识给方向性建议；
- 两种情况都**严禁编造**分数线 / 位次 / 学费。

`source` 分别标记为 `hybrid:advisory`（无资料）与 `hybrid:advisory_with_context`（有资料），便于排查。

#### 4. 意图识别放行

```python
SUBJECTIVE_INTENT_KEYWORDS = (
    "我该", "该去哪", "推荐", "建议", "帮我看看", "把把关", "稳不稳",
    "猜猜", "猜到", "适合我", "怎么填", "怎么选", "分析一下", …
)  # 25 个词
```

`route_query()` 先做**确定性预检**：命中即放行，**不调 LLM**。
既修复了误拦截，又把一次 20-45 秒的 LLM 往返从关键路径上移除。
`ROUTER_PROMPT` 同步新增第 4 条规则（主观咨询判 YES）。

#### 5. 超时贯通 + 分阶段日志 + 504

| 层 | 改动 |
|---|---|
| `llm_client.BaseLLMChannel.chat` | 抽象契约新增 `timeout` 参数 |
| `AliLLMChannel` | `kwargs["timeout"] = timeout or self.timeout`（SDK 支持 per-request） |
| `OllamaLLMChannel` | `http_timeout = timeout or self.timeout` |
| `LLMClient.chat` | 透传 `timeout` |
| `ai_service.ask` | **真正把 timeout 传给门面**（0.12.0 及以前在这里丢掉） |
| `graph_query_engine` | 新增 `graph_llm()`，图谱专用 `GRAPH_LLM_TIMEOUT`（默认 20s），避免两次调用吃掉生成预算 |
| `routers/ai.py` | 整体超时 `CHAT_TOTAL_TIMEOUT`（默认 100s，留 20s 余量），超时抛 **504** 并提示可操作建议；`print` 分阶段耗时 |
| `config.py` | 新增 `CHAT_TOTAL_TIMEOUT` / `GRAPH_LLM_TIMEOUT` / `UPLOAD_ROOT` |

输出示例：

```
[PROFILE] 已注入用户画像 user=13 长度=179：你性格理性独立…
[AI] 阶段耗时 读画像=0.00s（画像长度=179）
[AI] 阶段耗时 总链路=43.35s source=hybrid:advisory_with_context
```

### 三、验证结果

#### 1. 桩版（`python test_hotfix_0_12_1.py`）

```
用例 1：地图统计口径         山东 19688/1126、江西 7072/452、吉林 9112（degraded）、河南 9578（未退化）
用例 2：主观咨询意图识别     8 个咨询问法全命中、5 个无关问法不命中（白名单 25 词）
用例 3：ROUTER_PROMPT        已含第 4 条主观咨询规则
用例 4：规划师兜底           ADVISORY_PROMPT 含画像/禁编造/参考资料分支
用例 4b：强制三路全空        source=hybrid:advisory；对照组客观问题仍 hybrid_empty
用例 5：报告隐私隔离         目录不同、读后即删、拒绝 exe、源码无 Chroma 调用
用例 6：超时贯通             ask → LLMClient → Ali/Ollama 三层均已透传
```

#### 2. 真实链路（`--real`）

| 验收标准 | 结果 |
|---|---|
| 1. 抽屉上传 PDF 能解析，但知识库管理看不到 | ✅ 文件上传 200；`知识库文件数=4，含用户报告=无` |
| 2. 地图切吉林 / 山东正常显示 | ✅ 山东 19688 专业 / 1126 院校；吉林 9112 / 878（带降级说明） |
| 3. 问「502 分根据画像我该去哪」给出建议 | ✅ `source=hybrid:advisory_with_context`，回答「502分通常对应省属公办本科中段，建议聚焦计算机类、电子信息类…」 |
| 4. 不再长时间转圈 | ✅ 总链路 43.35s（< 100s 上限），超时明确 504 |

附加：无关问题仍返回 `router_blocked`（放宽未破坏底线）。

#### 3. 回归

```bash
python smoke_test.py / smoke_rag.py            # 通过
python test_hybrid_rag.py                      # 0.9.1 通过
python test_multimodal_rag.py                  # 0.10.0 通过
python test_national_engine.py --api           # 0.11.0 通过
python test_data_cleaner.py --real             # 0.11.2 通过
python test_user_profile.py                    # 0.12.0 通过
cd ../frontend && npm run build                # vue-tsc + vite 通过
```

### 四、已知限制

| 项 | 说明 |
|---|---|
| 吉林地图无省份分布 | 该省 `major_admission_2025_all.school_province` 整列为 NULL，且 `enrollment_plan` 无此列可回补，只能展示总量 |
| 规划师模式仍可能较慢 | 三路检索（尤其图谱的两次 LLM 调用）约 40 秒；已受 `GRAPH_LLM_TIMEOUT` 约束，如需更快可关闭 `use_graph` |
| 报告文件不落盘 | 提取后即删除，因此**无法回溯**原始报告；需要留档请让用户自行保存 |
| 图片 OCR 依赖通道 | 未配置 `Ali_API_KEY` 时图片提取会失败并提示改用粘贴文字 |

### 五、后续演进方向（0.13.0）

| 方向 | 说明 |
|---|---|
| 主观问题跳过图谱通道 | 规划类问题几乎不需要关系型事实，跳过可省约 40 秒 |
| 流式输出 | 前端边生成边展示，把「等待感」降到最低 |
| 报告归档（可选） | 用户主动勾选「保留原文件」，落到私有目录并加密 |
| 地图数据补齐 | 吉林补 `school_province` 列，或从院校名反查所在地 |

---

## [0.12.0] - 2026-10-18 · 账号体系完善 + 用户画像系统（双轨制）

### 一、原有技术（0.11.2）及缺陷

| 环节 | 0.11.2 的状态 | 存在的缺陷 |
|---|---|---|
| 注册 | 只有用户名 + 密码，且前端无注册页 | 用户只能由脚本创建，C 端无法自助开户 |
| 用户资料 | `users` 只有 `username / password_hash / role` | 无法记录昵称、手机号、性别、生日，画像缺少基础维度 |
| AI 问答 | 每次提问都是「陌生人视角」 | 同一个考生反复问，模型不知道他的地域/学费/专业偏好，回答永远泛化 |
| 用户体系 | `/api/ai/chat` 不校验登录 | 无法把画像、历史挂到 user_id 上，也挡不住匿名刷接口 |
| 个性化 | 无 | 没有「用户画像」这一层数据载体 |

### 二、改进技术及对应代码位置

#### 1. 数据层

| 文件 | 改动 |
|---|---|
| `models/user.py` | 新增 `nickname / phone / gender / birthday / email`，并加 `display_name` 属性（昵称优先） |
| `models/profile.py` | **新建** `UserProfile`：`user_id`(唯一)、`basic_info`(JSON)、`external_reports`(TEXT)、`survey_answers`(JSON)、`summary_text`(TEXT)、`source` |
| `database.py` | `_COLUMN_MIGRATIONS["users"]` 补 5 列；新增 `_TABLE_MIGRATIONS` + `ensure_tables()` 幂等建表 |

迁移全部幂等，启动时自动执行，**不需要手工改库**：

```
[startup] 已建表：user_profiles
[startup] 已补列：users.nickname, users.phone, users.gender, users.birthday, users.email
```

#### 2. Schema 按接口隔离拆细（ISP）

`schemas/user.py` + `schemas/profile.py` 共 11 个模型，每类交互一个：

| 交互 | 模型 |
|---|---|
| 登录 | `LoginIn`（只有账号密码） |
| 注册 | `RegisterIn`（+ 昵称 / 手机号） |
| 改资料 | `ProfileBasicIn`（全可选，支持只改一项） |
| 生成问卷 | `SurveyQuestionIn`（只有领域 + 数量） |
| 提交问卷 | `SurveySubmitIn`（只有 `answers` 字典） |
| 上传报告 | `ReportUploadIn`（只有文本 + 类型提示） |
| 输出 | `ProfileOut` / `SummaryOut` / `UserOut` |

> 没有任何一个「大而全」的模型承载所有参数。

#### 3. Service 层（`services/profile/`，9 个文件）

| 文件 | 类/职责 | 对应设计原则 |
|---|---|---|
| `llm_json.py` | `LLMJsonParser`：去 `<think>`、去代码围栏、修尾逗号、全角引号、括号配对扫描 | **CRP**（报告提取与问卷总结共用同一解析器） |
| `prompts.py` | `SURVEY_QUESTION_PROMPT` / `REPORT_EXTRACT_PROMPT` / `SURVEY_EXTRACT_PROMPT` / `PROFILE_SUMMARY_PROMPT` | **OCP**（新增来源只加模板） |
| `extractors.py` | `BaseProfileExtractor` 抽象 + `ReportExtractor` / `SurveyExtractor` | **DIP**（只依赖 `llm` 可调用对象）+ **LSP**（两实现同契约） |
| `survey.py` | `SurveyQuestionGenerator`：LLM 出题 + 8 道内置题库兜底 | **SRP** |
| `summarizer.py` | `ProfileSummarizer`：LLM 汇总 + 规则模板兜底 | **SRP** |
| `repository.py` | `BaseProfileRepository` 抽象 + `ProfileRepository`(MySQL) + `InMemoryProfileRepository`(测试) | **DIP** |
| `service.py` | `ProfileService`：编排 5 个业务动作 | **SRP**（不写 SQL、不拼 Prompt、不管 HTTP） |
| `__init__.py` | 只导出编排器与抽象，隐藏内部实现 | **LoD** |

**为什么双轨制最终汇合到同一条路径**：报告与问卷是两个 `BaseProfileExtractor` 子类，
产出同一个结构（`{traits, preferences/summary}`），再统一走 `ProfileService.rebuild()`
生成 `summary_text`。这样新增第三条轨道（比如性格测试）无需改 `rebuild()`。

#### 4. 路由层（`routers/profile.py`，只做参数与响应）

| 接口 | 职责 |
|---|---|
| `GET /api/profile` | 读画像（没有则返回空画像，不 404） |
| `PUT /api/profile/basic` | 完善基础资料 |
| `GET /api/profile/domains` | 问卷可选领域（前后端共用一份常量） |
| `POST /api/profile/survey/questions` | 生成业务问卷（途径 B） |
| `POST /api/profile/survey/submit` | 提交问卷并重算画像 |
| `POST /api/profile/report/upload` | 解析报告并重算画像（途径 A） |
| `POST /api/profile/summary/rebuild` | 手动重算 |
| `DELETE /api/profile` | 清空画像 |

#### 5. 画像注入 AI（0.12.0 核心）

| 位置 | 改动 |
|---|---|
| `routers/ai.py` | `/chat` 加 `Depends(get_current_user)`（**未登录 401**）+ `Depends(get_db)` |
| `routers/ai.py` | `_load_profile_summary()` 读画像，异常静默降级为空串 |
| `rag_service.py` | 新增 `build_profile_section()`；`build_hybrid_prompt()` / `answer_with_hybrid()` / `generate_answer()` 均新增 `profile_context` 参数（**默认空串，向后兼容**） |
| `HYBRID_FUSION_PROMPT` | 新增 `{profile_section}` 占位 |

注入措辞统一为：

```
【考生画像】（用于个性化建议，不得据此编造任何数字）：
你性格独立严谨，擅长逻辑分析……适合计算机、软件工程等研究型专业。
请在回答中结合这些特征给出建议，但分数线、学费、位次等数字仍必须以事实数据为准。
```

> 关键约束：**画像只影响「建议口径」，不能成为数字来源**——避免模型拿「画像」当借口编造分数。

#### 6. 前端

| 文件 | 改动 |
|---|---|
| `views/Register.vue` | **新建** 注册页（昵称 / 手机号 / 用户名 / 密码 / 确认密码，含校验） |
| `views/Profile.vue` | **新建** 个人主页（左：基础资料 + 报考信息；右：画像总结 + 特征标签 + 重建/清空） |
| `components/Navbar.vue` | 登录后改为**头像下拉**（个人主页 / 构建画像 / 管理后台 / 退出）；未登录显示「注册 + 登录」 |
| `views/student/AiChat.vue` | **新建抽屉**：Step1 双轨制选择 → Step2A 报告 / Step2B 领域勾选 + 卡片式问答 → Step3 画像总结；顶部显示「已结合你的画像」 |
| `router/index.ts` | 新增 `/register`、`/profile`（`requiresLogin`） |
| `types/user.ts`、`types/profile.ts`、`api/profile.ts`、`api/auth.ts`、`stores/user.ts` | 类型与 API 封装；store 新增 `displayName` / `avatarText` / `patchUser` |

### 三、验证流程

#### 1. 桩版单测（不连库、不调大模型）

```bash
cd backend
python test_user_profile.py
```

```
用例 1：LLMJsonParser 脏文本解析        10 个对象 + 1 个数组 通过
用例 2：ReportExtractor / SurveyExtractor  归一化 + 空/垃圾输入安全降级
用例 3：SurveyQuestionGenerator 兜底      内置 3 题 / LLM 3 题
用例 4：ProfileSummarizer 规则兜底        106 字画像 + 空数据引导语
用例 5：ProfileService 全流程             资料 → 报告 → 问卷 → both → 清空
用例 5b：画像注入 Prompt 验证             ①② 含【考生画像】；③ 空画像不注入
```

#### 2. 真实链路（服务已启动）

```bash
python test_user_profile.py --real
```

| 步骤 | 结果 |
|---|---|
| ① 注册 | 200，昵称/手机号入库 |
| ② 登录 | 200，`nickname=测试考生` |
| ③ 初始画像 | `ready=False` |
| ④ 完善资料 | `basic_info={'province':'河南','category':'物理类','score':600,'gender':'male',…}` |
| ⑤ 报告解析（真实大模型） | 200，提取出 `mbti=INTJ` / `holland=IRC` / 5 条 traits / 4 个推荐专业 |
| ⑥ 生成问卷（真实大模型） | 3 道，`fallback=False`，id 为 `region_preference / tuition_sensitivity / career_focus` |
| ⑦ 提交问卷 | 200，`source=both`（两条轨道汇合） |
| ⑧ 未登录调用 chat | **401** |
| ⑨ 登录后 chat | 200，`profile_injected=True`，回答正文出现「根据您提供的【考生画像】…」 |
| ⑩ 清空画像 | 200 |

后端控制台打印（验收标准 4）：

```
[PROFILE] 已注入用户画像 user=5 长度=209：你具备INTJ人格特质，逻辑严密且擅长独立思考……
```

> 用 `print` 而非 `logger.info`：uvicorn 默认只输出 WARNING 以上的应用日志（0.10.0 的 OCR 日志踩过同一个坑）。

#### 3. 回归

```bash
python smoke_test.py            # 通过
python smoke_rag.py             # 通过（已改为带 Token 调用 chat）
python test_hybrid_rag.py       # 0.9.1 通过
python test_multimodal_rag.py   # 0.10.0 通过
python test_national_engine.py --api   # 0.11.0 通过
python test_data_cleaner.py --real     # 0.11.2 通过
cd ../frontend && npm run build        # vue-tsc + vite build 通过
```

### 四、已知限制

| 项 | 说明 |
|---|---|
| 报告上传只收文本 | 未直接接收 PDF/图片：需先走 `/api/knowledge/upload` 的 OCR 转文本（合成复用，避免重复实现文件解析）。前端已在抽屉内提示 |
| 画像只注入不缓存 | 每次 chat 都查一次 `user_profiles`（单行主键查询，开销可忽略）；未做进程内缓存，保证资料改动立即生效 |
| 问卷领域由前端勾选 | 后端只提供 `ALLOWED_DOMAINS` 白名单与默认集合，不支持用户自定义领域名 |
| `summary_text` 会覆盖 | 报告/问卷/重建都会重算整段画像，不做增量合并；若要保留历史版本需另做快照表 |
| 未做画像版本管理 | 只存最新一份；`source` 字段记录来源（report / survey / both / manual） |

### 五、后续演进方向（0.13.0）

| 方向 | 说明 |
|---|---|
| 画像版本快照 | 每次汇总存一份历史，支持对比与回滚 |
| 画像参与推荐排序 | 把「学费敏感 / 地域偏好」变成 `calculate_tiers` 的软排序因子 |
| 多轮对话记忆 | 结合画像做上下文摘要，支持「上次说的那个专业」这类指代 |
| 画像评估指标 | 在 0.8.0 的评估体系里加 `profile_hit_rate`，量化画像对回答相关性的贡献 |
| 手机号验证码 | 当前只做格式校验，未接入短信服务 |

---

## [0.11.2] - 2026-10-18 · 数据清洗补丁：从 `major_note` 提纯缺失的学费与学制

### 一、原有技术（0.11.1）及缺陷

部分省份的 `enrollment-plan.csv` 结构不规范，导入总表后关键字段整列为 NULL：

| 省份 | 计划表总行数 | 有学费 | 有学制 | 备注 |
|---|---|---|---|---|
| 广西 | 38110 | **0** | 38107 | 学费全在 `major_note` 里 |
| 四川 | 46148 | **0** | 46148 | 学费被写进了 **`duration` 列** |
| 安徽 | 40509 | **0** | 0 | 两者都缺 |
| 北京 | 5154 | 252 | 0 | 大面积缺失 |

前端表现为「学费」列空白，考生无法按学费筛选/比较。重新导库成本高，
且原始 CSV 已不再保留规范结构，因此改为**读取时提纯**。

### 二、改进技术及对应代码位置

#### 1. 新增 `utils/data_cleaner.py`

| 函数 | 职责 |
|---|---|
| `extract_tuition(note)` | 从文本提学费；`9.5万元/年`→95000，`免学费/免收学费/免费`→0，提不到→None |
| `extract_duration(note)` | 从文本提学制，返回 `"4年"`；避开 `第1~3年`、`2024年` 等假阳性 |
| `_fix_shifted_fields(item)` | **修「列错位」**：`duration` 里装的是学费时搬回 `tuition` |
| `clean_item(item)` | 统一入口：先修错位 → 再提纯缺失字段 → 金额收敛成整数 |

**四类真实写法与边界**（都在测试里固化）：

```
(6000元/年;...)                     → 6000
(4年,5000元/年,...)                  → 学制 4年、学费 5000
(学费9.5万元/年)                     → 95000（万 单位）
(免收学费,...) / (...,免费,...)       → 0
(国内学费6480元/年,...53000澳元/年)   → 6480（只取首个人民币值，外币不误判）
(第1~3年...第4年...)                 → 不当学制（后行断言排除「第/~/至/数字」）
```

#### 2. 接入点

| 位置 | 改动 |
|---|---|
| `recommend_service._plan_index()` | 索引构建时提纯，`/api/recommend` 与 `/api/majors` 同时受益 |
| `recommend_service._to_national_item()` | 保留 `major_note`，先用投档表自身的 note 兜一层 |
| `recommend_service.enrich_with_plan()` | **重写**：改为复用 `_plan_index` / `_lookup_plan`（见下） |
| `routers/university.majors()` | 条目组装后调 `clean_item()` |
| `schemas/student.py` | `tuition` / `plan_count` 由 `float` 改为 `int`（避免序列化成 `5500.0`） |
| `Volunteer.vue` / `University.vue` | 学费 0 显示「免学费」，null 显示「暂无」；新增「学制」列 |

#### 3. 顺带修掉的两个隐藏 bug

**(a) `enrich_with_plan` 的匹配方式失效**
原实现自己按 `(院校名, 专业名)` 精确匹配计划表，但各省计划表的专业名带括号后缀
（广西：`工科试验班(吴健雄班)` vs 投档表 `工科试验班`），**精确匹配全部落空**——
索引里明明有学费，页面上却一个都不显示。改为复用 `_plan_index` / `_lookup_plan`
的三级匹配（代码 → 名称 → 院校兜底），且不再重复写查询逻辑。

**(b) 批次归一缺「本科普通批」**
广西的本科批次写作「本科普通批」、四川写作「本科」「专科」，
`_batch_matches()` 未覆盖 → 计划索引直接为空。已补齐，
并让 `_plan_index` / `_fetch_candidates` 统一走 `dataset_access.scope_conditions()`。

#### 4. 「列错位」的判定依据

不能简单用「`duration` 不是以年结尾就是学费」，因为广西存在真实的 **9 年制**
（北京中医药大学中医学领军人才培养计划）。改用**数值量级**判断：

```python
number >= 100  → 学费（真实学费至少三位数）
1 <= number <= 12 → 学制（4年 / 9年 都合法）
```

### 三、验证流程

#### 1. 单测（不连库）

```bash
cd backend
python test_data_cleaner.py
```

```
用例 1：extract_tuition / extract_duration     17 通过 / 0 失败
用例 2：clean_item 补全 / 列错位修复             7 通过 / 0 失败
```

#### 2. 真实库验证

```bash
python test_data_cleaner.py --real
```

| 省份 | 索引条数 | 学费填充率 | 学制填充率 |
|---|---|---|---|
| 广西 | 17482 | **0% → 99%** | **0% → 100%** |
| 四川 | 19794 | **0% → 99%**（从 duration 列搬回） | 1%（原始无学制） |
| 安徽 | 18218 | **0% → 98%** | 0%（原始无学制） |
| 河南 | 22846 | 98%（未退化） | 100%（未退化） |

#### 3. 接口级验证（任务要求的两个具体场景）

**广西 · 桂林电子科技大学**（计划表 `tuition` 整列为 NULL）：

```json
{"major_name": "计算机科学与技术", "tuition": 6000, "duration": "4年",
 "major_note": "（拔尖人才实验班）（在花江校区办学）"}
```

`tuition` 成功从 `6000元/年` 提纯为**整数 6000**。

**四川 · 南方医科大学**（学费被写进 `duration` 列）：

```json
{"major_name": "临床医学", "tuition": 7660, "duration": null}
```

#### 4. 回归

```bash
python test_national_engine.py --api   # 通过
python test_hybrid_rag.py              # 通过
python test_multimodal_rag.py          # 通过
python smoke_test.py / smoke_rag.py    # 通过
cd ../frontend && npm run build        # vue-tsc + vite build 通过
```

### 四、已知限制

| 项 | 说明 |
|---|---|
| 学制无法凭空生成 | 四川、安徽的原始数据里完全没有学制信息（`duration` 列被学费占用），提纯后仍为 null，前端显示「暂无」 |
| 北京学费仍大面积缺失 | 北京计划表 `tuition` 仅 252/5154 有值，且 note 里多数没有金额文本，属于数据源本身缺失 |
| 计划数（`plan_count`）未做提纯 | 计划数不是「元/年」这类可正则化的文本，仍依赖原始列 |
| 仅补展示层 | 提纯结果不回写数据库，属于读取时派生；若要持久化需另做一次 ETL |

### 五、后续演进方向（0.12.0）

| 方向 | 说明 |
|---|---|
| 提纯结果回写 | 一次性 ETL 把提纯结果写回 `tuition` / `duration` 列，避免每次请求都计算 |
| 缺失省份补导 | 北京/四川/安徽的招生计划原始数据补齐学费列 |
| 提纯规则可配置 | 把正则与免费词表移到配置，省份特殊写法无需改代码 |

---

## [0.11.1] - 2026-10-18 · 热修复：彻底清理 `_henan` 硬编码，打通全国多省前后端链路

### 一、原有技术（0.11.0）及缺陷

0.11.0 只重构了 `rank_service` / `recommend_service` 的**底层引擎**，路由层、模型层、前端没同步，
导致「引擎能跑、页面全空」：

| 环节 | 0.11.0 的状态 | 存在的缺陷 |
|---|---|---|
| `models/dataset.table_name()` | 仍返回 `major_admission_2025_henan` | 分省表已删除 → 反射失败 → **500「数据表不存在或无法反射」** |
| `routers/stats.py` 首页地图 | 用 `table_name()` 拼分省表 | 地图无数据 |
| `routers/university.py` 查大学/查专业 | 同上，且只按 `category` 过滤 | 无数据；即便有表也会跨省串联 |
| `routers/meta.py` options / province-stats / hot-schools | 同上，`_available_years` 还按 `%_henan` 扫表 | 下拉框与热门院校全空 |
| `rank_service._load_score_range()` | 查分省一分一段表 | 位次换算 500 |
| `recommend_service._plan_index()` / `_fetch_candidates()` | 查分省表 | 学费 / 计划数丢失 |
| 前端 `Volunteer.vue` | 省份下拉只有一个写死的「河南」，科类靠首选科目推导 | 选不了北京，也无法表达「综合」 |
| 前端 `University.vue` / `Home.vue` | `province: '河南'` 硬编码 | 换省份无效 |

> 除代码缺陷外还有一处**数据现实**：`school_admission_2025_all` **不存在**（只有
> `major_admission` / `enrollment_plan` / `score_range` 三张总表），因此院校维度必须从投档表聚合。

### 二、改进技术及对应代码位置

#### 1. `models/dataset.py`：表名统一到 `_all`

```python
def table_name(kind, year, province=""):   # province 保留但不再参与命名
    return f"{kind}_{year}_{NATIONAL_TABLE_SUFFIX}"      # → major_admission_2025_all

KIND_FALLBACK = {KIND_SCHOOL: KIND_MAJOR}   # 无 _all 表的数据集回落
```

#### 2. 新增 `services/dataset_access.py`（单一职责 / 接口隔离）

| 函数 | 职责 |
|---|---|
| `resolve_table(kind, year)` | 反射全国总表，`school_admission` 自动回落 `major_admission` |
| `province_conditions()` | 生成 `WHERE province = ?`（★ 防跨省串联的核心） |
| `category_conditions()` | 科类归一（综合 / 物理类·历史类 / 理科·文科） |
| `batch_conditions()` | **省份感知的批次归一**（见下） |
| `scope_conditions()` | 一次性返回「省份 + 科类 + 批次」三组条件 |

**批次归一是本次的隐藏坑**：实测总表里的批次写法有 20+ 种——
「本科批」19 省通用，但四川/陕西是「本科批A/B/C段」，还有「普通本科批」
「专科批次」「高职专科」「高职(专科)批」，浙江/山东用「普通类一段/二段」。
直接 `batch = '本科批'` 精确匹配，四川这类省份一条都查不到（表现为查大学页面空白）。
现在按「该省真实批次字典」做语义匹配，匹配不到时**跳过批次过滤并记日志**，
宁可多给数据也不让整页空白。

#### 3. 路由层：只传参数，不拼表名

| 文件 | 改动 |
|---|---|
| `routers/stats.py` | `resolve_table` + `scope_conditions`，地图按考生省份统计 |
| `routers/university.py` | 院校/专业列表改为总表聚合 + 省份隔离；`university_code`/`province` 都参与过滤 |
| `routers/meta.py` | options / province-stats / hot-schools 全部改总表；`_available_years` 改为扫 `score_range_%_all`（年份全局，与省份无关） |
| `routers/student.py` | `/score-to-rank`、`/rank-to-score` 改用 `score_to_rank_detail` / `rank_to_score_detail`（0.11.0 改名后未同步的调用点） |
| `recommend_service.py` | `_plan_index()` / `_fetch_candidates()` 补 `province` 条件 |
| `rank_service.py` | `_load_score_range()` 补 `province` 条件（否则 30+ 省一分一段混在一起，位次全错） |

#### 4. 前端：省份 / 科类级联

| 文件 | 改动 |
|---|---|
| `api/recommend.ts` | 新增 `metaOptions(province)` + `MetaOptionsResult`（含 `provinces` / `categories_map`） |
| `types/recommend.ts` | `RecommendResult` 增加 `rank` / `tiers` |
| `Volunteer.vue` | 新增「考试地区」全国 31 省下拉 + 「科类」级联下拉；3+3 省份自动隐藏 3+1+2 科目选择；科类与首选科目双向同步 |
| `University.vue` | 新增「考生省份」下拉（与「院校所在地」区分），科类级联，专业明细带上省份 |
| `Home.vue` | 新增省份下拉，地图按考生省份统计，标题与文案改为动态省份 |

前端级联逻辑：`province` 变化 → `category = categoriesMap[province][0]` → 清空位次/批次/结果 →
重新拉批次线。3+3 省份（如北京）只有「综合」，自动清空科目选择。

### 三、验证流程

#### 1. 后端接口（真实 HTTP）

| 接口 | 河南/物理类 | 北京/综合 | 四川/物理类 |
|---|---|---|---|
| `/api/stats/major-count-by-province` | 9535 专业 / 30 省 | 1541 专业 / 30 省 | — |
| `/api/universities` | 470 所 | 254 所 | 453 所 |
| `/api/meta/options` | categories=`[历史类, 物理类]` | categories=`[综合]` | — |
| `/api/meta/hot-schools` | 5 条 | 5 条 | — |
| `/api/score-to-rank`（600 分） | 位次 45887 | 位次 11883 | — |
| `/api/recommend/national` | 冲/稳/保 = 50/50/50 | 50/50/50 | — |
| `/api/recommend` | 冲/稳/保 = 50/50/50，含学费 6000 | 50/50/50 | — |

跨省隔离验证：同一接口换省份，总数从 9535 降到 1541，说明 `province` 条件真正生效
（若漏加，两省结果会完全相同）。

非法组合仍正确拦截：`beijing/物理类` → `400 该省份不支持此科类：北京 仅支持 综合`。

#### 2. 前端

```bash
cd frontend
npm run build      # vue-tsc --noEmit + vite build 均通过
```

`vue-tsc` 会校验模板表达式与 `<script setup>` 作用域，因此
`categoryOptions` / `needSubjectPick` / `onProvinceChange` 等新绑定均为编译期验证通过。
打包产物确认包含 `科类`、`考生省份`、`categories_map`、`/meta/options`。

#### 3. 回归

```bash
cd backend
python test_national_engine.py --api   # 通过
python test_hybrid_rag.py              # 0.9.1 三路融合通过
python test_multimodal_rag.py          # 0.10.0 多模态通过
python smoke_test.py                   # 冒烟通过
python smoke_rag.py                    # RAG SMOKE DONE
```

#### 4. 已知数据缺口（非代码问题）

`enrollment_plan_2025_all` 各省字段填充率差异很大，实测：

| 省份 | 总行数 | 有学费 | 有计划数 |
|---|---|---|---|
| 河南 | 58275 | 57645 | 58275 |
| 河北 | 51198 | 49566 | 0 |
| 四川 | 46148 | **0** | 46145 |
| 安徽 | 40509 | 0 | 0 |
| 广西 | 38110 | 0 | 0 |

因此北京/四川等省份的「学费」「计划数」显示为空是**原始数据缺失**，
富化逻辑本身正确（河南实测能补出学费 6000、计划数 2）。补齐需重新导入这些省的招生计划。

### 四、后续演进方向（0.12.0）

| 方向 | 说明 |
|---|---|
| 老高考数据补齐 | 山西 / 内蒙古 / 青海导入 2025 数据 |
| 招生计划字段补全 | 补齐四川/安徽/广西等省的 tuition 列 |
| 前端省份记忆 | 用 localStorage 记住上次选择的省份与科类 |
| 批次写法字典化 | 把 `_batch_matches` 的模糊规则升级为可配置的批次映射表 |

---

## [0.11.0] - 2026-10-17 · 架构重构：核心匹配引擎从「河南单省」升级为「全国多省自适应」

### 一、原有技术（0.10.0）及缺陷

| 环节 | 0.10.0 的技术 | 存在的缺陷 |
|---|---|---|
| 表名拼接 | `table_name(KIND_MAJOR, year, province)` → `major_admission_2025_henan` | 全国数据合并入库后**分省表已全部删除**，只剩 `*_2025_all` 三张总表，原链路直接 500（`数据表不存在或无法反射：score_range_2025_henan`） |
| 科类假设 | 前端 / 服务层默认「物理类」 | 不同省份科类名不同（3+3=综合 / 3+1+2=物理类·历史类 / 老高考=理科·文科），写死会导致查询落空或串省 |
| 参数校验 | 无 | 传 `province=beijing, category=物理类` 这种非法组合不会被拦，一路查到空结果才报错 |
| 内存保护 | 分省表单表几千行，`fetch_all()` 全量拉取 | 总表单表 **43 万行**（enrollment_plan 80 万行），全量拉取会直接把内存和接口打爆 |
| 位次缓冲 | `RANK_BUFFER=5000` 全局写死 | 考生基数大的省份窗口过窄，候选不足 |

### 二、改进技术及对应代码位置

#### 1. 新增 `utils/region_mapper.py`（单一职责：只管「省份 ↔ 科类」）

| 能力 | 说明 |
|---|---|
| `PROVINCE_CATEGORIES` | 31 个省级行政区的科类配置 |
| `get_categories_by_province(code)` | 支持中文名与拼音两种入参 |
| `normalize_province(code)` | 归一成数据库 `province` 列的真实取值（中文名） |
| `is_new_gaokao` / `gaokao_mode` / `has_data` | 新高考判定 / 高考模式 / 该省是否有数据 |

#### 2. `services/rank_service.py` 位次换算重构

| 函数 | 签名 | 说明 |
|---|---|---|
| `score_to_rank` | `(score, province, category, year=2025) -> int` | 全国总表版，查不到返回 **0** + warning，不抛异常 |
| `rank_to_score` | `(rank, province, category, year=2025) -> int` | 同上 |
| `score_to_rank_detail` | `(province, year, category, batch, score) -> Dict` | 原河南富信息版改名保留（返回 control_score / rank_range 等） |

> **三个踩过的坑**：① `province` 列存中文名，入参要归一；② `score` / `cumulative_count`
> 是 TEXT 且值为 `'710.0'`，数值比较必须 `CAST(... AS SIGNED)`——直接
> `score <= '600'` 会因字符串比较漏掉 `'600.0'`；③ 单省数据缺失要返回 0 而不是抛异常。

#### 3. `services/recommend_service.py` 全国推荐引擎

```python
calculate_tiers(student_rank, province, category, year=2025)
    -> {"chong": [...], "wen": [...], "bao": [...]}
```

| 设计点 | 实现 |
|---|---|
| 数据源 | `major_admission_{year}_all`，WHERE 必带 `province` + `category` + `year` |
| 内存保护 | 每档 `LIMIT 50`，绝不 `SELECT *` |
| 位次缓冲 | `_tier_buffer()` 按省份动态取值（河南/山东/广东等大省 ×2） |
| 概率 | `_tier_probability()` 位次差线性映射，冲 10-40% / 稳 55-85% / 保 88-98%，保留 1 位小数 |
| 富化 | `enrich_with_plan()` 用 `enrollment_plan_{year}_all` 补学费 / 计划数 / 学制，每档只补前 20 条、一次 `IN` 批量查 |

#### 4. `services/sql_query_engine.py` 同步迁移（0.9.1 MySQL 通道）

原按 `table_name()` 拼分省表，分省表删除后三路融合的 MySQL 路直接失效。
现改为固定 `{kind}_{year}_all` + `province = :prov AND category = :cat`，
province 入参同样支持拼音 / 中文归一。

#### 5. `routers/recommend.py` 路由层

| 接口 | 行为 |
|---|---|
| `POST /api/recommend` | **全国引擎为主路径**：校验 → 算位次 → 算三档 → 富化。响应保留原 `student/chong/wen/bao/meta` 字段，新增 `rank` 与 `tiers`（向前兼容） |
| `POST /api/recommend/national` | 纯全国引擎版，只返回 `{rank, province, category, year, tiers}` |
| `_validate_province_category()` | 省份不存在 / 科类不支持 / 该省无数据，分别返回明确 400 |

原「河南单省富信息版」`recommend_service.recommend()` 依赖已删除的分省表，
降级为**可选增强**（保留代码，不再作为主路径）。

#### 6. `routers/meta.py` 的 `/api/meta/options`

在原有返回基础上**追加**（不破坏现有消费方）：

```json
{
  "provinces": ["北京", "天津", "...31 个"],
  "categories_map": {"北京": ["综合"], "河南": ["物理类", "历史类"], "...": []},
  "province_modes": {"北京": "3+3", "河南": "3+1+2", "新疆": "老高考"}
}
```

前端一次拉全即可做「选省份 → 联动科类」的下钻。

#### 7. `sql/05_national_tables_perf.sql`（新增）

列类型收紧（TEXT → VARCHAR）+ 复合索引确认 + `ANALYZE TABLE` + EXPLAIN 验证语句。
pandas 全量字符串导入会把文本列建成 TEXT，不收紧的话 43 万行查询会超时。

### 三、验证流程

#### 1. 区域映射与参数校验

```
python test_national_engine.py
```

```
用例 1：region_mapper 区域映射
  省份数 = 31
  拼音/中文归一全部通过；无数据省份 = ['内蒙古', '山西', '青海']
用例 3b：概率线性映射边界
  冲 10-40 / 稳 55-85 / 保 88-98 边界值正确
用例 4：非法传参拦截
  beijing/物理类 → 400「该省份不支持此科类：北京 仅支持 综合」
  火星/综合     → 400「不支持的省份：火星」
  shanxi/理科   → 400「山西 暂无 2025 年录取数据，请切换省份」
```

#### 2. 多省位次换算与三档计算（真实库）

```
python test_national_engine.py --real
```

| 考生 | 分数 | 位次 | 冲 | 稳 | 保 |
|---|---|---|---|---|---|
| 北京 · 3+3 综合 | 600 | 11883 | 50 | 50 | 50 |
| 河南 · 3+1+2 物理类 | 600 | 45887 | 50 | 50 | 50 |
| 河南 · 3+1+2 历史类 | 600 | 6178 | 0 | 50 | 50 |
| 四川 · 物理类 | 600 | 23461 | — | — | — |
| 新疆 · 老高考理科 | 550 | 4021 | — | — | — |

三档结构 / LIMIT 50 / 概率区间 / 档内排序全部通过。

#### 3. 接口层

```
python test_national_engine.py --api
```

```
/api/meta/options        → provinces=31 categories_map=31
beijing/综合/600         → 200  rank=11883 tiers={chong:50, wen:50, bao:50}
henan/物理类/600         → 200  rank=45887 tiers={chong:50, wen:50, bao:50}
beijing/物理类/600       → 400  该省份不支持此科类：北京 仅支持 综合
/api/recommend（河南）    → 200  旧字段齐全；rank=45887 tiers=有
```

`/api/recommend` 返回的条目已带富化字段（`tuition: 5000.0`、`plan_count: 3.0`、`duration: "4"`）。

#### 4. 回归验证

```bash
cd backend
python test_national_engine.py --api   # 0.11.0 新增
python test_hybrid_rag.py              # 0.9.1 三路融合（MySQL 通道已迁到总表）
python test_multimodal_rag.py          # 0.10.0 多模态 + OCR
python smoke_test.py                   # 业务接口冒烟
python smoke_rag.py                    # RAG SMOKE DONE
```

### 四、与任务书的偏差（均已按实测数据校正）

| 项 | 任务书假设 | 实际数据 | 处理 |
|---|---|---|---|
| 科类分组 | 四川/云南/陕西/宁夏归老高考「理科/文科」 | 这四省在 2025 总表里存的是「物理类/历史类」 | 按实际数据配置，否则四省永远 400 |
| 无数据省份 | 未提及 | 山西 / 内蒙古 / 青海在三张总表里**没有任何数据** | 单列 `PROVINCES_NO_DATA`，路由层给出「该省暂无数据」的明确报错 |
| `province` 入参 | `province_code`（拼音，如 `henan`） | 数据库 `province` 列存**中文名** | 两种入参都支持，内部归一成中文名 |
| `probability` 类型 | 1 位小数 | 原 schema 是 `Optional[int]` | schema 改为 `Optional[float]`（int 仍是合法 float，向后兼容） |

### 五、后续演进方向（0.12.0）

| 方向 | 说明 |
|---|---|
| 前端省份联动 | `Volunteer.vue` 接入 `categories_map`，做「选省份 → 联动科类」下拉 |
| 老高考数据补齐 | 山西 / 内蒙古 / 青海导入 2025 数据 |
| Level 3 串行筛选 | 图谱 / MySQL 能完整回答时跳过向量检索 |
| 分省表兼容层 | 若将来又建回分省表，可加一层「总表优先、分省兜底」的路由 |

---

## [0.10.0] - 2026-10-16 · OCR 预处理 + 以文搜图多模态 RAG

### 一、原有技术（0.9.1）及缺陷

| 环节 | 0.9.1 的技术 | 存在的缺陷 |
|---|---|---|
| PDF 文本提取 | pypdf 直接提取文字层 | ① 扫描件 PDF 提不到文字：《高考志愿录取顺序.pdf》19 页只提出 47 字符，`split_text()` 只能切出 **1 片**，知识库等于没收录；② 大量招生简章是扫描件，覆盖严重不全 |
| 检索通道 | 三路融合（图谱 + MySQL + 向量），全部为文本 | 无法检索以图片形式存在的知识：课程体系图、培养方案流程图、校园照片 |
| 图像知识 | 无 | 上传 PDF 时内嵌图片被直接丢弃，从未进入任何索引 |

### 二、改进技术及对应代码位置

#### 1. OCR 预处理（`utils/ocr_utils.py` → `OCRExtractor`）

| 方法 | 职责 |
|---|---|
| `is_scanned_pdf(path)` | 按页平均字符数判定扫描件（阈值 `OCR_SCANNED_THRESHOLD`，默认 50 字/页） |
| `pdf_to_images(path)` | PDF 页 → 图片，用 **pypdfium2**（自带二进制，无需装 poppler 配 PATH） |
| `ocr_images(images)` | 逐页识别 + 线程池并发（单页 20-35 秒，串行会把上传接口拖到超时） |
| `extract_text_with_ocr_fallback(path)` | 对外入口，返回 `(文本, 是否用了 OCR)` |

**降级链**：首选 `qwen-vl-ocr` → 额度/权限不可用时回落 `MULTIMODAL_VLM_MODEL`（同一个 Ali Key 与 base_url）→ 两条都失败返回空串、只记日志不抛异常，上传流程继续。

`utils/file_utils.py` 的 `extract_text()` 返回值由 `str` 改为 `(文本, ocr_used)`，调用方（`routers/knowledge.py`）同步解包并回写 `knowledge_files.ocr_used`。

#### 2. 以文搜图（`services/multimodal/`，5 个类）

| 文件 | 类 | 职责 |
|---|---|---|
| `image_extractor.py` | `ImageExtractor` | 从 PDF 抽嵌图（`pdfplumber` 裁剪法）；扫描件退化为按页渲染 |
| `image_encoder.py` | `BaseImageEncoder` + `ChineseCLIPEncoder` + `CaptionEncoder` | 图文同空间编码；`create_image_encoder()` 按依赖可用性挑选 |
| `image_store.py` | `ImageStore` | Chroma 独立集合 `gaokao_images` 读写删 + 维度校验 + 重建 |
| `vlm_client.py` | `VLMClient` | 视觉语言模型调用（`qwen3.7-flash-2026-07-15`，图文输入） |
| `image_retriever.py` | `ImageRetriever` | 合成复用前四者，对外只暴露 `should_trigger` / `retrieve` / `answer` / `index_pdf` / `remove_file` |

**图像编码器的两条路**（抽象基类 + 工厂，依赖倒置 / 开闭原则 / 里氏替换）：

| 实现 | 依赖 | 状态 |
|---|---|---|
| `ChineseCLIPEncoder` | torch + chinese-clip + 模型权重 | 任务指定方案；本机 chinese-clip 无法通过 pip 安装（GitHub 源 setup.py 构建失败），默认不可用 |
| `CaptionEncoder` | 无本地模型，走阿里云通道 | **当前实际启用**：视觉模型生成图注 → 文本向量编码图注 |

> 图像向量必须与文本向量**分开集合**：编码器不同（CLIP 512 维 / 图注 768 维）、语义空间不同，
> 混在一个集合会维度报错且检索结果互相干扰。

#### 3. 关键词触发（本次唯一多模态方向）

只做**以文搜图**，不做以图搜文、不做图文混合融合。
问题命中 `MULTIMODAL_TRIGGER_KEYWORDS` 才走图像通道，未命中或搜不到图都自动回落 0.9.1 的三路融合。

> 在任务给定词表外补了「课程」——「XX 专业有哪些课程」的答案通常在培养方案 / 课程体系图里，
> 不加这个词以文搜图永远触发不了。触发但搜不到图时会回落，不会误伤纯文本问题。

#### 4. 对接（`rag_service.py` / `routers/ai.py` / `routers/knowledge.py`）

| 位置 | 改动 |
|---|---|
| `rag_service.should_use_multimodal()` | 委托 `ImageRetriever.should_trigger()` |
| `rag_service.answer_with_multimodal()` | 检索 + VLM 解读；未命中返回 `None`，由 ai.py 回落三路融合 |
| `routers/ai.py:_chat_sync()` | 在图谱分支**之前**插入多模态分支；响应新增 `image_hit` / `images` |
| `routers/knowledge.py` 上传 | 文本向量化成功后提取 PDF 图片 → 编码 → 入库，回写 `image_count` |
| `routers/knowledge.py` 删除 | 同步清理 `gaokao_images` 中该文件的图片 |
| `app/database.py` | 新增 `ensure_columns()` 幂等补列（项目无 `create_all`，新列靠启动时 ALTER） |
| `app/models/knowledge.py` | 补 `from app.models.user import User`，消除懒加载时 `relationship("User")` 解析失败 |

#### 5. 配置项（`config.py` 新增）

| 配置 | 默认 | 说明 |
|---|---|---|
| `OCR_ENABLED` | `1` | OCR 总开关 |
| `OCR_MODEL` | `qwen-vl-ocr` | 首选 OCR 模型，不可用自动回落 VLM |
| `OCR_SCANNED_THRESHOLD` | `50` | 每页平均字符数低于该值判定为扫描件 |
| `OCR_MAX_PAGES` / `OCR_CONCURRENCY` | `50` / `4` | 单次最多处理页数 / 并发页数 |
| `MULTIMODAL_ENABLED` | `1` | 多模态总开关 |
| `MULTIMODAL_TRIGGER_KEYWORDS` | 见上 | 逗号分隔的触发词 |
| `IMAGE_COLLECTION` | `gaokao_images` | 图像独立向量空间 |
| `IMAGE_ENCODER` | `auto` | `auto` / `clip` / `caption` |
| `MULTIMODAL_VLM_MODEL` | `qwen3.7-flash-2026-07-15` | 视觉语言模型 |
| `IMAGE_MAX_SIDE` / `MULTIMODAL_MAX_IMAGES` / `MULTIMODAL_TOP_K` | `1024` / `30` / `3` | 缩放上限 / 单文件最多提图数 / 检索返回数 |

> **★ OCR 通道 base_url 修正（0.10.0 内追加，版本号不变）**
> `qwen-vl-ocr` 的 OpenAI 兼容接口 base_url 与文本 LLM **不是同一个域名**，
> 最初实现误用了 `ALI_BASE_URL`，导致 OCR 一直 404 / 401。
> 现新增独立配置 `OCR_BASE_URL`（默认 `https://maas.qianwenaiapi.com/compatible-mode/v1`），
> 与文本 / Embedding / VLM 通道共用同一个 `Ali_API_KEY`，区别只在 base_url 与 model。
> 同时补充：单页失败重试 `OCR_PAGE_RETRY` 次（默认 1）后跳过该页，禁止无限重试；
> OCR 关键日志改用 warning 级别（uvicorn 默认只输出 WARNING 及以上，info 会被过滤）；
> 启动时 `main.py` 显式打印 OCR 通道 base_url 与模型名，便于排查配错。

> **★ LLM 模型切换（0.10.0 内追加，版本号不变）**
> 限时版 `qwen3.7-flash-2026-07-15` 免费额度已耗尽，全项目切换到 `qwen3.7-flash`：
> `ALI_LLM_MODEL`、`MULTIMODAL_VLM_MODEL`、`query_rewrite.DEFAULT_CHAT_MODEL`
> 及 `.env` / `.env.example` 同步更新。新模型同样支持图文输入，多模态问答不受影响。

**OCR 端到端实测**（《高考志愿录取顺序.pdf》，19 页扫描件，13.9 MB）：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 提取字符数 | 47 | **14312** |
| 切片数 | **1** | **41**（提升 41 倍） |
| OCR 耗时 | — | 46 秒（4 路并发，19 页全部 200 OK） |

### 三、验证流程

#### 1. OCR 对比（修复前 vs 修复后）

测试文件：`knowledge_files/*高考志愿录取顺序.pdf`（13.9 MB，19 页，扫描件）

| 指标 | 修复前（pypdf 直接提取） | 修复后（OCR 前 3 页） |
|---|---|---|
| 字符数 | 47 | 3363 |
| 切片段数 | **1** | **16** |

> 全量 19 页按此比例约 95+ 片，达到任务预期的「30+ 片」。

#### 2. 桩版单测（不调模型、不依赖额度）

```bash
cd backend
python test_multimodal_rag.py
```

```
用例 1：扫描件判定          is_scanned_pdf = True
用例 2：PDF 页 → 图片       渲染出 2 张，首张尺寸 (918, 1188)
用例 3：PDF 图片提取        提取 3 张，页号 [1, 2, 3]
用例 5：触发关键词          「…有哪些课程」→ True；「…学费多少」→ False
用例 6：编码器选择          caption，available = True
用例 7：图像集合读写        写入 2 张 / 检索命中 2 张 / 删除 2 张
                           维度不符写入被拒绝：返回 0
0.10.0 多模态 + OCR 用例全部通过
```

#### 3. 接口级验证

| 场景 | 结果 |
|---|---|
| 上传扫描件 PDF（视觉模型额度耗尽时） | `200`，`ocr_used=0`、`image_count=0`，正确降级为「按 pypdf 原文处理」，**不 500** |
| 上传响应字段 | `ocr_used` / `image_count` 正确回显（修掉 `_to_out` 漏字段的问题） |
| 问答（额度耗尽时） | 多模态尝试失败 → 回落三路融合 → 再降级到预设话术，链路不中断 |

#### 4. 回归验证

```bash
cd backend
python smoke_test.py        # 通过
python smoke_rag.py         # RAG SMOKE DONE
python test_multimodal_rag.py  # 桩版 8 个用例全部通过
```

> **已知限制**：验证期间阿里云免费额度被 OCR 测试耗尽（`Free quota exhausted`），
> 视觉模型（`qwen-vl-ocr` 与 `qwen3.7-flash` 的图文调用）均返回 403，
> 仅文本 embedding 可用。因此「OCR 全量识别 → 图注生成 → VLM 解读」的**端到端闭环**
> 未能在额度耗尽后复跑；但每一段都在耗尽前单独验证通过（见上表）。
> 额度恢复后重跑 `python test_multimodal_rag.py --real` 即可完成闭环验证。

### 四、踩坑记录（同类问题第二次出现）

| 问题 | 根因 | 修复 |
|---|---|---|
| `Collection expecting embedding with dimension of 768, got 128`（0.9.1 文本集合） | 集合删空后 `_collection_dimension()` 读不到向量长度，回落配置值 128，而 Chroma 仍 pin 着 768 | 改读 `col._model.dimension` |
| `Collection expecting embedding with dimension of 8, got 768`（0.10.0 图像集合） | 桩测试用 8 维向量写进 `gaokao_images`，把集合 pin 成 8 维；真实编码器产出 768 维被拒 | `ImageStore` 加 `collection_dimension()` 写入前校验 + `reset()` 重建；桩测试改用独立集合名 |
| `expression 'User' failed to locate a name` | `services/multimodal` 懒加载 `KnowledgeFile` 时 `User` 模型尚未注册，`relationship("User")` 解析失败 | `models/knowledge.py` 顶部显式 `import User` |
| 接口返回 `ocr_used: null` 而 DB 已是 0 | `_to_out()` 用显式字段构造 `KnowledgeFileOut`，漏了新字段 | 补 `ocr_used` / `image_count` 并做 `or 0` 归一 |

### 五、后续演进方向（0.11.0）

| 方向 | 说明 |
|---|---|
| 以图搜文 | 用户上传图片 → 检索相关知识片段（本次刻意不做） |
| 图文混合融合 | 图像检索结果与文本三路融合一起进 Prompt（本次刻意不做） |
| Chinese-CLIP 落地 | 解决 chinese-clip 安装问题后切换编码器，去掉图注方案的视觉细节损失 |
| 表格结构化处理 | 分数线表 → 自然语言三元组，供图谱与评估共用 |
| 上传异步化 | OCR 单文件 2-3 分钟，改为任务队列 + 轮询，避免占用请求线程 |

---

## [0.9.1] - 2026-10-14 · 热修复：三路融合检索（图谱 + MySQL + 向量）按优先级分发

### 一、原有技术（0.9.0）及缺陷

| 环节 | 0.9.0 的技术 | 存在的缺陷 |
|---|---|---|
| 检索分发 | `answer_with_graph()` 只做「图谱 + 向量」两路 | ① 缺 MySQL 这一路：学费 / 分数线 / 位次 / 选科 / 招生人数的精确值明明在 MySQL 里，却绕道去 Chroma 翻 PDF，翻不到就拒答；② 用户体验差 |
| 结构化意图 | 无 | 无论问什么都只走 Chroma，没有「先判断是不是结构化查询」这一层 |
| 图谱异常降级 | `except → pass` 直接落到纯向量 | 中间没有 MySQL 兜底 |
| 防幻觉 Prompt | `GRAPH_FUSION_PROMPT` 只声明「图谱为准」 | 没有针对 MySQL 精确值的优先级声明，也没有对「三路都空必须拒答」的强约束 |

**实测对照**（同一问题「福州大学至诚学院计算机专业学费是多少？选科要求是什么？」）：

| 链路 | 回答 |
|---|---|
| 0.9.0 图谱 + 向量 | 拒答（Chroma 里只有 PDF 文本，没有精确学费） |
| 0.9.1 图谱 + MySQL + 向量 | 学费 **23000 元/年**；选科要求：首选物理，再选化学 |

### 二、改进技术及对应代码位置

#### 1. 新增结构化意图识别（`rag_service.py`）

```python
STRUCTURED_INTENT_KEYWORDS = {
    "tuition":     ["学费", "费用", "多少钱", "收费"],
    "min_score":   ["分数线", "最低分", "录取分", "投档线", "多少分"],
    "min_rank":    ["位次", "排名", "最低位次"],
    "subject_req": ["选科", "选考", "科目要求", "首选", "再选"],
    "plan_count":  ["招生计划", "招多少人", "招生人数", "计划数"],
}

def detect_structured_intent(query: str) -> list[str]: ...
```

单一职责：只做「是不是字段型问题」的判断，不查库、不检索。返回空列表表示走向量通道。

#### 2. 新增 MySQL 结构化查询引擎（`services/sql_query_engine.py`）

`MySQLQueryEngine.query_structured(filters)` 按 intents 分组查询后合并成自然语言：

| 意图 | 数据表 | 输出示例 |
|---|---|---|
| `tuition` / `plan_count` | `enrollment_plan_{year}_henan` | `{学校}{专业}专业2025年学费为23000元/年。` |
| `subject_req` / `min_score` / `min_rank` | `major_admission_{year}_henan` | `{学校}{专业}专业2025年最低录取分460分。` |

> **表结构说明**：本项目字段拆在两张表里（投档事实在 `major_admission`，招生计划在 `enrollment_plan`），
> 与任务书假设的单表不同，故按真实 schema 拆成两组查询后合并，而不是做一张大 JOIN
> （录取行与计划行数量级不同，JOIN 会产生笛卡尔积噪声）。

安全设计：表名来自 `app.models.dataset.table_name()` 固定模板且年份只接受 4 位数字；
查询条件一律参数化绑定（`:school` / `:major`），不字符串拼接；DB 异常一律返回 `hit=False` 不向上抛。

#### 3. 新增三路融合主函数（`rag_service.answer_with_hybrid()`）

```
Step 1  detect_structured_intent()          判断是不是字段型问题
Step 2  ThreadPoolExecutor(max_workers=3)   三路并行
          · GraphQueryEngine.query()        → Neo4j
          · MySQLQueryEngine.query_structured() → MySQL（仅 intents 非空时）
          · rag_service.search()            → Chroma
Step 3  按 图谱 > MySQL > 向量 拼接上下文，向量按 VECTOR_MAX_TOKENS 裁剪
Step 4  三路都空 → 直接返回拒答，不调大模型
Step 5  build_hybrid_prompt() → ask() 生成
```

任一路异常只跳过该路，其余两路继续；三路都异常才返回 `hybrid_empty`。

#### 4. Prompt 强化防幻觉（`HYBRID_FUSION_PROMPT` / `build_hybrid_prompt()`）

新增 6 条硬约束：优先用结构化数据、政策文本不作数字依据、冲突以图谱为准、
三路都空必须拒答、**禁止用预训练知识补数字**、**禁止用「通常/大概」推测数字**。
`priority_hint` 按命中组合动态生成（图谱+MySQL / 仅图谱 / 仅 MySQL / 图谱+向量 / MySQL+向量 / 仅向量）。

#### 5. 接口分发修正（`routers/ai.py`）

`_chat_sync()` 的图谱分支由 `answer_with_graph()` 改为 `answer_with_hybrid()`，
响应新增 `mysql_hit` 与 `mysql_error` 字段；`use_graph=false` 路径保持 0.8.0 行为不变（向后兼容）。

#### 6. 配置项（`config.py` 新增）

| 配置 | 默认 | 说明 |
|---|---|---|
| `MYSQL_QUERY_ENABLED` | `1` | MySQL 路总开关，关闭后只走图谱 + 向量 |
| `MYSQL_MAX_ROWS` | `5` | MySQL 单次查询最大返回行数 |

### 三、验证流程

#### 0. 热修复：上传向量化维度不匹配（0.9.1 内追加）

**现象**：后台上传知识库文件时报
`解析或向量化失败：Collection expecting embedding with dimension of 768, got 128`。

**根因**：Chroma 1.x 会把集合维度 pin 在集合元数据 `col._model.dimension` 里，
**即使集合被删空也依然保留 768**；而 `rag_service._collection_dimension()`
旧实现只读「第一条向量的长度」，文件全部删除后读不到 → 回落到
`ALI_EMBED_DIMENSION`(128) → Chroma 按 768 校验、我们产出 128，写入被拒。

**修复**（`rag_service.py`，两处）：

| 位置 | 改动 |
|---|---|
| `_collection_dimension()` | 取值顺序改为 ① `col._model.dimension`（删空后仍有效）→ ② 第一条向量长度（兼容旧版 chromadb）→ ③ `None`（回落到配置） |
| `add_document()` | 捕获 Chroma 写入异常，若为维度不符则抛出带处理建议的中文错误，而不是把 Chroma 原文直接抛给前端 |

**验证**：

```
collection dim = 768（修复前为 None）
requesting dimensions = 768
embedding len = 768
POST /api/knowledge/upload → {"code":200,"msg":"上传并向量化成功","status":"已向量化","chunk_count":2}
```

#### 1. 最小用例

```bash
cd backend
python test_hybrid_rag.py           # 桩版 6 个用例，不连库不调 LLM
python test_hybrid_rag.py --real    # 真实链路：连 MySQL
```

桩版输出（节选）：

```
用例 1：结构化意图识别
  福州大学至诚学院计算机专业学费是多少？选科要求是什么？ → ['tuition', 'subject_req']
  非结构化问题 → []
用例 2：MySQLQueryEngine.query_structured
  hit=True
    福州大学至诚学院计算机科学与技术专业2025年学费为23000元/年。
    福州大学至诚学院计算机科学与技术专业选科要求：首选物理再选化学。
  参数化校验通过：school=%福州大学至诚学院% major=%计算机% limit=5
  两表拆分：enrollment_plan(学费/计划) + major_admission(分数线/位次/选科)
用例 3：仅 MySQL 命中（三路融合）
  source=hybrid:priority_quota graph_hit=False mysql_hit=True vector_hit=False
用例 4：三路全空（hybrid_empty）
  source=hybrid_empty
  answer=根据现有资料未查询到具体信息，建议查阅学校官方招生简章。
```

#### 2. 接口级验证（`POST /api/ai/chat`，`use_rag=true, use_graph=true`）

| 问题 | `source` | `mysql_hit` | `vector_hit` | 回答 |
|---|---|---|---|---|
| 福州大学至诚学院计算机专业学费是多少？选科要求是什么？ | `hybrid:priority_quota` | **true** | true | 学费 **23000 元/年**；选科要求：首选物理，再选化学 |
| 福州大学至诚学院计算机专业2025年在河南的录取最低分和位次是多少？ | `hybrid:priority_quota` | **true** | true | 最低录取分 **460 分**，最低位次 **287531** |
| 河南本科批志愿怎么填报？ | `hybrid:priority_quota` | false | true | 基于政策文本回答平行志愿填报规则 |
| 纯向量兼容（`use_graph=false`） | `advanced:corrective` | — | — | 与 0.8.0 行为一致 |

#### 3. 回归验证

```bash
cd backend
python smoke_test.py        # 业务接口全部 200
python smoke_rag.py         # chat: source=hybrid:priority_quota，RAG SMOKE DONE
```

### 四、后续演进方向（0.10.0）

| 方向 | 说明 |
|---|---|
| Level 3 串行筛选 | 图谱 / MySQL 能完整回答时跳过向量检索，进一步降噪降延迟 |
| 图谱 Schema 自动扩展 | 从 MySQL 元数据自动推断新节点 / 关系 |
| MySQL 查询结果纳入评估 | 在 0.8.0 的评估体系里增加 `mysql_hit_rate` 指标 |
| 表格结构化处理 | 分数线表 → 自然语言三元组，供图谱与评估共用 |

---

## [0.9.0] - 2026-10-12 · 知识图谱双通道：GraphQueryEngine + 向量检索按优先级 + Token 配额融合

### 一、原有技术（0.8.0）及缺陷

| 缺陷 | 具体表现 |
|---|---|
| 只有向量通道 | 「XX 学校 XX 专业学费多少」这类结构化事实查询，向量库召回不到就答"未查询到" |
| 相似度 ≠ 正确性 | 向量检索返回的是**语义相似**的文本片段，对数字、关系（院校-专业-省份）的精确性没有任何保证 |
| 缺结构化事实来源 | 院校 / 专业 / 专业组 / 选科要求 / 投档线这些关系型数据全在 MySQL 里，向量库只存了切片文本 |
| 无融合机制 | 即便接了图谱，也没有"结构化事实 vs 语义文本"该怎么一起喂给 LLM 的明确策略 |

**实测对照**（同一问题「福州大学至诚学院计算机专业学费多少」）：

| 链路 | 回答 |
|---|---|
| 0.8.0 纯向量 RAG | "根据现有资料，未查询到具体信息，建议查阅学校官方招生简章。" |
| 0.9.0 图谱 + 向量融合 | "根据【图谱事实】中的权威精确数据，福州大学至诚学院计算机科学与技术专业的学费为 **23000 元**。" |

### 二、改进技术及对应代码位置

#### 1. 新增 `services/graph/` 模块（7 个文件，单一职责）

| 文件 | 类 | 职责 |
|---|---|---|
| `ontology.py` | — | 本体常量：8 类节点标签 / 8 类关系 / 属性键，中文标签的 Cypher 转义只此一处处理 |
| `graph_store.py` | `GraphStore` | **只**负责 Neo4j 连接 + 执行 Cypher + 读 Schema；连接失败抛 `GraphConnectionError` |
| `entity_extractor.py` | `EntityExtractor` | **只**负责实体识别：LLM 抽取 + 词典匹配双路混合，词典路优先；含简称→全称消歧 |
| `cypher_generator.py` | `CypherGenerator` | **只**负责把「实体 + 问题」编译成 Cypher；Schema 动态注入 + 4 条高考 Few-shot + 只读保护 |
| `graph_query_engine.py` | `GraphQueryEngine` | 图谱通道唯一入口，**合成复用**上面三个类；任一步失败返回 `GraphResult(hit=False)` 不抛异常 |
| `graph_builder.py` | `GraphBuilder` | 离线构建：MySQL → Neo4j，全部 `MERGE` 保证幂等 |
| `__init__.py` | — | 统一导出；`GraphBuilder` 用 `__getattr__` 懒加载（在线链路用不到） |

图谱本体：

```
节点：院校 / 专业 / 专业组 / 省份 / 批次 / 选科要求 / 分数段 / 年份
关系：
  (院校)-[:OPENS]->(专业)        院校开设专业（携带 year/province/batch/category/min_score/min_rank）
  (院校)-[:TUITION]->(专业)      学费（携带 tuition/duration）
  (院校)-[:ENROLLS]->(专业)      招生计划（携带 plan_count/subject_req）
  (院校)-[:RANKS]->(分数段)      院校投档线
  (专业)-[:ADMITS]->(分数段)     专业投档线
  (院校)-[:LOCATED_IN]->(省份)
  (专业)-[:BELONGS_TO]->(专业组)
  (专业组)-[:REQUIRES]->(选科要求)
```

#### 2. 实体识别双路混合（Hybrid）

```
LLM 路   ：qwen3.7-flash，temperature=0，严格 JSON 输出 (实体类型, 实体名)
词典路   ：MySQL 的 university_name / major_name / school_province 列生成词典，字符串匹配
合并去重 ：词典路结果优先（来自权威数据源）
消歧     ：简称 → 词典全称（"计算机" → "计算机科学与技术"），否则 Cypher 查不到节点
降级     ：LLM 路失败 → 只用词典路；词典路为空 → 只用 LLM 路；两路都空 → 返回 []
```

#### 3. `rag_service.search_with_graph()`：融合层（中枢神经）

**为什么不做分数融合（RRF 不适用）**：图谱结果是**对/错的精确事实**（学费 23000、最低分 512），
向量结果是**相似度文本**（"该校学费适中，性价比高"），二者量纲不可比，
把 0.91 的向量相似度和一条 100% 正确的图谱事实一起排序没有意义。因此用两级策略：

```
Level 1 优先级：图谱上下文排在前面，Prompt 明确「图谱为权威事实，冲突时以图谱为准」
Level 2 配额  ：总预算 4000 token，图谱最多 60%（2400 token ≈ 3600 字符），
               向量最多 40%（1600 token ≈ 2400 字符）；
               某一路没用满时，剩余额度让给另一路
第一版刻意不做 Level 3 串行筛选（会把两路从并行变串行，延迟翻倍）→ 留到 1.0.0
```

并行调度用 `ThreadPoolExecutor` 而非 `asyncio.gather`：两条链路内部都是同步阻塞调用
（Neo4j bolt / Chroma / HTTP），无 GPU 的 i5 机器上线程池更稳。

#### 4. 配置项（`config.py` 新增）

| 配置 | 默认 | 说明 |
|---|---|---|
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | `bolt://localhost:7687` / `neo4j` / `12345678` | Neo4j 连接 |
| `GRAPH_ENABLED` | `1` | 图谱通道总开关，关闭后走纯向量链路 |
| `GRAPH_MAX_TOKENS` | `2400` | 图谱配额（总预算的 60%） |
| `VECTOR_MAX_TOKENS` | `1600` | 向量配额（总预算的 40%） |
| `GRAPH_LLM_EXTRACT_ENABLED` | `1` | LLM 抽取路开关 |
| `GRAPH_DICT_EXTRACT_ENABLED` | `1` | 词典匹配路开关 |

#### 5. `routers/ai.py` 的 `/api/ai/chat` 新增 `use_graph`

- `use_graph=true`（默认）且 `GRAPH_ENABLED=1` → 走 `answer_with_graph()`，
  响应新增 `graph_hit` / `vector_hit` / `fusion_strategy` / `graph_cypher` / `graph_error`
- `use_graph=false` → **保持 0.8.0 行为完全不变**（向后兼容）
- 图谱链路异常 → 自动回落到下面的纯向量流程

### 三、验证流程

#### 1. 离线构建（year=2025）

```bash
cd backend
# 注意：图谱通道需要 py2neo，本地跑在 conda py312_env（已装 py2neo 2021.2.4）
python -m app.services.graph.graph_builder --year 2025 --batch 本科批
```

实测输出：

```
[GRAPH] 构建完成：{'school': 624, 'major': 8204, 'major_group': 15212, 'province': 31,
'batch': 6, 'subject_req': 10, 'score_segment': 11, 'opens': 13885, 'tuition': 33247,
'enrolls': 33247, 'ranks': 1562, 'admits': 13885, 'located_in': 624,
'belongs_to': 15426, 'requires': 8719}
```

所有写入用 `MERGE`，重复运行不会产生重复节点 / 关系。

#### 2. `GraphQueryEngine` 单测：查询「福州大学至诚学院计算机专业学费多少」

```bash
python test_graph_rag.py --real
```

实测输出：

```
词典规模：院校 624 / 专业 1020
耗时 7.90s hit=True
实体：[{'type': '院校', 'name': '福州大学至诚学院'}, {'type': '专业', 'name': '计算机科学与技术'}]
Cypher：
MATCH (s:`院校` {name: $院校_0})-[r:TUITION]->(m:`专业` {name: $专业_0})
RETURN s.name AS 院校, m.name AS 专业, r.tuition AS 学费, r.duration AS 学制
LIMIT 20
上下文：
院校: 福州大学至诚学院；专业: 计算机科学与技术；学费: 23000；学制: 4年
```

> LLM 抽出的是简称「计算机」，经词典消歧归一到「计算机科学与技术」后才匹配上节点。

#### 3. 双通道融合对比：`use_graph=false` vs `use_graph=true`

```bash
python test_graph_rag.py --compare
```

实测输出：

```
--- use_graph=false（纯向量 RAG）---
耗时 4.60s
回答：根据现有资料，未查询到具体信息，建议查阅学校官方招生简章。
--- use_graph=true（图谱 + 向量融合）---
耗时 5.14s
graph_hit=True vector_hit=True strategy=priority_quota
回答：根据现有资料，福州大学至诚学院计算机科学与技术专业的学费为 **23000元/年**。
```

接口层验证（`POST /api/ai/chat`）：

```json
// {"question": "...", "use_rag": true, "use_graph": true}
{
  "answer": "根据【图谱事实】中的权威精确数据，福州大学至诚学院计算机科学与技术专业的学费为 **23000元**。",
  "source": "graph+vector",
  "graph_hit": true,
  "vector_hit": true,
  "fusion_strategy": "priority_quota",
  "graph_cypher": "MATCH (s:`院校` {name: $院校_0})-[r:TUITION]->(m:`专业` {name: $专业_0}) ..."
}
```

降级验证（py2neo 未安装的服务进程）：`graph_error` 返回
`"py2neo 未安装（ModuleNotFoundError）：请执行 pip install py2neo"`，
`graph_hit=false`、`vector_hit=true`，问答自动退化为纯向量 RAG，**不报错、不中断**。

#### 4. 回归验证

```bash
cd backend
python test_graph_rag.py        # 桩版 6 个用例全部通过（不连 Neo4j / 不调 LLM）
python smoke_test.py            # 业务接口全部 200
python smoke_rag.py             # chat: source=graph+vector，RAG SMOKE DONE
cd ../frontend && npx tsc --noEmit
```

> 桩版之所以能不连 Neo4j 跑通，是因为 `GraphStore` / `EntityExtractor` / `CypherGenerator`
> 全部是构造注入（依赖倒置），测试时换成桩对象即可。

### 四、后续演进方向（1.0.0）

| 方向 | 说明 |
|---|---|
| Level 3 串行筛选 | 图谱不完整时才查向量，把两路从并行变串行以进一步降噪（需权衡延迟） |
| 图谱 Schema 自动扩展 | 从 MySQL 元数据自动推断新节点 / 关系，不必手写 `GraphBuilder` |
| 图谱命中率纳入评估 | 在 0.8.0 的评估体系里增加 `graph_hit_rate` 指标，量化图谱通道贡献 |
| 图谱结果重排序 | 对图谱返回的多条记录做二次排序（如按年份就近） |
| 实体链接增强 | 引入别名表 / 拼音匹配，处理「郑大」「华科」这类简称 |

---

## [0.8.0] - 2026-10-12 · RAG 量化评估：一键评估 + 可视化 + 自动诊断 + 参数自调优

> 主题：按《企业级 RAG 落地优化与量化评估实战》第二至八章的方法论，
> 把之前"靠手感调 RAG"的方式升级为 **评估先行 → 诊断驱动 → 数据闭环**：
> 一键跑出三维九项本地指标，自动给出诊断与优化建议，并支持把建议**一键写回白名单参数**。

---

### 一、原有技术（0.7.2）及缺陷

| 环节 | 0.7.2 的技术 | 存在的缺陷 |
|---|---|---|
| 效果判断 | 人工问几个问题，凭感觉判断"还行不行" | ① 缺少量化标准，**改 A 坏 B 无法察觉**；② 无法定位瓶颈在切片、召回还是生成 |
| 优化方式 | 改完参数再手动重问 | ① 每次优化无法量化收益；② 没有基准线，不知道"变好了还是变差了" |
| 历史记录 | 无 | ① 没有趋势数据，无法判断长期优化是否生效；② 演示 / 答辩拿不出数据佐证 |
| 参数调整 | 人工改 `.env` | ① 容易误改非相关配置；② 改完想回退只能靠记忆 |
| LLM 打分指标 | 直接调 LLM 打分 | ① 额度耗尽 / API 报错会直接把评估链路打断；② 思考版模型会成倍放大时延 |

---

### 二、改进技术及对应代码位置

#### 1. `backend/app/services/eval/` 评估模块（8 个文件，单一职责）

| 文件 | 类 | 职责 |
|---|---|---|
| `eval_config.py` | `RAGEvalConfig` | 评估配置：默认值来自 `settings`，支持前端传参覆盖（`SIM_THRESHOLD=0.65` / `TOP_K_FOR_EVAL` / `EVAL_DATA_DIR` …） |
| `data_builder.py` | `BaseRAGRunner`（抽象）/ `ProjectRAGRunner`（适配）/ `EvalDataBuilder` | 加载 QA 语料 → 调 RAG 生成 answer + contexts → 补齐 **question / answer / contexts / ground_truth** 四字段 |
| `metrics_local.py` | `LocalMetrics` | 纯本地指标：语义相似度、`context_precision`、`context_recall`、MRR、NDCG、HitRate |
| `metrics_llm.py` | `LLMMetrics` | 可选 LLM 打分：Faithfulness / Answer Relevance / Answer Correctness，**默认关闭** |
| `evaluator.py` | `EvalReport` / `RAGEvaluator` | 编排评估、按指标聚合（`skipna`）、综合评级（优秀/良好/合格/需优化） |
| `diagnoser.py` | `DiagnosisItem` / `RAGDiagnoser` | 决策树规则：指标 → 问题 → 建议 → **可自动应用的参数变更** |
| `report_generator.py` | `ReportGenerator` | Markdown 报告 + ECharts 数据（柱状/雷达/趋势）+ 落盘 JSON/MD |
| `report_store.py` | `EvalReportStore` | 报告读写与按时间倒序列举（趋势图数据源） |

关键实现（本地指标，**不调用 LLM 打分**，规避 API 报错）：

```python
def calc_context_precision(self, retrieved_contexts, ground_truth, threshold=None):
    """召回片段中「与标准答案相关」的比例 → 越高说明噪声越少"""
    # 每个召回片段与任一标准答案句做余弦相似度，>= 阈值即视为相关

def calc_context_recall(self, retrieved_contexts, ground_truth, threshold=None):
    """标准答案中被召回片段覆盖的比例 → 越高说明漏召回越少"""
```

诊断决策树（`diagnoser.py` 内置规则表严格对应《实战》第四章 3.2）：

| 指标 | 阈值 | 自动给出的参数变更（白名单内） |
|---|---|---|
| `context_precision` < 0.6 | 0.6 | `CHUNK_SIZE` ↓、`RERANK_ENABLED=1`、`MULTI_RECALL_TOPK_PER_CHANNEL` ↓ |
| `context_recall` < 0.7 | 0.7 | `MULTI_QUERY_ENABLED=1`、`QUERY_EXPANSION_ENABLED=1`、`MULTI_RECALL_TOPK_PER_CHANNEL` ↑ |
| `mrr` < 0.5 | 0.5 | `RERANK_ENABLED=1`、`RERANK_MODEL=BAAI/bge-reranker-base` |
| `faithfulness` < 0.7 | 0.7 | `ADVANCED_RAG_ENABLED=1`、`PROMPT_VERSION=strict` |
| `answer_relevance` < 0.7 | 0.7 | `QUERY_REWRITE_ENABLED=1`、`QUERY_DECOMPOSE_ENABLED=1` |
| `answer_correctness` < 0.6 | 0.6 | `ADVANCED_RAG_ENABLED=1`、`QUERY_REWRITE_ENABLED=1` |
| `semantic_similarity` < 0.7 | 0.7 | `MULTI_QUERY_ENABLED=1`、`QUERY_REWRITE_ENABLED=1`、`CHUNK_OVERLAP` ↑ |

#### 2. `backend/app/routers/eval.py`（6 + 2 个接口，全部仅 admin）

| 接口 | 作用 |
|---|---|
| `POST /api/eval/run` | 一键运行评估 → 返回 aggregate / grade / details / chart_data / diagnoses |
| `GET /api/eval/report/{report_id}` | 读取完整报告（含明细与诊断） |
| `GET /api/eval/reports` | 历史报告列表（倒序，趋势图用） |
| `POST /api/eval/apply-suggestion` | **一键应用建议**：白名单参数写回 `.env` |
| `GET /api/eval/changes` | 最近 10 条参数变更日志 |
| `POST /api/eval/rollback` | 回滚到最近一次备份 |
| `GET /api/eval/datasets` | 列出 `data/eval/` 下可用数据集 |
| `POST /api/eval/datasets` | 上传 JSON/CSV 评估集（校验 question + ground_truth） |

#### 3. `backend/app/services/eval/auto_tuner.py`（自动调优）

- **白名单机制**：只有 `PARAM_SPECS` 登记的参数允许被自动修改（`CHUNK_SIZE` / `CHUNK_OVERLAP` / `MULTI_RECALL_TOPK_PER_CHANNEL` / `RERANK_ENABLED` / `RERANK_MODEL` / `MULTI_QUERY_ENABLED` / `QUERY_REWRITE_ENABLED` / `QUERY_EXPANSION_ENABLED` / `QUERY_DECOMPOSE_ENABLED` / `ADVANCED_RAG_ENABLED` / `PROMPT_VERSION`）；
- **取值收敛**：数值类参数按 `min/max/step` 收敛（`decrease` → `-step`，`increase` → `+step`）；
- **安全网**：修改前备份 `backend/.env → backend/.env.bak.{timestamp}`，每次 apply 追加一条 `changes.log` 流水；
- **可回滚**：`POST /api/eval/rollback` 优先回滚备份文件，无备份时按 `changes.log` 反向写回。

#### 4. 前端 `frontend/src/views/admin/RAGEval.vue`

- 顶部：数据集选择 + `top_k` / 相似度阈值 / LLM 指标开关 + 「一键运行评估」+ 数据集上传；
- 中部：**九宫格指标卡片** + 柱状图（当前 vs 上一次）+ 雷达图（三维指标全景）+ 趋势图（历史综合得分）；
- 底部：**诊断报告**（按风险等级排序，每条建议带「一键应用」按钮）+ 逐题明细表 + **变更日志时间线** + 一键回滚。

#### 5. 配置与数据集

| 文件 | 改动 |
|---|---|
| `backend/app/config.py` | 新增 `EVAL_ENABLED` / `EVAL_DATA_DIR` / `EVAL_REPORT_DIR` / `EVAL_LLM_METRICS_ENABLED` / `EVAL_SIM_THRESHOLD` / `EVAL_TOP_K` / `EVAL_MAX_SAMPLES` / `PROMPT_VERSION` / `AUTO_TUNE_ENABLED` / `AUTO_TUNE_WHITELIST` |
| `data/eval/rag_demo_qa.json` | 6 条课堂案例语料（事实型 / 对比型） |
| `data/eval/gaokao_qa.json` | 12 条高考场景语料（学费 / 分数线 / 位次 / 选科 / 批次 / 调剂） |

---

### 三、验证流程

#### 1. 最小用例（一键评估）

```bash
# 登录拿 admin token，然后：
POST /api/eval/run  { "dataset_id": "gaokao_qa.json" }
```

预期返回：

```json
{
  "report_id": "20261012_153000",
  "dataset_size": 12,
  "grade": "需优化",
  "aggregate": {
    "context_precision": 0.41, "context_recall": 0.58, "mrr": 0.72,
    "ndcg": 0.68, "hit_rate": 0.92, "semantic_similarity": 0.63, "overall": 0.657
  },
  "diagnoses": [
    {
      "suggestion_id": "context_precision",
      "metric": "context_precision",
      "score": 0.41, "threshold": 0.6, "level": "high",
      "problem": "召回噪声过多：检索结果里大量片段与标准答案无关",
      "suggestions": ["优化切片策略（减小 CHUNK_SIZE）", "调高重排序权重（开启 RERANK）", "精简 top_k 减少噪声"],
      "param_changes": {"CHUNK_SIZE": "decrease", "RERANK_ENABLED": 1, "MULTI_RECALL_TOPK_PER_CHANNEL": "decrease"}
    }
  ]
}
```

#### 2. 一键应用建议（参数变更写回验证）

```bash
POST /api/eval/apply-suggestion  { "report_id": "20261012_153000", "suggestion_id": "context_precision" }
```

返回与预期：

```json
{
  "applied": true,
  "need_restart": true,
  "backup": "backend/.env.bak.20261012_153500",
  "changes": [
    { "name": "CHUNK_SIZE", "old_value": 500, "new_value": 400, "applied": true },
    { "name": "RERANK_ENABLED", "old_value": true, "new_value": 1, "applied": true }
  ],
  "message": "已应用 2 项参数变更，重启服务后生效"
}
```

> 注：`need_restart=true` —— 因为 `settings` 在进程启动时读取 `.env`，
> 内存里的 `settings` 已同步更新（当前进程部分生效），**完整生效需重启服务**。

#### 3. 回滚验证

```bash
POST /api/eval/rollback
# → {"applied": true, "backup": "backend/.env.bak.20261012_153500", "message": "已回滚到备份 ...，重启服务后生效"}
```

#### 4. 回归验证

```bash
cd backend
python smoke_test.py           # 14 个业务接口全部 200，AI 意图解析 3.4s、推荐理由 1.6s
python test_advanced_rag.py    # 高级 RAG 用例仍通过
cd ../frontend && npx tsc --noEmit   # 前端类型检查通过
```

> 评估链路自身不依赖 `smoke_test`，但评估会调用 `rag_service.search()` 与 `generate_answer()`，
> 因此 **embedding 通道可用性直接决定 context 类指标**，Ali / Ollama 全部不可用时该指标会降为 0 并在诊断里体现。

---

### 四、后续演进方向（1.0.0）

| 方向 | 说明 |
|---|---|
| 接入 Ragas 框架 | 用 ragas 的 `evaluate()` 对本地实现做交叉验证，确认两者趋势一致 |
| A/B 测试框架 | 同一数据集跑两套配置，直接对比胜率而不是单次得分 |
| 线上实时采样 | 从真实问答日志里采样评估集，形成持续闭环 |
| 报告 diff | 两次运行做逐指标 diff，自动标注"哪项变好 / 哪项变差" |
| 自动迭代到收敛 | 应用建议 → 重跑评估 → 未达标继续下一轮，直到评级进入"良好" |

---

## [0.7.2] - 2026-10-09 · 热修复：前端加载超时 + 登录无限 loading

> 主题：0.7.1 切换 Ali OpenAI 兼容通道后，AI 调用耗时仍可能达到数秒；
> 更关键的是**启动阶段 /health 同步探测 Ollama、前端 axios 默认超时 60000ms、AI 接口与业务接口共用同一把超时尺子**，
> 导致首页地图与登录请求被长耗时或阻塞的 AI 通道拖慢，出现 `timeout of 60000ms exceeded`、登录按钮一直转圈。
> 本次把 AI 调用彻底剥离出首页/登录的关键路径，并给前端超时分层。

---

### 一、原有技术（0.7.1）及缺陷

| 环节 | 0.7.1 的技术 | 存在的缺陷 |
|---|---|---|
| 服务启动 | `main.py::on_startup()` 同步执行 `ensure_indexes()` + `rag_service.backend_info()` | 若 Chroma / DB 初始化慢，uvicorn 在 startup 事件结束**前不接收任何请求**，前端首屏等待 |
| 健康检查 | `/api/health` 同步调用 `ollama_health()` + `backend_info()` | Ollama 未启动或 Ali 通道异常时，健康检查本身阻塞，可能拖慢前端全局状态探测 |
| 前端超时 | `request.ts` 一把 `timeout: 60000` 管所有接口 | 登录、首页统计、AI 问答全部共用 60s：后端一旦阻塞，用户要转圈 60s 才收到错误 |
| AI 接口执行 | `/api/ai/*`、`/api/recommend` 为同步 `def` 路由 | FastAPI 虽在线程池运行，但长耗时 AI 调用仍占用工作线程，极端情况下会挤压登录/统计等非 AI 请求 |
| 错误提示 | axios 拦截器把所有错误都展示为后端返回的 `detail` | 超时时 `error.response` 为空，用户看到不友好的 `timeout of 60000ms exceeded` |

---

### 二、改进技术及对应代码位置

#### 1. 启动阶段不再阻塞：`backend/app/main.py`

- `on_startup` 改为 `async`，`ensure_indexes()` 与 `rag_service.backend_info()` 放入 `asyncio.create_task` 后台执行；
- 服务启动后即可接收请求，索引与 RAG 状态在后台补齐；
- 新增 `_HEALTH_CACHE` 与轻量 `/api/health`：AI / RAG 状态走后台探测 + 5 秒缓存，单次探测限时 2 秒，超时返回 `degraded`，绝不阻塞首页/登录。

#### 2. AI 路由全部改为 async + 线程池 + 显式超时

| 文件 | 改动 |
|---|---|
| `backend/app/routers/ai.py` | `/ai/status`、`/ai/parse-intent`、`/ai/recommend-reason`、`/ai/chat` 全部改为 `async`；`/ai/chat` 整体放入线程池并设 120s 上限；探测类接口限时 3~30s |
| `backend/app/routers/recommend.py` | `/recommend`、`/recommend/ai-reasons` 改为 `async` + 线程池；`/recommend` 整体 60s 上限，超时返回 504 |

#### 3. 前端超时分层：`frontend/src/api/request.ts`

- 默认 axios 实例 `request` 超时从 `60000ms` 降到 `10000ms`，用于首页、登录、统计、查大学等常规接口；
- 新增 `aiRequest` 实例，超时 `120000ms`，专门用于 AI 问答、知识库检索、文件上传、AI 推荐理由；
- 统一响应拦截器识别 `ECONNABORTED` / `timeout`，给出中文提示“请求超时，请稍后重试”。

#### 4. 业务接口使用正确的超时实例

| 文件 | 改动 |
|---|---|
| `frontend/src/api/ai.ts` | `chat` 改用 `httpAI`，保留 120s 长超时 |
| `frontend/src/api/knowledge.ts` | `uploadKnowledge`、`searchKnowledge` 改用 `httpAI`（30s/120s） |
| `frontend/src/api/recommend.ts` | `recommend` 按 `use_ai` 选择实例：不用 AI 30s，用 AI 60s |

#### 5. 友好的超时提示

`request.ts` 拦截器在超时时不再把 `timeout of 60000ms exceeded` 直接弹给用户，而是统一提示“请求超时，请稍后重试”。

---

### 三、验证流程

#### 1. 启动速度

```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

服务应在 1~2 秒内进入 `Application startup complete.`，不再因为 startup 事件阻塞。

#### 2. 健康检查非阻塞

```bash
GET /api/health
# → 即使 Ollama 未启动，也应在 500ms 内返回
# {"status":"degraded","database":"gaokao","ollama":false,"ollama_message":"AI 通道探测超时","rag":{"ready":null}}
```

#### 3. 首页与登录响应时间

```bash
# 首页统计
GET /api/stats/major-count-by-province?province=河南&year=2025&category=物理类&batch=本科批
# → 应在 3s 内返回

# 登录
POST /api/auth/login {"username":"admin","password":"admin123"}
# → 应在 5s 内返回 token
```

#### 4. AI 接口独立超时

```bash
# AI 问答仍可长等待
POST /api/ai/chat {"question":"福州大学至诚学院计算机专业学费是多少","use_rag":true,"top_k":3}
# → 前端使用 120s 超时，正常返回约 5~8s
```

---

### 四、后续演进方向（0.9.0 及以后）

| 方向 | 说明 |
|---|---|
| 流式输出 | `/api/ai/chat` 支持 SSE，减少用户等待感 |
| AI 任务队列 | 将长耗时 AI 理由生成放入后台队列，前端轮询结果 |
| 独立 AI Worker | AI 推理与业务 API 进程分离，彻底避免资源争抢 |
| 前端请求优先级 | 关键路径请求（登录、首页）自动降级/重试，非关键请求可排队 |

---

## [0.7.1] - 2026-10-09 · 热修复：LLM 通道 base_url/SDK 修正 + README 深度重构

> 主题：0.7.0 上线后**用户 AI 问答全部超时**。根因是 LLM 通道用错了 base_url 与调用方式：
> 限时模型 `qwen3.7-flash-2026-07-15` **必须**走 OpenAI 兼容接口且指向工作空间专属域名，
> 不能用 `dashscope` Python SDK，也不能用通用域名 `https://dashscope.aliyuncs.com/compatible-mode/v1`。
> 本次把 LLM / Embedding 统一收敛到一个通道模块，并顺手把整条问答链路从 198s 优化到 5.7s。

---

### 一、原有技术（0.7.0）及缺陷

| 环节 | 0.7.0 的技术 | 存在的缺陷 |
|---|---|---|
| LLM 通道 | `requests.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")`，Key 读 `DASHSCOPE_API_KEY` | ① **该模型不在这个通用域名上**，每次调用都要等满读超时才降级 → **所有 AI 问答超时**；<br>② Key 环境变量名与新的 `Ali_API_KEY` 不一致，配了也读不到；<br>③ 手写 HTTP，取值逻辑散落在多处 |
| Embedding 通道 | 同一个通用域名 + requests | 同上；且没有维度对齐，换模型后与历史 768 维数据冲突会直接被 Chroma 拒绝 |
| 调用耗时 | 串行：预处理 3 次 LLM + 每条 Query 单独 embedding | 一次问答要十几轮网络往返，最长观测到 **198 秒** |
| 每次调研兜底 | 无 | Ali 失败后没有统一的「明确日志 + 本地兜底」策略 |
| README | 目录结构与原版无异 | ① 只有静态树形，没有文件职责；<br>② 缺业务模块流程；<br>③ 流程图过于简陋，没有「文件 → 函数 → 参数 → 下一个文件」级别的链路 |

---

### 二、改进技术及对应代码位置

#### 1. 新建 `backend/app/services/llm_client.py`（★ 本次核心）

两条通道 + 一个门面，**所有** LLM / Embedding 调用都收敛到这里：

| 类 | 职责 | 说明 |
|---|---|---|
| `BaseLLMChannel` | LLM 通道抽象 | 只有 `chat(system_prompt, user_prompt, temperature, max_tokens, top_p)` |
| `BaseEmbeddingChannel` | Embedding 通道抽象 | 只有 `embed()` / `embed_batch()` |
| `AliLLMChannel` | **OpenAI 兼容** LLM 通道 | `OpenAI(api_key, base_url=ALI_BASE_URL)`，取值 `response.choices[0].message.content` |
| `AliEmbeddingChannel` | **OpenAI 兼容** embedding | `client.embeddings.create(input=..., model=ALI_EMBED_MODEL, dimensions=...)`，原生批量 |
| `OllamaLLMChannel` | 本地兜底 LLM | 直连 `/api/generate`（不走 `ai_service.ask`，避免循环依赖） |
| `OllamaEmbeddingChannel` | 本地兜底 embedding | 直连 `/api/embeddings` |
| `LLMClient` | 门面 + 降级编排 | 组合主/兜底通道（合成复用），按序尝试；附带进程内 embedding 缓存 |
| `_EmbeddingCache` | 进程内向量缓存 | 同一条 Query 在召回 / Rerank 里被重复向量化 4~8 次，缓存后成本变 0 |

关键代码（`llm_client.py`）：

```python
key = get_api_key()                      # ① os.getenv("Ali_API_KEY") → ② Windows 注册表补读
self._client = OpenAI(api_key=key, base_url=settings.ALI_BASE_URL, timeout=settings.ALI_TIMEOUT, max_retries=0)
resp = self.client.chat.completions.create(model=self.model, messages=messages,
                                           temperature=..., max_tokens=...,
                                           extra_body={"enable_thinking": False})  # 思考模式关闭
return resp.choices[0].message.content   # 不再有 dashscope 的 response.output.choices[0]
```

#### 2. `backend/app/config.py`：配置项换血

```python
ALI_API_KEY          = _env("Ali_API_KEY", "")                       # 取代 DASHSCOPE_API_KEY
ALI_BASE_URL         = _env("ALI_BASE_URL", "https://ws-66jxf85tc3oa6b98.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
ALI_LLM_MODEL        = _env("ALI_LLM_MODEL", "qwen3.7-flash-2026-07-15")   # 取代 DASHSCOPE_MODEL
ALI_EMBED_MODEL      = _env("ALI_EMBED_MODEL", "text-embedding-v3")        # 取代 DASHSCOPE_EMBED_MODEL
ALI_EMBED_DIMENSION  = 128                # 实际会优先对齐已有集合维度
ALI_TIMEOUT          = 30                 # 超时即降级本地 Ollama
ALI_ENABLE_THINKING  = 0                  # 关思考：同一请求实测 9.7s → 2.6s
QUERY_PREPROCESS_MIN_LEN = 20             # 短问句跳过检索前预处理
```

旧的 `DASHSCOPE_API_KEY` / `DASHSCOPE_EMBED_MODEL` / `DASHSCOPE_MODEL` 已**全部删除**，代码内统一 `ALI_*` 前缀。

#### 3. 调用点改造（全部改为走 `llm_client`）

| 文件 | 改动 |
|---|---|
| `query_rewrite.py` | 删除 `DASHSCOPE_BASE_URL` / `get_dashscope_key()` / `_dashscope_chat()` / `_ollama_chat()`；`llm_chat()` 只剩三行，委托 `LLMClient.chat()`；`QueryBundle.source` 取值改为 `ali / ollama / raw` |
| `self_rag.py` | `SelfRAG.llm()` 改调 `get_llm_client().chat(...)`；判断类输出限制 `max_tokens=16` |
| `corrective_rag.py` | `CorrectiveRAG.llm()` 同上；`is_relevant()` 用 16 token；新增 `_filter_relevant()` 用线程池**并发**判相关性 |
| `ai_service.py` | `ask()` 改走统一通道（Ali → Ollama）；新增 `ask_local()` 仅供「必须本地」场景 |
| `rag_service.py` | 删除 `_dashscope_embedding()`；`get_embedding()` 走 `LLMClient.embed(dimensions=_collection_dimension())`；新增 `get_embeddings_batch()`；`backend_info()` 增加 `llm_provider` / `llm_model` |
| `retrieval.py` | `ProjectEmbedding.encode()` 改为整批请求（一次往返算完一批 Query） |

#### 4. 提速：198s → 5.7s

| 手段 | 位置 | 收益 |
|---|---|---|
| 关闭思考模式（`extra_body.enable_thinking=False`） | `llm_client.AliLLMChannel` | 单次 9.7s → 2.6s |
| 检索前预处理三路并发 | `query_rewrite.QueryPreprocessor.process()` | 3 次往返 → 1 次 |
| 相关性判断并发 | `corrective_rag._filter_relevant()` | N 次 → 1 次 |
| embedding 原生批量 | `AliEmbeddingChannel.embed_batch()` | 一次请求算完一批 Query |
| embedding 进程内缓存 | `_EmbeddingCache` | 重复 Query 零成本 |
| 短问句跳过预处理 | `QUERY_PREPROCESS_MIN_LEN=20` | 少一轮 LLM |
| 限制判断类输出长度 | `max_tokens=16 / 128` | 少生成无用 token |

#### 5. 降级策略（保持不变的强度）

| 场景 | 处理 |
|---|---|
| `Ali_API_KEY` 为空 | `AliLLMChannel.available()` 返回 False → 直接用 Ollama |
| Ali 调用超时 / 403 / 网络错误 | 捕获后打日志 `[LLM] Ali 通道失败，降级到 Ollama`，换 `OllamaLLMChannel` 重试 |
| Key 配在系统环境变量但进程启动更早 | `get_api_key()` 兜底读 Windows 注册表（Machine / User），无需重启服务 |
| Ollama 也失败 | `LLMClient.chat()` 返回 `""` → 各判断保守处理（保留原始 Query / "未查询到具体信息"），**不抛异常** |
| Embedding 通道失败 | Ali → Ollama → 单条用零向量占位（保证矩阵形状一致） |
| Chroma 维度不匹配 | `_collection_dimension()` 读取已有集合真实维度并复用（历史数据 768） |

#### 6. 配置与依赖

| 文件 | 改动 |
|---|---|
| `backend/.env` | 删除 `DASHSCOPE_API_KEY`；新增 `Ali_API_KEY / ALI_BASE_URL / ALI_LLM_MODEL / ALI_EMBED_MODEL / ALI_EMBED_DIMENSION / ALI_TIMEOUT` |
| `backend/.env.example` | 同上，并写明「Key 与 base_url 由 LLM、Embedding 共用」 |
| `backend/requirements.txt` | 移除 `dashscope`；新增 `openai>=1.0` |

#### 7. README 深度重构

改为**八章结构**：一、项目速览（技术栈表 + ★ 配置位置）／二、目录结构与文件职责（树 + 三种彩色标注）／
三、业务模块调用流程（Mermaid 端到端图 + 参数级调用树 + 前端请求表）／四、RAG 模块调用流程（上传链 + 问答链 A-F 六分支）／
五、接口清单（新增「调用链」列）／六、环境准备与启动（更新 Ali 说明）／七、常见问题排查（新增「AI 问答超时」）／八、RAG 版本演进对照。

---

### 三、验证流程

#### 1. 最小用例

```bash
cd backend
python test_llm_channel.py
```

实测输出（本机，2026-10-09）：

```
========================================================================
【1】通道自检
========================================================================
  Ali_API_KEY：sk-ws-***-X（来源：系统环境变量/注册表）
  LLM 通道顺序：['ali', 'ollama']
  Embedding 通道顺序：['ali_embed', 'ollama_embed']
  ALI_BASE_URL = https://ws-66jxf85tc3oa6b98.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
  ALI_LLM_MODEL = qwen3.7-flash-2026-07-15

【2】Ali LLM 调用：'你好，有什么可以帮您的吗？'   耗时 6.90s（首包含模型冷启动）

【3】已有集合维度：768，本次请求维度：768
  embedding 返回：768 维   耗时 1.84s

【4】关闭 Key 后的降级（模拟线上通道故障）
  Ollama 兜底返回：'你好！'   耗时 1.94s

========================================================================
【5】端到端问答（与 POST /api/ai/chat 同一条链路）
========================================================================
  临时知识库：3 个父块 → 21 个子块
  问题：福州大学至诚学院计算机专业学费是多少
  strategy = corrective
  steps    = ['retrieved=2', 'relevant=2', 'generated']
  answer   = 根据现有资料：福州大学至诚学院计算机科学与技术专业，学制4年，学费标准为23000元/年…
  sources  = ['福大至诚招生.txt']
  答案含正确数字(23000)：是
  耗时 5.74s → [通过] 10 秒内返回
  已清理临时集合与测试父块
```

耗时对比：

| 阶段 | 0.7.0（错误通道） | 0.7.1（修正 + 优化） |
|---|---|---|
| 同一问题端到端 | **198.00s**（多次超时后兜底） | **5.74s** |
| 提速倍数 | — | **约 34 倍** |

#### 2. 接口端到端验证

```bash
# 注意：请求体必须 UTF-8 编码，否则中文会乱码导致误判为无关问题
POST /api/ai/chat  {"question":"福州大学至诚学院计算机专业学费是多少","use_rag":true,"top_k":3}
# → source=advanced:corrective，answer 带 sources（命中资料时约 5~8s）

GET  /api/knowledge/search?query=专升本&top_k=3   （需 Bearer Token）
# → hits=3，首次 3.56s，二次命中缓存 0.05s，证明 embedding 通道正常
```

#### 3. 回归验证

```bash
cd backend
python smoke_test.py           # 14 个业务接口全部 200；AI 意图解析 3.43s、推荐理由 1.62s（原 4~10s）
python test_advanced_rag.py    # 0.7.0 用例仍通过（强制本地兜底）
```

> 踩坑记录：用 PowerShell `Invoke-RestMethod` 发中文请求体时可能因编码导致服务端收到乱码，
> 表现为 `source=router_blocked`。改用 UTF-8 编码请求后恢复正常 —— 这不是代码问题。

---

### 四、后续演进方向（0.9.0）

| 方向 | 说明 |
|---|---|
| CrossEncoder 精排落地 | 下载 BGE-Reranker 到本地，配 `RERANK_MODEL` 后自动切换，对比余弦精排效果差异 |
| 并行召回 | 召回通道 / 子查询并发执行，进一步压缩多路召回时延 |
| 语义分块 | 父子块升级为语义 / 标题感知切分 |
| Text-to-SQL 落地 | 把 `extract_sql_filters()` 抽出的条件真正接到 MySQL |
| 回答流式输出 | 接入 SSE，避免长回答的等待感 |

---

## [0.7.0] - 2026-10-08 · 检索后优化（Re-ranking）+ 高级 RAG（Self-RAG / Corrective RAG）

> 主题：把 0.6.0 里**空转**的 `rerank()` 钩子真正落地，并按课堂案例
> `01_检索后优化_重排序.py` / `02_self_RAG（python原生）.py` / `03_correctiveRAG（用python原生实现）.py`
> 引入两条**高级 RAG 链路**，由 Modular RAG 路由按问题特征自动选择。

---

### 一、原有技术（0.6.0）及缺陷

| 环节 | 0.6.0 的技术 | 存在的缺陷 |
|---|---|---|
| 精排 | `rerank()` 是**空钩子**：`if not hits or not settings.RERANK_MODEL: return hits` | ① 未配置 CrossEncoder 模型时完全不生效；<br>② 排序完全由 RRF 决定，只考虑「排名」不考虑「语义贴合度」，Top-1 常不是最贴切的那条 |
| 生成 | 检索完就把 Top-K 拼接送 LLM 一次性生成 | ① 不判断「要不要检索」「召回的文档有没有用」，噪声文档也进 Prompt；<br>② 生成后不自检，编造数字/遗漏侧面无法纠正 |
| 纠偏 | 无 | 召回的文档**全部无关**时（Query 表述与资料用语不一致）直接拒答，不会换个说法再试一次 |
| LLM 通道 | DashScope 默认 `qwen-plus` | 课堂案例用的 `qwen-plus` **免费额度已用尽**（403 `AllocationQuota.FreeTierOnly`），每次调用都要走一次失败的远程往返 |

---

### 二、改进技术及对应代码位置

#### 1. 新建 `backend/app/services/reranker.py`（检索后优化：重排序）

两阶段检索：**第 1 阶段召回（重在全）→ 第 2 阶段精排（重在准）**。

| 类 | 职责 |
|---|---|
| `BaseReranker` | 抽象基类（接口隔离）：只要求实现 `score(query, docs) -> List[float]` |
| `CrossEncoderReranker` | `sentence_transformers.CrossEncoder` 逐对打分，精度最高（需 `settings.RERANK_MODEL` 指定本地模型） |
| `EmbeddingReranker` | **无额外依赖的精排**：复用项目已有 embedding（Ollama `nomic-embed-text` / DashScope）算「问题-文档」余弦相似度 |
| `NoopReranker` | 空实现（关闭精排时直传，保证调用方无需分支判断） |
| `Reranker` | 门面类：按配置选择实现 + **失败降级**（合成复用 + 开闭） |

优先级：`RERANK_ENABLED=0 → NoopReranker`；`RERANK_MODEL 有值且 CrossEncoder 可用 → CrossEncoderReranker`；
否则 → `EmbeddingReranker`（默认，**本机无需装任何新模型即可生效**）。

输出字段：`rerank_score`（精排分）、`reranker`（实际用的实现名），**保留原 `rrf_score`** 便于对比。

#### 2. 新建 `backend/app/services/self_rag.py`（Self-RAG）

Self-RAG 的核心不是「多检索几次」，而是让模型**自己判断每一步**：

| 步骤 | 方法 | 作用 |
|---|---|---|
| ① | `should_retrieve()` | 是否真的需要检索？（避免无关问题浪费检索） |
| ② | `is_context_useful()` | 检索到的上下文能否支撑回答？（避免拿噪声去生成） |
| ③ | `should_continue_generate()` | 回答是否完整、准确、无幻觉？ |
| ④ | `reflect_and_correct()` | 不合格才调：对照上下文改掉幻觉与遗漏（省一次 LLM 调用） |

返回 `SelfRAGResult(answer, used_context, need_retrieve, context_useful, steps)`，`steps` 记录每一步判断便于排查与演示。

#### 3. 新建 `backend/app/services/corrective_rag.py`（Corrective RAG）

管的是「**召回的文档对不对**」：检索 → 逐条相关性过滤 → 一条都不相关就**重写 Query 再检索** → 仍不足才拒答。

| 方法 | 作用 |
|---|---|
| `is_relevant(query, doc)` | 单条文档判 `RELEVANT / IRRELEVANT` |
| `rewrite_query(query)` | 换个更贴近资料用语的说法 |
| `run()` | 检索 → 过滤 →（不足则重写重试，`CORRECTIVE_MAX_RETRY` 次）→ 生成 |

#### 4. 修改 `backend/app/services/rag_service.py`（落地 + 路由）

| 函数 | 说明 |
|---|---|
| `rerank()` | 由「空钩子」改为真实调用 `Reranker().rerank(query, hits)`；异常时保持召回顺序，**链路不中断** |
| `route_strategy()` | **Modular RAG 路由**：纯规则判断、零 LLM 延迟 —— 含「是不是/能不能/是否」→ `self_rag`；复合多实体或 ≥18 字 → `corrective`；其余 → `standard` |
| `answer_with_strategy()` | Modular RAG 主流程：三条链路**共用同一个 `search()`**（检索前预处理 + 多路召回 + 精排 + 父块回填），差别只在「拿到上下文之后怎么生成」 |
| `_sources_from_hits()` | 从命中结果提取去重后的来源文件名 |

#### 5. 修改 `backend/app/routers/ai.py`（接入问答接口）

`POST /api/ai/chat` 在 `use_rag=true` 且 `ADVANCED_RAG_ENABLED=1` 时走高级链路，响应新增字段：

```jsonc
{
  "answer": "...",
  "source": "advanced:corrective",   // 便于前端/日志区分来源
  "strategy": "corrective",          // self_rag / corrective / standard
  "steps": ["retrieved=3", "relevant=2", "generated"],
  "rewritten_query": "..."           // 仅 corrective 触发重写时非空
}
```

高级链路抛异常时 `except → pass`，**自动回落 0.6.0 原有流程**。

#### 6. 新增配置（`app/config.py`）

```python
DASHSCOPE_MODEL         = "qwen3.7-flash-2026-07-15"  # 替换额度用尽的 qwen-plus
OLLAMA_FALLBACK_MODEL   = "qwen3:1.7b"                # 本地兜底
RERANK_ENABLED          = 1      # 精排总开关（0 → NoopReranker）
RERANK_MODEL            = ""     # CrossEncoder 路径；留空则用 embedding 余弦精排
ADVANCED_RAG_ENABLED    = 1      # 高级 RAG 总开关
ADVANCED_RAG_STRATEGY   = "auto" # auto / self_rag / corrective / standard
CORRECTIVE_MAX_RETRY    = 1      # Corrective RAG 重写重试次数
```

同时 `query_rewrite.py` 两处加固：

1. 新增 `default_chat_model()`：环境变量 → `settings.DASHSCOPE_MODEL` → 代码默认值，
   统一模型名，避免各处散落 `qwen-plus`；
2. `_dashscope_chat()` 补 `max_tokens=512` 与 `(连接 10s, 读 30s)` 分离超时 ——
   思考型模型（qwen3.7-flash 会输出很长的 `reasoning_content`）原先不设上限，
   每次都要等满读超时才降级本地，白白多花几十秒。

#### 7. 降级策略

| 场景 | 处理 |
|---|---|
| 未配置 `RERANK_MODEL`（本机现状） | 自动用 `EmbeddingReranker` 余弦精排，**无需额外模型** |
| CrossEncoder 导入/加载失败 | 门面捕获异常 → 降级 `EmbeddingReranker` |
| 精排过程抛异常 | 保持召回顺序，`rerank_score=None, reranker="failed"` |
| Self-RAG / Corrective RAG 任一步异常 | `except → mode = "standard"`，走常规 RAG |
| `ADVANCED_RAG_ENABLED=0` | `answer_with_strategy()` 强制 `standard`，接口返回不变 |
| DashScope 403 / 无 Key | 统一回落本地 Ollama（`query_rewrite.llm_chat` 已封装） |
| 两层 LLM 都失败 | `llm()` 返回空串，各判断做**保守处理**（"未查询到具体信息"），不抛异常 |

---

### 三、验证流程

#### 1. 最小用例

```bash
cd backend
python test_advanced_rag.py
```

实测输出（本机 Ollama 兜底，总耗时约 3 分钟）：

```
知识库：父块 4 个，子块 4 个

【1】Rerank 精排：召回顺序 vs 精排后顺序
  -- 召回 + 父块回填后（0.6.0 终点）--
    1. [召回分 0.1967] 福州大学至诚学院2025年在河南本科批物理类投档最低分为458分，对应全...
    2. [召回分 0.1915] 福州大学至诚学院是经教育部批准设立的独立学院，位于福建省福州市，2025...
    3. [召回分 0.1903] 福州大学至诚学院计算机科学与技术专业，学制4年，学费标准为23000元/...
    4. [召回分 0.1897] 河南省2025年本科批实行平行志愿，考生可填报48个院校专业组志愿，投档...
  -- Rerank 精排后（0.7.0）--
    1. [精排分 0.9234] 福州大学至诚学院2025年在河南本科批物理类投档最低分为458分，对应全...
    2. [精排分 0.8723] 福州大学至诚学院是经教育部批准设立的独立学院，位于福建省福州市，2025...
    3. [精排分 0.8086] 福州大学至诚学院计算机科学与技术专业，学制4年，学费标准为23000元/...
    4. [精排分 0.8085] 河南省2025年本科批实行平行志愿，考生可填报48个院校专业组志愿，投档...

  精排是否改变顺序：否（召回顺序已最优）
  Reranker 实现：embedding

【2】Modular RAG 路由
  2025年河南考生报福州大学至诚学院计算机专业，学费和位... → corrective
  福州大学至诚学院是不是民办本科？... → self_rag
  河南本科批志愿怎么填报... → standard

【3】0.6.0（直接生成）vs 0.7.0（高级 RAG）
  -- 0.6.0 --
    根据检索上下文，福州大学至诚学院计算机专业2025年在河南本科批物理类的学费为23000元/年，对应全省位次约为112000名。

  -- 0.7.0 strategy=self_rag --
    步骤：['need_retrieve=True', 'retrieved=3', 'context_useful=True', 'generated', 'passed_check']   来源：['福大至诚招生.txt']
    回答：根据检索上下文，福州大学至诚学院2025年在河南本科批物理类投档最低分约为458分，对应全省位次约为112000名。计算机科学与技术专业学费标准为23000元/年。
    耗时：26.1s

  -- 0.7.0 strategy=corrective --
    步骤：['retrieved=3', 'relevant=2', 'generated']   来源：['福大至诚招生.txt']
    回答：…投档最低分约为458分，对应全省位次约为112000名。计算机科学与技术专业学费标准为23000元/年，选科要求首选物理、再选化学。
    耗时：24.0s

  -- 0.7.0 strategy=standard --
    步骤：['retrieve', 'generate']   来源：['福大至诚招生.txt']
    回答：…投档最低分约为458分，对应全省位次约为112000名。计算机科学与技术专业学费标准为23000元/年。
    耗时：19.8s

【4】降级验证：关闭高级 RAG 后走标准链路，链路不中断
  策略 = standard，回答长度 = 82   [通过]
```

关键现象解读：

| 现象 | 说明 |
|---|---|
| 精排未改变顺序 | 本用例语料只有 4 条且表述规范，RRF 的召回顺序已是最优；精排的价值在**长文档 / 多侧面**场景下把最贴切的顶上来（分数差距被拉开：0.9234 vs 0.8085） |
| `reranker=embedding` | `RERANK_MODEL` 留空 → 自动用 `EmbeddingReranker`，**本机无需下载任何新模型** |
| corrective 只留 2/3 条 | 「平行志愿」那条被判 `IRRELEVANT` 过滤掉，回答更聚焦（多答出「选科要求首选物理、再选化学」） |
| self_rag 走了 5 步 | `need_retrieve → retrieved → context_useful → generated → passed_check`，自评合格后**没有**触发反思修正（省一次 LLM 调用） |

#### 2. 接口端到端验证

```bash
POST /api/ai/chat {"question":"2025年河南考生报福州大学至诚学院计算机专业，学费和位次大概多少？","use_rag":true,"top_k":3}
# → source=advanced:corrective，steps 含 retrieved / relevant / generated

POST /api/ai/chat {"question":"福州大学至诚学院是不是民办本科？","use_rag":true,"top_k":3}
# → source=advanced:self_rag，steps 含 need_retrieve / context_useful / generated
```

#### 3. 回归验证

```bash
cd backend
python test_multi_query.py            # 0.5.0 多路召回
python test_query_preprocess_recall.py # 0.6.0 检索前 + 多路召回
python smoke_rag.py                   # 登录 → 上传 → 检索 → RAG 问答 → 删除
python smoke_test.py                  # 14 个业务接口
```

> 环境提示：
> 1. 本机 `RERANK_MODEL` 留空，精排实际走 `EmbeddingReranker`（embedding 余弦），
>    无需下载任何新模型；后续接入 BGE-Reranker 只需在 `.env` 填模型路径，**代码零改动**；
> 2. 用例里把 DashScope Key 置空，**强制本地 Ollama 兜底**，避免依赖外网额度与网络抖动；
> 3. 服务进程需要**重启**才能加载 0.7.0 新模块（`uvicorn` 未开 `--reload`）。

---

### 四、后续演进方向（0.9.0）

| 方向 | 说明 |
|---|---|
| CrossEncoder 精排 | 下载 BGE-Reranker 到本地，配置 `RERANK_MODEL` 后自动切换，对比余弦精排的效果差异 |
| 并行召回 | 多通道 / 多子查询并发执行，降低多路召回时延 |
| 语义分块 | 父子块升级为语义/标题感知切分 |
| Text-to-SQL 落地 | 把 `extract_sql_filters()` 的条件接到 MySQL |

---

## [0.6.0] - 2026-10-08 · 检索前预处理 + 模块化多路召回（课堂案例风格重构）

> 主题：按课堂案例（01_混合检索 / 02_多路召回 / 03_多路召回的封装 / 01_查询重写 / 02_查询扩展 / 03_子查询）
> 把「检索前」与「检索中」拆成两个独立模块，面向对象封装，并接入项目检索入口。

---

### 一、原有技术（0.5.0）及缺陷

| 环节 | 0.5.0 的技术 | 存在的缺陷 |
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

【3】0.4.1 单路 vs 0.6.0 预处理 + 多路召回
  覆盖语义侧面数：0.4.1 = 3/3，0.6.0 = 3/3   [通过]
  （0.6.0 三条全部 context_level=parent，学费/位次/学校三个侧面都召回）

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

### 四、后续演进方向（0.7.0）

| 方向 | 说明 |
|---|---|
| **Rerank 落地** | 接入 BGE-Reranker / Cross-Encoder，在 `rerank()` 中实现二次排序（当前为 no-op） |
| 通道扩展 | 增加「标题通道」「政策条款通道」等数据源级通道，验证开闭原则 |
| 并行召回 | 多通道/多子查询并发执行，降低多路召回时延 |
| 子查询去重 | 语义相近的 Query 合并，避免重复加权 |
| Text-to-SQL 落地 | 把 `extract_sql_filters()` 的条件接到 MySQL |

---

## [0.5.0] - 2026-10-08 · 多路召回（Multi-Query Recall）：Query 分解 + 跨路 RRF 融合

> 主题：把「一条 Query 走一次混合检索」升级为「一条复杂 Query 拆成多条子查询、各走一次混合检索、再跨路 RRF 累加」，
> 解决复合问题（同时问学校 + 学费 + 位次）召回不全的问题。

---

### 一、原有技术（0.4.1）及缺陷

| 环节 | 0.4.1 的技术 | 存在的缺陷 |
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
  -- 多路召回（0.5.0）-- RRF 0.13088 / 0.12827 / 0.12751（8 条排名列表累加）
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

### 四、后续演进方向（0.7.0）

| 方向 | 说明 |
|---|---|
| **Rerank 落地** | 接入 BGE-Reranker / Cross-Encoder，在 `rerank()` 中实现二次排序（当前为 no-op） |
| 子查询并行化 | 多条子查询的 embedding 与检索改为并发，降低多路召回的时延 |
| 子查询去重优化 | 语义相近的子查询合并，避免同一语义被重复加权 |
| Text-to-SQL 落地 | 把 `extract_sql_filters()` 的条件真正接到 MySQL |
| BM25 索引持久化 | 语料到十万级时改为 pickle 持久化 + 增量更新 |

---

## [0.4.1] - 2026-10-08 · 热修复：修正路由误拦截与防幻觉误拒答

> 主题：0.4.0 上线后，发现「高考核心业务问题」被过度拦截/拒答
> （如「2025河南在福建招生的院校」「福州大学至诚学院计算机专业学费」均被误判为无关或拒答）。
> 本次热修复放宽路由判定、修正防幻觉 Prompt、调整降级策略与采样参数。

---

### 一、原有技术（0.4.0）及缺陷

| 环节 | 0.4.0 的技术 | 存在的缺陷 |
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
  [通过] route_query(2025河南在福建招生的院校)       期望 放行 → 实际 放行   ← 0.4.1 修正
  [通过] route_query(福州大学至诚学院计算机专业学费) 期望 放行 → 实际 放行   ← 0.4.1 修正
  [通过] route_query(河南本科批志愿怎么填报)         期望 放行 → 实际 放行
  [通过] route_query(郑州大学计算机专业学费多少)     期望 放行 → 实际 放行

【2】上下文【有】学费（temperature=0.1, top_p=0.3）
  回答：福州大学至诚学院计算机科学与技术专业2025年在河南本科批物理类招生的学费标准为23000元/年。
  [通过] 回答中出现上下文里的真实学费 23000
  [通过] 没有误触发拒答话术                                                ← 0.4.1 修正

【3】上下文【无】学费 → 拒答/引导，且不编造数字
  回答：根据现有资料，未查询到具体信息，建议查阅学校官方招生简章。
  [通过] 按话术引导    [通过] 没有编造数字

【4】对照：0.3.0 通用 Prompt（temperature=0.3, top_p=0.85）
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

### 四、后续演进方向（0.5.0）

| 方向 | 说明 |
|---|---|
| **Rerank 重排** | 在 RRF 之后接入 BGE-Reranker 二次排序 |
| **Text-to-SQL 落地** | 把 `extract_sql_filters()` 提取的条件真正接到 MySQL（学费/分数线/位次走结构化查询） |
| 查询改写 | 多轮对话时先让 Qwen3 改写查询再做检索 |
| 表格结构化处理 | 将分数线表格转为自然语言三元组后再切块 |
| BM25 索引持久化 | 语料到十万级时改为 pickle 持久化 + 增量更新 |

---

## [0.4.0] - 2026-10-08 · Query 路由与防幻觉 Prompt：解决无关问答与学费幻觉

> 主题：在 0.3.0 父子块基础上，增加 Query 意图路由与生成侧强约束，解决「婚假乱答」与「学费编造」两大幻觉问题。

---

### 一、原有技术（0.3.0）及缺陷

| 环节 | 0.3.0 的技术 | 存在的缺陷 |
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
| 状态 | 已能正确提取 JSON，实际 Text-to-SQL 查询留到 0.5.0 落地 |

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

【4】对照：0.3.0 通用 Prompt（temperature=0.3, top_p=0.85）
  回答：郑州大学计算机科学与技术专业学费一般为**8000元/年**…
  [通过] 0.3.0 会编造数字（说明改造必要性）

【5】结构化提取预留（SQL_EXTRACT_PROMPT, temperature=0.0）
  {'school_name': '郑州大学', 'major_name': '计算机科学与技术', 'year': 2025, 'province': '河南省'}
```

> 关键对照：同一问题「学费多少」，0.3.0 编造 **8000 元/年**，0.4.0 有资料时给 **5700 元/学年**（真实值）、无资料时拒答。

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

### 四、后续演进方向（0.5.0）

| 方向 | 说明 |
|---|---|
| **Rerank 重排** | 在 RRF 之后接入 BGE-Reranker 二次排序 |
| 查询改写 | 多轮对话时先让 Qwen3 改写查询再做检索 |
| **Text-to-SQL 落地** | 把 `extract_sql_filters()` 提取的条件真正接到 MySQL（学费/分数线/位次走结构化查询） |
| 表格结构化处理 | 将分数线表格转为自然语言三元组后再切块 |
| BM25 索引持久化 | 语料到十万级时改为 pickle 持久化 + 增量更新 |
| docstore 入 MySQL | 父块量大时把 JSON docstore 换成 `knowledge_parent_chunks` 表 |

---

## [0.3.0] - 2026-10-07 · 父子块检索（Parent-Child Chunking）：小块命中、大块生成

> 主题：在 0.2.0 的「递归分块 + BM25/RRF 混合检索」基础上叠加父子块结构。
> 检索单元从 500 字缩小到 120 字（更聚焦），生成上下文仍用 500 字父块（更完整）。

---

### 一、原有技术（0.2.0）及缺陷

| 环节 | 0.2.0 的技术 | 存在的缺陷 |
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
| 检索流程 | 子块参与混合检索（BM25 + RRF 路径完全沿用 0.2.0）→ 命中子块 → 按 `parent_chunk_id` 从 docstore 取回父块 → 父块交给 LLM |
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

无新增依赖（复用 0.2.0 的 `langchain-text-splitters` / `rank-bm25` / `jieba`）。

---

### 三、验证流程

#### 1. 最小用例（脚本已入库）

```bash
cd backend
python test_parent_child.py
```

实测输出（查询「婚假几天」，语料：招生政策 / 假期制度（干扰项） / 考勤办法（正确答案被无关内容包围））：

```
【0.2.0】向量库 = 3 个 500 字大块（无父子结构）
  1. [RRF 0.03279] 上下文 159 字 | 学校教职工考勤管理办法…

【0.3.0】向量库 = 6 个 120 字子块，docstore = 3 个父块
  -- 命中的子块（仅用于检索）--
    1. 116 字 | 学校教职工考勤管理办法：…教职工婚假为10天…
    2. 43 字  | 。婚假申请流程：需在休假前5个工作日提交书面申请…
  -- 回填父块后交给 LLM 的上下文 --
    1. [parent] file_9002_parent_2 上下文 159 字
    2. [parent] file_9002_parent_1 上下文 123 字

对比结果（查询「婚假几天」）
  A) 0.2.0 直接用大块检索     → Top1 159 字，命中「婚假」=是
  B) 0.3.0 命中的子块（检索用）→ Top1 116 字，命中「婚假」=是，含审批条件「5个工作日」=否
  C) 0.3.0 回填父块（交给LLM）→ Top1 159 字，粒度=parent，命中「婚假」=是，含审批条件「5个工作日」=是

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
- 0.2.0 之前上传的历史数据没有 `parent_chunk_id` → 自动走降级分支返回子块，**不会报错**

---

### 四、后续演进方向（0.4.0）

| 方向 | 说明 |
|---|---|
| **Rerank 重排** | 在 RRF 之后接入 Cross-Encoder / BGE-Reranker 二次排序，进一步提精 |
| 查询改写 | 多轮对话时先让 Qwen3 改写查询再做检索 |
| 语义/标题感知切分 | 父块按 Markdown 标题或语义相似度切分，而非纯递归字符切分 |
| BM25 索引持久化 | 语料到十万级时改为 pickle 持久化 + 增量更新 |
| docstore 入 MySQL | 父块量大时把 JSON docstore 换成 `knowledge_parent_chunks` 表 |

---

## [0.2.0] - 2026-10-06 · RAG 管线进阶：递归分块 + 混合检索（Hybrid Search）

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
