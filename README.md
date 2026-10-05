# 高考志愿填报系统（河南 2024-2025）+ RAG 知识库

基于河南 2024-2025 年高考录取数据，构建「冲 / 稳 / 保」三档志愿推荐系统，
并在其上扩展了独立的 **RAG 知识库模块**（Chroma 向量库 + Ollama embedding + Qwen3 生成）。

核心分工：

- **规则引擎负责计算**：分数 → 位次换算、分档、筛选过滤、概率估算
- **本地大模型负责理解与表达**：自然语言意图解析、推荐理由生成、知识库问答
- **RAG 负责政策类问答**：上传政策文档 → 切片 → 向量化 → 检索 → 拼进 Prompt
- **物理隔离维度**：所有查询必须带 `province + year + category + batch`

---

## 本次升级改动一览

| 类别 | 改动 |
|---|---|
| 后端结构 | 单文件 `backend/main.py` → `backend/app/` 包（models / schemas / routers / services / utils） |
| 前端 | 原生 HTML/CSS/JS → **Vue3 + TypeScript + Vite + Element Plus**（旧版归档到 `frontend/_legacy/`） |
| 数据库 | 新增 `users`（role: admin/student）与新版 `knowledge_files`（stored_filename / chunk_count / uploaded_by） |
| 鉴权 | JWT（python-jose）+ bcrypt（passlib），`get_current_admin` 依赖注入 |
| RAG | 新增 `services/rag_service.py`（Chroma 持久化 + Ollama embedding + 切片 + 检索） |
| 文件处理 | 新增 `utils/file_utils.py`（UUID 保存、PDF/DOCX/TXT 提取、500/50 切片） |
| 接口 | 新增 auth（登录/注册/me）与 knowledge（上传/列表/详情/下载/删除/检索/status） |
| 页面 | 新增管理端 `Dashboard.vue` / `Knowledge.vue`、考生端 `AiChat.vue`（RAG 问答） |
| 工程化 | 新增 `.gitignore`、`backend/.env`、`frontend/.npmrc.local`，Git 已初始化并提交 |

---

## 一、目录结构（前后端分离）

```
gaokao_project/
├── backend/                          # FastAPI 后端
│   ├── app/
│   │   ├── main.py                   # FastAPI 入口（含 Vue SPA 回退）
│   │   ├── config.py                 # 配置（DB / Ollama / Chroma / JWT / RAG）
│   │   ├── database.py               # 引擎、动态表反射、ORM Base、get_db
│   │   ├── models/
│   │   │   ├── dataset.py            # 录取数据集表名解析与维度归一化
│   │   │   ├── user.py               # 用户表 ORM（role: admin/student）
│   │   │   └── knowledge.py          # 知识库文件表 ORM
│   │   ├── schemas/
│   │   │   ├── student.py            # 考生信息 / 推荐请求响应
│   │   │   ├── user.py               # 登录 / 注册 / Token
│   │   │   └── knowledge.py          # 知识库列表 / 检索
│   │   ├── routers/
│   │   │   ├── auth.py               # 登录注册 + get_current_admin 依赖
│   │   │   ├── student.py            # 考生信息、分数 ↔ 位次
│   │   │   ├── recommend.py          # 冲稳保推荐
│   │   │   ├── university.py         # 查大学 / 查专业
│   │   │   ├── meta.py               # 维度选项、省控线、一分一段
│   │   │   ├── ai.py                 # 意图解析、推荐理由、RAG 问答
│   │   │   └── knowledge.py          # 上传 / 列表 / 详情 / 删除 / 检索
│   │   ├── services/
│   │   │   ├── rank_service.py       # 分数 ↔ 位次换算
│   │   │   ├── recommend_service.py  # 冲稳保规则引擎
│   │   │   ├── ai_service.py         # Ollama 调用 + 规则兜底
│   │   │   └── rag_service.py        # Chroma + embedding + 切片 + 检索
│   │   └── utils/
│   │       ├── security.py           # bcrypt 密码哈希 + JWT
│   │       └── file_utils.py         # UUID 保存、PDF/DOCX/TXT 提取、切片
│   ├── scripts/create_admin.py       # 创建 / 重置管理员
│   ├── sql/
│   │   ├── 03_knowledge.sql          # 旧版 knowledge_files（历史）
│   │   └── 04_rag_tables.sql         # 新版 users + knowledge_files
│   ├── knowledge_files/              # 上传的原始文件（已 gitignore）
│   ├── chroma_db/                    # Chroma 持久化目录（已 gitignore）
│   ├── smoke_test.py                 # 业务接口冒烟测试
│   ├── smoke_rag.py                  # RAG 全链路冒烟测试
│   ├── requirements.txt
│   ├── .env                          # 本地配置（已 gitignore）
│   └── .env.example
├── frontend/                         # Vue3 + TypeScript 前端
│   ├── src/
│   │   ├── main.ts / App.vue
│   │   ├── router/index.ts           # 路由 + 管理员守卫
│   │   ├── api/{request,auth,knowledge,recommend,ai}.ts
│   │   ├── stores/{user,knowledge}.ts
│   │   ├── types/{user,knowledge,recommend}.ts
│   │   ├── views/student/{Home,Volunteer,University,AiChat}.vue
│   │   ├── views/admin/{Dashboard,Knowledge}.vue
│   │   ├── views/Login.vue
│   │   └── components/{Navbar,ChatBubble,UploadModal}.vue
│   ├── _legacy/                      # 旧版原生 HTML/JS 前端（归档，不再使用）
│   ├── package.json / vite.config.ts / tsconfig.json
│   └── .npmrc.local                  # 本机 npm 配置（代理不可用时使用）
├── gaokao_data/                      # CSV 原始数据 + 导入脚本
├── .gitignore
└── README.md
```

