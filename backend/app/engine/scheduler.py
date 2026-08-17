import networkx as nx

from app.engine.types import WorkflowDefinition, NodeDefinition


class DAGScheduler:
    def __init__(self, workflow: WorkflowDefinition):
        self._workflow = workflow
        self._node_map: dict[str, NodeDefinition] = {n.id: n for n in workflow.nodes}
        self._completed: set[str] = set()
        self._in_degree: dict[str, int] = {}

        self._graph = nx.DiGraph()
        for node in workflow.nodes:
            self._graph.add_node(node.id)
        for edge in workflow.edges:
            self._graph.add_edge(edge.source, edge.target)

        for nid in self._graph.nodes:
            self._in_degree[nid] = self._graph.in_degree(nid)

    def get_ready_nodes(self) -> list[NodeDefinition]:
        ready: list[NodeDefinition] = []
        for nid, deg in self._in_degree.items():
            if deg == 0 and nid not in self._completed:
                ready.append(self._node_map[nid])
        return ready

    def mark_completed(self, node_id: str) -> list[NodeDefinition]:
        self._completed.add(node_id)
        newly_ready: list[NodeDefinition] = []
        for successor in self._graph.successors(node_id):
            self._in_degree[successor] -= 1
            if self._in_degree[successor] == 0 and successor not in self._completed:
                newly_ready.append(self._node_map[successor])
        return newly_ready

    def is_complete(self) -> bool:
        return len(self._completed) == len(self._node_map)

    def get_execution_order(self) -> list[list[str]]:
        layers: list[list[str]] = []
        remaining = set(self._graph.nodes)
        in_degree = {n: self._graph.in_degree(n) for n in remaining}

        while remaining:
            layer = [n for n in remaining if in_degree[n] == 0]
            if not layer:
                break
            layers.append(layer)
            remaining -= set(layer)
            for n in layer:
                for s in self._graph.successors(n):
                    if s in remaining:
                        in_degree[s] -= 1

        return layers

    def has_cycle(self) -> bool:
        try:
            list(nx.topological_sort(self._graph))
            return False
        except nx.NetworkXUnfeasible:
            return True
