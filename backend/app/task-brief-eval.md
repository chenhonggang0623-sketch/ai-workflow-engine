# Task: Implement Evaluation + Supervisor Agent

## Files to create

### 1. `backend/app/supervisor/__init__.py`
Export: EvaluationEngine, QualityGate, RecoveryManager, SupervisorOrchestrator

### 2. `backend/app/supervisor/evaluation.py` — EvaluationEngine

```python
class EvaluationEngine:
    """
    Multi-dimensional scoring of Agent outputs.
    
    evaluate(agent_id, agent_output, expected_schema, criteria) → EvaluationResult
    
    3 dimensions (MVP simplified):
    - completeness (25%): output covers all required fields
    - correctness (40%): output is logically/technically correct
    - efficiency (35%): output is well-structured and efficient
    
    For MVP: use schema validation for completeness, LLM review for correctness/efficiency.
    If no LLM available, do basic schema validation only.
    
    get_agent_performance(agent_id) → aggregate stats
    calibrate(human_feedback, auto_eval) → adjust LLM evaluation bias
    """

    def __init__(self, db_session, llm_gateway=None): ...
    async def evaluate(self, agent_id: str, node_execution_id: UUID,
                        agent_output: dict, expected_schema: dict = None,
                        criteria: list[str] = None) -> EvaluationResult: ...
    async def evaluate_contract(self, contract_id: UUID, result: dict) -> EvaluationResult: ...
    async def get_agent_performance(self, agent_id: str) -> dict: ...
```

### 3. `backend/app/supervisor/quality_gate.py` — QualityGate

```python
class QualityGate:
    """
    Quality gates that check agent outputs before allowing them to proceed.
    
    Gate types (MVP):
    - "schema_validate": validate output against output_schema
    - "llm_review": LLM checks quality against criteria
    - "human_approve": pause and wait for human approval
    
    check(gate_config, agent_output, context) → GateResult(passed, score, feedback)
    """

    GATE_TYPES = {
        "schema_validate": {"description": "Validate output against schema"},
        "llm_review": {"description": "LLM quality review", "min_score": 0.7},
        "human_approve": {"description": "Human approval required"},
    }

    def __init__(self, evaluation_engine: EvaluationEngine): ...
    async def check(self, gate_type: str, config: dict,
                     agent_output: dict, context: dict) -> dict:
        """
        Returns: {"passed": bool, "score": float, "feedback": str}
        """
        ...

    async def check_contract(self, contract, result: dict) -> dict: ...
```

### 4. `backend/app/supervisor/recovery.py` — RecoveryManager

```python
class RecoveryManager:
    """
    Handles agent/contract failures with configurable strategies.
    
    Recovery strategies:
    - retry: re-execute with same config (exponential backoff)
    - replace: switch to alternative agent
    - skip: skip and continue
    - pause: wait for human intervention
    - modify_workflow: change the workflow (fallback to Planner)
    
    handle_failure(contract_id, error, strategy) → RecoveryAction
    """

    def __init__(self, contract_manager, agent_registry): ...
    async def handle_failure(self, contract_id: UUID, error: str,
                               strategy: str = "auto") -> dict:
        """
        Returns: {"action": "retry"|"replace"|"skip"|"pause", "detail": str}
        """
        ...

    async def retry(self, contract_id: UUID) -> None: ...
    async def replace_agent(self, contract_id: UUID, new_agent_id: str) -> None: ...
```

### 5. `backend/app/supervisor/orchestrator.py` — SupervisorOrchestrator

```python
class SupervisorOrchestrator:
    """
    High-level supervisor that coordinates the entire execution.
    
    supervise(execution_id) → manages workflow execution with quality control
    
    Workflow:
    1. Load execution and workflow definition
    2. For each node:
       a. Pre-check: verify dependencies, inject context
       b. Create contract for agent nodes
       c. Monitor execution (heartbeat, timeout)
       d. Post-check: run quality gate on output
       e. On failure: execute recovery strategy
    3. Track overall progress
    4. Generate execution report
    
    supervise_node(node_execution, context) → handles one node with quality gates
    get_progress(execution_id) → current execution status
    """

    def __init__(self, db_session, evaluation_engine, quality_gate,
                   recovery_manager, contract_manager, comm_broker,
                   agent_executor, context_manager, artifact_manager): ...
    async def supervise(self, execution_id: UUID) -> None: ...
    async def supervise_node(self, node_exec: dict, context: dict) -> dict: ...
    async def get_progress(self, execution_id: UUID) -> dict: ...
```

## Constraints
- For MVP: if LLM not available, gates fall back to schema validation only
- EvaluationEngine should handle the case where llm_gateway is None gracefully
- RecoveryManager's retry uses exponential backoff: 5s, 10s, 20s
- SupervisorOrchestrator should be usable as both a standalone class and called from ExecutionManager
- Models already exist: `app/models/evaluation.py`

## Output
- Status: DONE / DONE_WITH_CONCERNS / BLOCKED
- Report file: `backend/app/task-brief-eval-report.md`
- Test output summary