---

## 二、环境准备（首次只需做一次）

### 1. 后端依赖

```bash
pip install -r backend/requirements.txt
```

> 注意：`passlib 1.7.4` 与 `bcrypt>=4.1` 不兼容，requirements 中已锁定 `bcrypt==4.0.1`。

### 2. MySQL 数据库

```bash
# （可选）导入河南 2024-2025 录取数据 8 张表
cd gaokao_data && python import_to_mysql.py

# 建 RAG / 鉴权相关两张表
mysql -u root -p gaokao < backend/sql/04_rag_tables.sql
```

数据表：

- 录取数据：`enrollment_plan_{y}_henan`、`major_admission_{y}_henan`、`school_admission_{y}_henan`、`score_range_{y}_henan`（y = 2024 / 2025）
- RAG / 鉴权：`users`、`knowledge_files`

### 3. 创建管理员

```bash
cd backend
python scripts/create_admin.py                    # 默认 admin / admin123（角色 admin）
python scripts/create_admin.py 用户名 密码 [admin|student]
```

已创建的测试账号：`admin / admin123`（管理员）、`student01 / student123`（考生）。

### 4. 本地大模型（生成 + embedding）

```bash
ollama pull qwen3:1.7b          # 生成模型
ollama pull nomic-embed-text    # embedding 模型（768 维）
ollama serve                    # 默认 http://localhost:11434
```

### 5. 前端依赖

```bash
cd frontend
npm install
```

> 若 `~/.npmrc` 配了代理（如 `127.0.0.1:7890`）而代理未启动，npm 会报 `ECONNREFUSED`，
> 可改用项目内配置绕过：`npm install --userconfig .npmrc.local`

### 6. 环境变量

复制并按需修改（也可直接用仓库里已配好的 `backend/.env`）：

