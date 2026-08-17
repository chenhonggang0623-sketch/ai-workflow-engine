# Task: Agent Runtime — Implementation Report

## Status: DONE

## Files Created

| File | Description |
|------|-------------|
| `app/agent/__init__.py` | Module exports: AgentRegistry, LLMGateway, PromptTemplate, AgentExecutor, AgentCommClient |
| `app/agent/registry.py` | AgentRegistry — CRUD for agent definitions via `agents` table |
| `app/agent/llm_gateway.py` | LLMGateway — OpenAI API calls with retry (429/5xx), streaming, tool calling |
| `app/agent/prompt_template.py` | PromptTemplate — `{{ variable }}` interpolation |
| `app/agent/comm_client.py` | AgentCommClient — async messaging via `agent_messages` table |
| `app/agent/runtime.py` | AgentExecutor + BUILTIN_AGENTS (5 built-in dev agents) + `register_builtin_agents()` |
| `tests/test_agent_runtime.py` | 27 tests covering all components |

## Files Modified

| File | Change |
|------|--------|
| `app/main.py` | Added lifespan hook to auto-register 5 built-in agents on startup |

## Architecture

```
app/agent/
├── __init__.py          # Public API exports
├── registry.py          # AgentRegistry — DB-backed agent CRUD
├── llm_gateway.py       # LLMGateway — OpenAI client with retry
├── prompt_template.py   # PromptTemplate — {{ var }} rendering
├── comm_client.py       # AgentCommClient — message broker
└── runtime.py           # AgentExecutor — agent execution loop + BUILTIN_AGENTS
```

## Test Results

**27 passed, 0 failed**
- PromptTemplate: 5 tests (render, multiple vars, missing vars, empty, no vars)
- AgentRegistry: 6 tests (register, get found/not found, list, list status filter, delete)
- BUILTIN_AGENTS: 3 tests (defined, required fields, auto-registration)
- LLMGateway: 2 tests (invalid provider, retry on 429, parse tool calls)
- AgentCommClient: 6 tests (send, broadcast, request timeout, subscribe, wildcard, stop, reply)
- AgentExecutor: 3 tests (agent not found, success, tool call loop)

## Built-in Agents

Registered at startup via `register_builtin_agents()`:
- `pm_agent` — Product Manager (PRD generation)
- `architect_agent` — Software Architect (system design)
- `developer_agent` — Software Developer (code generation)
- `qa_agent` — QA Engineer (testing)
- `devops_agent` — DevOps Engineer (infrastructure)

## Key Design Decisions

1. **LLM retry**: 3 attempts with exponential backoff (1s, 2s, 4s) on 429/5xx
2. **Message polling**: AgentCommClient uses polling loop (1s interval) with `agent_messages` table; no external broker needed for MVP
3. **Tool loop**: AgentExecutor runs LLM→tool→LLM loop until no more tool_calls
4. **Agent definition storage**: JSON in `agents.definition` column via SQLAlchemy
5. **Startup registration**: `register_builtin_agents()` called in FastAPI lifespan with its own session, committed before `init_redis()`

## Concerns

- `chat` method with `stream=True` uses a simplified handler that accumulates text only (no tool calls in streaming mode yet)
- `request()` uses polling loop — acceptable for MVP but should be replaced with Redis pub/sub or async queue for production
- LLMGateway only supports OpenAI provider currently; Anthropic/Azure stubs are in ModelConfig but not implemented
- AgentCommClient has no auth/security; any agent can message any other agent
