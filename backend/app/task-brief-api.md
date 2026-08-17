# Task: Implement API Layer (Epic 9)

## Files to create

### 1. `backend/app/api/__init__.py`
Export router

### 2. `backend/app/api/routes/__init__.py`
Main API router aggregating all sub-routers

### 3. `backend/app/api/routes/workflows.py` — Workflow CRUD + Execute

```
GET    /api/workflows              — List all workflows
POST   /api/workflows              — Create workflow
GET    /api/workflows/{id}         — Get workflow detail
PUT    /api/workflows/{id}         — Update workflow
DELETE /api/workflows/{id}         — Delete workflow

POST   /api/workflows/{id}/execute — Execute workflow (returns execution_id)
GET    /api/executions/{id}        — Get execution detail
GET    /api/executions/{id}/logs   — Get execution logs
POST   /api/executions/{id}/pause  — Pause execution
POST   /api/executions/{id}/resume — Resume execution
POST   /api/executions/{id}/cancel — Cancel execution
```

Use WorkflowCreate/WorkflowUpdate/WorkflowResponse from schemas.
Use ExecutionManager for execution control.

### 4. `backend/app/api/routes/agents.py` — Agent Management

```
GET    /api/agents              — List agents
POST   /api/agents              — Register agent
GET    /api/agents/{id}         — Get agent detail
DELETE /api/agents/{id}         — Unregister agent
```

Use AgentRegistry.

### 5. `backend/app/api/routes/planner.py` — Planner

```
POST   /api/planner/plan        — Generate workflow plan from requirement
POST   /api/planner/confirm     — Confirm and execute plan
GET    /api/planner/templates   — List available templates
```

Use PlannerAgent.

### 6. `backend/app/api/routes/artifacts.py` — Artifact

```
GET    /api/artifacts           — List artifacts
GET    /api/artifacts/{id}      — Get artifact detail
GET    /api/artifacts/{id}/download — Download artifact content
POST   /api/artifacts           — Upload artifact
DELETE /api/artifacts/{id}      — Delete artifact
```

Use ArtifactManager.

### 7. `backend/app/api/routes/contracts.py` — Contracts

```
GET    /api/contracts                     — List contracts
GET    /api/contracts/{id}                — Get contract detail
POST   /api/contracts/{id}/accept         — Accept contract
POST   /api/contracts/{id}/complete       — Complete with result
POST   /api/contracts/{id}/fail           — Fail contract
POST   /api/contracts/{id}/dispute        — Dispute evaluation
```

Use ContractManager.

### 8. `backend/app/api/routes/supervisor.py` — Supervisor/Evaluation

```
GET    /api/executions/{id}/gates     — Get quality gate status
GET    /api/executions/{id}/report    — Get execution report
GET    /api/evaluations?agent_id=     — Get evaluations
```

Use Orchestrator and EvaluationEngine.

### 9. `backend/app/api/websocket/__init__.py`

### 10. `backend/app/api/websocket/handlers.py` — WebSocket

```
WS /ws/executions/{execution_id}     — Real-time execution logs
WS /ws/agent-messages/{execution_id} — Real-time agent messages
```

### 11. Update `backend/app/main.py`
Include all routers, register WebSocket handlers.

## Important Implementation Details

Each route handler should:
1. Get DB session from dependency
2. Instantiate the required manager/service (or get from app.state)
3. Return proper response models
4. Handle errors with HTTPException

For the app.state pattern, in main.py lifespan, create instances of all managers and store them:

```python
# In lifespan
from app.agent.registry import AgentRegistry
from app.engine.execution_manager import ExecutionManager
# ... etc

app.state.agent_registry = AgentRegistry(...)
app.state.execution_manager = ExecutionManager(...)
```

Then routes access via `request.app.state.agent_registry`.

## Constraints
- Use FastAPI dependency injection for DB sessions
- All responses use Pydantic response models
- WebSocket sends JSON messages
- Proper error handling with HTTPException and proper status codes
- Async throughout

## Files that already exist:
- `app/main.py` — app entry point
- `app/schemas/workflow.py` — WorkflowCreate, WorkflowUpdate, WorkflowResponse, etc.
- `app/schemas/agent.py` — AgentCreate, AgentResponse
- `app/schemas/artifact.py` — ArtifactResponse
- `app/schemas/contract.py` — ContractCreate, ContractResponse
- `app/schemas/evaluation.py` — EvaluationResponse
- `app/schemas/planner.py` — PlanRequest, PlanResponse, PlanConfirm
- `app/core/db.py` — get_db
- `app/core/config.py` — settings

## Output
- Status: DONE / DONE_WITH_CONCERNS / BLOCKED
- Report file: `backend/app/task-brief-api-report.md`
- Test output: test all routes with httpx AsyncClient
