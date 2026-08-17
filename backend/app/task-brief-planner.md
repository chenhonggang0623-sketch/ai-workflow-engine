# Task: Implement Planner Agent

## Files to create

### 1. `backend/app/planner/__init__.py`
Export: PlannerAgent, WorkflowTemplate, PlanningReview

### 2. `backend/app/planner/planner_agent.py` — PlannerAgent

```python
class PlannerAgent:
    """
    Meta-agent that generates Workflow DAGs from user requirements.
    
    plan(requirement, constraints) → WorkflowPlan
    - Parses natural language requirement
    - Queries available agents/tools from registries
    - Selects appropriate template or generates custom DAG
    - Uses LLM to decompose requirements into steps
    - Returns complete Workflow JSON
    
    WorkflowPlan: {"workflow": {...}, "explanation": "...", "estimated_duration": 300}
    
    For MVP: use template-based approach + LLM refinement.
    1. Classify requirement into template category
    2. Load template (pre-defined DAG structure)
    3. Ask LLM to customize: fill in agent configs, set branch conditions
    4. Validate resulting DAG (no cycles)
    5. Return plan
    """

    def __init__(self, llm_gateway, agent_registry, tool_registry): ...
    async def plan(self, requirement: str, constraints: dict = None) -> dict:
        """
        Returns: {"workflow": WorkflowDefinition, "explanation": str, "estimated_duration_seconds": int}
        """
        ...

    async def _classify_requirement(self, requirement: str) -> str:
        """Classify into 'fullstack-app', 'api-only', 'frontend-only', 'bugfix', etc."""
        ...

    async def _get_template(self, category: str) -> dict: ...
    async def _customize_template(self, template: dict, requirement: str) -> dict:
        """Ask LLM to fill in details of the template based on the requirement."""
        ...

    async def revise(self, plan: dict, feedback: str) -> dict:
        """Revise plan based on user feedback."""
        ...
```

### 3. `backend/app/planner/templates.py` — Workflow Templates

```python
WORKFLOW_TEMPLATES = {
    "fullstack-app": {
        "name": "Full Stack Application Development",
        "description": "Develop a full-stack application with frontend and backend",
        "nodes": [
            {"id": "pm", "type": "agent", "label": "Product Manager",
             "config": {"agent_id": "pm_agent", "timeout_seconds": 300}},
            {"id": "architect", "type": "agent", "label": "Software Architect",
             "config": {"agent_id": "architect_agent", "timeout_seconds": 300}},
            {"id": "planner", "type": "planner", "label": "Task Planner",
             "config": {"agent_id": "planner_agent", "mode": "auto"}},
            {"id": "frontend_dev", "type": "agent", "label": "Frontend Developer",
             "config": {"agent_id": "developer_agent", "timeout_seconds": 600}},
            {"id": "backend_dev", "type": "agent", "label": "Backend Developer",
             "config": {"agent_id": "developer_agent", "timeout_seconds": 600}},
            {"id": "qa", "type": "agent", "label": "QA Engineer",
             "config": {"agent_id": "qa_agent", "timeout_seconds": 300}},
            {"id": "review", "type": "condition", "label": "QA Passed?",
             "config": {"expression": "context['qa_result']['passed'] == true",
                        "branches": {"true": "deploy", "false": "frontend_dev"}}},
            {"id": "deploy", "type": "agent", "label": "DevOps",
             "config": {"agent_id": "devops_agent", "timeout_seconds": 300}},
        ],
        "edges": [
            {"id": "e1", "source": "pm", "target": "architect"},
            {"id": "e2", "source": "architect", "target": "planner"},
            {"id": "e3", "source": "planner", "target": "frontend_dev"},
            {"id": "e4", "source": "planner", "target": "backend_dev"},
            {"id": "e5", "source": "frontend_dev", "target": "qa"},
            {"id": "e6", "source": "backend_dev", "target": "qa"},
            {"id": "e7", "source": "qa", "target": "review"},
            {"id": "e8", "source": "review", "target": "deploy", "label": "passed"},
            {"id": "e9", "source": "review", "target": "frontend_dev", "label": "failed"},
        ]
    },
    "api-only": {
        "name": "API Development",
        "description": "Develop a backend API service",
        # Similar structure with fewer nodes
    },
    "frontend-only": {
        "name": "Frontend Development",
        "description": "Develop a frontend application",
        # Frontend-only template
    },
    "bugfix": {
        "name": "Bug Fix",
        "description": "Identify and fix bugs in existing code",
        # Simple: dev -> qa -> deploy
    },
}

class WorkflowTemplate:
    @staticmethod
    def get(category: str) -> dict: ...
    @staticmethod
    def list_categories() -> list[str]: ...
```

### 4. `backend/app/planner/planning_review.py` — PlanningReview (basic)

```python
class PlanningReview:
    """
    Basic complexity review of generated Workflow plans.
    
    For MVP: only checks:
    - Total node count (warn if > 15)
    - DAG depth (warn if > 10)
    - Cycles (block if detected)
    - Duplicate node IDs
    
    Returns: {"approved": bool, "warnings": list[str], "suggestions": list[str]}
    """

    @staticmethod
    def review(workflow: dict) -> dict: ...
```

## Constraints
- PlannerAgent uses LLM to classify requirements and customize templates
- If LLM is unavailable, fall back to template selection by keyword matching
- All template workflows must be valid DAGs (no cycles)
- The planner should NOT generate code — only workflow structure
- Output must be valid WorkflowDefinition JSON

## Output
- Status: DONE / DONE_WITH_CONCERNS / BLOCKED
- Report file: `backend/app/task-brief-planner-report.md`
- Test output summary
