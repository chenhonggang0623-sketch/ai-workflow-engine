# Blueprint Pipeline — Requirements → PRD → Blueprint → DAG Architecture Design

## 1. Background and Goals

The current MVP execution chain is `User Requirements → PlannerAgent → DAG → Execution`, which has four structural problems:

| # | Problem | Consequence |
|---|---------|-------------|
| 1 | Vague requirements go directly into the LLM to generate a DAG | DAG quality depends on a single prompt; no requirement clarification stage |
| 2 | No architecture planning layer | No single authoritative record of module layout, tech stack, or interface contracts |
| 3 | DAG is generated from requirements rather than architecture | Node responsibilities lack constraints; data flow between nodes has no contract |
| 4 | Only node-level retry after failure | No cascading replan; cannot "start over with a different approach", and decisions cannot be handed back to the user |

This document defines the pipeline redesign: **Requirements → PRD → Blueprint → DAG**, plus the **cascading replan loop** on execution failure.

### Confirmed Decisions

1. **Failure loop strategy**: automatically regenerate a new DAG is allowed; if the replan loop still fails to resolve the issue after more than **3** attempts, execution pauses and is set to `blocked`, and the problem with decision options is thrown back to the user.
2. **Blueprint persistence + versioning**: The blueprint is persisted; each revision creates a new version (`version+1`), and the old version is marked `superseded` and kept.

## 2. Overall Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                        Planning Pipeline (规划期)                    │
│                                                                    │
│  用户需求 ──①RequirementAnalyzer──> PRD ──②Architect──> Blueprint vN │
│                                                                    │
│                                                      ┌───────────┐ │
│   Blueprint ──③PlannerAgent──> DAG vN ──> 执行 ──────▶ 质量结果      │ │
│                                                    └─────┬─────┘   │
│                                                          │失败      │
│                 ┌────────────────────────────────────────┘          │
│                 ▼                                                   │
│        重规划循环（上限 3 次）: Architect.revise(Blueprint vN+1)       │
│              └──> PlannerAgent(DAG vN+1) ──> 重新执行                 │
│                 │                                                    │
│                 仍失败 ──> Execution.status = blocked                │
│                              └──> 写入 ExecutionDecision ──> 用户决策 │
└────────────────────────────────────────────────────────────────────┘
```

### Hierarchical Responsibilities

| Layer | Module | Input | Output | Authority |
|-------|--------|-------|--------|-----------|
| Requirements layer | `requirement_analyzer.py` | Vague user requirements | Structured PRD | The single source of requirement definition |
| Architecture layer | `architect.py` | PRD | Blueprint vN (persisted) | The single source of architecture decisions (single source of truth) |
| Orchestration layer | `planner_agent.py` (modified) | Blueprint | DAG vN | The single source of execution plans (constrained by the blueprint) |
| Execution layer | `engine/` (unchanged) | DAG vN | Execution result | Unchanged |
| Replan layer | `replan_coordinator.py` | Failure result + blueprint | blocked / new blueprint+DAG | Arbitrator of failure convergence |

## 3. Data Models

### 3.1 New `blueprints` table (versioned)

```
blueprints
  id                  UUID PK
  workflow_id         UUID FK → workflows.id        (nullable; null during the plan phase, backfilled after confirm)
  source_execution_id UUID FK → executions.id       (the execution that triggered this blueprint creation; nullable)
  version             Integer default 1             (version number, +1 per revision)
  status              String default "active"       (active / superseded)
  content             JSON                          (blueprint content, see 3.3)
  created_at          DateTime
```

- Multiple generations of the same logical blueprint: `status=active` always has exactly one record (the latest); on revision, the old version is set to `superseded`.
- Associations: `workflow_id` points to the workflow this blueprint currently serves; `source_execution_id` records "which failed execution gave birth to this version".

### 3.2 Table structure changes

- Add column `replan_count Integer default 0` — the number of cascading replans that have been executed — to `executions`.

### 3.3 New `execution_decisions` table (decision slips thrown back to the user)

```
execution_decisions
  id              UUID PK
  execution_id    UUID FK → executions.id   NOT NULL
  reason          Text                      (failure cause summary)
  attempts        Integer default 3         (replan attempts consumed)
  options         JSON                      (["retry","revise_blueprint","abandon"])
  blueprint       JSON                      (current blueprint snapshot, for user revision)
  workflow        JSON                      (current DAG snapshot)
  status          String default "pending"  (pending / resolved)
  resolved_action String
  resolved_at     DateTime
  created_at      DateTime
