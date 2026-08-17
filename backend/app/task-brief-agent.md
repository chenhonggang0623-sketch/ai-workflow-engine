# Task: Implement Agent Runtime

## Files to create

### 1. `backend/app/agent/__init__.py`
Export: AgentRegistry, LLMGateway, PromptTemplate, AgentExecutor, AgentCommClient

### 2. `backend/app/agent/registry.py` — AgentRegistry

```python
class AgentRegistry:
    """
    Central registry for Agent definitions.
    - register(agent_id, definition: dict) → stores agent in DB
    - get(agent_id) → AgentDefinition (Pydantic model)
    - list(filters) → list of agents
    - build(agent_id, context) → AgentInstance (runtime instance with populated context)
    
    AgentDefinition is stored as JSON in the `agents` table.
    """

    def __init__(self, db_session): ...
    async def register(self, agent_id: str, name: str, description: str, definition: dict) -> Agent: ...
    async def get(self, agent_id: str) -> dict: ...
    async def list(self, status: str = None) -> list[dict]: ...
    async def delete(self, agent_id: str) -> None: ...
```

### 3. `backend/app/agent/llm_gateway.py` — LLMGateway

```python
class LLMGateway:
    """
    Unified LLM calling interface.
    Supports OpenAI and OpenAI-compatible APIs.
    
    - chat(model_config, messages, tools, stream) → response
    - Supports: system prompt, function calling, streaming
    - Provider routing based on model_config.provider
    
    ModelConfig fields:
    - provider: "openai" | "anthropic" | "azure"
    - model: "gpt-4o" | "gpt-4o-mini" | "claude-3-5-sonnet"
    - temperature: float
    - max_tokens: int
    
    Uses setting: settings.openai_api_key, settings.openai_base_url
    """

    def __init__(self): ...
    async def chat(self, model_config: dict, messages: list[dict],
                    tools: list[dict] = None, stream: bool = False) -> dict:
        """
        Returns: {"content": "...", "tool_calls": [...], "usage": {"prompt_tokens": N, "completion_tokens": N}}
        If streaming: returns AsyncIterator of delta chunks
        """
        ...

    async def chat_stream(self, model_config: dict, messages: list[dict],
                           tools: list[dict] = None):
        """Async generator yielding {"type": "text"|"tool_call", "content": ...}"""
        ...
```

### 4. `backend/app/agent/prompt_template.py` — PromptTemplate

```python
class PromptTemplate:
    """
    Renders system prompts with context injection.
    
    - render(template: str, context: dict) → rendered string
    - Supports {{ variable }} interpolation
    - Supports {{#each items}}...{{/each}} loops
    - Supports {{#if condition}}...{{/if}} conditionals
    
    For MVP: implement simple {{ variable }} replacement only.
    """

    @staticmethod
    def render(template: str, variables: dict) -> str: ...
```

### 5. `backend/app/agent/comm_client.py` — AgentCommClient

```python
class AgentCommClient:
    """
    Communication client for Agent-to-Agent and Agent-to-Supervisor messaging.
    
    - send(target_id, subject, payload) → sends message via broker
    - request(target_id, subject, payload, timeout) → sends and waits for response
    - broadcast(subject, payload) → sends to all agents
    - on(subject, handler) → subscribes to messages
    - listen() → starts message processing loop
    
    Messages stored in agent_messages table.
    """

    def __init__(self, agent_id: str, execution_id: UUID, db_session): ...
    async def send(self, target_id: str, subject: str, payload: dict) -> None: ...
    async def request(self, target_id: str, subject: str, payload: dict, timeout: int = 60) -> dict: ...
    async def broadcast(self, subject: str, payload: dict) -> None: ...
    def on(self, subject: str, handler): ...
    async def listen(self): ...
```

### 6. `backend/app/agent/runtime.py` — AgentExecutor

```python
class AgentExecutor:
    """
    Executes an agent node: loads agent config, calls LLM, handles tool calls.
    
    execute(agent_id: str, node_input: dict, context: dict, comm_client: AgentCommClient) → dict
    
    Execution flow:
    1. Load agent definition from registry
    2. Render system prompt with context
    3. Build messages: system + user input
    4. Call LLM Gateway
    5. Handle tool_calls (if any):
       - Execute tool via ToolRegistry
       - Feed result back to LLM
       - Continue until LLM returns final answer
    6. Return structured output
    
    For built-in development agents (pm_agent, architect_agent, dev_agent, qa_agent, devops_agent):
    - Register them with hardcoded system prompts on startup
    - Each has specific role instructions for software development
    """

    def __init__(self, registry: AgentRegistry, llm_gateway: LLMGateway, tool_registry): ...
    async def execute(self, agent_id: str, node_input: dict,
                       context: dict, comm_client: AgentCommClient = None) -> dict: ...


# Built-in Agent prompts (register these on startup):
BUILTIN_AGENTS = {
    "pm_agent": {
        "name": "Product Manager",
        "description": "Analyzes requirements and produces PRD",
        "system_prompt": "You are a senior product manager. Analyze the given requirements and produce a detailed PRD.",
    },
    "architect_agent": {
        "name": "Software Architect",
        "description": "Designs software architecture",
        "system_prompt": "You are a senior software architect. Design the system architecture based on the PRD.",
    },
    "developer_agent": {
        "name": "Software Developer",
        "description": "Writes code based on specifications",
        "system_prompt": "You are a senior software developer. Write clean, well-tested code based on the specifications.",
    },
    "qa_agent": {
        "name": "QA Engineer",
        "description": "Tests code and finds bugs",
        "system_prompt": "You are a QA engineer. Write and execute tests to verify the code works correctly.",
    },
    "devops_agent": {
        "name": "DevOps Engineer",
        "description": "Handles deployment and infrastructure",
        "system_prompt": "You are a DevOps engineer. Set up deployment pipelines and infrastructure.",
    },
}
```

## Constraints
- LLM Gateway should handle API errors gracefully (retry on 429/500)
- Agent definitions stored in `agents` table
- Built-in agents auto-registered on app startup
- The AgentCommClient stores messages in the `agent_messages` table
- All async methods with proper error handling

## Output
- Status: DONE / DONE_WITH_CONCERNS / BLOCKED
- Report file: `backend/app/task-brief-agent-report.md`
- Test output summary
