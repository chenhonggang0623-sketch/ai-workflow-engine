import json
import logging

from app.agent.registry import AgentRegistry
from app.agent.llm_gateway import LLMGateway
from app.agent.prompt_template import PromptTemplate

logger = logging.getLogger(__name__)

BUILTIN_AGENTS = {
    "pm_agent": {
        "name": "Product Manager",
        "description": "Analyzes requirements and produces PRD",
        "system_prompt": (
            "You are a senior product manager. Analyze the given requirements "
            "and produce a detailed PRD."
        ),
    },
    "architect_agent": {
        "name": "Software Architect",
        "description": "Designs software architecture",
        "system_prompt": (
            "You are a senior software architect. Design the system architecture "
            "based on the PRD."
        ),
    },
    "developer_agent": {
        "name": "Software Developer",
        "description": "Writes code based on specifications",
        "system_prompt": (
            "You are a senior software developer. Write clean, well-tested code "
            "based on the specifications."
        ),
    },
    "qa_agent": {
        "name": "QA Engineer",
        "description": "Tests code and finds bugs",
        "system_prompt": (
            "You are a QA engineer. Write and execute tests to verify the code "
            "works correctly."
        ),
    },
    "devops_agent": {
        "name": "DevOps Engineer",
        "description": "Handles deployment and infrastructure",
        "system_prompt": (
            "You are a DevOps engineer. Set up deployment pipelines and "
            "infrastructure."
        ),
    },
}


async def register_builtin_agents(registry: AgentRegistry) -> None:
    for agent_id, spec in BUILTIN_AGENTS.items():
        definition = {
            "agent_id": agent_id,
            "system_prompt": spec["system_prompt"],
            "model_config": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "temperature": 0.7,
                "max_tokens": 4096,
            },
        }
        await registry.register(
            agent_id=agent_id,
            name=spec["name"],
            description=spec["description"],
            definition=definition,
        )
        logger.info("Registered built-in agent: %s", agent_id)


class AgentExecutor:
    def __init__(
        self,
        registry: AgentRegistry,
        llm_gateway: LLMGateway,
        tool_registry,
    ):
        self._registry = registry
        self._llm = llm_gateway
        self._tools = tool_registry

    async def execute(
        self,
        agent_id: str,
        node_input: dict,
        context: dict,
        system_prompt: str | None = None,
        comm_client=None,
    ) -> dict:
        model_config = {}
        if system_prompt is None:
            if self._registry:
                agent_def = await self._registry.get(agent_id)
                if not agent_def:
                    return {"error": f"Agent not found: {agent_id}"}
                definition = agent_def.get("definition", {})
                system_prompt = definition.get("system_prompt", "You are a helpful assistant.")
                model_config = definition.get("model_config", {})
            else:
                system_prompt = "You are a helpful assistant."

        rendered_system = PromptTemplate.render(system_prompt, context)

        messages = [
            {"role": "system", "content": rendered_system},
            {"role": "user", "content": json.dumps(node_input, ensure_ascii=False)},
        ]

        tool_defs = self._tools.list() if self._tools else []
        openai_tools = []
        for td in tool_defs:
            if td.schema:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": td.id,
                        "description": td.description,
                        "parameters": td.schema,
                    },
                })

        response = await self._llm.chat(
            model_config=model_config,
            messages=messages,
            tools=openai_tools if openai_tools else None,
        )

        tool_results = []
        while response.get("tool_calls"):
            for tc in response["tool_calls"]:
                func_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                tool_result = await self._tools.execute(func_name, args)
                tool_results.append({
                    "tool_call_id": tc["id"],
                    "tool_name": func_name,
                    "result": tool_result,
                })

                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": func_name,
                                "arguments": tc["function"]["arguments"],
                            },
                        }
                    ],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })

            response = await self._llm.chat(
                model_config=model_config,
                messages=messages,
                tools=openai_tools if openai_tools else None,
            )

        return {
            "output": response.get("content", ""),
            "tool_calls": tool_results,
            "usage": response.get("usage", {}),
        }