```

### 3.4 Blueprint content structure (`content`)

```jsonc
{
  "prd": {
    "summary": "一句话目标",
    "goals": ["业务目标"],
    "features": ["功能清单"],
    "non_functional": ["非功能需求"],
    "acceptance_criteria": ["验收标准"],
    "assumptions": ["假设"],
    "open_questions": ["未决疑问"]
  },
  "architecture": {
    "tech_stack": ["技术栈"],
    "directory_structure": ["目录布局"],
    "data_model": ["数据实体"],
    "api_contracts": ["接口契约"]
  },
  "modules": [
    {
      "id": "唯一模块 id",
      "name": "模块名",
      "description": "职责",
      "depends_on": ["依赖的模块 id"],
      "input_contract": ["允许的输入字段"],
      "output_contract": ["承诺的输出字段"]
    }
  ],
  "constraints": ["蓝图约束，如：所有代码必须遵守模块划分；技术栈必须为 X"]
}
```

## 4. Module Design

### 4.1 Requirement analysis layer `app/planner/requirement_analyzer.py` (new)

```python
class RequirementAnalyzer:
    def __init__(self, llm_gateway): ...
    async def analyze(self, requirement: str) -> dict:  # → PRD dict
```

- Flow: the LLM generates a structured PRD (`REQUIREMENT_PROMPT`) → on parsing failure, fall back to **keyword fallback** (reuse the `ComplexityAnalyzer` heuristic: generate a basic PRD by length/keywords), guaranteeing usability even without an API key.
- Same fault-tolerance philosophy as the existing `PlannerAgent._build_fallback_workflow`.

### 4.2 Architecture planning layer `app/planner/architect.py` (new)

```python
class Architect:
    def __init__(self, llm_gateway): ...
    async def design(self, prd: dict) -> dict:          # PRD → Blueprint dict
    async def revise(self, blueprint: dict, failure: str,
                     extra_context: dict | None = None) -> dict:  # blueprint revision → new content
    async def save(self, content: dict, db, *,
                   workflow_id=None, source_execution_id=None) -> Blueprint  # persist + version
```

- `design`: the LLM generates module layout, tech stack, data model, interface contracts, and constraints from the PRD; on failure falls back to **template module splitting** (split by feature keywords: auth/user/admin etc.).
- `revise`: injects the previous execution's failure cause (failed node + error message + relevant context) into the prompt, requiring adjustments to the module layout or contracts; likewise has a fallback.
- `save`: within a transaction, find the workflow's active blueprint → set the old version to `superseded` → insert a new `version+1` record.

### 4.3 Orchestration layer changes `app/planner/planner_agent.py`

- `plan(requirement, constraints)` internally becomes a three-stage pipeline: `RequirementAnalyzer.analyze → Architect.design/save → generate_dag(blueprint)`.
- New `generate_dag(blueprint: dict) -> dict`: takes a blueprint, outputs DAG JSON. `PLAN_PROMPT` is rewritten as "expand by blueprint modules":
  - each blueprint module → at least one node; node `config.module_id` must be the module id;
  - node input/output mappings must be taken from the module's contract fields;
  - the DAG must cover all blueprint modules;
  - nodes with the same `module_id` can be serially split into an "implement → self-test" two-step.
- `plan()` return value extended: add `blueprint` (including id/version/content) for frontend display and the confirm association.

### 4.4 Blueprint consistency review `app/planner/planning_review.py` (upgraded)

Keep the existing structure checks (a cycle-free/unique/size/single-root-single-terminal), add a static method:

```python
@staticmethod
def review_against_blueprint(workflow: dict, blueprint: dict) -> dict:
    # 1. coverage: every blueprint module has at least one node (by config.module_id)
    # 2. compliance: agent nodes must have module_id, and module_id must exist in the blueprint
    # 3. data flow: node input/output mapping field names ⊆ that module's contract
    # returns {"approved": bool, "warnings": [...], "suggestions": [...]}
```

- When `approved=False`, PlannerAgent rejects the DAG and regenerates it (consistent with existing cycles handling).

### 4.5 Replan coordinator `app/planner/replan_coordinator.py` (new)

```python
MAX_REPLAN = 3

class ReplanCoordinator:
    def __init__(self, planner, architect, analyzer,
                 exec_mgr, db_factory): ...

    async def run(self, *, requirement, blueprint, workflow_def,
                  execution_id, project_path) -> dict:
        for attempt in range(MAX_REPLAN + 1):
            result = await exec_mgr.execute_workflow(workflow_def, execution_id,
                                                     db_factory, initial_context={...})
            if result.status == SUCCEEDED:
                return {success payload...}
            if result.status in (CANCELLED, PAUSED):
                return {return as-is...}
            if attempt >= MAX_REPLAN:
                return self._block(execution_id, result, blueprint, workflow_def)
            # cascading replan
            blueprint_content = await architect.revise(blueprint, failure_reason)
            blueprint = await architect.save(blueprint_content, source_execution_id=execution_id)
            workflow_def = await planner.generate_dag(blueprint_content)
            workflow_def = inject_workspace(workflow_def, project_path)   # keep the same workspace
            replan_count += 1
