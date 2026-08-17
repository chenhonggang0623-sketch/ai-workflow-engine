import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.planner.architect import Architect

SAMPLE_PRD = {
    "summary": "Blog system",
    "goals": ["publish posts"],
    "features": ["create post", "list posts"],
    "non_functional": [],
    "acceptance_criteria": ["can create post"],
    "assumptions": [],
    "open_questions": [],
}

SAMPLE_BLUEPRINT = {
    "prd": SAMPLE_PRD,
    "architecture": {"tech_stack": ["python"], "directory_structure": [], "data_model": [], "api_contracts": []},
    "modules": [
        {
            "id": "backend",
            "name": "Backend",
            "description": "server",
            "depends_on": [],
            "input_contract": ["requirement"],
            "output_contract": ["api_impl"],
        },
        {
            "id": "frontend",
            "name": "Frontend",
            "description": "ui",
            "depends_on": ["backend"],
            "input_contract": ["api_impl"],
            "output_contract": ["ui_impl"],
        },
    ],
    "constraints": ["follow module split"],
}


def make_llm(content):
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value={"content": content, "tool_calls": [], "usage": {}})
    return llm


class TestArchitectDesign:
    @pytest.mark.asyncio
    async def test_llm_success(self):
        llm = make_llm(json.dumps(SAMPLE_BLUEPRINT))
        bp = await Architect(llm).design(SAMPLE_PRD, "build a blog")
        assert bp["prd"]["summary"] == "Blog system"
        assert len(bp["modules"]) == 2
        assert bp["modules"][0]["id"] == "backend"

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=Exception("LLM down"))
        bp = await Architect(llm).design(SAMPLE_PRD, "build a blog system")
        assert bp["modules"], "fallback must produce modules"
        assert bp["constraints"]

    @pytest.mark.asyncio
    async def test_llm_missing_modules_falls_back(self):
        llm = make_llm(json.dumps({"prd": SAMPLE_PRD, "architecture": {}}))
        bp = await Architect(llm).design(SAMPLE_PRD, "build a blog system")
        assert bp["modules"]

    @pytest.mark.asyncio
    async def test_prompt_handles_braces_in_prd(self):
        weird = dict(SAMPLE_PRD)
        weird["summary"] = "contains {braces} and {{nested}}"
        llm = make_llm(json.dumps(SAMPLE_BLUEPRINT))
        bp = await Architect(llm).design(weird, "x")
        assert bp["modules"]


class TestArchitectRevise:
    @pytest.mark.asyncio
    async def test_llm_revise_success(self):
        llm = make_llm(json.dumps(SAMPLE_BLUEPRINT))
        revised = await Architect(llm).revise(SAMPLE_BLUEPRINT, "backend module failed")
        assert revised["modules"][0]["id"] == "backend"

    @pytest.mark.asyncio
    async def test_llm_failure_keeps_original_and_notes_failure(self):
        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=Exception("LLM down"))
        revised = await Architect(llm).revise(SAMPLE_BLUEPRINT, "backend module failed")
        assert revised["modules"] == SAMPLE_BLUEPRINT["modules"]
        assert any("auto-revised" in c for c in revised["constraints"])
        assert "backend module failed" in revised["constraints"][-1]


class TestArchitectSave:
    def _mock_session(self, latest_version=None):
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        session.execute = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_save_first_version(self):
        architect = Architect(make_llm("{}"))
        session = self._mock_session()
        saved = await architect.save(SAMPLE_BLUEPRINT, session)
        assert saved.version == 1
        assert saved.status == "active"
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_increments_version_and_supersedes(self):
        architect = Architect(make_llm("{}"))

        existing = MagicMock()
        existing.version = 1
        existing.status = "active"

        execute_result = MagicMock()
        execute_result.scalar_one_or_none = MagicMock(return_value=existing)

        session = self._mock_session()
        session.execute = AsyncMock(return_value=execute_result)

        saved = await architect.save(SAMPLE_BLUEPRINT, session, workflow_id=__import__("uuid").uuid4())
        assert saved.version == 2
        assert existing.status == "superseded"

    @pytest.mark.asyncio
    async def test_cleanup_dangling_drafts_keeps_latest(self):
        architect = Architect(make_llm("{}"))

        latest_draft = MagicMock()
        latest_draft.id = __import__("uuid").uuid4()

        schedule = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=latest_draft)),
            MagicMock(rowcount=2),
        ]
        session = MagicMock()
        session.execute = AsyncMock(side_effect=lambda *a, **k: schedule.pop(0))

        deleted = await architect.cleanup_dangling_drafts(session)
        assert deleted == 2
        stmt = session.execute.call_args_list[1].args[0]
        assert str(stmt).startswith("DELETE")
        assert "workflow_id IS NULL" in str(stmt)
        params = stmt.compile().params
        assert latest_draft.id in set(params.values())

    @pytest.mark.asyncio
    async def test_cleanup_dangling_drafts_none_left(self):
        architect = Architect(make_llm("{}"))

        schedule = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            MagicMock(rowcount=3),
        ]
        session = MagicMock()
        session.execute = AsyncMock(side_effect=lambda *a, **k: schedule.pop(0))

        deleted = await architect.cleanup_dangling_drafts(session)
        assert deleted == 3
        stmt = str(session.execute.call_args_list[1].args[0])
        assert stmt.startswith("DELETE")
        assert "workflow_id IS NULL" in stmt
