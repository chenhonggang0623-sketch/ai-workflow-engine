from enum import Enum
from pydantic import BaseModel, Field


class ExecutorType(str, Enum):
    LLM_API = "llm_api"
    LOCAL_CLI = "local_cli"
    LOCAL_MODEL = "local_model"
    MCP = "mcp"
    HUMAN = "human"


class ExecutionRequest(BaseModel):
    task: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    working_directory: str | None = None
    timeout: int = 300


class ExecutionResult(BaseModel):
    success: bool
    output: dict = Field(default_factory=dict)
    error: str | None = None
    metadata: dict = Field(default_factory=dict)