```bash
cp backend/.env.example backend/.env
```

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME` | localhost / 3306 / root / 123456 / gaokao | MySQL 连接 |
| `OLLAMA_URL` / `OLLAMA_MODEL` | http://localhost:11434 / qwen3:1.7b | 生成模型 |
| `OLLAMA_EMBED_MODEL` | nomic-embed-text | 本地 embedding 模型 |
| `DASHSCOPE_API_KEY` | 空 | 填了则走千问 text-embedding-v3 |
| `JWT_SECRET` / `JWT_ALGORITHM` / `JWT_EXPIRE_MINUTES` | gaokao-dev-secret-change-me / HS256 / 720 | JWT 配置 |
| `CHROMA_DB_PATH` / `CHROMA_COLLECTION` | backend/chroma_db / gaokao_knowledge | 向量库 |
| `KNOWLEDGE_DIR` | backend/knowledge_files | 上传文件目录 |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 500 / 50 | 切片参数 |
| `RANK_BUFFER` / `RANK_SPAN_FACTOR` / `TIER_LIMIT` | 5000 / 8 / 60 | 冲稳保参数 |

---

## 三、如何启动

### 方式一：开发模式（推荐，前端热更新）

需要开 **两个终端**。

```bash
# 终端 1：后端（8000 端口）
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# 或：python -m app.main

# 终端 2：前端（5173 端口，vite 已配置 /api 代理到 8000）
cd frontend
npm run dev
```

访问：

| 地址 | 说明 |
|---|---|
| <http://127.0.0.1:5173/> | 前端开发服务器（考生端首页） |
| <http://127.0.0.1:8000/docs> | 后端交互式接口文档 |
| <http://127.0.0.1:8000/api/health> | 健康检查（含 DB / Ollama / RAG 状态） |

### 方式二：生产模式（后端直接托管 dist）

```bash
# 1. 构建前端
cd frontend
npm run build          # 输出 frontend/dist

# 2. 启动后端（自动托管 dist，并支持 /admin/knowledge 等前端路由回退）
cd ../backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

访问 <http://127.0.0.1:8000/> 即可，无需再开前端服务。

### 登录与页面入口

| 页面 | 路径 | 权限 |
|---|---|---|
| 考生端首页 | `/` | 公开 |
| 志愿填报 | `/volunteer` | 公开 |
| 查大学 / 专业 | `/university` | 公开 |
| AI 助手（RAG 问答） | `/ai-chat` | 需登录 |
| 后台首页 | `/admin` | 仅管理员 |
| 知识库管理 | `/admin/knowledge` | 仅管理员 |
| 登录 | `/login` | 公开 |

> 未登录访问 `/admin` 会被路由守卫重定向到 `/login`；
> 知识库检索接口要求登录态，上传 / 列表 / 删除要求管理员角色。

### 冒烟测试

```bash
cd backend
python smoke_test.py     # 志愿推荐等 14 个业务接口
python smoke_rag.py      # 登录 → 上传 → 向量化 → 检索 → RAG 问答 → 删除
```

### 停止服务

