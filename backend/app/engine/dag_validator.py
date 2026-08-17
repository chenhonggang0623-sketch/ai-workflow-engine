import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DAGIssue(BaseModel):
    code: str
    level: str = "warning"  # "error" | "warning"
    node_id: str | None = None
    message: str


class ValidationReport(BaseModel):
    approved: bool
    errors: list[DAGIssue] = Field(default_factory=list)
    warnings: list[DAGIssue] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


MAX_NODES = 32
MAX_EDGES = 96
MAX_FAN_IN = 8
MAX_FAN_OUT = 6
DEFAULT_TIMEOUT_BUDGET_SECONDS = 3600

# 与 config_store / Settings 中的键一一对应，便于上层覆盖
DAG_LIMIT_KEYS = (
    "dag_max_nodes",
    "dag_max_edges",
    "dag_max_fan_in",
    "dag_max_fan_out",
    "dag_timeout_budget_seconds",
)


class DagLimits(BaseModel):
    """DAG 校验阈值，None 表示使用默认常量。"""

    max_nodes: int | None = None
    max_edges: int | None = None
    max_fan_in: int | None = None
    max_fan_out: int | None = None
    timeout_budget_seconds: int | None = None

    @property
    def resolved(self) -> dict:
        return {
            "max_nodes": self.max_nodes or MAX_NODES,
            "max_edges": self.max_edges or MAX_EDGES,
            "max_fan_in": self.max_fan_in or MAX_FAN_IN,
            "max_fan_out": self.max_fan_out or MAX_FAN_OUT,
            "timeout_budget_seconds": self.timeout_budget_seconds
            or DEFAULT_TIMEOUT_BUDGET_SECONDS,
        }


def resolve_dag_limits(config_store) -> DagLimits:
    """从 config_store 读取可选覆盖（如 dag_max_nodes），未配置则回落默认常量。"""
    return DagLimits(
        max_nodes=config_store.get("dag_max_nodes") if config_store else None,
        max_edges=config_store.get("dag_max_edges") if config_store else None,
        max_fan_in=config_store.get("dag_max_fan_in") if config_store else None,
        max_fan_out=config_store.get("dag_max_fan_out") if config_store else None,
        timeout_budget_seconds=config_store.get("dag_timeout_budget_seconds")
        if config_store
        else None,
    )


