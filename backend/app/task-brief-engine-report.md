# Task: Workflow Engine — Task Brief Report

## Status
**DONE**

## Files Created/Modified

### `backend/app/engine/scheduler.py`
- `DAGScheduler` class built on `networkx.DiGraph`
- Computes in-degree per node, tracks completed nodes
- `get_ready_nodes()` — returns nodes with in-degree 0 and not completed
- `mark_completed(node_id)` — marks node done, decrements downstream in-degrees, returns newly-ready nodes
- `is_complete()` — all nodes finished
- `get_execution_order()` — topological layers for parallel execution
- `has_cycle()` — cycle detection via `nx.topological_sort`

### `backend/app/engine/state_machine.py`
- `ExecutionStateMachine` — lifecycle: PENDING → RUNNING ⇄ PAUSED → SUCCEEDED | FAILED | CANCELLED
- `NodeStateMachine` — lifecycle: PENDING → READY → RUNNING → (WAITING) → SUCCEEDED | FAILED
- Both validate state transitions at each call, raising `RuntimeError` on invalid transitions
- `get_progress()` returns completed/total/pct

### `backend/app/engine/node_runner.py`
- `NodeRunner` dispatches by `NodeType`:
  - `AGENT` → simulates agent execution
  - `TOOL` → simulates tool execution
  - `CONDITION` → evaluates expression against context via `eval()`
  - `LOOP` → returns iteration config
  - `HUMAN` → returns awaiting_input status
  - `PLANNER` → simulates planning
- Input mapping: extracts values from context via JSONPath (`$.foo.bar`)
- Output mapping: writes node outputs into context at JSONPath targets
- Retry logic: configurable `max_retries` + `backoff_seconds`
- Timeout handling via `asyncio.wait_for`

### `backend/app/engine/execution_manager.py`
- `ExecutionManager` ties scheduler + state machine + node runner
- Main loop: validate DAG → init state machine → parallel execution via `asyncio.gather` with `Semaphore` (default max_concurrency=5)
- Cancellation via `asyncio.Event`
- Pause/resume/cancel by execution ID
- Context propagation through output mappings between nodes

### `backend/app/engine/__init__.py`
- Updated exports: added `NodeStateMachine`, `ExecutionManager`

### `backend/tests/test_scheduler.py` (7 tests)
- get_ready_nodes initial, mark_completed, is_complete, execution_order, cycle detection, partial completion

### `backend/tests/test_state_machine.py` (19 tests)
- ExecutionStateMachine: all transitions, error states, progress tracking
- NodeStateMachine: all transitions, ready/start/wait/succeed/fail/retry, error states

### `backend/tests/test_node_runner.py` (13 tests)
- All 6 node types, input/output mapping, timeout, retry, unknown type

### `backend/tests/test_execution_manager.py` (12 tests)
- Linear workflow, diamond workflow, empty workflow, single node, cyclic rejection
- Pause/resume lifecycle, cancel, get_status, not-found errors, context propagation

## Test Output

