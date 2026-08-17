# Task: Implement Workflow Engine

## Context
This is the core execution engine of the AI Workflow Engine platform. File at `backend/app/engine/types.py` already defines the base types: NodeType, NodeStatus, ExecutionStatus, NodeDefinition, EdgeDefinition, WorkflowDefinition, NodeResult, WorkflowResult, RetryConfig, NodeConfig, InputMapping, OutputMapping.

## Files to create/modify

### 1. `backend/app/engine/scheduler.py` — DAGScheduler
Class that schedules node execution based on DAG topology:

```python
class DAGScheduler:
    """
    Builds adjacency graph from edges, computes in-degree for each node.
    Provides: get_ready_nodes(), mark_completed(), is_complete(), get_execution_order()
    Uses networkx under the hood for topological sort and cycle detection.
    """

    def __init__(self, workflow: WorkflowDefinition): ...
    def get_ready_nodes(self) -> list[NodeDefinition]:
        """Returns nodes with in-degree 0 that haven't been executed."""
    def mark_completed(self, node_id: str) -> list[NodeDefinition]:
        """Marks node done, decrements downstream in-degrees, returns newly ready nodes."""
    def is_complete(self) -> bool: ...
    def get_execution_order(self) -> list[list[str]]:
        """Returns topological layers: [[n1,n2], [n3,n4,n5], ...] for parallel execution."""
    def has_cycle(self) -> bool: ...
```

### 2. `backend/app/engine/state_machine.py` — ExecutionStateMachine
Manages the lifecycle state of the entire execution and individual nodes:

```python
class ExecutionStateMachine:
    """
    States: PENDING → RUNNING → (PAUSED → RUNNING) → SUCCEEDED | FAILED | CANCELLED
    Methods: start(), pause(), resume(), cancel(), fail()
    Tracks: status, started_at, finished_at, progress (completed/total)
    """

    def __init__(self, execution_id: UUID): ...
    def start(self) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def cancel(self) -> None: ...
    def fail(self, reason: str) -> None: ...
    def is_terminal(self) -> bool: ...
    def get_progress(self) -> dict: ...

class NodeStateMachine:
    """
    States: PENDING → READY → RUNNING → (WAITING) → SUCCEEDED | FAILED
    Methods: mark_ready(), start(), wait(), succeed(output), fail(error), retry()
    Tracks: status, started_at, finished_at, retry_count, error
    """
```

### 3. `backend/app/engine/node_runner.py` — NodeRunner
Executes individual nodes by dispatching to the appropriate handler:

```python
class NodeRunner:
    """
    Routes node execution by type:
    - AGENT → AgentRuntime.execute()
    - TOOL → ToolExecutor.execute()
    - CONDITION → evaluate expression, activate branch
    - LOOP → re-schedule body nodes
    - HUMAN → create HumanTask, wait for input
    - PLANNER → PlannerAgent.plan()

    handle_node(node: NodeDefinition, context: dict, comm_broker) -> NodeResult
    Handles: input_mapping (extract from context), output_mapping (write to context),
             timeout, retry logic, error wrapping.
    """
```

### 4. `backend/app/engine/execution_manager.py` — ExecutionManager
High-level orchestrator that ties scheduler + state machine + node runner together:

```python
class ExecutionManager:
    """
    execute_workflow(workflow: WorkflowDefinition, initial_context: dict) -> WorkflowResult
    pause(execution_id) / resume(execution_id) / cancel(execution_id)
    get_status(execution_id) -> ExecutionStatus

    The main execute loop:
    1. Validate DAG (no cycles)
    2. Initialize state machine
    3. Loop: get_ready_nodes() → run in parallel → mark_completed → until complete
    4. Handle failures, retries, pauses
    """
```

## Constraints
- Use `asyncio` for parallel execution (asyncio.gather with semaphore)
- Use `datetime.utcnow()` for timestamps
- All errors should be caught and wrapped, never crash the scheduler
- The execution loop MUST support cancellation via asyncio.Event
- Default max_concurrency = 5
- Write to `backend/app/engine/__init__.py` to export all 4 classes

## Output
- Status: DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED
- Report file: `backend/app/task-brief-engine-report.md`
- Commits made
- Test output summary (pytest on engine tests)