def validate_dag(workflow: dict, limits: DagLimits | None = None) -> ValidationReport:
    """DAG 静态校验（生成后、执行前，零 LLM 成本）。

    在 PlanningReview 的结构校验（环/去重/规模）之上，补充：
    - INPUT_NO_SOURCE: input_mapping.source 必须能被上游（或 $.requirement）提供
    - OUTPUT_UNCONSUMED: 输出字段无人消费（末端节点豁免）
    - ORPHAN_NODE: 孤立节点（无入边无出边）
    - FAN_IN_LIMIT / FAN_OUT_LIMIT: 扇入扇出风暴
    - TIMEOUT_BUDGET: 全 DAG 超时预算
    """
    nodes = workflow.get("nodes", []) or []
    edges = workflow.get("edges", []) or []

    limits = (limits or DagLimits()).resolved
    max_nodes = limits["max_nodes"]
    max_edges = limits["max_edges"]
    max_fan_in = limits["max_fan_in"]
    max_fan_out = limits["max_fan_out"]
    timeout_budget_seconds = limits["timeout_budget_seconds"]

    errors: list[DAGIssue] = []
    warnings: list[DAGIssue] = []
    suggestions: list[str] = []

    node_ids = [n.get("id", "") for n in nodes]
    id_set = set(node_ids)

    if not nodes:
        errors.append(DAGIssue(code="EMPTY_DAG", level="error", message="Workflow has no nodes"))
        return _report(errors, warnings, suggestions)

    if len(nodes) > max_nodes:
        errors.append(DAGIssue(
            code="NODE_SIZE_LIMIT",
            level="error",
            message=f"Node count ({len(nodes)}) exceeds limit {max_nodes}",
        ))
    if len(edges) > max_edges:
        errors.append(DAGIssue(
            code="EDGE_SIZE_LIMIT",
            level="error",
            message=f"Edge count ({len(edges)}) exceeds limit {max_edges}",
        ))

    # 图结构：邻接表、入度、出度、孤点
    children: dict[str, list[str]] = {nid: [] for nid in id_set}
    parents: dict[str, list[str]] = {nid: [] for nid in id_set}
    in_degree: dict[str, int] = {nid: 0 for nid in id_set}
    out_degree: dict[str, int] = {nid: 0 for nid in id_set}
    ancestors_cache: dict[str, set[str]] = {}

    for e in edges:
        src, tgt = e.get("source", ""), e.get("target", "")
        if src not in id_set:
            errors.append(DAGIssue(
                code="EDGE_UNKNOWN_SOURCE", level="error",
                node_id=tgt, message=f"Edge source '{src}' is not a node id",
            ))
            continue
        if tgt not in id_set:
            errors.append(DAGIssue(
                code="EDGE_UNKNOWN_TARGET", level="error",
                node_id=src, message=f"Edge target '{tgt}' is not a node id",
            ))
            continue
        children[src].append(tgt)
        parents[tgt].append(src)
        in_degree[tgt] += 1
        out_degree[src] += 1

    # 祖先（沿反向边传递闭包）计算一次，供数据流闭合检查
    def _ancestors(nid: str) -> set[str]:
        if nid in ancestors_cache:
            return ancestors_cache[nid]
        result: set[str] = set()
        stack = list(parents[nid])
        seen: set[str] = {nid}
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            result.add(cur)
            stack.extend(parents[cur])
        ancestors_cache[nid] = result
        return result

    # 数据流闭合：每个 input source 都有生产者，且生产者在该节点上游
    producers: dict[str, set[str]] = {}  # context 键 -> 生产它的节点集合
    for n in nodes:
        nid = n.get("id", "")
        for mapping in n.get("output_mapping", []) or []:
            target = mapping.get("target", "")
            if target:
                producers.setdefault(target, set()).add(nid)

    consumed_source: dict[str, int] = {}
    for n in nodes:
        nid = n.get("id", "")
        for mapping in n.get("input_mapping", []) or []:
            source = mapping.get("source", "")
            if source == "$.requirement":
                continue
            producer_set = producers.get(source)
            if not producer_set:
                errors.append(DAGIssue(
                    code="INPUT_NO_SOURCE",
                    level="error",
                    node_id=nid,
                    message=f"Input '{source}' has no producer: no node outputs this context key "
                            f"(and it is not $.requirement)",
                ))
            else:
                available = any(anc in _ancestors(nid)
                                or anc == nid
                                for anc in producer_set)
                if not available:
                    errors.append(DAGIssue(
                        code="INPUT_NO_SOURCE",
                        level="error",
                        node_id=nid,
                        message=f"Input '{source}' is produced by {sorted(producer_set)} but "
                                f"none of them is upstream of '{nid}'",
                    ))
                consumed_source[source] = consumed_source.get(source, 0) + 1

    # 输出未消费（末端节点豁免：末端输出即最终交付物）
    terminal = {nid for nid in node_ids if out_degree[nid] == 0}
    for n in nodes:
        nid = n.get("id", "")
        for mapping in n.get("output_mapping", []) or []:
            target = mapping.get("target", "")
            no_consumers = consumed_source.get(target, 0) == 0
            if no_consumers and nid not in terminal:
                warnings.append(DAGIssue(
                    code="OUTPUT_UNCONSUMED",
                    level="warning",
                    node_id=nid,
                    message=f"Output '{target}' is never referenced by any downstream input",
                ))

    # 孤点
    orphans = [nid for nid in node_ids
               if in_degree[nid] == 0 and out_degree[nid] == 0 and len(nodes) > 1]
    for nid in orphans:
        errors.append(DAGIssue(
            code="ORPHAN_NODE",
            level="error",
            node_id=nid,
            message=f"Node '{nid}' has no incoming or outgoing edges — it will never "
                    f"run and cannot be reached",
        ))
    if orphans:
        suggestions.append("Connect orphan nodes to the existing DAG or remove them")

    # 连通性：整个 DAG 必须是一个弱连通分量（把边视为无向，从任意节点出发
    # 必须能到达所有节点）。断连组件 / 半孤立节点意味着「线段连接不上」：
    # 节点要么永远不被调度，要么脱离主流水线顺序，视为 error。
    # （对无环图，弱连通 ⇔ 每个节点都处于「从某起点可达」且「能到达某终点」的路径上）
    if len(node_ids) > 1:
        visited: set[str] = set()
        stack = [node_ids[0]]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            stack.extend(children[cur])
            stack.extend(parents[cur])
        disconnected = [nid for nid in node_ids if nid not in visited]
        for nid in disconnected:
            errors.append(DAGIssue(
                code="DISCONNECTED",
                level="error",
                node_id=nid,
                message=f"Node '{nid}' is disconnected from the main DAG — no line "
                        f"connects it to the rest of the graph",
            ))
        if disconnected:
            suggestions.append("Connect disconnected nodes into the main chain so "
                               "every node runs in order")

    # 扇入扇出
    for nid in node_ids:
        if in_degree[nid] > max_fan_in:
            warnings.append(DAGIssue(
                code="FAN_IN_LIMIT", level="warning", node_id=nid,
                message=f"Node '{nid}' has fan-in {in_degree[nid]} (limit {max_fan_in})",
            ))
        if out_degree[nid] > max_fan_out:
            warnings.append(DAGIssue(
                code="FAN_OUT_LIMIT", level="warning", node_id=nid,
                message=f"Node '{nid}' has fan-out {out_degree[nid]} (limit {max_fan_out})",
            ))
    if any(w.code == "FAN_IN_LIMIT" for w in warnings):
        suggestions.append("High fan-in: add an aggregator/condition node")

    # 超时预算
    total_timeout = sum(
        (n.get("config") or {}).get("timeout_seconds", 300) for n in nodes
    )
    if total_timeout > timeout_budget_seconds:
        warnings.append(DAGIssue(
            code="TIMEOUT_BUDGET",
            level="warning",
            message=f"Total node timeout ({total_timeout}s) exceeds budget "
                    f"({timeout_budget_seconds}s)",
        ))

    return _report(errors, warnings, suggestions)


