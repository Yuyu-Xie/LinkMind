# LinkMind

个人知识研究 Agent 平台。用户在本地书签库里提出研究问题，系统规划子问题、多轮调用工具收集证据、生成带引用的报告，并对整个过程做进度持久化、失败恢复和离线评测。

后端书签域参考 [linkding](https://github.com/sissbruecker/linkding)，在此基础上增加研究任务、证据链、异步执行与评测。

## 功能

- **Research Agent**：两阶段执行（规划 → 研究循环），支持网页检索、书签检索、正文读取、证据提取、主张建立、子问题回答、终止判断 7 个工具
- **证据链**：任务 → 子问题 → 来源 → 证据 → 主张 → 报告，主张与来源双向可追溯
- **异步执行**：DRF API + Huey + Redis，数据库租约 + Redis 分布式锁，超时、重试、崩溃恢复
- **失败恢复**：空检索改写、工具参数错误回传、重复调用缓存、无进展检测、取消、SSRF 防护
- **系统评测**：11 篇本地语料 + 10 道固定问题，对比 BM25 基线与 Agent 的完成率、引用准确率、Token、耗时

## 技术栈

| 层 | 选型 |
| --- | --- |
| Web | Django 6.1、Django REST Framework 3.18 |
| 数据库 | PostgreSQL 18（psycopg 3） |
| 队列 | Huey 3.4（RedisHuey）+ Redis 7 兼容服务 Memurai |
| 模型 | DeepSeek `deepseek-chat`（OpenAI 兼容接口） |
| 前端 | Django 模板 + HTMX 2.0，无 Node 构建 |
| 正文提取 | trafilatura、BeautifulSoup、lxml |
| 报告渲染 | markdown + bleach |
| 测试 | pytest、pytest-django、ruff |

## 目录结构

```
LinkMind/
├── config/settings/          # base / dev / prod
├── bookmarks/                # 书签、标签、正文缓存
│   ├── services/             # URL 规范化、合并、正文提取、检索
│   └── api/                  # DRF ViewSet
├── research/
│   ├── agent/                # LLM 客户端、上下文构建、提示词、Fake 客户端
│   ├── tools/                # 7 个 Agent 工具 + 注册表
│   ├── services/             # runner、报告、恢复、锁、网页检索
│   ├── api/                  # 研究任务 API
│   └── tasks.py              # Huey 任务入口与定时 sweeper
├── evaluation/
│   ├── data/corpus/          # 11 篇本地语料
│   ├── data/datasets/        # linkmind_v1.json，10 道题
│   └── services/             # BM25、指标、策略、评测运行器
├── scripts/                  # start_pg.bat、start_redis.bat、dev.bat
├── templates/  static/
└── pyproject.toml
```

## 快速开始

本项目在 Windows 11 上开发和验证，运行时目录为 `D:\app\linkmind-runtime`（虚拟环境、PostgreSQL 数据、Memurai、日志）。

### 1. 启动依赖

```bat
scripts\start_pg.bat
scripts\start_redis.bat
```

验证：

```bat
D:\app\linkmind-runtime\pg-env\Library\bin\pg_isready.exe -h 127.0.0.1 -p 5432
D:\app\linkmind-runtime\Memurai\Memurai\memurai-cli.exe ping
```

### 2. 安装依赖

```bat
D:\app\linkmind-runtime\venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env`，填入 `DEEPSEEK_API_KEY`。Key 只从环境读取，不写入代码，`.env` 已在 `.gitignore` 中。

### 4. 初始化数据库

```bat
set PYTHONUTF8=1
D:\app\linkmind-runtime\venv\Scripts\python.exe manage.py migrate
D:\app\linkmind-runtime\venv\Scripts\python.exe manage.py seed_demo
D:\app\linkmind-runtime\venv\Scripts\python.exe manage.py seed_eval_corpus --fresh
```

`seed_demo` 创建账号 `demo` / `linkmind123`，写入 6 条带本地正文的书签。

### 5. 启动服务

```bat
scripts\dev.bat
```

该脚本在新窗口启动 Huey 消费者，并在当前窗口启动 Django。也可以分开执行：

```bat
D:\app\linkmind-runtime\venv\Scripts\python.exe manage.py run_huey --logfile D:\app\linkmind-runtime\logs\huey.log
D:\app\linkmind-runtime\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

访问 `http://127.0.0.1:8000/`，用 `demo` 登录。

### 6. 不经过队列执行一个任务

```bat
D:\app\linkmind-runtime\venv\Scripts\python.exe manage.py run_research --user demo --offline ^
  --question "PostgreSQL 的 B-tree、GIN、BRIN 索引分别适合什么场景？"
```

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | `change-me-in-production` | 生产环境必须替换 |
| `DATABASE_URL` | `postgresql://linkmind:linkmind@127.0.0.1:5432/linkmind` | 数据库连接 |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Huey 与任务锁共用 |
| `DEEPSEEK_API_KEY` | 空 | 必填，缺失时任务直接 failed 并给出提示 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `DEEPSEEK_TIMEOUT` | `90` | 单次请求超时（秒） |
| `WEB_SEARCH_PROVIDER` | `bing` | `bing` / `tavily` / `off` |
| `TAVILY_API_KEY` | 空 | 仅 `tavily` 后端需要 |
| `RESEARCH_MAX_STEPS` | `12` | 单任务最大思考轮数 |
| `RESEARCH_BUDGET_TOKENS` | `60000` | 单任务 Token 预算 |
| `RESEARCH_TIMEOUT_SECONDS` | `600` | 单任务截止时间 |
| `RESEARCH_LEASE_SECONDS` | `300` | 租约时长，需大于单次 LLM 重试总耗时 |

## 数据模型

书签域：

| 模型 | 关键字段 |
| --- | --- |
| `Tag` | `name`、`owner`，`Lower(name)` 唯一 |
| `Bookmark` | `url`、`url_normalized`、`title`、`description`、`notes`、`unread`、`is_archived`、`tags`；同 URL 重复创建走合并更新 |
| `DocumentContent` | 与书签一对一，缓存正文、抓取状态、内容哈希 |

研究域：

| 模型 | 作用 |
| --- | --- |
| `ResearchTask` | 问题、策略、状态、阶段、预算、截止时间、租约、尝试次数、Token 统计 |
| `SubQuestion` | 规划产出的子问题，状态 `pending/in_progress/answered/insufficient` |
| `Source` | 来源快照，`unique(task, source_key)`，正文按需 `defer` |
| `Evidence` | 证据引文，保存时校验引文能在来源正文中定位，记录 `char_start/char_end` |
| `Claim` | 主张，按 `(task, normalized_hash)` 去重，状态随证据关系变化 |
| `ClaimEvidence` | 主张与证据的支持/反驳关系 |
| `Report` | 与任务一对一，`version` 递增，`citations` 与 `validation` 落 JSON |
| `AgentStep` | 执行日志：thought、tool_call、tool_result、error，`unique(task, step_no)` |
| `TaskEvent` | 状态审计：迁移、重试、恢复、取消，只追加 |
| `LLMUsage` | 每次模型调用的 prompt/completion/cached token 与耗时 |
| `ToolCallCache` | `(task, tool_name, args_hash)` 去重，命中标记 `reused` |

## 任务状态机

```
pending → running → completed | failed | timed_out | canceled
running → pending     仅租约过期的崩溃恢复
failed  → pending     手动或自动重试
```

- 所有迁移经由 `transition()`：事务内 `select_for_update`，非法迁移抛 `ValueError`，同时写 `TaskEvent`
- `completed / timed_out / canceled` 是终态，重跑创建新任务
- `claim_task` 用条件更新 `WHERE status='pending'` 抢占，返回 0 行即跳过
- 租约 `lease_owner = host:pid:uuid`，每步续租；租约过期由每分钟一次的 sweeper 回收
- 重试延迟 15 / 45 / 135 秒，超过 `max_attempts` 标记 failed
- 取消由 API 写 `cancel_requested_at`，循环在每步和每次工具执行前检查

## Agent Runtime

### 规划

一次独立 LLM 调用（`response_format=json_object`）生成 2–5 个子问题，解析失败回退为单子问题。结果写入 `SubQuestion` 与 `plan_raw`。

### 研究循环

每轮：

1. 从数据库重建上下文（不累积历史消息）
2. 调用模型，最多执行 2 个工具调用
3. 持久化 thought / tool_call / tool_result
4. 续租、检查取消与截止时间、重算进度
5. 满足终止条件则退出

终止优先级：取消 → 超时 → 步数或 Token 预算 → `finish_research` 通过覆盖率检查 → 连续 6 步无进展 → 证据不足的部分完成。

### 上下文

每轮最多 3 条消息：

1. system：角色、研究规则、引用格式 `[e:<id>]`、把来源内容视为不可信数据
2. system：结构化状态（问题、子问题状态、主张、证据索引、最近 6 步、恢复提示、剩余预算）
3. user：要求选择下一步工具

证据按每个子问题 Top 2 + 全局 Top 8 截取，单条引文最多 300 字；工具输出硬截断 6 KB。

### 工具

| 工具 | 作用 | 约束 |
| --- | --- | --- |
| `search_bookmarks` | 本地书签检索 | 关键词 + 标签，返回摘要 |
| `web_search` | 网页检索 | Bing HTML 为主，Baidu 回退，Tavily 可选；离线模式禁用 |
| `read_document` | 读取来源正文 | 先查缓存，trafilatura 提取，分段返回 |
| `extract_evidence` | 截取证据 | 引文必须能在正文中定位，失败返回最接近片段 |
| `add_claim` | 建立主张 | 证据必须属于本任务 |
| `answer_subquestion` | 更新子问题 | 只能操作本任务子问题 |
| `finish_research` | 终止信号 | 先做覆盖率检查，未覆盖过多时返回错误让模型继续 |

工具参数用 Pydantic 校验，返回统一结构 `{"ok", "data", "error_code", "message", "hint"}`。

## 失败恢复

| 失败 | 处理 |
| --- | --- |
| 检索空结果 | 返回改写提示；同一查询最多 2 次；仍空则子问题标 `insufficient` |
| 检索网络错误 | 退避重试 2 次，仍失败返回结构化错误 |
| 重复工具调用 | `ToolCallCache` 命中，标记 `reused`，不重复执行 |
| 工具参数非法 | 错误回传模型；连续 3 次失败终止任务 |
| LLM 超时 / 429 / 5xx | 2 / 4 / 8 秒重试 3 次；耗尽后任务进入重试队列 |
| LLM 401 / 400 | 不重试，任务 failed，错误可见 |
| Worker 崩溃 | 租约过期后 sweeper 重置 pending 并重新入队 |
| 证据不足 | 报告单列未解决问题，任务 completed + partial |
| 连续无进展 | 注入恢复提示；累计 6 步无进展则收尾 |
| 用户取消 | 安全点转 canceled，保留已产生证据 |
| SSRF | 只允许 http/https，DNS 解析后拒绝内网与保留地址，逐跳校验重定向，响应体 2 MB |

## 引用与报告

- 模型只允许输出 `[e:<evidence_id>]`
- 后端正则解析，校验 ID 属于本任务；未知引用触发一次修复调用，仍失败则剔除并写入 `validation`
- 无有效引用时用模板生成证据清单式报告，任务仍可 completed + partial
- 页面先转义，再替换引用为上标链接，最后用 bleach 白名单清洗
- 引用可点击跳转到证据，再跳转到原始来源

## API

Token 认证，先 `POST /api/api-token-auth/` 获取 Token。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET / POST | `/api/bookmarks/` | 列表（`q`、`tags`）、创建 |
| GET / PATCH / DELETE | `/api/bookmarks/{id}/` | 详情、更新、删除 |
| GET / POST | `/api/research/tasks/` | 任务列表、创建（入队异步执行） |
| GET | `/api/research/tasks/{id}/` | 详情与计数 |
| POST | `/api/research/tasks/{id}/cancel/` | 请求取消 |
| POST | `/api/research/tasks/{id}/retry/` | 重试 failed 任务 |
| GET | `/api/research/tasks/{id}/steps/` | 执行步骤 |
| GET | `/api/research/tasks/{id}/events/` | 状态事件 |
| GET | `/api/research/tasks/{id}/subquestions/` | 子问题 |
| GET | `/api/research/tasks/{id}/sources/` | 来源 |
| GET | `/api/research/tasks/{id}/evidence/` | 证据 |
| GET | `/api/research/tasks/{id}/claims/` | 主张 |
| GET | `/api/research/tasks/{id}/report/` | 报告 |
| GET | `/api/research/tasks/{id}/usage/` | Token 用量 |

## 页面

| 路径 | 内容 |
| --- | --- |
| `/` | 书签数、任务统计、最近任务 |
| `/bookmarks/` | 搜索、标签过滤、新增，HTMX 局部刷新 |
| `/research/` | 任务列表、新建、取消、重试 |
| `/research/{id}/` | 状态、进度、子问题、Agent 时间线、证据、主张表、报告；每 2 秒轮询到终态 |
| `/research/claims/` | 跨任务的主张与证据 |
| `/evaluation/` | 评测运行与指标 |

## 系统评测

### 数据

- `evaluation/data/corpus/`：11 篇技术文档（PostgreSQL 索引与执行计划、MVCC、Redis 持久化与缓存模式、Django 异步任务与 ORM、RAG 与 Agent 设计、BM25、函数调用、HNSW）
- `evaluation/data/datasets/linkmind_v1.json`：10 道题，每题包含参考来源、参考证据（引文 + 关键事实，同义词用 `{"any": [...]}`）、参考答案

语料导入后属于 `demo` 用户，带 `eval-corpus` 标签；数据集计算 SHA256 并记录到评测运行。

### 策略

- **baseline**：问题原文对语料做 BM25 检索，固定取 Top 5 段落，建 Source 与 Evidence，单次 LLM 生成带引用的回答。无规划、无多步。
- **agent**：完整研究循环，`options={"offline": true}` 禁用网页检索。

两者共用报告落库、引用校验与指标计算。

### 指标

| 指标 | 定义 |
| --- | --- |
| 技术完成率 | completed 且报告非空且所有引用标记可解析 |
| 严格完成率 | 技术完成 + 引用 precision ≥ 0.8 + 关键事实覆盖率 ≥ 0.6 |
| 引用 precision | 正确引用 / 总引用；正确 = 引用属于本任务证据 + 来源 URL 在参考集 + 引文与参考引文匹配 |
| 引用 recall / F1 | 命中的参考证据 / 参考证据总数 |
| 引文匹配 | 字符二元组 Jaccard ≥ 0.7，或包含度 ≥ 0.8 |
| 主张支撑率 | 至少有一条支持证据的主张占比 |
| 关键事实覆盖率 | 归一化后出现在报告或已支撑主张中的关键事实占比 |
| Token | 所有 `LLMUsage` 之和，含规划、重试、报告 |
| 耗时 | `finished_at - started_at` |

### 运行

```bat
D:\app\linkmind-runtime\venv\Scripts\python.exe manage.py seed_eval_corpus --fresh
D:\app\linkmind-runtime\venv\Scripts\python.exe manage.py evaluate ^
  --dataset linkmind_v1 --strategies baseline,agent --runs 3 --output evaluation/results
```

固定 temperature=0、Top K 和预算；离线模式保证可复现。结果 JSON 写入 `evaluation/results/`，同时落 `EvaluationRun` 与 `EvaluationCaseResult`，可在 `/evaluation/` 查看。

## 测试

```bat
D:\app\linkmind-runtime\venv\Scripts\python.exe -m pytest
D:\app\linkmind-runtime\venv\Scripts\python.exe -m ruff check .
```

当前 29 个测试通过，覆盖状态机、证据引文定位、主张状态、取消与超时、引用校验、BM25、指标计算、评测输出、书签合并与 API 权限。

## 已知限制

- 中文书签检索用 `icontains`，没有启用 PostgreSQL 全文检索；语料规模下足够，数据量增大后需要 `tsvector`
- 网页检索依赖 Bing HTML 结构；结构变化时回退 Baidu，评测走离线语料
- `max_steps` 只统计思考轮次，工具调用不单独占用预算
- Huey 消费者为单进程双线程，任务级并发靠数据库租约与 Redis 锁控制
- Memurai 4.1 对应 Redis 7.2，Huey 的 hash-field TTL 锁不可用，任务锁改用 `SET NX EX` 实现

## 简历对应

| 简历条目 | 实现位置 |
| --- | --- |
| 基于大模型工具调用构建多步 Research Agent | `research/agent/`、`research/tools/`、`research/services/runner.py` |
| 研究任务与证据管理 | `research/models.py`、`research/services/report.py`、`research/api/` |
| DRF + Huey + Redis 异步任务系统 | `research/tasks.py`、`research/services/locking.py`、`research/api/views.py` |
| 上下文与失败恢复 | `research/agent/context.py`、`research/services/recovery.py`、`research/services/runner.py` |
| 固定问题与参考证据集的系统评测 | `evaluation/`、`evaluation/data/` |
