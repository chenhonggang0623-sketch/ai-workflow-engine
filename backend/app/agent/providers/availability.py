import logging
import shutil
from dataclasses import dataclass, asdict

from app.core.app_config import config_store
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ProviderStatus:
    name: str
    label: str
    kind: str  # cli | api | local
    enabled: bool
    reason: str
    default: bool = False


CLI_PROVIDER_DEFS: list[tuple[str, str, str]] = [
    ("opencode_cli", "OpenCode CLI", "opencode_path"),
    ("claude_cli", "Claude Code CLI", "claude_code_path"),
    ("codex_cli", "Codex CLI", "codex_path"),
]

API_PROVIDER_DEFS: list[tuple[str, str]] = [
    ("openai", "LLM API (OpenAI 兼容)"),
]


def _is_placeholder(key: str) -> bool:
    return not key or key in ("sk-your-key-here", "sk-your-api-key", "your-api-key")


def _cli_path(cfg_key: str) -> str:
    return config_store.get(cfg_key, getattr(settings, cfg_key)) or ""


def _default_provider_name() -> str:
    configured = config_store.get("agent_default_provider", settings.agent_default_provider)
    if configured:
        return configured
    return "opencode_cli"


def probe_providers() -> list[ProviderStatus]:
    """扫描所有 provider 的可用性：CLI 看命令是否存在，API 看 key 是否配置。"""
    default = _default_provider_name()
    statuses: list[ProviderStatus] = []

    for name, label, cfg_key in CLI_PROVIDER_DEFS:
        path = _cli_path(cfg_key)
        resolved = shutil.which(path) if path else None
        if resolved:
            statuses.append(
                ProviderStatus(name=name, label=label, kind="cli", enabled=True,
                               reason=f"命令可用: {resolved}", default=(name == default))
            )
        else:
            statuses.append(
                ProviderStatus(name=name, label=label, kind="cli", enabled=False,
                               reason=f"未找到命令: {path or cfg_key}（可在配置页 Local CLI Paths 中设置）",
                               default=(name == default))
            )

    for name, label in API_PROVIDER_DEFS:
        key = config_store.get("openai_api_key", settings.openai_api_key)
        base_url = config_store.get("openai_base_url", settings.openai_base_url)
        if not _is_placeholder(key):
            statuses.append(
                ProviderStatus(name=name, label=label, kind="api", enabled=True,
                               reason=f"Key 已配置 ({base_url})", default=(name == default))
            )
        else:
            statuses.append(
                ProviderStatus(name=name, label=label, kind="api", enabled=False,
                               reason="未配置 API Key（可在配置页 LLM API 中填写）",
                               default=(name == default))
            )

    return statuses


def available_provider_names() -> list[str]:
    """当前可用的 provider 名列表（enabled）。"""
    return [s.name for s in probe_providers() if s.enabled]


def resolve_effective_default() -> str | None:
    """解析实际生效的默认 provider：配置的默认不可用 → 第一个可用 CLI。

    返回 None 表示当前没有任何可用 provider。
    """
    statuses = probe_providers()
    enabled = [s for s in statuses if s.enabled]
    if not enabled:
        return None
    configured = _default_provider_name()
    for s in enabled:
        if s.name == configured:
            return s.name
    return enabled[0].name


def providers_payload() -> dict:
    """供 GET /api/providers 使用的结构化输出。"""
    statuses = probe_providers()
    return {
        "providers": [asdict(s) for s in statuses],
        "default_provider": resolve_effective_default() or "",
        "configured_default": _default_provider_name(),
        "any_available": any(s.enabled for s in statuses),
    }
