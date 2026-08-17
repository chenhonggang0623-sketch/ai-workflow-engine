# API Layer (Epic 9) — Report

**Status:** DONE

## Files Created

| File | Description |
|------|-------------|
| `app/api/__init__.py` | Exports router |
| `app/api/routes/__init__.py` | Aggregates all sub-routers with proper prefixes |
| `app/api/routes/workflows.py` | Workflow CRUD + `/execute` endpoint |
| `app/api/routes/executions.py` | Execution GET/logs/pause/resume/cancel |
| `app/api/routes/agents.py` | Agent register/list/get/delete |
| `app/api/routes/planner.py` | Plan generation/confirm/templates |
| `app/api/routes/artifacts.py` | Artifact CRUD + upload/download |
| `app/api/routes/contracts.py` | Contract CRUD + accept/complete/fail/dispute |
| `app/api/routes/supervisor.py` | Quality gates, execution report, evaluations |
| `app/api/websocket/__init__.py` | Package init |
| `app/api/websocket/handlers.py` | WebSocket connection manager + handlers |

## Files Modified

| File | Change |
|------|--------|
| `app/main.py` | Added `app.state.execution_manager`/`llm_gateway`/`tool_registry`; included WebSocket routes |
| `app/artifact/manager.py` | Fixed missing `await` on `self.db.delete()` (line 128) |
| `tests/conftest.py` | Fixed `mock_db.delete` from `MagicMock` → `AsyncMock` |

## Routes Implemented

```
GET    /api/workflows              — List workflows
POST   /api/workflows              — Create workflow
GET    /api/workflows/{id}         — Get workflow
PUT    /api/workflows/{id}         — Update workflow
DELETE /api/workflows/{id}         — Delete workflow
POST   /api/workflows/{id}/execute — Execute workflow (async)

GET    /api/executions/{id}        — Get execution detail
GET    /api/executions/{id}/logs   — Execution logs
GET    /api/executions/{id}/nodes  — Node execution details
POST   /api/executions/{id}/pause  — Pause
POST   /api/executions/{id}/resume — Resume
POST   /api/executions/{id}/cancel — Cancel

GET    /api/agents                 — List agents
POST   /api/agents                 — Register agent
GET    /api/agents/{id}            — Get agent
DELETE /api/agents/{id}            — Unregister

POST   /api/planner/plan           — Generate plan from requirement
POST   /api/planner/confirm        — Confirm plan and execute
GET    /api/planner/templates      — List template categories

GET    /api/artifacts              — List artifacts
GET    /api/artifacts/{id}         — Get artifact detail
GET    /api/artifacts/{id}/download— Download content
POST   /api/artifacts              — Upload (multipart)
DELETE /api/artifacts/{id}         — Delete

GET    /api/contracts              — List contracts
GET    /api/contracts/{id}         — Get contract
POST   /api/contracts/{id}/accept  — Accept
POST   /api/contracts/{id}/complete— Complete with result
POST   /api/contracts/{id}/fail    — Fail
POST   /api/contracts/{id}/dispute — Dispute

GET    /api/executions/{id}/gates  — Quality gate status
GET    /api/executions/{id}/report — Execution report
GET    /api/evaluations            — Get evaluations

WS     /ws/executions/{id}         — Real-time execution logs
WS     /ws/agent-messages/{id}     — Real-time agent messages
```

## Test Summary

- **240/240 tests passing** (all 10 new API tests + 230 existing tests)
- Only pre-existing test failure fixed: `mock_db.delete` needed `AsyncMock`
- One pre-existing bug fixed: `ArtifactManager.delete()` had missing `await`
- Known: Redis is optional (lifespan catches init failure)

## Key Implementation Details

- **Stateless managers** (`ExecutionManager`, `LLMGateway`, `ToolRegistry`) stored in `app.state` at module level
- **DB-dependent managers** created per-request with injected `AsyncSession` via `get_db`
- Execution runs asynchronously via `asyncio.ensure_future`, returns `execution_id` immediately
- WebSocket uses a simple `ConnectionManager` with per-execution broadcast
- All routes use Pydantic response models from `app/schemas/`
- Error handling with `HTTPException` and proper status codes (400, 404, 204)

## Concerns

None.