```bash
# Windows：结束占用端口的进程
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

---

## 四、接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务 + 数据库 + Ollama + RAG 状态 |
| POST | `/api/student/profile` | 保存考生信息并返回换算位次 |
| GET | `/api/score-to-rank` | 分数 → 位次（查一分一段表） |
| GET | `/api/rank-to-score` | 位次 → 分数 |
| POST | `/api/recommend` | **冲稳保推荐**（核心） |
| POST | `/api/recommend/ai-reasons` | 批量补充 AI 推荐理由 |
| GET | `/api/universities` | 院校列表（分页、筛选、概率） |
| GET | `/api/majors` | 院校专业录取明细 |
| GET | `/api/meta/options` | 可用年份 / 科类 / 批次 |
| GET | `/api/meta/province-stats` | 各省份在豫招生数量 |
| GET | `/api/meta/hot-schools` | 热门院校（985/211 优先） |
| GET | `/api/meta/score-table` | 一分一段表 |
| GET | `/api/meta/control-lines` | 各批次省控线 + 本科/专科可填分数区间 |
| GET | `/api/meta/score-check` | 分数校验：是否过线 + 自动推荐批次 + 自动换算位次 |
| GET | `/api/ai/status` | Ollama 状态 |
| POST | `/api/ai/parse-intent` | 自然语言 → 筛选条件 |
| POST | `/api/ai/recommend-reason` | 单条志愿推荐理由 |
| POST | `/api/ai/chat` | 志愿问答（`use_rag=true` 时先检索知识库再回答） |
| POST | `/api/auth/login` | 登录（支持 JSON 与 form），返回 JWT |
| POST | `/api/auth/register` | 注册（默认 student） |
| GET | `/api/auth/me` | 当前用户信息 |
| GET | `/api/knowledge/status` | 向量库 / embedding 状态（admin） |
| POST | `/api/knowledge/upload` | **上传并向量化**（admin，PDF/TXT/DOCX，≤20MB） |
| GET | `/api/knowledge/list` | 文件列表（admin，支持 keyword） |
| GET | `/api/knowledge/detail/{id}` | 文件详情（admin） |
| GET | `/api/knowledge/download/{id}` | 下载原文件（admin） |
| DELETE | `/api/knowledge/delete/{id}` | 删除文件 + 向量 + 记录（admin） |
| GET | `/api/knowledge/search` | **向量检索**（所有登录用户，供 RAG 调用） |

---

## 五、冲稳保规则

设考生位次 `R`，院校专业最低录取位次 `M`，缓冲 `B`（默认 5000，可配 `RANK_BUFFER`）：

| 档位 | 判定 | 排序 | 概率区间 |
|---|---|---|---|
| 冲 | `R - 8B ≤ M < R - B` | 位次降序（越接近越有希望） | 10% – 40% |
| 稳 | `R - B ≤ M ≤ R + B` | 位次差绝对值升序 | 55% – 85% |
| 保 | `R + B < M ≤ R + 8B` | 位次升序（越稳妥越靠前） | 88% – 98% |

- 若某档在窗口内无结果，自动放宽窗口重新取数，保证三档都有内容
- 概率是**规则估算值**，用于排序与直观展示，不是官方录取概率
- 位次差 `rank_diff = M - R`：正数表示该专业往年位次比你低，更稳妥

---

## 六、数据维度的两个坑（已在 `app/models/dataset.py` 抹平）

1. **科类口径不同**：2025 是 `物理类 / 历史类`，2024 是 `理科 / 文科`；
   且 2024 的 `major_admission` / `school_admission` 表 `category` 列整列为空
   → 查 2024 录取表时**必须跳过 category 过滤**，否则结果为空。
2. **批次写法不同**：2024 录取表写 `本一 / 本二 / 专科`，招生计划与一分一段写
   `本科一批 / 本科二批 / 专科批`；2025 统一为 `本科批 / 专科批`
   → 统一按「新高考口径」传入，由 `resolve_batch()` 翻译成该表的真实取值。

另外：院校代码 / 专业代码在库里是 DOUBLE（pymysql 返回 `Decimal('2385.0000000000')`），
已在 `normalize_code()` 统一成 `2385`。

---

## 七、AI 集成与降级

- 模型：`qwen3:1.7b`（Ollama），配置见 `OLLAMA_MODEL`
- **意图解析**：少样本 Prompt 输出 JSON，解析失败或超时自动降级到关键词规则
  （`_rule_parse_intent`），响应里的 `source` 字段标明 `llm` 或 `rule`
- **推荐理由**：默认使用规则生成的理由（瞬时返回，含位次差、学费、计划人数）；
  需要时再调用大模型，不可用时自动回退规则文案，**推荐列表永远可用**
- **RAG 问答**：`/api/ai/chat` 传 `use_rag=true` 时先检索知识库片段，再拼进 Prompt 生成，
  返回 `answer` + `sources`（引用了哪些文档）
- 单次调用约 4–10 秒，批量生成采用线程池并发（`AI_MAX_WORKERS`）
- 设置 `AI_ENABLED=0` 可完全关闭 AI

---

## 八、3+1+2 选科与分数校验（考生端 `/volunteer`）

由 `frontend/src/views/student/Volunteer.vue` 实现（逻辑与旧版 `profile-form.js` 一致）：

- **普通类 / 艺术类 Tab**：顶部大分类，当前仅支持普通类（艺术类置灰提示）
- **考试地区**：当前仅河南，省份是后续扩展的最大分支
- **成绩类型**：本科 / 专科单选，决定「预估分数」可填区间
  - 本科：`1 - 750`（满分）
  - 专科：`1 - 本科线 - 1`（低于本科线的分数段，按年份科类动态计算）
    - 例：2025 河南 物理类 → 专科 `1 - 426`；2024 河南 理科 → 专科 `1 - 395`
- **高考科目（3+1+2）**：
  - 一行 6 个 pill：物理 / 化学 / 生物 / 政治 / 历史 / 地理
  - 物理和历史互斥，作为「首选科目」决定科类（2025 物理类/历史类，2024 理科/文科）
  - 化学 / 生物 / 政治 / 地理为「再选科目」，最多选 2 门；全部最多选 3 门
  - 再选科目作为 `filters.subject_selected` 传给推荐接口，按专业 `subject_req` 过滤
    （「再选不限」通过；「再选化学、生物(2科必选)」必须全部包含；含「或」任一命中即可）
- **自动换算**：填入分数 → 调 `/api/meta/score-check` → 自动填充位次、
  推荐填报批次（带「推荐」标签），并显示排名区间；均可手动修改
  - 已取消单独的「换算位次」按钮
- **区间校验**：分数不在当前成绩类型区间内时给出红字提示，不会错误换算
- **联动重算**：年份、首选科目、地区、批次、成绩类型任一变化都会重新换算
- **未过线提示**：分数低于本省最低批次线时提示各批次高考批次线
- 每次进入志愿填报页，分数 / 位次 / 批次 / 选科一律留空

---

## 九、RAG 知识库模块

### 9.1 链路

```
上传（PDF / TXT / DOCX）
  → save_upload_file：UUID 重命名落盘 knowledge_files/
  → extract_text：pypdf / python-docx / 纯文本
  → split_text：500 字切片、50 字重叠
  → get_embedding：Ollama nomic-embed-text（或 DashScope text-embedding-v3）
  → Chroma PersistentClient 写入集合 gaokao_knowledge
  → MySQL 回写 chunk_count / status = 已向量化

