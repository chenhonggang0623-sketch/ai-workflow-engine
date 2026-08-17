from enum import Enum
from typing import Awaitable, Callable

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
    # 逐行控制台输出回调：log_sink(line, stream)，stream 为 "stdout" | "stderr"
    log_sink: Callable[[str, str], Awaitable[None]] | None = None


class ExecutionResult(BaseModel):
    success: bool
    output: dict = Field(default_factory=dict)
    error: str | None = None
    metadata: dict = Field(default_factory=dict)
