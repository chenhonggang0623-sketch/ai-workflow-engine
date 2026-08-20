import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _abs(p: str) -> str:
    expanded = os.path.expanduser(p)
    if os.path.isabs(expanded):
        return expanded
    return os.path.abspath(str(BACKEND_DIR / expanded))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    app_name: str = "AI Workflow Engine"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_workflow"
    redis_url: str = "redis://localhost:6379/0"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    storage_backend: str = "local"
    storage_path: str = "./data/artifacts"
    project_root: str = "./generated_projects"

    @property
    def project_root_abs(self) -> str:
        return _abs(self.project_root)

    @property
    def storage_path_abs(self) -> str:
        return _abs(self.storage_path)

    default_llm_model: str = "gpt-4o-mini"
    default_llm_provider: str = "openai"

    agent_default_provider: str = "opencode_cli"
    opencode_path: str = "opencode"
    claude_code_path: str = "claude"
    codex_path: str = "codex"

    # DAG 校验阈值（dag_validator 可通过 config_store 覆盖）
    dag_max_nodes: int = 32
    dag_max_edges: int = 96
    dag_max_fan_in: int = 8
    dag_max_fan_out: int = 6
    dag_timeout_budget_seconds: int = 3600

    # 执行预算（None = 按本机配置自动推荐）
    max_concurrency: int | None = None
    # 运行时 CPU 占用上限（%），ResourceMonitor 超限自动降并发
    cpu_usage_cap_percent: int = 75

    # 慢节点干预：节点运行超过该秒数后向前端提示用户选择干预动作
    slow_node_after_seconds: int = 300


settings = Settings()
