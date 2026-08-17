import json
import logging
import re

from app.planner.complexity_analyzer import ComplexityAnalyzer

logger = logging.getLogger(__name__)

REQUIREMENT_PROMPT = """You are a product analyst. Given a user requirement, produce a structured PRD.

Output ONLY valid JSON with this exact structure:
{
  "summary": "one-sentence goal",
  "goals": ["business goals"],
  "features": ["functional requirements"],
  "non_functional": ["performance/security/usability requirements"],
  "acceptance_criteria": ["verifiable acceptance criteria"],
  "assumptions": ["assumptions made"],
  "open_questions": ["questions that need human clarification"]
}

Rules:
1. Do not invent requirements the user did not mention. Keep features minimal and faithful.
2. If the requirement is vague, state the gaps explicitly in open_questions.
3. Each feature must be concrete enough for a developer to act on.
4. Keep the PRD in the same language as the user requirement.

Requirement: __REQUIREMENT__"""


class RequirementAnalyzer:
    """需求澄清层：模糊用户需求 → 结构化 PRD。

    LLM 生成优先，失败时使用启发式回退（保证无 API key 也可用）。
    """

    def __init__(self, llm_gateway):
        self._llm = llm_gateway
        self._complexity_analyzer = ComplexityAnalyzer()

    async def analyze(self, requirement: str) -> dict:
        try:
            result = await self._llm.chat(
                model_config={
                    "model": "gpt-4o-mini",
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
                messages=[
                    {
                        "role": "system",
                        "content": "You are a product analyst that outputs valid JSON.",
                    },
                    {
                        "role": "user",
                        "content": REQUIREMENT_PROMPT.replace("__REQUIREMENT__", requirement),
                    },
                ],
            )
            content = result.get("content", "")
            prd = self._parse_llm_output(content)
            if prd:
                return prd
        except Exception as e:
            logger.warning("LLM PRD generation failed: %s. Using heuristic fallback.", e)

        return self._build_fallback_prd(requirement)

    def _parse_llm_output(self, content: str) -> dict | None:
        content = content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        content = content.strip()

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            brace_start = content.find("{")
            brace_end = content.rfind("}")
            if brace_start == -1 or brace_end <= brace_start:
                logger.warning("No valid JSON found in LLM PRD output")
                return None
            try:
                data = json.loads(content[brace_start : brace_end + 1])
            except json.JSONDecodeError:
                return None

        required = ("summary", "goals", "features")
        if not all(k in data for k in required):
            logger.warning("LLM PRD output missing required fields")
            return None

        return {
            "summary": str(data.get("summary", "")),
            "goals": [str(x) for x in data.get("goals", [])],
            "features": [str(x) for x in data.get("features", [])],
            "non_functional": [str(x) for x in data.get("non_functional", [])],
            "acceptance_criteria": [str(x) for x in data.get("acceptance_criteria", [])],
            "assumptions": [str(x) for x in data.get("assumptions", [])],
            "open_questions": [str(x) for x in data.get("open_questions", [])],
        }

    def _build_fallback_prd(self, requirement: str) -> dict:
        """启发式回退：不依赖 LLM 的基础 PRD。

        以复杂度分析给出的推荐团队为骨架，推断功能清单与验收标准。
        """
        complexity = self._complexity_analyzer.analyze(requirement)
        roles = [a["role"] for a in complexity.recommended_agents]

        features = [f"满足核心需求：{requirement.strip()[:200]}"]
        if "backend_developer" in roles or "database_engineer" in roles:
            features.append("服务端与数据存储实现")
        if "frontend_developer" in roles:
            features.append("用户界面实现")
        if "tester" in roles or "qa_engineer" in roles:
            features.append("测试与质量验证")

        return {
            "summary": requirement.strip()[:200],
            "goals": [f"完成需求：{requirement.strip()[:200]}"],
            "features": features,
            "non_functional": ["代码可运行、无阻塞性错误"],
            "acceptance_criteria": ["核心功能按需求工作", "生成的项目可以启动运行"],
            "assumptions": ["用户描述即为需求边界"],
            "open_questions": [],
        }
