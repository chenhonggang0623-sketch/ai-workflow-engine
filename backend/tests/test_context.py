from app.engine.context_service import ContextService
from app.engine.types import (
    NodeDefinition,
    NodeType,
    InputMapping,
    OutputMapping,
)


def _node(node_id="n1", input_mapping=None, output_mapping=None):
    return NodeDefinition(
        id=node_id,
        type=NodeType.AGENT,
        label=node_id,
        input_mapping=input_mapping or [],
        output_mapping=output_mapping or [],
    )


class TestBuildAgentContext:
    def test_injects_upstream_outputs(self):
        svc = ContextService()
        node = _node(
            "leaf",
            input_mapping=[InputMapping(source="$.a", target="product_doc")],
        )
        ctx = {"product_doc": {"title": "t1"}}
        shared = svc.build_agent_context(node, {}, ctx)
        assert shared["product_doc"] == {"title": "t1"}

    def test_falls_back_to_node_input(self):
        svc = ContextService()
        node = _node(
            "leaf",
            input_mapping=[InputMapping(source="$.req", target="requirement")],
        )
        shared = svc.build_agent_context(
            node, {"requirement": "build x"}, {}
        )
        assert shared["requirement"] == "build x"

    def test_adds_global_requirement(self):
        svc = ContextService()
        node = _node("root")
        shared = svc.build_agent_context(node, {}, {"requirement": "the goal"})
        assert shared["requirement"] == "the goal"

    def test_never_leaks_whole_context(self):
        svc = ContextService()
        node = _node("leaf", input_mapping=[InputMapping(source="$.a", target="a")])
        ctx = {"a": 1, "secret_upstream": "big", "_context_audit": {}}
        shared = svc.build_agent_context(node, {}, ctx)
        assert "secret_upstream" not in shared
        assert "_context_audit" not in shared


class TestNormalizeOutput:
    def test_local_cli_text_output(self):
        svc = ContextService()
        out = svc.normalize_output("codex_cli", {"output": "hello"})
        assert out["text"] == "hello"
        assert not out["empty"]
        assert out["provider"] == "codex_cli"

    def test_llm_api_content_output(self):
        svc = ContextService()
        out = svc.normalize_output("openai", {"content": "hi", "usage": {"n": 1}})
        assert out["text"] == "hi"
        assert out["structured"] == {"usage": {"n": 1}}

    def test_empty_output_marked(self):
        svc = ContextService()
        assert svc.normalize_output("openai", {})["empty"] is True

    def test_truncation(self):
        svc = ContextService(max_node_output_chars=20)
        out = svc.normalize_output("openai", {"content": "x" * 100})
        assert out["truncated"] is True
        assert out["text"].endswith("...(output truncated)")
        assert len(out["text"]) < 50


class TestWriteOutput:
    def test_writes_ctx_and_audit(self):
        svc = ContextService()
        node = _node("n1", output_mapping=[OutputMapping(source="output", target="$.final")])
        ctx = {}
        svc.write_output(ctx, "n1", {"output": "done"}, node.output_mapping)
        assert ctx["$.final"] == "done"
        assert "n1" in ctx["_context_audit"]
        assert ctx["_context_audit"]["n1"]["provider"] == "unknown"