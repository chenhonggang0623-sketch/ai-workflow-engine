"use client";

import { useEffect, useState, use, useCallback } from "react";
import Link from "next/link";
import { getExecution, getExecutionLogs, getExecutionNodes, getExecutionFiles, cancelExecution, getExecutionDecision, resolveExecution } from "@/lib/executions";
import { listArtifacts } from "@/lib/artifacts";
import { getExecutionReport } from "@/lib/evaluations";
import { WorkflowDAG } from "@/components/WorkflowDAG";
import { NodeStatusBadge } from "@/components/NodeStatusBadge";
import { LogViewer } from "@/components/LogViewer";
import { TabNav } from "@/components/TabNav";
import { EnsembleMetadata } from "@/components/EnsembleMetadata";
import type { Execution as ExecutionType, ExecutionLog, NodeExecution, Artifact, WorkflowNode, WorkflowEdge, NodeStatus, ProjectFile, ExecutionDecision, RerunRecommendation } from "@/lib/types";

type TabKey = "nodes" | "logs" | "artifacts" | "files" | "evaluations";

export default function ExecutionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [execution, setExecution] = useState<ExecutionType | null>(null);
  const [nodeExecs, setNodeExecs] = useState<NodeExecution[]>([]);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [projectPath, setProjectPath] = useState<string | null>(null);
  const [evaluations, setEvaluations] = useState<ExecutionEval[]>([]);
  const [dagNodes, setDagNodes] = useState<WorkflowNode[]>([]);
  const [dagEdges, setDagEdges] = useState<WorkflowEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("nodes");
  const [cancelling, setCancelling] = useState(false);
  const [decision, setDecision] = useState<ExecutionDecision | null>(null);
  const [resolving, setResolving] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [showBlueprintEdit, setShowBlueprintEdit] = useState(false);
  const [blueprintText, setBlueprintText] = useState("");

  const load = useCallback(async () => {
    try {
      const [exec, nodeList, logList, artList, fileList, report, decisionRes] = await Promise.all([
        getExecution(id),
        getExecutionNodes(id),
        getExecutionLogs(id),
        listArtifacts({ execution_id: id }),
        getExecutionFiles(id).catch(() => null),
        getExecutionReport(id).catch(() => null),
        getExecutionDecision(id).catch(() => null),
      ]);

      setExecution(exec);
      setNodeExecs(nodeList);
      setLogs(logList);
      setArtifacts(artList);
      setDecision(decisionRes);
      if (decisionRes?.blueprint) {
        setBlueprintText(JSON.stringify(decisionRes.blueprint, null, 2));
      }
      if (fileList) {
        setFiles(fileList.files);
        setProjectPath(fileList.project_path);
      }
      if (report) setEvaluations(report.evaluations);

      if (exec.context?.workflow_definition) {
        const def = exec.context.workflow_definition as { nodes?: WorkflowNode[]; edges?: WorkflowEdge[] };
        setDagNodes(def.nodes || []);
        setDagEdges(def.edges || []);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 2000);
    return () => clearInterval(interval);
  }, [load]);

  async function handleCancel() {
    if (!confirm("Cancel this execution?")) return;
    setCancelling(true);
    try {
      await cancelExecution(id);
      await load();
    } catch {
      alert("Failed to cancel");
    } finally {
      setCancelling(false);
    }
  }

  async function handleResolve(action: "retry" | "revise_blueprint" | "abandon") {
    if (action === "abandon" && !confirm("Abandon this execution?")) return;
    setResolving(true);
    try {
      let blueprintPayload: Record<string, unknown> | undefined;
      if (action === "revise_blueprint" && showBlueprintEdit) {
        try {
          blueprintPayload = JSON.parse(blueprintText);
        } catch {
          alert("Blueprint JSON is invalid");
          setResolving(false);
          return;
        }
      }
      await resolveExecution(id, action, {
        feedback: feedback || undefined,
        blueprint: blueprintPayload,
      });
      setDecision(null);
      await load();
    } catch {
      alert("Failed to submit decision");
    } finally {
      setResolving(false);
    }
  }

  if (loading) return <div className="text-gray-400 py-8">Loading execution...</div>;
  if (error) return <div className="bg-red-900/30 border border-red-800 text-red-300 px-4 py-3 rounded-lg text-sm">{error}</div>;
  if (!execution) return <div className="text-gray-400">Execution not found</div>;

  const statusColors: Record<string, string> = {
    running: "text-yellow-400",
    succeeded: "text-green-400",
    failed: "text-red-400",
    pending: "text-gray-400",
    paused: "text-yellow-400",
    cancelled: "text-orange-400",
    blocked: "text-red-500",
  };

  const runningNode = nodeExecs.find((n) => n.status === "running");
  const completedCount = nodeExecs.filter((n) => n.status === "succeeded").length;
  const totalNodes = dagNodes.length || nodeExecs.length;
  const progressPct = totalNodes > 0 ? Math.round((completedCount / totalNodes) * 100) : 0;

  const rerunRecommendations =
    (execution.context?._rerun_recommendations as RerunRecommendation[] | undefined) ?? [];

  return (
    <div>
      {/* audit 推荐重跑提示（不自动执行） */}
      {rerunRecommendations.length > 0 && (
        <div className="mb-4 bg-yellow-950/30 border border-yellow-800/60 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-sm font-semibold text-yellow-300">
              ⚠ Audit recommends rerunning
            </span>
          </div>
          <p className="text-xs text-yellow-200/70 mb-2">
            Execution succeeded but audit found critical issues. Rerun was NOT triggered
            automatically — review the nodes below and rerun if appropriate.
          </p>
          <ul className="space-y-1">
            {rerunRecommendations.map((r) => (
              <li key={r.node_id} className="text-xs text-yellow-200/90">
                <span className="font-mono">{r.node_id}</span>
                <span className="text-yellow-400/80">
                  {" "}– {r.critical_count} critical, {r.findings_count} finding(s)
                </span>
                {r.reviewers.length > 0 && (
                  <span className="text-yellow-500/60">
                    {" "}from {r.reviewers.join(", ")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-bold text-white">Execution</h2>
            <span className={`text-sm font-medium ${statusColors[execution.status] || "text-gray-400"}`}>
              {execution.status.toUpperCase()}
            </span>
            {execution.replan_count > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full border border-yellow-700 bg-yellow-950/40 text-yellow-400">
                replanned ×{execution.replan_count}
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 mt-1">
            ID: {execution.id} · Started {execution.started_at ? new Date(execution.started_at).toLocaleString() : "N/A"}
            {execution.finished_at && ` · Finished ${new Date(execution.finished_at).toLocaleString()}`}
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            href={`/workflows/${execution.workflow_id}`}
            className="px-3 py-1.5 text-xs bg-gray-800 text-gray-300 rounded-md hover:bg-gray-700 transition-colors"
          >
            View Workflow
          </Link>
          {execution.status === "running" && (
            <button
              onClick={handleCancel}
              disabled={cancelling}
              className="px-3 py-1.5 text-xs bg-red-800 text-red-200 rounded-md hover:bg-red-700 disabled:opacity-50 transition-colors"
            >
              {cancelling ? "Cancelling..." : "Cancel"}
            </button>
          )}
        </div>
      </div>

      {/* 整体进度条 */}
      {execution.status === "running" && (
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
          {runningNode && (
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
            </div>
          )}
        </div>
      )}

      {/* Blocked 决策面板 */}
      {execution.status === "blocked" && decision && decision.status === "pending" && (
        <DecisionPanel
          decision={decision}
          feedback={feedback}
          setFeedback={setFeedback}
          showBlueprintEdit={showBlueprintEdit}
          setShowBlueprintEdit={setShowBlueprintEdit}
          blueprintText={blueprintText}
          setBlueprintText={setBlueprintText}
          resolving={resolving}
          onResolve={handleResolve}
        />
      )}

      {(dagNodes.length > 0) && (
        <div className="mb-6">
          <h3 className="text-sm font-medium text-gray-300 mb-2">Workflow DAG</h3>
          <WorkflowDAG
            nodes={dagNodes}
            edges={dagEdges}
            nodeStatuses={new Map(nodeExecs.map((n) => [n.node_id, n.status as NodeStatus]))}
          />
        </div>
      )}

      <TabNav
        tabs={[
          { key: "nodes", label: `Nodes (${nodeExecs.length})` },
          { key: "logs", label: `Logs (${logs.length})` },
          { key: "artifacts", label: `Artifacts (${artifacts.length})` },
          { key: "files", label: `Generated Files (${files.length})` },
          { key: "evaluations", label: `Evaluations (${evaluations.length})` },
        ]}
        active={activeTab}
        onTabChange={(key) => setActiveTab(key as TabKey)}
      />

      {activeTab === "nodes" && <NodesTab nodes={nodeExecs} />}
      {activeTab === "logs" && <LogsTab logs={logs} />}
      {activeTab === "artifacts" && <ArtifactsTab artifacts={artifacts} />}
      {activeTab === "files" && <FilesTab files={files} projectPath={projectPath} />}
      {activeTab === "evaluations" && <EvaluationsTab evaluations={evaluations} />}
    </div>
  );
}

function NodesTab({ nodes }: { nodes: NodeExecution[] }) {
  if (nodes.length === 0) {
    return <div className="text-gray-500 text-sm py-8 text-center">No nodes executed yet</div>;
  }

  return (
    <div className="space-y-2">
      {nodes.map((n) => (
        <div key={n.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-medium text-gray-500 uppercase bg-gray-800 px-1.5 py-0.5 rounded">
                  {n.node_type}
                </span>
                <span className="text-sm font-medium text-white">{n.node_id}</span>
              </div>
              <NodeStatusBadge status={n.status as NodeStatus} />
              {n.retry_count > 0 && (
                <span className="text-xs text-yellow-500 ml-2">Retries: {n.retry_count}</span>
              )}
            </div>
            <div className="text-xs text-gray-500 text-right shrink-0">
              {n.started_at && <div>Start: {new Date(n.started_at).toLocaleTimeString()}</div>}
              {n.finished_at && <div>End: {new Date(n.finished_at).toLocaleTimeString()}</div>}
            </div>
          </div>

          {n.error && (
            <div className="mt-2 bg-red-900/20 border border-red-800/50 rounded px-3 py-2 text-xs text-red-300 font-mono">
              {n.error}
            </div>
          )}

          {n.output && Object.keys(n.output).length > 0 && (
            <details className="mt-2">
              <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-300">Output</summary>
              <pre className="mt-1 text-xs text-gray-400 bg-gray-950 rounded p-2 overflow-x-auto max-h-40">
                {JSON.stringify(n.output, null, 2)}
              </pre>
            </details>
          )}

          <EnsembleMetadata output={n.output} />
        </div>
      ))}
    </div>
  );
}

function LogsTab({ logs }: { logs: ExecutionLog[] }) {
  return <LogViewer logs={logs} />;
}

function ArtifactsTab({ artifacts }: { artifacts: Artifact[] }) {
  if (artifacts.length === 0) {
    return <div className="text-gray-500 text-sm py-8 text-center">No artifacts generated yet</div>;
  }

  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {artifacts.map((a) => (
        <div key={a.id} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
          <div className="flex items-start justify-between gap-2 mb-2">
            <div className="min-w-0">
              <div className="text-sm font-medium text-white truncate">{a.name}</div>
              <div className="text-xs text-gray-500 mt-0.5">{a.type}</div>
            </div>
            <span className="text-xs text-gray-500 shrink-0">
              {(a.size / 1024).toFixed(1)} KB
            </span>
          </div>
          <div className="flex items-center gap-2">
            <a
              href={`/api/artifacts/${a.id}/download`}
              className="text-xs text-blue-400 hover:text-blue-300"
              download
            >
              Download
            </a>
            <span className="text-xs text-gray-600">v{a.version}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function FilesTab({ files, projectPath }: { files: ProjectFile[]; projectPath: string | null }) {
  if (files.length === 0) {
    return (
      <div className="text-gray-500 text-sm py-8 text-center">
        {projectPath ? "No files generated yet" : "No project workspace for this execution"}
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg">
      {projectPath && (
        <div className="px-4 py-2 border-b border-gray-800 text-xs text-gray-500 font-mono truncate">
          {projectPath}
        </div>
      )}
      <div className="p-2 font-mono text-sm max-h-96 overflow-y-auto">
        {files.map((f) => {
          const depth = f.path.split("/").length - 1;
          return (
            <div
              key={f.path}
              className="flex items-center justify-between px-2 py-1 rounded hover:bg-gray-800/60"
            >
              <span
                className={f.type === "dir" ? "text-gray-400" : "text-gray-200"}
                style={{ paddingLeft: `${depth * 16}px` }}
              >
                {f.type === "dir" ? "▸ " : "  "}
                {f.path}
              </span>
              {f.type === "file" && (
                <span className="text-xs text-gray-500 shrink-0 ml-4">
                  {(f.size / 1024).toFixed(1)} KB
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function EvaluationsTab({ evaluations }: { evaluations: ExecutionEval[] }) {
  if (evaluations.length === 0) {
    return <div className="text-gray-500 text-sm py-8 text-center">No evaluations yet</div>;
  }

  return (
    <div className="space-y-3">
      {evaluations.map((e) => (
        <div key={e.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div className="flex items-start justify-between gap-4 mb-2">
            <div>
              <span className="text-sm font-medium text-white">{e.agent_id}</span>
              <span className={`ml-2 text-xs px-2 py-0.5 rounded-full ${
                e.passed ? "bg-green-900/50 text-green-400" : "bg-red-900/50 text-red-400"
              }`}>
                {e.passed ? "PASSED" : "FAILED"}
              </span>
            </div>
            <span className="text-sm font-semibold text-blue-400">Score: {e.weighted_score.toFixed(1)}</span>
          </div>
          {e.summary && (
            <p className="text-sm text-gray-400 mb-2">{e.summary}</p>
          )}
          <p className="text-xs text-gray-600">
            Evaluated by {e.evaluator} · {new Date(e.created_at).toLocaleString()}
          </p>
        </div>
      ))}
    </div>
  );
}

interface ExecutionEval {
  id: string;
  agent_id: string;
  evaluator?: string;
  weighted_score: number;
  passed: boolean;
  summary: string;
  created_at: string;
}

function DecisionPanel({
  decision,
  feedback,
  setFeedback,
  showBlueprintEdit,
  setShowBlueprintEdit,
  blueprintText,
  setBlueprintText,
  resolving,
  onResolve,
}: {
  decision: ExecutionDecision;
  feedback: string;
  setFeedback: (v: string) => void;
  showBlueprintEdit: boolean;
  setShowBlueprintEdit: (v: boolean) => void;
  blueprintText: string;
  setBlueprintText: (v: string) => void;
  resolving: boolean;
  onResolve: (action: "retry" | "revise_blueprint" | "abandon") => void;
}) {
  return (
    <div className="mb-6 bg-red-950/30 border border-red-800/60 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-semibold text-red-300">⚠ Execution blocked</span>
        <span className="text-xs text-red-400/70">
          {decision.attempts} auto-replan attempts exhausted
        </span>
      </div>
      <p className="text-sm text-red-200/80 mb-4">
        {decision.reason || "Automatic replanning could not resolve the failures. Please choose how to proceed."}
      </p>

      <div className="mb-4">
        <label className="block text-xs font-medium text-gray-400 mb-1.5">
          Feedback for revision (optional)
        </label>
        <textarea
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          rows={3}
          placeholder="例如：后端模块应该改用 SQLite，去掉 Redis 依赖..."
          className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-red-500 resize-y"
          spellCheck={false}
        />
      </div>

      <div className="mb-4">
        <button
          onClick={() => setShowBlueprintEdit(!showBlueprintEdit)}
          className="text-xs text-red-300 hover:text-red-200 underline"
        >
          {showBlueprintEdit ? "Hide blueprint editor" : "Edit blueprint JSON"}
        </button>
        {showBlueprintEdit && (
          <textarea
            value={blueprintText}
            onChange={(e) => setBlueprintText(e.target.value)}
            rows={12}
            spellCheck={false}
            className="mt-2 w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-xs font-mono text-green-300 focus:outline-none focus:ring-2 focus:ring-red-500 resize-y"
          />
        )}
      </div>

      <div className="flex flex-wrap gap-3">
        <button
          onClick={() => onResolve("retry")}
          disabled={resolving}
          className="px-4 py-2 text-sm bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-500 disabled:opacity-50 transition-colors"
        >
          {resolving ? "Submitting..." : "Retry current plan"}
        </button>
        <button
          onClick={() => onResolve("revise_blueprint")}
          disabled={resolving}
          className="px-4 py-2 text-sm bg-red-600 text-white font-medium rounded-lg hover:bg-red-500 disabled:opacity-50 transition-colors"
        >
          {resolving ? "Submitting..." : "Revise blueprint & rerun"}
        </button>
        <button
          onClick={() => onResolve("abandon")}
          disabled={resolving}
          className="px-4 py-2 text-sm bg-gray-800 text-gray-300 font-medium rounded-lg hover:bg-gray-700 disabled:opacity-50 transition-colors"
        >
          Abandon
        </button>
      </div>
    </div>
  );
}
