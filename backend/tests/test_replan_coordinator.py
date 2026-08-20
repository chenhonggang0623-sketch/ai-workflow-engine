import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.planner.replan_coordinator import ReplanCoordinator, MAX_REPLAN
from app.engine.types import (
    WorkflowDefinition,
    WorkflowResult,
    ExecutionStatus,
    NodeResult,
    NodeStatus,
)


def make_workflow_dict(n=2):
    return {
        "name": "wf",
        "description": "",
        "nodes": [
            {"id": f"n{i}", "type": "agent", "label": f"N{i}",
             "config": {"module_id": f"m{i}", "provider": "opencode_cli",
                        "executor_type": "local_cli", "system_prompt": "x"},
             "input_mapping": [], "output_mapping": []}
            for i in range(n)
        ],
        "edges": [{"source": "n0", "target": "n1"}],
    }


def make_result(status: ExecutionStatus, error: str | None = None) -> WorkflowResult:
    return WorkflowResult(
        execution_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        status=status,
        node_results=[
            NodeResult(node_id="n1", status=NodeStatus.FAILED, error=error or "boom")
        ] if status == ExecutionStatus.FAILED else [],
        context={"requirement": "req"},
    )


def make_result_with_recommendations() -> WorkflowResult:
    recs = [
        {"node_id": "n1", "critical_count": 2, "findings_count": 3, "reviewers": ["a"]},
    ]
    return WorkflowResult(
        execution_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        status=ExecutionStatus.SUCCEEDED,
        context={"requirement": "req", "_rerun_recommendations": recs},
        rerun_recommendations=recs,
    )


def make_db_factory(execution=None):
    session = MagicMock()
    session.get = AsyncMock(return_value=execution)
    session.commit = AsyncMock()

    def add_side_effect(obj):
        if not hasattr(obj, "id"):
            obj.id = uuid.uuid4()

    session.add = MagicMock(side_effect=add_side_effect)
    session.flush = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=session)
    return factory, session


def make_coordinator(exec_results, execution=None):
    exec_mgr = AsyncMock()
    exec_mgr.execute_workflow = AsyncMock(side_effect=exec_results)
    planner = AsyncMock()
    planner.generate_dag = AsyncMock(return_value=make_workflow_dict(3))
    architect = AsyncMock()
    architect.revise = AsyncMock(return_value={"modules": [{"id": "m0"}]})
    architect.save = AsyncMock()
    db_factory, session = make_db_factory(execution)
    coordinator = ReplanCoordinator(
        planner=planner,
        architect=architect,
        exec_mgr=exec_mgr,
        db_factory=db_factory,
        workspace_injector=lambda wf, path: wf,
    )
    return coordinator, exec_mgr, planner, architect, session


