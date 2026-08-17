import logging

logger = logging.getLogger(__name__)


class PlanningReview:
    @staticmethod
    def review(workflow: dict) -> dict:
        warnings: list[str] = []
        suggestions: list[str] = []
        approved = True

        nodes = workflow.get("nodes", [])
        edges = workflow.get("edges", [])

        node_count = len(nodes)
        if node_count > 15:
            warnings.append(f"Node count ({node_count}) exceeds 15 — may increase complexity")
            approved = False

        edge_count = len(edges)
        if edge_count > 30:
            warnings.append(f"Edge count ({edge_count}) exceeds 30 — DAG may be hard to maintain")

        node_ids = [n.get("id") for n in nodes]
        if len(node_ids) != len(set(node_ids)):
            duplicates = [nid for nid in node_ids if node_ids.count(nid) > 1]
            warnings.append(f"Duplicate node IDs found: {list(set(duplicates))}")
            approved = False

        depth = PlanningReview._compute_dag_depth(nodes, edges)
        if depth > 10:
            warnings.append(f"DAG depth ({depth}) exceeds 10 — consider reducing sequential steps")
            suggestions.append("Merge sequential agent nodes or use parallel branches")

        if PlanningReview._has_cycle(nodes, edges):
            warnings.append("DAG contains a cycle — workflow cannot execute")
            approved = False

        if not planningreview_check_single_root(nodes, edges):
            suggestions.append("DAG has multiple root nodes — consider adding a single start node")

        if not planningreview_check_single_terminal(nodes, edges):
            suggestions.append("DAG has multiple terminal nodes — consider adding a single end node")

        if node_count < 2:
            suggestions.append("Workflow has fewer than 2 nodes — is this intentional?")

        return {
            "approved": approved,
            "warnings": warnings,
            "suggestions": suggestions,
        }

    @staticmethod
    def review_against_blueprint(workflow: dict, blueprint: dict | None) -> dict:
        """蓝图一致性校验：DAG 必须完整覆盖蓝图模块且遵守模块契约。

        检查项：
        1. 覆盖率：每个蓝图模块至少有一个节点实现（config.module_id）
        2. 合规性：agent 节点的 module_id 必须存在于蓝图
        3. 数据流：节点 input/output mapping 字段 ⊆ 该模块契约字段
        """
        warnings: list[str] = []
        suggestions: list[str] = []
        approved = True

        if not blueprint or not isinstance(blueprint, dict):
            return {"approved": True, "warnings": warnings, "suggestions": suggestions}

        modules = blueprint.get("modules") or []
        if not modules:
            return {"approved": True, "warnings": warnings, "suggestions": suggestions}

        module_ids = [m.get("id") for m in modules if m.get("id")]
        covered: set[str] = set()
        node_module_ids: list[str] = []

        for node in workflow.get("nodes", []):
            if node.get("type") != "agent":
                continue
            config = node.get("config") or {}
            module_id = config.get("module_id")
            node_module_ids.append(module_id)
            if module_id:
                if module_id not in module_ids:
                    warnings.append(
                        f"Node '{node.get('id')}' declares unknown module_id '{module_id}'"
                    )
                    approved = False
                else:
                    covered.add(module_id)
                    module = next(m for m in modules if m.get("id") == module_id)
                    if not PlanningReview._check_contract_fields(node, module, warnings):
                        approved = False

        missing = [mid for mid in module_ids if mid not in covered]
        if missing:
            warnings.append(f"Blueprint modules not covered by any node: {missing}")
            approved = False
            suggestions.append("Add one node per uncovered module (config.module_id)")

        if not node_module_ids:
            warnings.append("No agent node declares a module_id — blueprint constraints not enforced")
            approved = False

        return {"approved": approved, "warnings": warnings, "suggestions": suggestions}

    @staticmethod
    def _check_contract_fields(node: dict, module: dict, warnings: list[str]) -> bool:
        input_contract = set(module.get("input_contract") or [])
        output_contract = set(module.get("output_contract") or [])
        ok = True

        for mapping in node.get("input_mapping", []):
            target = mapping.get("target")
            source = mapping.get("source", "")
            if target and input_contract and target not in input_contract and source != "$.requirement":
                warnings.append(
                    f"Node '{node.get('id')}' input field '{target}' not in "
                    f"module '{module.get('id')}' input_contract {sorted(input_contract)}"
                )
                ok = False

        for mapping in node.get("output_mapping", []):
            source = mapping.get("source")
            if source and output_contract and source not in output_contract:
                warnings.append(
                    f"Node '{node.get('id')}' output field '{source}' not in "
                    f"module '{module.get('id')}' output_contract {sorted(output_contract)}"
                )
                ok = False

        return ok

    @staticmethod
    def _compute_dag_depth(nodes: list[dict], edges: list[dict]) -> int:
        if not edges:
            return len(nodes) if nodes else 0

        children: dict[str, list[str]] = {}
        in_degree: dict[str, int] = {}
        for n in nodes:
            nid = n.get("id", "")
            children.setdefault(nid, [])
            in_degree.setdefault(nid, 0)

        for e in edges:
            src = e.get("source", "")
            tgt = e.get("target", "")
            children.setdefault(src, []).append(tgt)
            in_degree.setdefault(tgt, 0)
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        depth_map = {nid: 1 for nid in queue}
        for nid in queue:
            for child in children.get(nid, []):
                new_depth = depth_map[nid] + 1
                if new_depth > depth_map.get(child, 0):
                    depth_map[child] = new_depth
                    queue.append(child)
        return max(depth_map.values()) if depth_map else 0

    @staticmethod
    def _has_cycle(nodes: list[dict], edges: list[dict]) -> bool:
        children: dict[str, list[str]] = {}
        in_degree: dict[str, int] = {}
        for n in nodes:
            nid = n.get("id", "")
            children.setdefault(nid, [])
            in_degree.setdefault(nid, 0)
        for e in edges:
            src = e.get("source", "")
            tgt = e.get("target", "")
            children.setdefault(src, []).append(tgt)
            in_degree.setdefault(tgt, 0)
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        visited = 0
        while queue:
            nid = queue.pop()
            visited += 1
            for child in children.get(nid, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)
        return visited != len(nodes)


def planningreview_check_single_root(nodes: list[dict], edges: list[dict]) -> bool:
    has_incoming: set[str] = {e.get("source", "") for e in edges}
    targets: set[str] = {e.get("target", "") for e in edges}
    roots = [nid for nid in has_incoming if nid not in targets]
    return len(roots) <= 1


def planningreview_check_single_terminal(nodes: list[dict], edges: list[dict]) -> bool:
    sources: set[str] = {e.get("source", "") for e in edges}
    all_node_ids = {n.get("id", "") for n in nodes}
    terminals = [nid for nid in all_node_ids if nid not in sources]
    return len(terminals) <= 1
