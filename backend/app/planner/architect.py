import json
import logging
import re
from uuid import UUID

from sqlalchemy import select, delete

from app.models.blueprint import Blueprint
from app.planner.complexity_analyzer import ComplexityAnalyzer
from app.agent.llm_gateway import default_model_config

logger = logging.getLogger(__name__)

ARCHITECT_PROMPT = """You are a software architect. Given a PRD, design the system blueprint.

Output ONLY valid JSON with this exact structure:
{
  "prd": {"summary": "...", "goals": [...], "features": [...], "non_functional": [...], "acceptance_criteria": [...], "assumptions": [...], "open_questions": [...]},
  "architecture": {
    "tech_stack": ["recommended technologies"],
    "directory_structure": ["expected directories"],
    "data_model": ["key data entities"],
    "api_contracts": ["key API contracts"]
  },
  "modules": [
    {
      "id": "unique_module_id",
      "name": "module name",
      "description": "responsibility",
      "depends_on": ["dependent module ids"],
      "input_contract": ["allowed input field names"],
      "output_contract": ["promised output field names"]
    }
  ],
  "constraints": ["architecture constraints every implementation node must obey"]
}

Rules:
1. Each module must map to a clear deliverable that one agent can implement.
2. input_contract / output_contract use simple field names (e.g. "user_input", "db_schema").
3. Keep the number of modules proportional to task complexity (2-8).
4. Copy the prd object verbatim from the input.
5. Constraints must be enforceable rules, e.g. "all code must follow the module split", "tech stack must be {chosen}".

PRD: __PRD_JSON__"""

REVISE_PROMPT = """Revise this blueprint based on the execution failure below.

Current blueprint JSON:
__BLUEPRINT_JSON__

Execution failure:
__FAILURE__

Rules:
1. Keep the overall structure. Only adjust what the failure demands (e.g. module boundaries, contracts, tech stack, constraints).
2. Keep prd verbatim.
3. Output the complete updated blueprint JSON in the same format."""