提问
  → /api/knowledge/search 检索 top_k 片段
  → /api/ai/chat 把片段拼进 Prompt → Qwen3 生成 → 返回 answer + sources
```

### 9.2 关键文件

| 文件 | 职责 |
|---|---|
| `backend/app/services/rag_service.py` | Chroma 客户端、embedding、切片写入、`search()`、`delete_by_file()` |
| `backend/app/utils/file_utils.py` | UUID 保存、文本提取、切片（500 / 50） |
| `backend/app/routers/knowledge.py` | upload / list / detail / download / delete / search / status |
| `backend/app/routers/auth.py` | JWT、bcrypt、`get_current_user` / `get_current_admin` |
| `frontend/src/views/admin/Knowledge.vue` | 管理端列表（文件名称 / 大小 / 上传时间 / 操作：详情、删除） |
| `frontend/src/components/UploadModal.vue` | 拖拽上传弹窗 |
| `frontend/src/views/student/AiChat.vue` | 考生端 RAG 问答（可开关知识库增强） |

### 9.3 建表 SQL（`backend/sql/04_rag_tables.sql`）

```sql
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('admin', 'student') DEFAULT 'student',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE knowledge_files (
    id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255) NOT NULL,   -- UUID 重命名后的文件名
    file_path VARCHAR(500) NOT NULL,
    file_type VARCHAR(20),                   -- pdf / txt / docx
    file_size INT,
    upload_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    chunk_count INT DEFAULT 0,               -- 切分后的片段数
    status VARCHAR(50) DEFAULT '已上传',      -- 已上传 / 已向量化 / 失败
    uploaded_by INT,
    FOREIGN KEY (uploaded_by) REFERENCES users(id)
);
```

### 9.4 权限与鉴权

- 密码：`passlib[bcrypt]`（bcrypt 锁 4.0.1）；JWT：`python-jose` HS256
- 依赖链：`OAuth2PasswordBearer → get_current_user（解析 JWT）→ get_current_admin（校验 role）`
- `/api/knowledge/upload|list|detail|download|delete|status` 仅 admin（非 admin → 403，无 Token → 401）
- `/api/knowledge/search` 对所有登录用户开放（考生端 AI 助手调用）
- 前端 `router.beforeEach` 校验 `meta.requiresAdmin`，非管理员跳 `/login`

### 9.5 切换向量库 / embedding

- 迁移 Milvus：只需替换 `rag_service.py` 中的集合读写函数（客户端、写入、检索、删除）
- 切换千问官方 embedding：在 `.env` 填 `DASHSCOPE_API_KEY`，`get_embedding()` 会优先走 DashScope
- Ollama 不可用时 `search()` 自动退化为关键词匹配，链路不中断

### 9.6 上传安全

- 文件类型白名单：`.pdf` / `.txt` / `.docx`
- UUID 重命名落盘，避免文件名冲突与路径遍历
- 单文件上限 20MB
- 删除时同时清理：磁盘文件 + MySQL 记录 + Chroma 向量

---

## 十、联调用例

### 志愿推荐

输入：**河南 · 2025 · 物理类 · 本科批 · 611 分**

- 位次换算：`/api/score-to-rank?score=611` → `rank = 34569`（省控线 427，线差 +184）
- 推荐：`POST /api/recommend` → 冲 / 稳 / 保 三档，规则理由立即返回
- 示例结果：稳档 `北京建筑大学 计算机科学与技术`，最低位次 34569，位次差 0，概率 70%
- AI 理由：`POST /api/ai/recommend-reason` → 约 4 秒返回 60 字以内文案

### RAG 问答（`python smoke_rag.py` 实测）

```
login: admin & student ok
no token search: 401          # 未登录拦截
student list: 403             # 学生访问管理接口被拒
student search: 200           # 检索对登录用户开放
upload: 200 上传并向量化成功 chunk_count = 2
search hits: 2                # 命中原文片段
chat: 200 source = rag+llm sources = ['河南志愿填报指南.txt']
delete: 200 已删除 → list / search 归零
```

---

## 十一、常见问题排查

| 现象 | 原因 / 处理 |
|---|---|
| npm install 报 `ECONNREFUSED 127.0.0.1:7890` | `~/.npmrc` 里的代理未启动，用 `npm install --userconfig .npmrc.local` |
| `AttributeError: module 'bcrypt'` / passlib 报错 | bcrypt 版本过高，安装 `bcrypt==4.0.1` |
| 端口 8000 被占用 | `netstat -ano \| findstr :8000` 找到 PID 后 `taskkill /PID <PID> /F` |
| `/admin/knowledge` 刷新后 404 | 后端未构建 dist 或未启用 SPA 回退；开发模式请用 5173 端口 |
| 上传成功但检索为空 | 检查 Ollama 是否运行、`ollama pull nomic-embed-text` 是否完成；可看 `/api/knowledge/status` |
| 回答没有引用知识库 | `/api/ai/chat` 需传 `use_rag=true`，且当前用户已登录 |
| 推荐结果为空 | 确认科类 / 批次与年份匹配（2024 用理科/文科，2025 用物理类/历史类） |

---

## 十二、注意事项

- `major_admission` 表的 `min_score / min_rank` 是**专业组投档线**粒度，不是单个专业精确线，
  结果仅供演示，正式使用应替换为官方投档表。
- 数据集没有「双一流」独立字段，目前以 `985 / 211` 近似。
- 位次优先于分数：分数每年波动，位次才是硬通货。
- 首次启动会自动为 4 类表补 `(category, batch, min_rank)` 索引（幂等）。
- 考生信息与「我的志愿表」保存在浏览器 localStorage / sessionStorage，不入库。
- `knowledge_files/` 与 `chroma_db/` 已在 `.gitignore` 中排除，不会提交到仓库。
- 旧版原生前端已归档到 `frontend/_legacy/`，当前前端为 Vue3 + TypeScript。
