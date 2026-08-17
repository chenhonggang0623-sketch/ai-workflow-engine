from enum import Enum
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    AGENT = "agent"
    TOOL = "tool"
    CONDITION = "condition"
    LOOP = "loop"
    HUMAN = "human"
    PLANNER = "planner"


class NodeStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class InputMapping(BaseModel):
    source: str  # JSONPath in context, e.g. "$.requirement"
    target: str  # field name in node input


class OutputMapping(BaseModel):
    source: str  # field name in node output
    target: str  # JSONPath in context, e.g. "$.product_doc"


class RetryConfig(BaseModel):
    max_retries: int = 2
    backoff_seconds: int = 5


class NodeConfig(BaseModel):
    agent_id: str | None = None
    tool_id: str | None = None
    expression: str | None = None
    max_iterations: int | None = None
    body_node_ids: list[str] | None = None
    branches: dict | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    model_params: dict | None = Field(None, alias="model_config")
    timeout_seconds: int = 900
    retry_config: RetryConfig = RetryConfig()
    system_prompt: str | None = None
    prompt_message: str | None = None
    executor_type: str = "llm_api"
    provider: str | None = None
    agent_provider: str | None = None
    model: str | None = None
    cli_command: str | None = None
    working_directory: str | None = None
    role: str | None = None
    purpose: str | None = None
    agent_capability: list[str] | None = None
    executor_config: dict = {}


class NodeDefinition(BaseModel):
    id: str
    type: NodeType
    label: str
    config: NodeConfig = NodeConfig()
    input_mapping: list[InputMapping] = []
    output_mapping: list[OutputMapping] = []
    position: dict | None = None


class EdgeDefinition(BaseModel):
    id: str = ""
    source: str
    target: str
    label: str = ""
    condition: str | None = None


class WorkflowDefinition(BaseModel):
    id: str | None = None
    name: str
    description: str = ""
    version: str = "1.0.0"
    nodes: list[NodeDefinition]
    edges: list[EdgeDefinition]

    def validate_dag(self) -> bool:
        import networkx as nx
        G = nx.DiGraph()
        for node in self.nodes:
            G.add_node(node.id)
        for edge in self.edges:
            G.add_edge(edge.source, edge.target)
        return nx.is_directed_acyclic_graph(G)


class NodeResult(BaseModel):
    node_id: str
    status: NodeStatus
    output: dict = {}
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class WorkflowResult(BaseModel):
    execution_id: UUID
    workflow_id: UUID
    status: ExecutionStatus
    node_results: list[NodeResult] = []
    context: dict = {}
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # audit 模式下 recommend_rerun=true 的节点明细（不自动重跑，交给上层提示决策）
    rerun_recommendations: list[dict] = Field(default_factory=list)