class Architect:
    """架构规划层：PRD → Blueprint，负责生成与修订，并持久化（版本化）。"""

    def __init__(self, llm_gateway):
        self._llm = llm_gateway
        self._complexity_analyzer = ComplexityAnalyzer()

    async def design(self, prd: dict, requirement: str | None = None) -> dict:
        """PRD → 蓝图内容 dict。LLM 优先，失败回退到启发式模块拆分。"""
        try:
            result = await self._llm.chat(
                model_config={
                    **default_model_config(),
                    "temperature": 0.3,
                    "max_tokens": 4096,
                },
                messages=[
                    {
                        "role": "system",
                        "content": "You are a software architect that outputs valid JSON.",
                    },
                    {
                        "role": "user",
                        "content": ARCHITECT_PROMPT.replace(
                            "__PRD_JSON__", json.dumps(prd, ensure_ascii=False)
                        ),
                    },
                ],
            )
            content = result.get("content", "")
            blueprint = self._parse_llm_output(content, prd)
            if blueprint:
                return blueprint
        except Exception as e:
            logger.warning("LLM blueprint design failed: %s. Using fallback.", e)

        return self._build_fallback_blueprint(prd, requirement or "")

    async def revise(self, blueprint: dict, failure: str) -> dict:
        """依据执行失败原因修订蓝图，返回新蓝图内容 dict。"""
        try:
            result = await self._llm.chat(
                model_config={
                    **default_model_config(),
                    "temperature": 0.4,
                    "max_tokens": 4096,
                },
                messages=[
                    {
                        "role": "system",
                        "content": "You are a software architect that outputs valid JSON.",
                    },
                    {
                        "role": "user",
                        "content": REVISE_PROMPT.replace(
                            "__BLUEPRINT_JSON__", json.dumps(blueprint, ensure_ascii=False)
                        ).replace("__FAILURE__", failure),
                    },
                ],
            )
            content = result.get("content", "")
            revised = self._parse_llm_output(content, blueprint.get("prd", {}))
            if revised:
                return revised
        except Exception as e:
            logger.warning("LLM blueprint revision failed: %s. Keeping original.", e)

        revised = json.loads(json.dumps(blueprint))
        constraints = revised.setdefault("constraints", [])
        note = f"[auto-revised] previous failure: {failure[:200]}"
        if note not in constraints:
            constraints.append(note)
        return revised

    async def save(
        self,
        content: dict,
        db,
        *,
        workflow_id: UUID | None = None,
        source_execution_id: UUID | None = None,
        status: str = "active",
    ) -> Blueprint:
        """持久化蓝图并版本化：旧 active 置 superseded，新记录 version+1。

        status 传 "draft" 时（plan 阶段预览）不参与版本链，仅作草稿。
        """
        next_version = 1
        latest = await self._get_active(db, workflow_id)
        if latest is not None and status == "active":
            next_version = latest.version + 1
            latest.status = "superseded"
            db.add(latest)

        blueprint = Blueprint(
            workflow_id=workflow_id,
            source_execution_id=source_execution_id,
            version=next_version,
            status=status,
            content=content,
        )
        db.add(blueprint)
        await db.flush()
        await db.refresh(blueprint)
        return blueprint

    async def cleanup_dangling_drafts(self, db) -> int:
        """清理悬挂草稿：workflow_id 与 source_execution_id 均为 NULL 的
        plan 预览记录，但保留最新一条（供 confirm 阶段回填 blueprint_id 使用），
        避免无限堆积。
        """
        latest = (
            await db.execute(
                select(Blueprint)
                .where(
                    Blueprint.workflow_id.is_(None),
                    Blueprint.source_execution_id.is_(None),
                )
                .order_by(Blueprint.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        q = delete(Blueprint).where(
            Blueprint.workflow_id.is_(None),
            Blueprint.source_execution_id.is_(None),
        )
        if latest is not None:
            q = q.where(Blueprint.id != latest.id)
        result = await db.execute(q)
        deleted = result.rowcount or 0
        if deleted:
            logger.info("Cleaned up %d dangling blueprint drafts", deleted)
        return deleted

    async def get_latest(self, db, workflow_id: UUID) -> Blueprint | None:
        return await self._get_active(db, workflow_id)

    async def _get_active(self, db, workflow_id: UUID | None) -> Blueprint | None:
        if workflow_id is None:
            return None
        result = await db.execute(
            select(Blueprint)
            .where(
                Blueprint.workflow_id == workflow_id,
                Blueprint.status == "active",
            )
            .order_by(Blueprint.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _parse_llm_output(self, content: str, prd: dict) -> dict | None:
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
                logger.warning("No valid JSON found in LLM blueprint output")
                return None
            try:
                data = json.loads(content[brace_start : brace_end + 1])
            except json.JSONDecodeError:
                return None

        if not isinstance(data.get("modules"), list) or not data["modules"]:
            logger.warning("LLM blueprint output missing modules")
            return None

        if not data.get("prd"):
            data["prd"] = prd

        return data

    def _build_fallback_blueprint(self, prd: dict, requirement: str) -> dict:
        """启发式回退：按复杂度推荐团队拆模块，生成基础蓝图。"""
        complexity = self._complexity_analyzer.analyze(requirement or prd.get("summary", ""))
        roles = complexity.recommended_agents

        module_by_role = {
            "product_manager": ("pm", "Product & Requirements", ["feasibility", "scope"], ["scope_definition"]),
            "system_architect": ("architecture", "System Architecture", ["scope_definition"], ["architecture_design"]),
            "database_engineer": ("data", "Data & Storage", ["architecture_design"], ["db_schema"]),
            "backend_developer": ("backend", "Backend Services", ["architecture_design", "db_schema"], ["api_impl"]),
            "frontend_developer": ("frontend", "Frontend UI", ["architecture_design", "api_impl"], ["ui_impl"]),
            "security_reviewer": ("security", "Security Review", ["backend", "frontend"], ["security_report"]),
            "qa_engineer": ("qa", "Quality Assurance", ["backend", "frontend"], ["test_report"]),
            "devops_engineer": ("devops", "Deployment", ["backend", "frontend"], ["deploy_guide"]),
            "requirement_analyst": ("requirements", "Requirements", ["feasibility"], ["requirement_spec"]),
            "architect": ("architecture", "System Architecture", ["requirement_spec"], ["architecture_design"]),
            "developer": ("core", "Core Implementation", [], ["implementation"]),
            "tester": ("qa", "Quality Assurance", ["implementation"], ["test_report"]),
        }

        modules = []
        seen: set[str] = set()
        for agent in roles:
            spec = module_by_role.get(agent["role"])
            if spec is None:
                continue
            mid, name, deps, outputs = spec
            if mid in seen:
                continue
            seen.add(mid)
            modules.append(
                {
                    "id": mid,
                    "name": name,
                    "description": f"{name} 模块：对应 {agent['label']} 职责",
                    "depends_on": deps,
                    "input_contract": ["requirement"] + [d for d in deps if d not in ("architecture_design",)],
                    "output_contract": outputs,
                }
            )

        if not modules:
            modules = [
                {
                    "id": "core",
                    "name": "Core Implementation",
                    "description": "核心实现",
                    "depends_on": [],
                    "input_contract": ["requirement"],
                    "output_contract": ["implementation"],
                }
            ]

        return {
            "prd": prd,
            "architecture": {
                "tech_stack": ["opencode_cli"],
                "directory_structure": ["src/"],
                "data_model": [],
                "api_contracts": [],
            },
            "modules": modules,
            "constraints": [
                "所有实现必须遵守模块划分，不得越权修改其他模块",
                "技术栈由执行环境决定（opencode_cli）",
            ],
        }