class TestReplanCoordinator:
    @pytest.mark.asyncio
    async def test_success_first_try_no_replan(self):
        execution = MagicMock()
        coordinator, exec_mgr, planner, architect, session = make_coordinator(
            [make_result(ExecutionStatus.SUCCEEDED)], execution
        )
        result = await coordinator.run(
            requirement="req",
            blueprint_content={"modules": []},
            workflow_definition=make_workflow_dict(),
            execution_id=uuid.uuid4(),
            project_path="/tmp/p",
        )
        assert result["status"] == "succeeded"
        assert result["replan_count"] == 0
        architect.revise.assert_not_called()
        assert execution.status == "succeeded"

    @pytest.mark.asyncio
    async def test_initial_context_injects_blueprint(self):
        """replan 执行必须把当前蓝图注入 initial_context，供方案节点组装 $.plan。"""
        execution = MagicMock()
        coordinator, exec_mgr, planner, architect, session = make_coordinator(
            [make_result(ExecutionStatus.SUCCEEDED)], execution
        )
        blueprint = {"modules": [{"id": "m1"}], "constraints": ["c1"]}
        await coordinator.run(
            requirement="req",
            blueprint_content=blueprint,
            workflow_definition=make_workflow_dict(),
            execution_id=uuid.uuid4(),
            project_path="/tmp/p",
        )
        _, kwargs = exec_mgr.execute_workflow.call_args
        ctx = kwargs["initial_context"]
        assert ctx["blueprint"] == blueprint
        assert ctx["requirement"] == "req"
        assert ctx["project_path"] == "/tmp/p"

    @pytest.mark.asyncio
    async def test_success_surfaces_rerun_recommendation_without_replan(self):
        execution = MagicMock()
        coordinator, exec_mgr, planner, architect, session = make_coordinator(
            [make_result_with_recommendations()], execution
        )
        result = await coordinator.run(
            requirement="req",
            blueprint_content={"modules": []},
            workflow_definition=make_workflow_dict(),
            execution_id=uuid.uuid4(),
            project_path="/tmp/p",
        )
        assert result["status"] == "succeeded"
        assert result["rerun_recommended"] is True
        assert result["rerun_recommendations"][0]["node_id"] == "n1"
        architect.revise.assert_not_called()
        planner.generate_dag.assert_not_called()
        assert execution.status == "succeeded"

    @pytest.mark.asyncio
    async def test_fail_then_succeed_replans_once(self):
        execution = MagicMock()
        coordinator, exec_mgr, planner, architect, session = make_coordinator(
            [make_result(ExecutionStatus.FAILED, "module m1 exploded"),
             make_result(ExecutionStatus.SUCCEEDED)],
            execution,
        )
        result = await coordinator.run(
            requirement="req",
            blueprint_content={"modules": [{"id": "m1"}]},
            workflow_definition=make_workflow_dict(),
            execution_id=uuid.uuid4(),
            project_path="/tmp/p",
        )
        assert result["status"] == "succeeded"
        assert result["replan_count"] == 1
        architect.revise.assert_awaited_once()
        planner.generate_dag.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_three_failures_blocks_and_writes_decision(self):
        execution = MagicMock()
        failure = make_result(ExecutionStatus.FAILED, "persistent issue")
        coordinator, exec_mgr, planner, architect, session = make_coordinator(
            [failure, failure, failure, failure], execution
        )
        result = await coordinator.run(
            requirement="req",
            blueprint_content={"modules": [{"id": "m1"}]},
            workflow_definition=make_workflow_dict(),
            execution_id=uuid.uuid4(),
            project_path="/tmp/p",
        )
        assert result["status"] == "blocked"
        assert result["replan_count"] == MAX_REPLAN
        assert result["reason"]
        # 4 次执行：第 1-3 次失败触发 replan，第 4 次失败触发 block
        assert exec_mgr.execute_workflow.await_count == MAX_REPLAN + 1
        assert architect.revise.await_count == MAX_REPLAN
        # execution 置 blocked
        assert execution.status == "blocked"
        # decision 落库
        assert session.add.called
        added = [c.args[0] for c in session.add.call_args_list if c.args]
        from app.models.blueprint import ExecutionDecision
        decision = next((o for o in added if isinstance(o, ExecutionDecision)), None)
        assert decision is not None
        assert decision.status == "pending"
        assert decision.options == ["retry", "revise_blueprint", "abandon"]

    @pytest.mark.asyncio
    async def test_cancelled_does_not_replan(self):
        execution = MagicMock()
        coordinator, exec_mgr, planner, architect, session = make_coordinator(
            [make_result(ExecutionStatus.CANCELLED)], execution
        )
        result = await coordinator.run(
            requirement="req",
            blueprint_content={"modules": []},
            workflow_definition=make_workflow_dict(),
            execution_id=uuid.uuid4(),
            project_path="/tmp/p",
        )
        assert result["status"] == "cancelled"
        architect.revise.assert_not_called()

    @pytest.mark.asyncio
    async def test_replan_applies_id_suffix_to_nodes(self):
        execution = MagicMock()
        coordinator, exec_mgr, planner, architect, session = make_coordinator(
            [make_result(ExecutionStatus.FAILED, "x"),
             make_result(ExecutionStatus.SUCCEEDED)],
            execution,
        )
        await coordinator.run(
            requirement="req",
            blueprint_content={"modules": []},
            workflow_definition=make_workflow_dict(2),
            execution_id=uuid.uuid4(),
            project_path="/tmp/p",
        )
        calls = exec_mgr.execute_workflow.await_args_list
        assert len(calls) == 2
        wf_def: WorkflowDefinition = calls[1].args[0]
        assert wf_def.nodes[0].id == "n0_r1"
        assert wf_def.nodes[1].id == "n1_r1"
        assert wf_def.edges[0].source == "n0_r1"
        assert wf_def.edges[0].target == "n1_r1"

    @pytest.mark.asyncio
    async def test_replan_crash_blocks_with_reason(self):
        execution = MagicMock()
        coordinator, exec_mgr, planner, architect, session = make_coordinator(
            [make_result(ExecutionStatus.FAILED, "x")], execution
        )
        planner.generate_dag = AsyncMock(side_effect=RuntimeError("planner crash"))
        result = await coordinator.run(
            requirement="req",
            blueprint_content={"modules": []},
            workflow_definition=make_workflow_dict(),
            execution_id=uuid.uuid4(),
            project_path="/tmp/p",
        )
        assert result["status"] == "blocked"
        assert "planner crash" in result["reason"]
