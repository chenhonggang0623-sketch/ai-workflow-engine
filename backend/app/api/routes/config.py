import logging
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm_gateway import LLMGateway
from app.agent.providers.availability import providers_payload
from app.core.app_config import config_store
from app.core.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


class ConfigUpdate(BaseModel):
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    default_llm_model: str | None = None
    default_llm_provider: str | None = None
    agent_default_provider: str | None = None
    opencode_path: str | None = None
    claude_code_path: str | None = None
    codex_path: str | None = None
    dag_max_nodes: int | None = None
    dag_max_edges: int | None = None
    dag_max_fan_in: int | None = None
    dag_max_fan_out: int | None = None
    dag_timeout_budget_seconds: int | None = None


def _is_placeholder(key: str) -> bool:
    return not key or key in ("sk-your-key-here", "sk-your-api-key", "your-api-key")


@router.get("/providers")
async def get_providers():
    """Provider 可用性列表：每个 CLI/API 的启用状态与默认标记。"""
    return providers_payload()


@router.get("/config")
async def get_config():
    """Current effective config. API keys are masked unless empty."""
    config = config_store.all()
    config["loaded_from"] = "db+env"
    return config


@router.put("/config")
async def update_config(update: ConfigUpdate, db: AsyncSession = Depends(get_db)):
    payload = update.model_dump(exclude_none=True)

    if "openai_api_key" in payload and _is_placeholder(payload["openai_api_key"]):
        payload.pop("openai_api_key")

    saved = await config_store.save(db, payload)
    fresh = config_store.all()
    fresh["saved_keys"] = [k for k in saved] if isinstance(saved, dict) else saved
    return fresh


class LLMTestRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


@router.post("/config/test-llm")
async def test_llm(req: LLMTestRequest):
    base_url = req.base_url or config_store.get("openai_base_url", "https://api.openai.com/v1")
    api_key = req.api_key or config_store.get("openai_api_key", "")
    model = req.model or config_store.get("default_llm_model", "")

    if _is_placeholder(api_key):
        return {"ok": False, "error": "API key is not configured"}

    gateway = LLMGateway()
    try:
        result = await gateway.chat(
            {
                "provider": "openai",
                "model": model,
                "base_url": base_url,
                "api_key": api_key,
                "max_tokens": 16,
                "temperature": 0,
            },
            [{"role": "user", "content": "ping"}],
        )
        content = (result.get("content") or "…")[:80]
        return {"ok": True, "model": model, "base_url": base_url, "reply": content}
    except Exception as exc:
        logger.warning("LLM connectivity test failed: %s", exc)
        return {"ok": False, "error": str(exc), "base_url": base_url, "model": model}