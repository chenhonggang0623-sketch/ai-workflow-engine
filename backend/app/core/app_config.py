from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.models.app_config import AppConfig

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {"openai_api_key"}

DEFAULT_KEYS = [
    "openai_api_key",
    "openai_base_url",
    "default_llm_model",
    "default_llm_provider",
    "agent_default_provider",
    "opencode_path",
    "claude_code_path",
    "codex_path",
    "dag_max_nodes",
    "dag_max_edges",
    "dag_max_fan_in",
    "dag_max_fan_out",
    "dag_timeout_budget_seconds",
    "max_concurrency",
    "cpu_usage_cap_percent",
]


class ConfigStore:
    """Runtime config layer: DB values override .env defaults.

    Reads fall back to pydantic settings, so .env remains the baseline.
    """

    def __init__(self, initial: dict[str, Any] | None = None):
        self._overrides: dict[str, Any] = {}
        self._lock = threading.Lock()
        if initial:
            self._overrides.update(initial)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._overrides:
                return self._overrides[key]
        return getattr(settings, key, default)

    def all(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in DEFAULT_KEYS:
            result[key] = self.get(key)
        masked = self.mask_api_key(result.get("openai_api_key", ""))
        result["openai_api_key"] = masked
        result["has_openai_api_key"] = bool(masked)
        return result

    @staticmethod
    def mask_api_key(key: str) -> str:
        if not key or key in ("", "sk-your-key-here", "your-api-key"):
            return ""
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:4]}{'*' * 8}{key[-4:]}"

    async def load_from_db(self, session) -> None:
        try:
            rows = (await session.execute(select(AppConfig))).scalars().all()
            with self._lock:
                self._overrides = {row.key: row.value for row in rows}
            logger.info("ConfigStore: loaded %d overrides from DB", len(rows))
        except Exception:
            logger.exception("ConfigStore: failed to load config from DB")

    async def save(self, session, values: dict[str, Any]) -> dict[str, str]:
        mapped: dict[str, str] = {}
        for key, value in values.items():
            if key not in DEFAULT_KEYS:
                continue
            if value is None:
                continue
            if isinstance(value, bool):
                value = "1" if value else "0"
            mapped[key] = str(value)

        for key, value in mapped.items():
            row = await session.get(AppConfig, key)
            if row is None:
                session.add(AppConfig(key=key, value=value))
            else:
                row.value = value
        await session.commit()

        with self._lock:
            self._overrides.update(mapped)
        return {k: v for k, v in mapped.items() if k in DEFAULT_KEYS}


config_store = ConfigStore()