from app.planner.planning_review import PlanningReview


BLUEPRINT = {
    "modules": [
        {
            "id": "backend",
            "name": "Backend",
            "depends_on": [],
            "input_contract": ["requirement"],
            "output_contract": ["api_impl"],
        },
        {
            "id": "frontend",
            "name": "Frontend",
            "depends_on": ["backend"],
            "input_contract": ["api_impl"],
            "output_contract": ["ui_impl"],
        },
    ],
    "constraints": [],
}


def agent_node(node_id, module_id, input_mapping=None, output_mapping=None):
    defaults = {
        "backend": {"out": "api_impl"},
        "frontend": {"out": "ui_impl"},
    }
    out_field = defaults.get(module_id, {}).get("out", "output")
    return {
        "id": node_id,
        "type": "agent",
        "config": {"module_id": module_id},
        "input_mapping": input_mapping or [{"source": "$.requirement", "target": "requirement"}],
        "output_mapping": output_mapping or [{"source": out_field, "target": "$.module"}],
    }


class TestReviewAgainstBlueprint:
    def test_full_coverage_approved(self):
        wf = {
            "nodes": [
                agent_node("b", "backend"),
                agent_node("f", "frontend"),
            ],
            "edges": [{"source": "b", "target": "f"}],
        }
        result = PlanningReview.review_against_blueprint(wf, BLUEPRINT)
        assert result["approved"] is True
        assert result["warnings"] == []

    def test_missing_module_rejected(self):
        wf = {"nodes": [agent_node("b", "backend")], "edges": []}
        result = PlanningReview.review_against_blueprint(wf, BLUEPRINT)
        assert result["approved"] is False
        assert any("not covered" in w for w in result["warnings"])

    def test_unknown_module_id_rejected(self):
        wf = {
            "nodes": [
                agent_node("b", "backend"),
                agent_node("x", "does_not_exist"),
            ],
            "edges": [],
        }
        result = PlanningReview.review_against_blueprint(wf, BLUEPRINT)
        assert result["approved"] is False
        assert any("unknown module_id" in w for w in result["warnings"])

    def test_input_contract_violation_rejected(self):
        wf = {
            "nodes": [
                agent_node("b", "backend", input_mapping=[
                    {"source": "$.requirement", "target": "requirement"},
                    {"source": "$.hack", "target": "undeclared_field"},
                ]),
                agent_node("f", "frontend"),
            ],
            "edges": [],
        }
        result = PlanningReview.review_against_blueprint(wf, BLUEPRINT)
        assert result["approved"] is False
        assert any("undeclared_field" in w for w in result["warnings"])

    def test_output_contract_violation_rejected(self):
        wf = {
            "nodes": [
                agent_node("b", "backend", output_mapping=[
                    {"source": "not_in_contract", "target": "$.x"},
                ]),
                agent_node("f", "frontend"),
            ],
            "edges": [],
        }
        result = PlanningReview.review_against_blueprint(wf, BLUEPRINT)
        assert result["approved"] is False
        assert any("not_in_contract" in w for w in result["warnings"])

    def test_no_agent_nodes_rejected(self):
        wf = {"nodes": [{"id": "t", "type": "tool", "config": {}}], "edges": []}
        result = PlanningReview.review_against_blueprint(wf, BLUEPRINT)
        assert result["approved"] is False
        assert any("module_id" in w for w in result["warnings"])

    def test_blueprint_none_bypasses(self):
        result = PlanningReview.review_against_blueprint(
            {"nodes": [agent_node("b", "backend")], "edges": []}, None
        )
        assert result["approved"] is True

    def test_blueprint_empty_modules_bypasses(self):
        result = PlanningReview.review_against_blueprint(
            {"nodes": [], "edges": []}, {"modules": []}
        )
        assert result["approved"] is True