```

Key rules:

1. **Same execution instance continues**: no new Execution record is created; `replan_count` increments; DAG node ids get a `_r{n}` suffix to distinguish replan generations (naturally traceable via NodeExecution).
2. **Workspace preserved**: after a replan, the same `project_path` keeps being injected, and the previous round's artifacts are kept as context (the `context` includes historical results).
3. **Failure cause injected**: the input to `architect.revise` includes the failed node id, the error/secondary report, and the produced-ahead context snapshot.
4. **Threshold**: `replan_count >= 3` still failing → set `blocked` + write `execution_decisions`.

### 4.6 State and semantics

- `ExecutionStatus` enum gains value `BLOCKED = "blocked"` (engine/types.py).
- blocked semantics: the execution is permanently paused awaiting user adjudication; it is not a terminal state (distinct from FAILED — the user can still resume execution from it).

## 5. API Design

### 5.1 Modifications

| Endpoint | Change |
|----------|--------|
| `POST /api/planner/plan` | Response adds `blueprint` field: `{id, version, content}` |
| `POST /api/planner/confirm` | Request adds optional `blueprint_id`; after creating the workflow, backfill the blueprint association; execution switches to `ReplanCoordinator.run` |

### 5.2 New endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/blueprints/{workflow_id}` | The workflow's latest active blueprint (with version-list summary) |
| `GET /api/blueprints/{workflow_id}/versions` | All versions of the blueprint |
| `POST /api/blueprints/{blueprint_id}/revise` | body: `{feedback}` → generates a new blueprint version (manual revision entry; does not auto-re-execute) |
| `GET /api/executions/{id}/decision` | The execution's pending decision (returned when blocked) |
| `POST /api/executions/{id}/resolve` | body: `{action, feedback?, blueprint?}`, action ∈ retry / revise_blueprint / abandon |

### 5.3 resolve semantics

| action | Behavior |
|--------|----------|
| `retry` | Re-execute with the current blueprint + current DAG (replan_count reset to 0), workspace preserved |
| `revise_blueprint` | User submits a revised blueprint content (or feedback for the Architect to revise) → generate a new version → regenerate the DAG → re-execute |
| `abandon` | execution set to `cancelled`, decision set to `resolved`, pipeline terminated |

## 6. Frontend Design

### 6.1 Workflow detail page (`workflows/[id]/page.tsx`)

- Add a **Blueprint** tab: shows the PRD summary, module list (with dependency relations), interface contracts, constraint list, version number shown as `v{n}`.

### 6.2 Execution detail page (`executions/[id]/page.tsx`)

- `blocked` status highlighted (red).
- Polling detects blocked → show the **decision panel** (overlay):
  - failure cause (from decision.reason)
  - three buttons: retry the current plan / modify the blueprint and re-run (opens an editable blueprint JSON text area, or leaves a feedback text area) / abandon
  - after submission, call `POST /api/executions/{id}/resolve` and refresh the page.

## 7. Implementation order

| Step | Content | Verification |
|------|---------|--------------|
| 1 | Data layer: Blueprint / ExecutionDecision models + Execution.replan_count + create_all registration | `test_blueprint_models.py` |
| 2 | PRD layer: RequirementAnalyzer (LLM + fallback) | `test_requirement_analyzer.py` |
| 3 | Blueprint layer: Architect (design/revise/save, versioning) | `test_architect.py` |
| 4 | DAG generation changes + blueprint-consistency validation | `test_planning_review_blueprint.py`, `test_planner.py` updated |
| 5 | Replan coordinator + blocked + resolve API + ExecutionStatus.BLOCKED | `test_replan_coordinator.py`, `test_api.py` updated |
| 6 | Frontend Blueprint tab + decision panel | `npm run lint`, `npm run build` |
| 7 | End-to-end integration verification (extending test.sh) | the full pytest suite + manual page walk-through |

## 8. Testing Strategy

- Unit tests use the pytest-asyncio auto mode; all LLM calls are covered with `FakeLLM`/keyword-fallback paths and do not depend on real APIs.
- Replan coordinator key test points:
  - success path: first execution succeeds → no replan triggered;
  - fails once then succeeds on the 2nd attempt → replan_count=1, final status succeeded;
  - 3 consecutive failures → blocked + decision persisted;
  - can execute again after resolve=retry;
  - blueprint versioning: every revise generates version+1, the old version is superseded.
- Blueprint-consistency validation key test points: uncovered module / non-existent module_id / contract fields out-of-bounds → validation rejects.

## 9. Risks and Trade-offs

| Risk | Mitigation |
|------|------------|
| LLM-generated blueprints are unstable | keyword fallback + blueprint-consistency validation as a failsafe; validation failures bounce back for regeneration |
| Replan loses progress | workspace preserved + same execution continued + generation node-id suffixes |
| Decision panel blocks the user too much | triggered only after 3 automated replans; otherwise fully automatic |
| Excessive freedom in blueprint editing | the revise branch of resolve still passes PlanningReview.review_against_blueprint |
