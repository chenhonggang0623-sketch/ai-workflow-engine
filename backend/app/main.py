import logging
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.api.websocket.handlers import execution_ws, agent_messages_ws, manager
from app.core.db import engine, Base, async_session_factory
from app.core.redis import init_redis, close_redis, get_redis
from app.core.app_config import config_store
from app.agent.registry import AgentRegistry
from app.agent.runtime import AgentExecutor, register_builtin_agents
from app.agent.llm_gateway import LLMGateway
from app.agent.executor.router import ExecutorRouter
from app.agent.executor.llm_executor import LLMExecutor
from app.agent.executor.local_cli_executor import LocalCLIExecutor
from app.agent.executor.local_model_executor import LocalModelExecutor
from app.agent.executor.human_executor import HumanExecutor
from app.agent.executor.mcp_executor import MCPExecutor
from app.agent.providers import (
    AgentProviderRegistry,
    OpenAIProvider,
    LocalCLIProvider,
    EnsembleProvider,
)
from app.engine.node_runner import NodeRunner
from app.engine.execution_manager import ExecutionManager
from app.engine.context_service import ContextService
from app.mcp.tool_registry import ToolRegistry
from app.core.limiter import AdaptiveLimiter
from app.core.resource_monitor import ResourceMonitor
from app.core.system_probe import detect_hardware, recommend_limits

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        root.addHandler(handler)
    root.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with async_session_factory() as session:
            registry = AgentRegistry(session)
            await register_builtin_agents(registry)
            await session.commit()
    except Exception:
        logger.exception("Failed to initialize database schema / builtin agents")

    try:
        await init_redis()
    except Exception:
        logger.exception("Failed to initialize Redis")

    try:
        async with async_session_factory() as session:
            await config_store.load_from_db(session)
    except Exception:
        logger.exception("Failed to load config store from DB")

    llm = LLMGateway()
    tool_registry = ToolRegistry()
    agent_executor = AgentExecutor(
        registry=None,
        llm_gateway=llm,
        tool_registry=tool_registry,
    )

    llm_executor = LLMExecutor(
        llm_gateway=llm,
        tool_registry=tool_registry,
        agent_registry=None,
    )
    local_cli_executor = LocalCLIExecutor()
    local_model_executor = LocalModelExecutor(
        llm_gateway=llm,
        tool_registry=tool_registry,
        agent_registry=None,
    )
    human_executor = HumanExecutor()
    mcp_executor = MCPExecutor(bridge=None)

    provider_registry = AgentProviderRegistry()
    provider_registry.register(OpenAIProvider(llm_executor))
    provider_registry.register(LocalCLIProvider(local_cli_executor, cli_provider="opencode"))
    provider_registry.register(
        LocalCLIProvider(
            local_cli_executor,
            cli_provider="claude",
            name="claude_cli",
        )
    )
    provider_registry.register(
        LocalCLIProvider(
            local_cli_executor,
            cli_provider="codex",
            name="codex_cli",
        )
    )
    provider_registry.register(EnsembleProvider(provider_registry))

    executor_router = ExecutorRouter(
        llm_executor=llm_executor,
        local_cli_executor=local_cli_executor,
        local_model_executor=local_model_executor,
        human_executor=human_executor,
        mcp_executor=mcp_executor,
        provider_registry=provider_registry,
    )

    node_runner = NodeRunner(
        agent_executor=agent_executor,
        tool_registry=tool_registry,
        executor_router=executor_router,
    )
    context_service = ContextService()
    node_runner._context_service = context_service

    hardware = detect_hardware()
    recommended = recommend_limits(hardware)
    configured = config_store.get("max_concurrency")
    base_budget = int(configured) if configured else int(recommended["max_concurrency"])
    exec_limiter = AdaptiveLimiter(base_budget)
    exec_mgr = ExecutionManager(
        node_runner=node_runner,
        max_concurrency=base_budget,
        limiter=exec_limiter,
        context_service=context_service,
        redis_client=get_redis(),
    )
    resource_monitor = ResourceMonitor(
        exec_limiter,
        base_budget=base_budget,
        cpu_cap_percent=int(
            config_store.get("cpu_usage_cap_percent")
            or recommended["cpu_usage_cap_percent"]
        ),
    )
    await resource_monitor.start()
    exec_mgr.set_event_callback(
        lambda execution_id, message: manager.broadcast_execution(execution_id, message)
    )

    try:
        # 进程重启后,把 DB 里残留的 running execution 标记为 failed,
        # 避免 UI 永久卡在 running(worker 重启会杀掉所有执行中任务)。
        await exec_mgr.recover_stale_executions(async_session_factory)
    except Exception:
        logger.exception("Failed to recover stale executions")

    app.state.llm_gateway = llm
    app.state.tool_registry = tool_registry
    app.state.agent_executor = agent_executor
    app.state.executor_router = executor_router
    app.state.node_runner = node_runner
    app.state.execution_manager = exec_mgr

    yield
    try:
        await resource_monitor.stop()
    except Exception:
        logger.exception("Failed to stop resource monitor")
    try:
        await close_redis()
    except Exception:
        pass


app = FastAPI(title="AI Workflow Engine", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.websocket("/ws/executions/{execution_id}")
async def websocket_execution(websocket: WebSocket, execution_id: UUID):
    await execution_ws(websocket, execution_id)


@app.websocket("/ws/agent-messages/{execution_id}")
async def websocket_agent_messages(websocket: WebSocket, execution_id: UUID):
    await agent_messages_ws(websocket, execution_id)


@app.get("/health")
async def health():
    return {"status": "ok"}
