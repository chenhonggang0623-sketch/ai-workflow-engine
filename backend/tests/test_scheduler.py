import pytest
from app.engine.types import (
    WorkflowDefinition, NodeDefinition, EdgeDefinition,
    NodeType, NodeConfig,
)
from app.engine.scheduler import DAGScheduler


def _make_workflow(nodes: list[dict], edges: list[dict]) -> WorkflowDefinition:
    return WorkflowDefinition(
        name="test",
        nodes=[NodeDefinition(**n) for n in nodes],
        edges=[EdgeDefinition(**e) for e in edges],
    )


def test_get_ready_nodes_initial():
    wf = _make_workflow(
        nodes=[
            {"id": "a", "type": NodeType.AGENT, "label": "A"},
            {"id": "b", "type": NodeType.AGENT, "label": "B"},
            {"id": "c", "type": NodeType.AGENT, "label": "C"},
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    sched = DAGScheduler(wf)
    ready = sched.get_ready_nodes()
    assert {n.id for n in ready} == {"a", "c"}


def test_mark_completed():
    wf = _make_workflow(
        nodes=[
            {"id": "a", "type": NodeType.AGENT, "label": "A"},
            {"id": "b", "type": NodeType.AGENT, "label": "B"},
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    sched = DAGScheduler(wf)
    sched.mark_completed("a")
    assert sched.is_complete() is False
    ready = sched.get_ready_nodes()
    assert [n.id for n in ready] == ["b"]


def test_is_complete():
    wf = _make_workflow(
        nodes=[
            {"id": "a", "type": NodeType.AGENT, "label": "A"},
        ],
        edges=[],
    )
    sched = DAGScheduler(wf)
    assert sched.is_complete() is False
    sched.mark_completed("a")
    assert sched.is_complete() is True


def test_get_execution_order():
    wf = _make_workflow(
        nodes=[
            {"id": "a", "type": NodeType.AGENT, "label": "A"},
            {"id": "b", "type": NodeType.AGENT, "label": "B"},
            {"id": "c", "type": NodeType.AGENT, "label": "C"},
            {"id": "d", "type": NodeType.AGENT, "label": "D"},
        ],
        edges=[
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "a", "target": "c"},
            {"id": "e3", "source": "b", "target": "d"},
            {"id": "e4", "source": "c", "target": "d"},
        ],
    )
    sched = DAGScheduler(wf)
    order = sched.get_execution_order()
    assert len(order) == 3
    assert order[0] == ["a"]
    assert sorted(order[1]) == ["b", "c"]
    assert order[2] == ["d"]


def test_has_cycle():
    wf = _make_workflow(
        nodes=[
            {"id": "a", "type": NodeType.AGENT, "label": "A"},
            {"id": "b", "type": NodeType.AGENT, "label": "B"},
        ],
        edges=[
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "a"},
        ],
    )
    sched = DAGScheduler(wf)
    assert sched.has_cycle() is True


def test_no_cycle():
    wf = _make_workflow(
        nodes=[
            {"id": "a", "type": NodeType.AGENT, "label": "A"},
            {"id": "b", "type": NodeType.AGENT, "label": "B"},
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    sched = DAGScheduler(wf)
    assert sched.has_cycle() is False


def test_ready_nodes_after_partial_completion():
    wf = _make_workflow(
        nodes=[
            {"id": "a", "type": NodeType.AGENT, "label": "A"},
            {"id": "b", "type": NodeType.AGENT, "label": "B"},
            {"id": "c", "type": NodeType.AGENT, "label": "C"},
            {"id": "d", "type": NodeType.AGENT, "label": "D"},
        ],
        edges=[
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "d"},
            {"id": "e3", "source": "c", "target": "d"},
        ],
    )
    sched = DAGScheduler(wf)
    assert {n.id for n in sched.get_ready_nodes()} == {"a", "c"}
    sched.mark_completed("a")
    assert {n.id for n in sched.get_ready_nodes()} == {"b", "c"}
    sched.mark_completed("c")
    assert {n.id for n in sched.get_ready_nodes()} == {"b"}
    sched.mark_completed("b")
    assert {n.id for n in sched.get_ready_nodes()} == {"d"}
