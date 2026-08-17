import logging

from app.agent.providers.base import AgentProvider
from app.core.app_config import config_store

logger = logging.getLogger(__name__)

PROVIDER_OPENAI = "openai"
PROVIDER_OPENCODE_CLI = "opencode_cli"
PROVIDER_CLAUDE_CLI = "claude_cli"
PROVIDER_CODEX_CLI = "codex_cli"
PROVIDER_LOCAL_MODEL = "local_model"
PROVIDER_ENSEMBLE = "ensemble"

SUPPORTED_PROVIDERS = [
    PROVIDER_OPENAI,
    PROVIDER_OPENCODE_CLI,
    PROVIDER_CLAUDE_CLI,
    PROVIDER_CODEX_CLI,
    PROVIDER_LOCAL_MODEL,
    PROVIDER_ENSEMBLE,
]


class AgentProviderRegistry:
    def __init__(self, default_provider: str | None = None):
        self._providers: dict[str, AgentProvider] = {}
        self._default_provider = default_provider

    def register(self, provider: AgentProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str | None) -> AgentProvider | None:
        if not name:
            return None
        return self._providers.get(name)

    def get_default(self) -> AgentProvider | None:
        return self._providers.get(self.default_provider)

    def get_or_default(self, name: str | None) -> AgentProvider | None:
        return self.get(name) or self.get_default()

    def names(self) -> list[str]:
        return list(self._providers.keys())

    @property
    def default_provider(self) -> str:
        return self._default_provider or config_store.get(
            "agent_default_provider", "opencode_cli"
        )
