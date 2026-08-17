# AI Agent Workflow Engine — MVP Implementation Plan

## Goal
用户输入一句需求 → Planner 自动生成 Workflow → Engine 调度多个 Agent 完成软件项目

## Epics & Dependencies

```
Epic 1: Project Foundation (无依赖)
  ├── pyproject.toml / requirements.txt
  ├── Docker Compose (PG + Redis + Qdrant)
  ├── Core config + database connection
  └── SQLAlchemy models (all tables)

Epic 2: Workflow Engine (依赖 Epic 1)
  ├── Workflow definition models (Pydantic)
  ├── DAG Scheduler
  ├── Node Runner (Agent/Tool/Condition/Loop/Human)
  ├── State Machine
  └── Execution Manager

Epic 3: Context + Artifact (依赖 Epic 1)
  ├── Context Manager
  ├── Artifact Manager
  └── Storage adapter

Epic 4: Agent Runtime (依赖 Epic 1)
  ├── Agent Registry
  ├── LLM Gateway
  ├── Prompt Template Engine
  └── Agent Executor

Epic 5: Task Contract + Comm (依赖 Epic 3, 4)
  ├── Contract Manager
  ├── Contract Lifecycle
  ├── Communication Broker
  └── Agent Comm Client

Epic 6: Evaluation + Supervisor (依赖 Epic 4, 5)
  ├── Evaluation Engine
  ├── Quality Gate
  ├── Recovery Manager
  └── Supervisor Orchestrator

Epic 7: Planner Agent (依赖 Epic 2, 4)
  ├── Planner Agent logic
  ├── Template library
  └── Planning Review Layer

Epic 8: MCP Tool System (依赖 Epic 1)
  ├── MCP Bridge
  ├── Tool Executor
  └── Tool Registry

Epic 9: API Layer + Integration (依赖 All)
  ├── FastAPI routes
  ├── WebSocket handlers
  ├── API schemas
  └── Integration tests
```

## Implementation Order

```
Week 1: Epic 1 → Epic 2 → Epic 3
Week 2: Epic 4 → Epic 5 → Epic 6
Week 3: Epic 7 → Epic 8 → Epic 9
```

## MVP Scope Reduction

For MVP, some V3 features are simplified:
- Evaluation: 3 dimensions (completeness/correctness/efficiency) instead of 6
- Artifact: no lifecycle state machine, just store + retrieve
- Multi-project: not in scope
- Cost control: not in scope
- Planning Review: basic complexity check only
