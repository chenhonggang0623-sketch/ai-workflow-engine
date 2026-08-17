"use client";

import { useEffect, useState, use, useCallback, useRef } from "react";
import Link from "next/link";
import { getExecution, getExecutionNodes, getExecutionLogs, cancelExecution, interveneExecution } from "@/lib/executions";
import { WorkflowDAG } from "@/components/WorkflowDAG";
import { EnsembleMetadata } from "@/components/EnsembleMetadata";
import type { Execution as ExecutionType, ExecutionLog, NodeExecution, WorkflowNode, WorkflowEdge, NodeStatus } from "@/lib/types";

type WsMessage = {
  type: string;
  node_id?: string;
  node_type?: string;
  node_execution_id?: string;
  stream?: string;
  message?: string;
  status?: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  completed?: number;
  total?: number;
  created_at?: string;
};

function buildWsUrl(id: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const port = window.location.port === "8080" ? "8000" : window.location.port;
  return `${proto}://${window.location.hostname}${port ? `:${port}` : ""}/ws/executions/${id}`;
}

export default function ExecutionLivePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [execution, setExecution] = useState<ExecutionType | null>(null);
  const [nodeExecs, setNodeExecs] = useState<NodeExecution[]>([]);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [dagNodes, setDagNodes] = useState<WorkflowNode[]>([]);
  const [dagEdges, setDagEdges] = useState<WorkflowEdge[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [intervening, setIntervening] = useState(false);
  const [switchProvider, setSwitchProvider] = useState("claude_cli");
  const [switchModel, setSwitchModel] = useState("");
  const [wsConnected, setWsConnected] = useState(false);
  const logBoxRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const [exec, nodeList, logList] = await Promise.all([
        getExecution(id),
        getExecutionNodes(id),
        getExecutionLogs(id),
      ]);
      setExecution(exec);
      setNodeExecs(nodeList);
      setLogs(logList);
      if (exec.context?.workflow_definition) {
        const def = exec.context.workflow_definition as { nodes?: WorkflowNode[]; edges?: WorkflowEdge[] };
        setDagNodes(def.nodes || []);
        setDagEdges(def.edges || []);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [id]);

  // WebSocket 实时推送（节点状态 / 控制台输出），HTTP 轮询 5s 兜底
  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const connect = () => {
      if (closed) return;
      try {
        ws = new WebSocket(buildWsUrl(id));
      } catch {
        return;
      }
      ws.onopen = () => setWsConnected(true);
      ws.onmessage = (ev) => {
        let msg: WsMessage;
        try {
          msg = JSON.parse(ev.data as string);
        } catch {
          return;
        }
        if (msg.type === "node_output" && msg.message != null) {
          setLogs((prev) => [
            ...prev,
            {
              id: `ws-${prev.length}-${Date.now()}`,
              level: "output",
              message: msg.message ?? "",
              metadata: { stream: msg.stream || "stdout" },
              node_execution_id: msg.node_execution_id ?? null,
              created_at: msg.created_at ?? new Date().toISOString(),
            },
          ]);
        } else if (msg.type === "node_started") {
          setNodeExecs((prev) => {
            const exists = prev.some((n) => n.node_execution_id === msg.node_execution_id);
            if (exists) return prev;
            return [
              ...prev,
              {
                id: msg.node_execution_id ?? "",
                execution_id: id,
                node_execution_id: msg.node_execution_id ?? null,
                node_id: msg.node_id ?? "",
                node_type: msg.node_type ?? "agent",
                status: "running",
                input: null,
                output: null,
                error: null,
                retry_count: 0,
                started_at: msg.started_at ?? null,
                finished_at: null,
              },
            ];
          });
        } else if (msg.type === "node_finished") {
          setNodeExecs((prev) =>
            prev.map((n) =>
              n.node_execution_id === msg.node_execution_id
                ? { ...n, status: (msg.status as NodeStatus) || n.status, error: msg.error ?? n.error, finished_at: msg.finished_at ?? n.finished_at }
                : n
            )
          );
        } else if (msg.type === "execution_status" && msg.status) {
          setExecution((prev) =>
            prev
              ? {
                  ...prev,
                  status: msg.status as ExecutionType["status"],
                  started_at: msg.started_at ?? prev.started_at,
                  finished_at: msg.finished_at ?? prev.finished_at,
                }
              : prev
          );
        }
      };
      ws.onclose = () => {
        setWsConnected(false);
        if (!closed) reconnectTimer = setTimeout(connect, 3000);
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [id]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [load]);

  // 控制台输出自动滚动到底部
  useEffect(() => {
    if (logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
    }
  }, [logs, selectedNodeId]);

  async function handleCancel() {
    if (!confirm("Cancel this execution?")) return;
    setCancelling(true);
    try {
      await cancelExecution(id);
    } catch {
      alert("Failed to cancel");
    } finally {
      setCancelling(false);
    }
  }

  async function handleIntervene(nodeId: string, action: "wait" | "switch_model" | "terminate") {
    if (action === "terminate" && !confirm(`Terminate the whole execution? Node ${nodeId} will be cancelled and downstream nodes will not run.`)) return;
    setIntervening(true);
    try {
      await interveneExecution(id, {
        node_id: nodeId,
        action,
        provider: action === "switch_model" ? switchProvider : undefined,
        model: action === "switch_model" && switchModel.trim() ? switchModel.trim() : undefined,
      });
      await load();
    } catch {
      alert("Failed to send intervention");
    } finally {
      setIntervening(false);
    }
  }

  if (error) {
    return (
      <div className="bg-red-900/30 border border-red-800 text-red-300 px-4 py-3 rounded-lg text-sm">
        Failed to load execution: {error}
      </div>
    );
  }
  if (!execution) {
    return <div className="text-gray-400 py-8">Loading execution...</div>;
  }

  const runningNode = nodeExecs.find((n) => n.status === "running");
  const slowNodes = nodeExecs.filter((n) => n.status === "running" && n.slow);
  const completedCount = nodeExecs.filter((n) => n.status === "succeeded").length;
  const totalNodes = dagNodes.length || nodeExecs.length;
  const progressPct = totalNodes > 0 ? Math.round((completedCount / totalNodes) * 100) : 0;
  const selectedNode = nodeExecs.find((n) => n.node_id === selectedNodeId) ?? null;
  const selectedNodeLogs = selectedNode
    ? logs.filter((l) => l.node_execution_id === selectedNode.id)
    : [];
  const slowElapsedByNode = new Map(
    slowNodes.map((n) => [n.node_id, n.slow_elapsed_seconds ?? 0])
  );

  const isTerminal = ["succeeded", "failed", "blocked", "cancelled"].includes(execution.status);
  const statusColor: Record<string, string> = {
    running: "text-yellow-400",
    succeeded: "text-green-400",
    failed: "text-red-400",
    blocked: "text-red-500",
    cancelled: "text-orange-400",
    pending: "text-gray-400",
  };

  return (
    <div className="h-full flex flex-col">
      {/* 顶部状态栏 */}
      <div className="flex items-center justify-between gap-4 pb-3 border-b border-gray-800 mb-4">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold text-white">Execution Monitor</h2>
          <span className={`text-sm font-medium ${statusColor[execution.status] || "text-gray-400"}`}>
            {execution.status.toUpperCase()}
          </span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
            wsConnected
              ? "border-green-700 bg-green-950/40 text-green-400"
              : "border-gray-700 bg-gray-900 text-gray-500"
          }`}>
            {wsConnected ? "LIVE" : "POLLING"}
          </span>
          {execution.replan_count > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full border border-yellow-700 bg-yellow-950/40 text-yellow-400">
              replanned ×{execution.replan_count}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {execution.status === "running" && (
            <button
              onClick={handleCancel}
              disabled={cancelling}
              className="px-3 py-1.5 text-xs bg-red-800 text-red-200 rounded-md hover:bg-red-700 disabled:opacity-50 transition-colors"
            >
              {cancelling ? "Cancelling..." : "Cancel"}
            </button>
          )}
          <Link
            href={`/executions/${id}`}
            className="px-3 py-1.5 text-xs bg-gray-800 text-gray-300 rounded-md hover:bg-gray-700 transition-colors"
          >
            Full detail
          </Link>
        </div>
      </div>

      {/* 进度条 */}
      <div className="mb-4 bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div className="flex items-center justify-between text-xs text-gray-400 mb-1.5">
          <span>
            Progress: <span className="text-white font-medium">{completedCount} / {totalNodes}</span> nodes completed
          </span>
          <span className="font-mono text-white">{progressPct}%</span>
        </div>
        <div className="w-full h-2 bg-gray-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-blue-500 to-green-400 rounded-full transition-all duration-700"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        {execution.status === "running" && runningNode ? (
          <div className="mt-2 flex items-center gap-2 text-sm text-yellow-300">
            <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
            <span>
              Now executing: <span className="text-white font-medium">{runningNode.node_id}</span>
              {runningNode.started_at && (
                <span className="text-xs text-gray-500 ml-2">
                  since {new Date(runningNode.started_at).toLocaleTimeString()}
                </span>
              )}
            </span>
            <button
              onClick={() => setSelectedNodeId(runningNode.node_id)}
              className="ml-1 text-xs text-blue-400 hover:text-blue-300 underline"
            >
              view console
            </button>
          </div>
        ) : (
          <div className="mt-2 text-xs text-gray-500">
            {isTerminal ? "Execution finished" : "Waiting for next node..."}
          </div>
        )}
      </div>

      {/* 慢节点干预横幅 */}
      {execution.status === "running" && slowNodes.length > 0 && (
        <div className="mb-4 rounded-lg border border-orange-700 bg-orange-950/30 p-4">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="text-sm text-orange-200">
              <span className="font-bold text-orange-300">Slow node detected:</span>{" "}
              {slowNodes.map((n) => (
                <span key={n.node_id} className="font-mono font-medium text-white">
                  {n.node_id}
                  {n.slow_elapsed_seconds != null && (
                    <span className="text-orange-400/80 ml-1">
                      ({Math.floor(n.slow_elapsed_seconds / 60)}m{Math.floor(n.slow_elapsed_seconds % 60)}s)
                    </span>
                  )}
                </span>
              ))}
              <div className="text-xs text-orange-300/70 mt-1">
                Choose how to proceed — the node is still running and may finish on its own.
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <select
                value={switchProvider}
                onChange={(e) => setSwitchProvider(e.target.value)}
                className="bg-gray-800 border border-gray-700 text-xs text-gray-200 rounded-md px-2 py-1.5 focus:outline-none focus:border-orange-600"
                aria-label="Provider"
              >
                <option value="claude_cli">Claude CLI</option>
                <option value="opencode_cli">OpenCode CLI</option>
                <option value="codex_cli">Codex CLI</option>
                <option value="openai">OpenAI API</option>
                <option value="local_model">Local Model</option>
              </select>
              <input
                value={switchModel}
                onChange={(e) => setSwitchModel(e.target.value)}
                placeholder="model (optional)"
                className="bg-gray-800 border border-gray-700 text-xs text-gray-200 rounded-md px-2 py-1.5 w-40 focus:outline-none focus:border-orange-600"
              />
              <button
                onClick={() => slowNodes[0] && handleIntervene(slowNodes[0].node_id, "wait")}
                disabled={intervening}
                className="px-3 py-1.5 text-xs bg-gray-700 text-gray-200 rounded-md hover:bg-gray-600 disabled:opacity-50 transition-colors"
              >
                Keep waiting
              </button>
              <button
                onClick={() => slowNodes[0] && handleIntervene(slowNodes[0].node_id, "switch_model")}
                disabled={intervening}
                className="px-3 py-1.5 text-xs bg-orange-800 text-orange-100 rounded-md hover:bg-orange-700 disabled:opacity-50 transition-colors"
              >
                Switch model
              </button>
              <button
                onClick={() => slowNodes[0] && handleIntervene(slowNodes[0].node_id, "terminate")}
                disabled={intervening}
                className="px-3 py-1.5 text-xs bg-red-800 text-red-200 rounded-md hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                Terminate task
              </button>
            </div>
          </div>
        </div>
      )}

      {/* DAG + 节点详情 */}
      <div className="flex-1 flex gap-4 min-h-0">
        <div className="flex-1 min-w-0">
          <WorkflowDAG
            nodes={dagNodes}
            edges={dagEdges}
            nodeStatuses={new Map(nodeExecs.map((n) => [n.node_id, n.status as NodeStatus]))}
            slowElapsedByNode={slowElapsedByNode}
            readonly
            onNodeClick={setSelectedNodeId}
          />
        </div>

        {/* 节点详情抽屉：点击节点 → 右侧实时控制台输出 */}
        <aside className={`w-96 shrink-0 bg-gray-900 border border-gray-800 rounded-lg overflow-y-auto transition-all ${selectedNode ? "block" : "hidden"}`}>
          {selectedNode && (
            <div className="p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-gray-500 uppercase bg-gray-800 px-1.5 py-0.5 rounded">
                    {selectedNode.node_type}
                  </span>
                  <span className="text-sm font-semibold text-white">{selectedNode.node_id}</span>
                </div>
                <button
                  onClick={() => setSelectedNodeId(null)}
                  className="text-gray-500 hover:text-gray-300 text-sm"
                  aria-label="Close"
                >
                  ✕
                </button>
              </div>

              <div className="flex flex-wrap items-center gap-2 mb-3">
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                  selectedNode.status === "running"
                    ? "bg-yellow-900/40 text-yellow-300 border border-yellow-700 animate-pulse"
                    : selectedNode.status === "succeeded"
                    ? "bg-green-900/40 text-green-400 border border-green-700"
                    : selectedNode.status === "failed"
                    ? "bg-red-900/40 text-red-400 border border-red-700"
                    : "bg-gray-800 text-gray-400 border border-gray-700"
                }`}>
                  {selectedNode.status.toUpperCase()}
                </span>
                {selectedNode.retry_count > 0 && (
                  <span className="text-xs text-yellow-500">Retries: {selectedNode.retry_count}</span>
                )}
              </div>

              <div className="text-xs text-gray-500 mb-4 space-y-0.5">
                {selectedNode.started_at && (
                  <div>Start: {new Date(selectedNode.started_at).toLocaleTimeString()}</div>
                )}
                {selectedNode.finished_at && (
                  <div>End: {new Date(selectedNode.finished_at).toLocaleTimeString()}</div>
                )}
              </div>

              {selectedNode.error && (
                <div className="mb-3 bg-red-900/20 border border-red-800/50 rounded px-3 py-2 text-xs text-red-300 font-mono whitespace-pre-wrap">
                  {selectedNode.error}
                </div>
              )}

              <div className="mb-2 text-xs font-medium text-gray-400 uppercase tracking-wide">Agent output</div>
              {selectedNode.output && Object.keys(selectedNode.output).length > 0 ? (
                <pre className="text-xs text-gray-300 bg-gray-950 rounded p-3 overflow-x-auto max-h-64 whitespace-pre-wrap">
                  {JSON.stringify(selectedNode.output, null, 2)}
                </pre>
              ) : (
                <div className="text-xs text-gray-600 bg-gray-950 rounded p-3">
                  {selectedNode.status === "running"
                    ? "Agent is still working — output will appear here..."
                    : "No output recorded"}
                </div>
              )}

              <EnsembleMetadata output={selectedNode.output} />

              <div className="mt-4 mb-2 flex items-center justify-between">
                <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">
                  Console output ({selectedNodeLogs.length})
                </span>
                {selectedNode.status === "running" && (
                  <span className="flex items-center gap-1 text-[10px] text-green-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                    streaming
                  </span>
                )}
              </div>
              <div
                ref={logBoxRef}
                className="max-h-72 overflow-y-auto bg-gray-950 rounded border border-gray-800"
              >
                {selectedNodeLogs.length > 0 ? (
                  <div className="p-2 space-y-px font-mono text-[11px] leading-relaxed">
                    {selectedNodeLogs.map((l, i) => {
                      const stream = (l.metadata as { stream?: string } | null)?.stream;
                      const isErr = l.level === "error" || stream === "stderr";
                      return (
                        <div key={l.id || i} className="flex gap-1.5">
                          <span className={`shrink-0 select-none ${isErr ? "text-red-500" : "text-gray-600"}`}>
                            {stream === "stderr" ? "ERR" : isErr ? "ERR" : "OUT"}
                          </span>
                          <span className={`whitespace-pre-wrap break-all ${isErr ? "text-red-300" : "text-gray-300"}`}>
                            {l.message}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="p-3 text-xs text-gray-600">
                    {selectedNode.status === "running"
                      ? "Waiting for console output..."
                      : "No console output recorded"}
                  </div>
                )}
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}