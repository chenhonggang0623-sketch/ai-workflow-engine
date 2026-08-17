# AI Workflow Engine

Automated software development platform: describe a requirement, and the engine
turns it into a blueprint → multi-node DAG → executes each node with local CLI
agents, with a live progress view and human-in-the-loop intervention.

把需求描述直接变成可执行工作流：需求 → 蓝图 → 多节点 DAG → 本地 CLI Agent 逐节点执行，
带实时进度视图与人工干预。

---

## ✨ Features / 特性

- **Requirement → Blueprint → DAG** — complexity-aware planning that breaks a
  requirement into modules and a multi-node execution graph.
  需求 → 蓝图 → DAG：按复杂度拆解为多模块多节点的执行图。
- **Single default provider** — every planned node runs on the configured
  default provider (`opencode_cli` by default), no matter how many API keys you
  have; change any node's provider right in the DAG editor.
  单默认 Provider：规划出的所有节点统一走默认执行器（默认 opencode_cli），
  无论配置了多少 key；DAG 编辑器中可随时按节点切换。
- **Click-to-configure DAG** — click a node to view its system prompt and
  provider, tweak the prompt or switch the provider before running.
  点击即配置：点击节点查看/修改 Prompt 与 Provider。
- **Live execution view** — real-time node status, slow-node detection and
  intervention (keep waiting / switch model / terminate).
  实时执行视图：节点状态实时刷新，慢节点自动提示干预（继续等待 / 切换模型 / 终止）。
- **Skill injection** — methodology skills are injected into each node's
  workspace so agents follow proven workflows (TDD, code review, etc.).
  Skill 注入：按节点职责注入方法论技能（TDD、代码审查等）。
- **Contract alignment** — LLM-hallucinated mapping keys are rebuilt against the
  blueprint's input/output contracts deterministically.
  契约对齐：LLM 编造的映射键按蓝图契约确定性重建。
- **Planner fallback** — if the LLM is unavailable, a local heuristic planner
  still produces a valid multi-node workflow (works fully offline).
  Planner 兜底：LLM 不可用时本地启发式规划仍可生成合法多节点工作流（可完全离线）。

---

## 🏗 Architecture / 架构

```
Requirement
   │
   ▼
┌─────────────────────┐
│ PlannerAgent        │  ComplexityAnalyzer / Architect / RequirementAnalyzer
│ (LLM  + fallback)   │  SkillRegistry + workspace.inject_skills
└─────────────────────┘
   │ blueprint + DAG (nodes/edges/mappings)
   ▼
┌─────────────────────┐
│ ExecutionManager    │  node_runner → provider executors
│ (slow detection,    │    opencode_cli / claude_cli / codex_cli / openai / ensemble
│  intervention)      │  replan_coordinator (auto-retry / revise)
└─────────────────────┘
   │ context store (PostgreSQL + Redis + Qdrant)
   ▼
 Frontend (Next.js): create → DAG editor → live view → results
```

```
backend/app/
├── planner/          # complexity, requirement, architect, planner_agent, fallback
├── engine/           # execution_manager, node_runner, replan, prompt_factory
├── agent/            # registry, provider executors (CLI / API / ensemble)
├── skills/           # skill registry + catalog
├── api/              # FastAPI routes (workflows, executions, plans…)
├── models/           # SQLAlchemy models
├── core/             # settings, config
└── planner/workspace.py  # project scaffolding + skill injection
frontend/src/
├── app/workflows/    # create (generate + configure) / [id] (detail + DAG editor)
├── app/executions/   # live view, node status, intervention
└── components/       # WorkflowDAG, AgentConfigDialog
```

---

## 🚀 Quick Start / 快速开始

### Prerequisites / 前置依赖

- Docker (PostgreSQL 16, Redis 7, Qdrant)
- Python ≥ 3.11
- Node.js ≥ 18
- At least one local CLI agent available: `opencode` (default) and/or `claude`, `codex`

### Setup / 安装

```bash
cp backend/.env.example backend/.env   # then edit keys if you have any
./start.sh
```

`start.sh` starts Docker services, installs backend + frontend deps, runs
migrations, then launches:

- Backend API: http://localhost:8000  (docs at `/docs`)
- Frontend UI: http://localhost:8080

Then open http://localhost:8080 → **+ New Project** → paste a requirement →
**Generate Workflow Plan** → click nodes to adjust provider/prompt →
**Confirm & Execute** → watch the live DAG.

```bash
./start.sh   # 一键启动：Docker 依赖 + 后端 + 前端
```

### Configuration / 配置（backend/.env）

| Key | Default | Description / 说明 |
|---|---|---|
| `OPENAI_API_KEY` | *(empty)* | Optional cloud LLM key for planning (not required — fallback planner works offline) |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `DEFAULT_LLM_MODEL` | `gpt-4o-mini` | Planner model |
| `AGENT_DEFAULT_PROVIDER` | `opencode_cli` | Default executor for every planned node |
| `OPENCODE_PATH` | `opencode` | Local OpenCode CLI binary |
| `CLAUDE_CODE_PATH` | `claude` | Claude Code CLI binary |
| `CODEX_PATH` | `codex` | Codex CLI binary |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/ai_workflow` | PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `SLOW_NODE_AFTER_SECONDS` | `300` | Seconds before a node is flagged slow (intervention prompt) |

### Run tests / 运行测试

```bash
cd backend
python3 -m pytest tests/ -q    # 439 tests
cd ../frontend && npx tsc --noEmit && npx next build
```

---

## 🧭 Usage Flow / 使用流程

1. **New Project** — paste a requirement (Chinese or English) and optional constraints.
2. **Generate** — engine scores complexity, builds the blueprint and a multi-node DAG;
   every node defaults to `AGENT_DEFAULT_PROVIDER`.
3. **Configure** — click any node in the DAG: view the full system prompt, switch the
   provider (openai / opencode_cli / claude_cli / codex_cli / local_model / ensemble),
   or rewrite the prompt.
4. **Execute** — each node runs with its own prompt/task on the same provider;
   skill bodies are injected into the node workspace.
5. **Intervene** — if a node runs slow, the live view offers: keep waiting,
   switch model (provider + model), or terminate.

1. **新建项目** — 输入需求（中英文均可）与可选约束。
2. **生成规划** — 引擎评估复杂度，产出蓝图与多节点 DAG；所有节点默认 `AGENT_DEFAULT_PROVIDER`。
3. **配置节点** — 点击 DAG 中任意节点：查看完整 Prompt、切换 Provider
   （openai / opencode_cli / claude_cli / codex_cli / local_model / ensemble）或改写 Prompt。
4. **执行** — 各节点在统一 Provider 上按各自任务/Prompt 执行；技能正文注入节点工作区。
5. **干预** — 节点变慢时实时视图提供：继续等待 / 切换模型（Provider + model）/ 终止。

---

## 🗂 Project Structure / 目录结构

```
├── backend/            # FastAPI + SQLAlchemy + planner + engine
│   ├── app/
│   ├── tests/          # 439 tests
│   └── pyproject.toml
├── frontend/           # Next.js console
├── skills/             # methodology skills (TDD, code review, …)
├── docs/               # design docs (EN + 中文)
├── docker-compose.yml  # postgres / redis / qdrant
├── start.sh            # one-command launch
└── test.sh
```

---

## 📄 Docs / 文档

See [docs/](docs/) for detailed design documents (planner pipeline, engine,
contracts, MCP, evaluation — EN & 中文).

---

## License / 许可证

Not specified. Contact the owner for usage terms.
未指定，如需商用请与作者联系。