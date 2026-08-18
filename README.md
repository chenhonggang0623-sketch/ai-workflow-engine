# AI Workflow Engine

> **[中文版 README](README.zh-CN.md)**

Automated software development platform: describe a requirement, and the engine
turns it into a blueprint → multi-node DAG → executes each node with local CLI
agents, with a live progress view and human-in-the-loop intervention.

## Features

- **Requirement → Blueprint → DAG** — complexity-aware planning that breaks a
  requirement into modules and a multi-node execution graph.
- **Single default provider** — every planned node runs on the configured
  default provider (`opencode_cli` by default), no matter how many API keys you
  have; change any node's provider right in the DAG editor.
- **Click-to-configure DAG** — click a node to view its system prompt and
  provider, tweak the prompt or switch the provider before running.
- **Live execution view** — real-time node status, slow-node detection and
  intervention (keep waiting / switch model / terminate).
- **Skill injection** — methodology skills are injected into each node's
  workspace so agents follow proven workflows (TDD, code review, etc.).
- **Contract alignment** — LLM-hallucinated mapping keys are rebuilt against the
  blueprint's input/output contracts deterministically.
- **Planner fallback** — if the LLM is unavailable, a local heuristic planner
  still produces a valid multi-node workflow (works fully offline).

## Architecture

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

## Quick Start

### Prerequisites

- Docker (PostgreSQL 16, Redis 7, Qdrant)
- Python ≥ 3.11
- Node.js ≥ 18
- At least one local CLI agent available: `opencode` (default) and/or `claude`, `codex`

### Setup

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

### Configuration (`backend/.env`)

| Key | Default | Description |
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

### Run tests

```bash
cd backend
python3 -m pytest tests/ -q    # 444 tests (2026-08-18 full app-load verified)
cd ../frontend && npx tsc --noEmit && npx next build
```

## Usage Flow

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

## Project Structure

```
├── backend/            # FastAPI + SQLAlchemy + planner + engine
│   ├── app/
│   ├── tests/          # 444 tests
│   └── pyproject.toml
├── frontend/           # Next.js console
├── skills/             # methodology skills (TDD, code review, …)
├── docs/               # design docs (EN)
├── docker-compose.yml  # postgres / redis
├── start.sh            # one-command launch
└── test.sh
```

## Docs

See [docs/](docs/) for detailed design documents (planner pipeline, engine,
contracts, MCP, evaluation).

## License

Not specified. Contact the owner for usage terms.