```
tests/test_scheduler.py::test_get_ready_nodes_initial PASSED           [  1%]
tests/test_scheduler.py::test_mark_completed PASSED                    [  3%]
tests/test_scheduler.py::test_is_complete PASSED                       [  5%]
tests/test_scheduler.py::test_get_execution_order PASSED               [  7%]
tests/test_scheduler.py::test_has_cycle PASSED                         [  9%]
tests/test_scheduler.py::test_no_cycle PASSED                          [ 11%]
tests/test_scheduler.py::test_ready_nodes_after_partial_completion PASSED [ 13%]
tests/test_state_machine.py::TestExecutionStateMachine::test_initial_state PASSED [ 15%]
tests/test_state_machine.py::TestExecutionStateMachine::test_start PASSED [ 17%]
tests/test_state_machine.py::TestExecutionStateMachine::test_start_from_running_raises PASSED [ 19%]
tests/test_state_machine.py::TestExecutionStateMachine::test_pause_and_resume PASSED [ 20%]
tests/test_state_machine.py::TestExecutionStateMachine::test_pause_from_pending_raises PASSED [ 22%]
tests/test_state_machine.py::TestExecutionStateMachine::test_cancel PASSED [ 24%]
tests/test_state_machine.py::TestExecutionStateMachine::test_fail PASSED [ 26%]
tests/test_state_machine.py::TestExecutionStateMachine::test_succeed PASSED [ 28%]
tests/test_state_machine.py::TestExecutionStateMachine::test_succeed_from_pending_raises PASSED [ 30%]
tests/test_state_machine.py::TestExecutionStateMachine::test_cancel_from_terminal_raises PASSED [ 31%]
tests/test_state_machine.py::TestExecutionStateMachine::test_get_progress PASSED [ 33%]
tests/test_state_machine.py::TestExecutionStateMachine::test_is_terminal PASSED [ 35%]
tests/test_state_machine.py::TestNodeStateMachine::test_initial_state PASSED [ 37%]
tests/test_state_machine.py::TestNodeStateMachine::test_mark_ready PASSED [ 39%]
tests/test_state_machine.py::TestNodeStateMachine::test_mark_ready_from_ready_raises PASSED [ 41%]
tests/test_state_machine.py::TestNodeStateMachine::test_start PASSED     [ 43%]
tests/test_state_machine.py::TestNodeStateMachine::test_start_from_pending_raises PASSED [ 44%]
tests/test_state_machine.py::TestNodeStateMachine::test_wait PASSED      [ 46%]
tests/test_state_machine.py::TestNodeStateMachine::test_succeed PASSED   [ 48%]
tests/test_state_machine.py::TestNodeStateMachine::test_fail PASSED      [ 50%]
tests/test_state_machine.py::TestNodeStateMachine::test_retry PASSED     [ 52%]
tests/test_state_machine.py::TestNodeStateMachine::test_retry_from_success_raises PASSED [ 54%]
tests/test_state_machine.py::TestNodeStateMachine::test_fail_from_pending_raises PASSED [ 56%]
tests/test_node_runner.py::test_agent_node PASSED                        [ 57%]
tests/test_node_runner.py::test_tool_node PASSED                         [ 59%]
tests/test_node_runner.py::test_condition_node PASSED                    [ 61%]
tests/test_node_runner.py::test_condition_node_false PASSED              [ 63%]
tests/test_node_runner.py::test_loop_node PASSED                         [ 64%]
tests/test_node_runner.py::test_human_node PASSED                        [ 66%]
tests/test_node_runner.py::test_planner_node PASSED                      [ 68%]
tests/test_node_runner.py::test_input_mapping PASSED                     [ 70%]
tests/test_node_runner.py::test_output_mapping PASSED                    [ 72%]
tests/test_node_runner.py::test_timeout PASSED                           [ 74%]
tests/test_node_runner.py::test_retry_then_succeed PASSED                [ 75%]
tests/test_node_runner.py::test_unknown_node_type PASSED                 [ 77%]
tests/test_execution_manager.py::test_execute_linear_workflow PASSED     [ 79%]
tests/test_execution_manager.py::test_execute_diamond_workflow PASSED    [ 81%]
tests/test_execution_manager.py::test_execute_empty_workflow PASSED      [ 83%]
tests/test_execution_manager.py::test_execute_single_node PASSED         [ 85%]
tests/test_execution_manager.py::test_cyclic_workflow_raises PASSED      [ 87%]
tests/test_execution_manager.py::test_pause_and_resume PASSED            [ 88%]
tests/test_execution_manager.py::test_pause_resume_lifecycle PASSED      [ 90%]
tests/test_execution_manager.py::test_cancel PASSED                      [ 92%]
tests/test_execution_manager.py::test_get_status PASSED                  [ 94%]
tests/test_execution_manager.py::test_get_status_not_found PASSED        [ 96%]
tests/test_execution_manager.py::test_pause_not_found PASSED             [ 98%]
tests/test_execution_manager.py::test_context_propagation PASSED         [100%]

======================= 54 passed in 1.49s =======================
```

## Concerns
1. **`datetime.utcnow()` deprecation** — Python 3.14 warns about `utcnow()`. The task spec explicitly says to use `datetime.utcnow()`, so kept as-is. Should migrate to `datetime.now(datetime.UTC)` when the spec allows.
2. **Condition node uses `eval()`** — functional for the engine, but `eval` with user-supplied expressions is a security concern. For production, replace with a sandboxed expression parser (e.g., a restricted DSL or `asteval`).
3. **Node handlers are stubs** — `AGENT`, `TOOL`, `PLANNER` handlers use `asyncio.sleep(0.05)` sims. These need real integrations with AgentRuntime, ToolExecutor, etc. in a follow-up.
4. **No DB persistence** — `ExecutionManager` works purely in-memory. Persisting states via the ORM models (`Execution`, `NodeExecution`) is a separate epic.
5. **Race condition on pause** — The execution loop polls `sm.status == PAUSED` with a sleep. A proper async wait/notify pattern would be more responsive.
