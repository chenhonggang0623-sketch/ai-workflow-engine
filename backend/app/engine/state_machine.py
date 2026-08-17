from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.engine.types import ExecutionStatus, NodeStatus, NodeResult


class ExecutionStateMachine:
    def __init__(self, execution_id: UUID | None = None):
        self.execution_id = execution_id or uuid4()
        self.status: ExecutionStatus = ExecutionStatus.PENDING
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.completed_count: int = 0
        self.total_count: int = 0
        self.error: str | None = None

    def start(self, total_nodes: int) -> None:
        if self.status != ExecutionStatus.PENDING:
            raise RuntimeError(f"Cannot start from {self.status}")
        self.status = ExecutionStatus.RUNNING
        self.started_at = datetime.now(UTC).replace(tzinfo=None)
        self.total_count = total_nodes
        self.completed_count = 0

    def pause(self) -> None:
        if self.status != ExecutionStatus.RUNNING:
            raise RuntimeError(f"Cannot pause from {self.status}")
        self.status = ExecutionStatus.PAUSED

    def resume(self) -> None:
        if self.status != ExecutionStatus.PAUSED:
            raise RuntimeError(f"Cannot resume from {self.status}")
        self.status = ExecutionStatus.RUNNING

    def cancel(self) -> None:
        if self.is_terminal():
            raise RuntimeError(f"Cannot cancel from terminal state {self.status}")
        self.status = ExecutionStatus.CANCELLED
        self.finished_at = datetime.now(UTC).replace(tzinfo=None)

    def fail(self, reason: str) -> None:
        if self.is_terminal():
            raise RuntimeError(f"Cannot fail from terminal state {self.status}")
        self.status = ExecutionStatus.FAILED
        self.finished_at = datetime.now(UTC).replace(tzinfo=None)
        self.error = reason

    def succeed(self) -> None:
        if self.status != ExecutionStatus.RUNNING:
            raise RuntimeError(f"Cannot succeed from {self.status}")
        self.status = ExecutionStatus.SUCCEEDED
        self.finished_at = datetime.now(UTC).replace(tzinfo=None)

    def is_terminal(self) -> bool:
        return self.status in (
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        )

    def increment_progress(self) -> None:
        self.completed_count += 1

    def get_progress(self) -> dict:
        return {
            "execution_id": str(self.execution_id),
            "status": self.status.value,
            "completed": self.completed_count,
            "total": self.total_count,
            "progress_pct": round(self.completed_count / self.total_count * 100, 1) if self.total_count else 0.0,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
        }


class NodeStateMachine:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.status: NodeStatus = NodeStatus.PENDING
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.retry_count: int = 0
        self.error: str | None = None

    def mark_ready(self) -> None:
        if self.status != NodeStatus.PENDING:
            raise RuntimeError(f"Cannot mark ready from {self.status}")
        self.status = NodeStatus.READY

    def start(self) -> None:
        if self.status not in (NodeStatus.READY, NodeStatus.WAITING):
            raise RuntimeError(f"Cannot start from {self.status}")
        self.status = NodeStatus.RUNNING
        self.started_at = datetime.now(UTC).replace(tzinfo=None)

    def wait(self) -> None:
        if self.status != NodeStatus.RUNNING:
            raise RuntimeError(f"Cannot wait from {self.status}")
        self.status = NodeStatus.WAITING

    def succeed(self, output: dict | None = None) -> NodeResult:
        if self.status != NodeStatus.RUNNING:
            raise RuntimeError(f"Cannot succeed from {self.status}")
        self.status = NodeStatus.SUCCEEDED
        self.finished_at = datetime.now(UTC).replace(tzinfo=None)
        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.SUCCEEDED,
            output=output or {},
            started_at=self.started_at,
            finished_at=self.finished_at,
        )

    def fail(self, error: str) -> NodeResult:
        if self.status not in (NodeStatus.RUNNING, NodeStatus.WAITING):
            raise RuntimeError(f"Cannot fail from {self.status}")
        self.status = NodeStatus.FAILED
        self.finished_at = datetime.now(UTC).replace(tzinfo=None)
        self.error = error
        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.FAILED,
            error=error,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )

    def retry(self) -> None:
        if self.status != NodeStatus.FAILED:
            raise RuntimeError(f"Cannot retry from {self.status}")
        self.retry_count += 1
        self.status = NodeStatus.READY
        self.error = None
        self.started_at = None
        self.finished_at = None
