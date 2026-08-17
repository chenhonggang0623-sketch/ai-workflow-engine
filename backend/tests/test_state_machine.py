import pytest
from app.engine.state_machine import ExecutionStateMachine, NodeStateMachine
from app.engine.types import ExecutionStatus, NodeStatus


class TestExecutionStateMachine:
    def test_initial_state(self):
        sm = ExecutionStateMachine()
        assert sm.status == ExecutionStatus.PENDING
        assert sm.started_at is None
        assert sm.finished_at is None

    def test_start(self):
        sm = ExecutionStateMachine()
        sm.start(5)
        assert sm.status == ExecutionStatus.RUNNING
        assert sm.started_at is not None
        assert sm.total_count == 5

    def test_start_from_running_raises(self):
        sm = ExecutionStateMachine()
        sm.start(1)
        with pytest.raises(RuntimeError):
            sm.start(1)

    def test_pause_and_resume(self):
        sm = ExecutionStateMachine()
        sm.start(5)
        sm.pause()
        assert sm.status == ExecutionStatus.PAUSED
        sm.resume()
        assert sm.status == ExecutionStatus.RUNNING

    def test_pause_from_pending_raises(self):
        sm = ExecutionStateMachine()
        with pytest.raises(RuntimeError):
            sm.pause()

    def test_cancel(self):
        sm = ExecutionStateMachine()
        sm.start(5)
        sm.cancel()
        assert sm.status == ExecutionStatus.CANCELLED
        assert sm.finished_at is not None
        assert sm.is_terminal()

    def test_fail(self):
        sm = ExecutionStateMachine()
        sm.start(5)
        sm.fail("something broke")
        assert sm.status == ExecutionStatus.FAILED
        assert sm.error == "something broke"
        assert sm.is_terminal()

    def test_succeed(self):
        sm = ExecutionStateMachine()
        sm.start(5)
        sm.succeed()
        assert sm.status == ExecutionStatus.SUCCEEDED
        assert sm.is_terminal()

    def test_succeed_from_pending_raises(self):
        sm = ExecutionStateMachine()
        with pytest.raises(RuntimeError):
            sm.succeed()

    def test_cancel_from_terminal_raises(self):
        sm = ExecutionStateMachine()
        sm.start(1)
        sm.succeed()
        with pytest.raises(RuntimeError):
            sm.cancel()

    def test_get_progress(self):
        sm = ExecutionStateMachine()
        sm.start(10)
        sm.increment_progress()
        sm.increment_progress()
        progress = sm.get_progress()
        assert progress["completed"] == 2
        assert progress["total"] == 10
        assert progress["progress_pct"] == 20.0
        assert progress["status"] == "running"

    def test_is_terminal(self):
        sm = ExecutionStateMachine()
        assert sm.is_terminal() is False
        sm.start(1)
        sm.succeed()
        assert sm.is_terminal() is True


class TestNodeStateMachine:
    def test_initial_state(self):
        nsm = NodeStateMachine("node_1")
        assert nsm.status == NodeStatus.PENDING
        assert nsm.node_id == "node_1"

    def test_mark_ready(self):
        nsm = NodeStateMachine("n1")
        nsm.mark_ready()
        assert nsm.status == NodeStatus.READY

    def test_mark_ready_from_ready_raises(self):
        nsm = NodeStateMachine("n1")
        nsm.mark_ready()
        with pytest.raises(RuntimeError):
            nsm.mark_ready()

    def test_start(self):
        nsm = NodeStateMachine("n1")
        nsm.mark_ready()
        nsm.start()
        assert nsm.status == NodeStatus.RUNNING
        assert nsm.started_at is not None

    def test_start_from_pending_raises(self):
        nsm = NodeStateMachine("n1")
        with pytest.raises(RuntimeError):
            nsm.start()

    def test_wait(self):
        nsm = NodeStateMachine("n1")
        nsm.mark_ready()
        nsm.start()
        nsm.wait()
        assert nsm.status == NodeStatus.WAITING

    def test_succeed(self):
        nsm = NodeStateMachine("n1")
        nsm.mark_ready()
        nsm.start()
        result = nsm.succeed({"key": "val"})
        assert nsm.status == NodeStatus.SUCCEEDED
        assert result.status == NodeStatus.SUCCEEDED
        assert result.output == {"key": "val"}
        assert result.finished_at is not None

    def test_fail(self):
        nsm = NodeStateMachine("n1")
        nsm.mark_ready()
        nsm.start()
        result = nsm.fail("error msg")
        assert nsm.status == NodeStatus.FAILED
        assert nsm.error == "error msg"
        assert result.status == NodeStatus.FAILED

    def test_retry(self):
        nsm = NodeStateMachine("n1")
        nsm.mark_ready()
        nsm.start()
        nsm.fail("oops")
        nsm.retry()
        assert nsm.status == NodeStatus.READY
        assert nsm.retry_count == 1
        assert nsm.error is None

    def test_retry_from_success_raises(self):
        nsm = NodeStateMachine("n1")
        nsm.mark_ready()
        nsm.start()
        nsm.succeed()
        with pytest.raises(RuntimeError):
            nsm.retry()

    def test_fail_from_pending_raises(self):
        nsm = NodeStateMachine("n1")
        with pytest.raises(RuntimeError):
            nsm.fail("no")