def _report(
    errors: list[DAGIssue],
    warnings: list[DAGIssue],
    suggestions: list[str],
) -> ValidationReport:
    return ValidationReport(
        approved=not errors,
        errors=errors,
        warnings=warnings,
        suggestions=suggestions,
    )


def ensure_dag_connected(workflow: dict) -> dict:
    """修复断连的 DAG：把孤立节点 / 断连组件按顺序串入主链。

    策略（确定性、零 LLM 成本）：
    1. 以无向连通分量划分节点，包含首个节点的分量为「主链」；
    2. 其余分量各取拓扑序第一个节点作为入口；
    3. 依次把主链末尾（拓扑序最后节点）与下一分量的入口连边，
       形成单条弱连通 DAG，且不会引入环。

    返回修复后的 workflow（副本，不修改入参）。
    """
    nodes = list(workflow.get("nodes", []) or [])
    edges = [dict(e) for e in (workflow.get("edges", []) or [])]
    if len(nodes) <= 1:
        return {**workflow, "nodes": nodes, "edges": edges}

    node_ids = [n.get("id", "") for n in nodes]
    id_set = set(node_ids)
    children: dict[str, list[str]] = {nid: [] for nid in id_set}
    parents: dict[str, list[str]] = {nid: [] for nid in id_set}
    for e in edges:
        src, tgt = e.get("source", ""), e.get("target", "")
        if src in id_set and tgt in id_set:
            children[src].append(tgt)
            parents[tgt].append(src)

    # 无向连通分量
    visited: set[str] = set()
    components: list[list[str]] = []
    for nid in node_ids:
        if nid in visited:
            continue
        comp: list[str] = []
        stack = [nid]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            comp.append(cur)
            stack.extend(children[cur])
            stack.extend(parents[cur])
        components.append(comp)

    if len(components) <= 1:
        return {**workflow, "nodes": nodes, "edges": edges}

    def _component_order(comp: list[str]) -> list[str]:
        # 分量内拓扑序（Kahn），返回顺序执行的第一/最后一个节点
        local_in = {nid: 0 for nid in comp}
        local_children: dict[str, list[str]] = {nid: [] for nid in comp}
        for e in edges:
            src, tgt = e.get("source", ""), e.get("target", "")
            if src in local_in and tgt in local_in:
                local_children[src].append(tgt)
                local_in[tgt] += 1
        ready = [nid for nid in comp if local_in[nid] == 0]
        order: list[str] = []
        while ready:
            cur = ready.pop(0)
            order.append(cur)
            for s in local_children[cur]:
                local_in[s] -= 1
                if local_in[s] == 0:
                    ready.append(s)
        return order or comp

    main_comp = components[0]
    main_order = _component_order(main_comp)
    tail = main_order[-1]
    added = 0
    for comp in components[1:]:
        comp_order = _component_order(comp)
        head = comp_order[0]
        edges.append({"source": tail, "target": head, "label": "ordered"})
        added += 1
        tail = comp_order[-1]

    if added:
        logger.info("ensure_dag_connected: linked %d disconnected component(s)", added)

    return {**workflow, "nodes": nodes, "edges": edges}