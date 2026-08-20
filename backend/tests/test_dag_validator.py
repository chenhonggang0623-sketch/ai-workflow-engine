from app.engine.dag_validator import validate_dag, DagLimits, resolve_dag_limits


def _node(nid, input_mapping=None, output_mapping=None, timeout=300, type="agent"):
    node = {"id": nid, "type": type, "config": {"timeout_seconds": timeout}}
    if input_mapping is not None:
        node["input_mapping"] = input_mapping
    if output_mapping is not None:
        node["output_mapping"] = output_mapping
    return node


def _dag(nodes, edges):
    return {"nodes": nodes, "edges": edges}


class TestDAGValidatorBasics:
    def test_valid_dag_approved(self):
        wf = _dag(
            [
                _node("a", output_mapping=[{"source": "x", "target": "$.foo"}]),
                _node(
                    "b",
                    input_mapping=[{"source": "$.foo", "target": "in"}],
                    output_mapping=[{"source": "y", "target": "$.bar"}],
                ),
                _node("c", input_mapping=[{"source": "$.bar", "target": "in"}]),
            ],
            [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
        )
        report = validate_dag(wf)
        assert report.approved
        assert report.errors == []

    def test_empty_dag_rejected(self):
        report = validate_dag({"nodes": [], "edges": []})
        assert not report.approved
        assert report.errors[0].code == "EMPTY_DAG"

    def test_size_limits(self):
        nodes = [_node(f"n{i}") for i in range(40)]
        report = validate_dag(_dag(nodes, []))
        assert any(e.code == "NODE_SIZE_LIMIT" for e in report.errors)

    def test_unknown_edge_endpoints(self):
        report = validate_dag(_dag(
            [_node("a")],
            [{"source": "a", "target": "ghost"}, {"source": "ghost2", "target": "a"}],
        ))
        codes = {e.code for e in report.errors}
        assert "EDGE_UNKNOWN_SOURCE" in codes
        assert "EDGE_UNKNOWN_TARGET" in codes


class TestDAGValidatorDataFlow:
    def test_input_with_no_producer(self):
        wf = _dag(
            [_node("a", input_mapping=[{"source": "$.nope", "target": "in"}])],
            [],
        )
        report = validate_dag(wf)
        assert not report.approved
        assert any(e.code == "INPUT_NO_SOURCE" for e in report.errors)

    def test_plan_source_requires_plan_node_upstream(self):
        """$.plan 源必须有方案节点（planner 类型）上游；缺失时明确报错。"""
        wf = _dag(
            [
                _node(
                    "plan",
                    type="planner",
                    input_mapping=[{"source": "$.requirement", "target": "requirement"}],
                    output_mapping=[
                        {"source": "plan", "target": "$.plan"},
                        {"source": "plan_markdown", "target": "$.plan_markdown"},
                    ],
                    timeout=120,
                ),
                _node(
                    "impl",
                    input_mapping=[{"source": "$.plan", "target": "plan"}],
                    output_mapping=[{"source": "x", "target": "$.out"}],
                ),
            ],
            [{"source": "plan", "target": "impl"}],
        )
        report = validate_dag(wf)
        assert report.approved
        assert not any(e.code == "INPUT_NO_SOURCE" for e in report.errors)

    def test_plan_source_without_plan_node_rejected(self):
        wf = _dag(
            [_node("a", input_mapping=[{"source": "$.plan", "target": "plan"}])],
            [],
        )
        report = validate_dag(wf)
        assert not report.approved
        assert any(e.code == "INPUT_NO_SOURCE" for e in report.errors)

    def test_input_produced_by_downstream_not_ancestor(self):
        wf = _dag(
            [
                _node("a", input_mapping=[{"source": "$.later", "target": "in"}]),
                _node("b", output_mapping=[{"source": "x", "target": "$.later"}]),
            ],
            [],  # no edge b->a, so b is NOT upstream of a
        )
        report = validate_dag(wf)
        assert any(e.code == "INPUT_NO_SOURCE" for e in report.errors)

    def test_input_from_any_ancestor_ok(self):
        wf = _dag(
            [
                _node("root", output_mapping=[{"source": "x", "target": "$.r"}]),
                _node(
                    "mid",
                    output_mapping=[{"source": "y", "target": "$.m"}],
                    input_mapping=[{"source": "$.r", "target": "in"}],
                ),
                _node(
                    "leaf",
                    input_mapping=[{"source": "$.r", "target": "in"},
                                   {"source": "$.m", "target": "in2"}],
                ),
            ],
            [{"source": "root", "target": "mid"}, {"source": "mid", "target": "leaf"}],
        )
        report = validate_dag(wf)
        assert report.approved

    def test_requirement_always_available(self):
        wf = _dag(
            [_node("a", input_mapping=[{"source": "$.requirement", "target": "req"}])],
            [],
        )
        assert validate_dag(wf).approved

    def test_unconsumed_output_warns(self):
        wf = _dag(
            [
                _node("a", output_mapping=[{"source": "x", "target": "$.foo"}]),
                _node("b", input_mapping=[{"source": "$.requirement", "target": "req"}]),
            ],
            [{"source": "a", "target": "b"}],
        )
        report = validate_dag(wf)
        assert any(w.code == "OUTPUT_UNCONSUMED" for w in report.warnings)


class TestDAGValidatorStructure:
    def test_orphan_node_is_error(self):
        wf = _dag([_node("a"), _node("b")], [])
        report = validate_dag(wf)
        orphans = [e for e in report.errors if e.code == "ORPHAN_NODE"]
        assert len(orphans) == 2
        assert not report.approved

    def test_disconnected_component_is_error(self):
        wf = _dag(
            [_node("a"), _node("b"), _node("c"), _node("d")],
            [
                {"source": "a", "target": "b"},
                {"source": "c", "target": "d"},
            ],
        )
        report = validate_dag(wf)
        assert not report.approved
        assert any(e.code == "DISCONNECTED" for e in report.errors)

    def test_connected_dag_approved(self):
        wf = _dag(
            [_node("a"), _node("b"), _node("c"), _node("d")],
            [
                {"source": "a", "target": "b"},
                {"source": "a", "target": "c"},
                {"source": "c", "target": "d"},
            ],
        )
        report = validate_dag(wf)
        assert report.approved
        assert not any(e.code == "DISCONNECTED" for e in report.errors)

    def test_fan_in_limit(self):
        nodes = [_node("agg"), *[_node(f"src{i}") for i in range(10)]]
        edges = [{"source": f"src{i}", "target": "agg"} for i in range(10)]
        report = validate_dag(_dag(nodes, edges))
        assert any(w.code == "FAN_IN_LIMIT" for w in report.warnings)

    def test_fan_out_limit(self):
        nodes = [_node("src"), *[_node(f"dst{i}") for i in range(8)]]
        edges = [{"source": "src", "target": f"dst{i}"} for i in range(8)]
        report = validate_dag(_dag(nodes, edges))
        assert any(w.code == "FAN_OUT_LIMIT" for w in report.warnings)

    def test_timeout_budget(self):
        nodes = [_node(f"n{i}", timeout=900) for i in range(6)]
        report = validate_dag(_dag(nodes, []))
        assert any(w.code == "TIMEOUT_BUDGET" for w in report.warnings)


class TestDAGValidatorConfigurableLimits:
    def test_limits_override_default_size(self):
        nodes = [_node(f"n{i}") for i in range(40)]
        edges = [
            {"source": f"n{i}", "target": f"n{i+1}"} for i in range(39)
        ]
        report = validate_dag(_dag(nodes, edges), limits=DagLimits(max_nodes=50))
        assert report.approved
        assert not any(e.code == "NODE_SIZE_LIMIT" for e in report.errors)

        tight = validate_dag(_dag(nodes, edges), limits=DagLimits(max_nodes=10))
        assert any(e.code == "NODE_SIZE_LIMIT" for e in tight.errors)

    def test_limits_override_fan_in(self):
        nodes = [_node("agg"), *[_node(f"src{i}") for i in range(10)]]
        edges = [{"source": f"src{i}", "target": "agg"} for i in range(10)]
        report = validate_dag(
            _dag(nodes, edges), limits=DagLimits(max_fan_in=20)
        )
        assert report.approved
        assert not any(w.code == "FAN_IN_LIMIT" for w in report.warnings)

    def test_limits_override_timeout_budget(self):
        nodes = [_node(f"n{i}", timeout=900) for i in range(6)]
        report = validate_dag(
            _dag(nodes, []), limits=DagLimits(timeout_budget_seconds=10000)
        )
        assert not any(w.code == "TIMEOUT_BUDGET" for w in report.warnings)

    def test_resolve_dag_limits_reads_config_store(self):
        class StubStore:
            def get(self, key, default=None):
                mapping = {
                    "dag_max_nodes": 5,
                    "dag_max_edges": 10,
                    "dag_max_fan_in": 3,
                    "dag_max_fan_out": 2,
                    "dag_timeout_budget_seconds": 120,
                }
                return mapping.get(key, default)

        resolved = resolve_dag_limits(StubStore())
        assert resolved.max_nodes == 5
        assert resolved.max_edges == 10
        assert resolved.max_fan_in == 3
        assert resolved.max_fan_out == 2
        assert resolved.timeout_budget_seconds == 120

        none_resolved = resolve_dag_limits(None)
        assert none_resolved.resolved == {
            "max_nodes": 32,
            "max_edges": 96,
            "max_fan_in": 8,
            "max_fan_out": 6,
            "timeout_budget_seconds": 3600,
        }

    def test_validate_with_resolved_limits(self):
        nodes = [_node(f"n{i}") for i in range(6)]
        report = validate_dag(_dag(nodes, []), limits=DagLimits(max_nodes=5))
        assert any(e.code == "NODE_SIZE_LIMIT" for e in report.errors)