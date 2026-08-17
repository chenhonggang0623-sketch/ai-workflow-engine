# AI Workflow Engine

> **[English README](README.md)**

自动化软件开发平台：输入需求描述，引擎将其转化为蓝图 → 多节点 DAG → 由本地 CLI Agent
逐节点执行，并提供实时进度视图与人工干预能力。

## 特性

- **需求 → 蓝图 → DAG**：按复杂度感知规划，将需求拆解为多模块、多节点的执行图。
- **单默认 Provider**：无论配置了多少 API key，规划出的所有节点统一走默认执行器
  （默认 `opencode_cli`）；可在 DAG 编辑器中随时按节点切换。
- **点击即配置 DAG**：点击节点即可查看完整 System Prompt 与 Provider，
  运行前可改写 Prompt 或切换 Provider。
- **实时执行视图**：节点状态实时刷新，慢节点自动提示干预
  （继续等待 / 切换模型 / 终止任务）。
- **Skill 注入**：按节点职责自动注入方法论技能（TDD、代码审查等），
  让 Agent 遵循经过验证的工作流程。
- **契约对齐**：LLM 编造的映射键按蓝图 input/output 契约确定性重建。
- **Planner 兜底**：LLM 不可用时，本地启发式规划器仍能生成合法的多节点工作流
  （可完全离线运行）。

## 架构

```
需求输入
   │
   ▼
┌─────────────────────┐
│ PlannerAgent        │  ComplexityAnalyzer / Architect / RequirementAnalyzer
│ (LLM + fallback)    │  SkillRegistry + workspace.inject_skills
└─────────────────────┘
   │ 蓝图 + DAG（节点/边/映射）
   ▼
┌─────────────────────┐
│ ExecutionManager    │  node_runner → provider executors
│ (慢节点检测、干预)   │    opencode_cli / claude_cli / codex_cli / openai / ensemble
│                     │  replan_coordinator（自动重试 / 修订）
└─────────────────────┘
   │ 上下文存储（PostgreSQL + Redis + Qdrant）
   ▼
 前端（Next.js）：创建 → DAG 编辑器 → 实时视图 → 结果
```

```
backend/app/
├── planner/          # 复杂度分析、需求分析、架构师、planner_agent、fallback
├── engine/           # execution_manager、node_runner、replan、prompt_factory
├── agent/            # 注册表、provider 执行器（CLI / API / ensemble）
├── skills/           # 技能注册表与目录
├── api/              # FastAPI 路由（workflows、executions、plans…）
├── models/           # SQLAlchemy 模型
├── core/             # 配置
└── planner/workspace.py  # 项目脚手架 + skill 注入
frontend/src/
├── app/workflows/    # create（生成 + 配置）/ [id]（详情 + DAG 编辑器）
├── app/executions/   # 实时视图、节点状态、干预
└── components/       # WorkflowDAG、AgentConfigDialog
```

## 快速开始

### 前置依赖

- Docker（PostgreSQL 16、Redis 7、Qdrant）
- Python ≥ 3.11
- Node.js ≥ 18
- 至少一个本地 CLI Agent：`opencode`（默认）和/或 `claude`、`codex`

### 安装启动

```bash
cp backend/.env.example backend/.env   # 如有 key 可编辑
./start.sh
```

`start.sh` 会启动 Docker 服务、安装前后端依赖、执行迁移，然后启动：

- 后端 API：http://localhost:8000 （接口文档 `/docs`）
- 前端 UI：http://localhost:8080

打开 http://localhost:8080 → **+ New Project** → 粘贴需求 → **Generate Workflow Plan**
→ 点击节点调整 Provider/Prompt → **Confirm & Execute** → 查看实时 DAG。

### 配置（`backend/.env`）

| Key | 默认值 | 说明 |
|---|---|---|
| `OPENAI_API_KEY` | *（空）* | 可选：云端 LLM key 用于规划（非必需——fallback 可离线规划） |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容端点 |
| `DEFAULT_LLM_MODEL` | `gpt-4o-mini` | 规划器模型 |
| `AGENT_DEFAULT_PROVIDER` | `opencode_cli` | 所有规划节点的默认执行器 |
| `OPENCODE_PATH` | `opencode` | 本地 OpenCode CLI 可执行文件 |
| `CLAUDE_CODE_PATH` | `claude` | Claude Code CLI 可执行文件 |
| `CODEX_PATH` | `codex` | Codex CLI 可执行文件 |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/ai_workflow` | PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `SLOW_NODE_AFTER_SECONDS` | `300` | 节点运行多少秒后标记为慢（触发干预提示） |

### 运行测试

```bash
cd backend
python3 -m pytest tests/ -q    # 439 个测试
cd ../frontend && npx tsc --noEmit && npx next build
```

## 使用流程

1. **新建项目** — 输入需求（中英文均可）与可选约束。
2. **生成规划** — 引擎评估复杂度，产出蓝图与多节点 DAG；所有节点默认
   `AGENT_DEFAULT_PROVIDER`。
3. **配置节点** — 点击 DAG 中任意节点：查看完整 System Prompt、切换 Provider
   （openai / opencode_cli / claude_cli / codex_cli / local_model / ensemble）
   或改写 Prompt。
4. **执行** — 各节点在统一 Provider 上按各自任务/Prompt 执行；技能正文注入节点工作区。
5. **干预** — 节点变慢时实时视图提供：继续等待 / 切换模型（Provider + model）/ 终止。

## 项目结构

```
├── backend/            # FastAPI + SQLAlchemy + planner + engine
│   ├── app/
│   ├── tests/          # 439 个测试
│   └── pyproject.toml
├── frontend/           # Next.js 控制台
├── skills/             # 方法论技能（TDD、代码审查…）
├── docs/               # 设计文档（中英双语）
├── docker-compose.yml  # postgres / redis / qdrant
├── start.sh            # 一键启动
└── test.sh
```

## 文档

详见 [docs/](docs/) 中的设计文档（规划管线、引擎、契约、MCP、评测）。

## 许可证

未指定，如需商用请与作者联系。