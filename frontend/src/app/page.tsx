"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listWorkflows, deleteWorkflow, executeWorkflow } from "@/lib/workflows";
import { listExecutions } from "@/lib/executions";
import type { Workflow, ExecutionListItem, ExecutionStatus } from "@/lib/types";

const NON_TERMINAL: ExecutionStatus[] = ["pending", "running", "paused", "blocked"];

export default function HomePage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [executions, setExecutions] = useState<ExecutionListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [wfData, exeData] = await Promise.all([
        listWorkflows(),
        listExecutions({ limit: 100 }),
      ]);
      setWorkflows(wfData);
      setExecutions(exeData);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function latestExecution(workflowId: string): ExecutionListItem | undefined {
    return executions.find((e) => e.workflow_id === workflowId && NON_TERMINAL.includes(e.status))
      ?? executions.find((e) => e.workflow_id === workflowId);
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this project?")) return;
    try {
      await deleteWorkflow(id);
      setWorkflows((prev) => prev.filter((w) => w.id !== id));
    } catch {
      alert("Failed to delete");
    }
  }

  async function handleExecute(id: string) {
    try {
      const res = await executeWorkflow(id);
      window.open(`/executions/${res.execution_id}`, "_blank");
    } catch {
      alert("Failed to execute");
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-white">Projects</h2>
          <p className="text-sm text-gray-400 mt-1">Manage your AI agent workflow projects</p>
        </div>
        <Link
          href="/workflows/create"
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-500 transition-colors"
        >
          + New Project
        </Link>
      </div>

      {loading && <div className="text-gray-400 py-8 text-center">Loading...</div>}
      {error && (
        <div className="bg-red-900/30 border border-red-800 text-red-300 px-4 py-3 rounded-lg text-sm">{error}</div>
      )}

      {!loading && !error && workflows.length === 0 && (
        <div className="text-center py-16 border border-dashed border-gray-700 rounded-lg">
          <p className="text-gray-400">No projects yet</p>
          <Link
            href="/workflows/create"
            className="inline-block mt-3 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-500 transition-colors"
          >
            Create your first project
          </Link>
        </div>
      )}

      {!loading && workflows.length > 0 && (
        <div className="grid gap-3">
          {workflows.map((wf) => (
            <div
              key={wf.id}
              className="bg-gray-900 border border-gray-800 rounded-lg p-4 hover:border-gray-700 transition-colors"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-3">
                    <Link
                      href={`/workflows/${wf.id}`}
                      className="text-base font-semibold text-white hover:text-blue-400 truncate"
                    >
                      {wf.name}
                    </Link>
                    <StatusBadge status={wf.status} />
                  </div>
                  {wf.description && (
                    <p className="text-sm text-gray-400 mt-1 line-clamp-2">{wf.description}</p>
                  )}
                  <p className="text-xs text-gray-500 mt-2">
                    Created {new Date(wf.created_at).toLocaleString()} | v{wf.version}
                  </p>
                </div>
                <div className="flex gap-2 shrink-0">
                  {(() => {
                    const exe = latestExecution(wf.id);
                    return exe && NON_TERMINAL.includes(exe.status) ? (
                      <Link
                        href={`/executions/${exe.id}/live`}
                        className="px-3 py-1.5 text-xs bg-green-700 text-white rounded-md hover:bg-green-600 transition-colors"
                      >
                        Progress
                      </Link>
                    ) : null;
                  })()}
                  <button
                    onClick={() => handleExecute(wf.id)}
                    className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-500 transition-colors"
                  >
                    Run
                  </button>
                  <Link
                    href={`/workflows/${wf.id}`}
                    className="px-3 py-1.5 text-xs bg-gray-800 text-gray-300 rounded-md hover:bg-gray-700 transition-colors"
                  >
                    View
                  </Link>
                  <button
                    onClick={() => handleDelete(wf.id)}
                    className="px-3 py-1.5 text-xs bg-gray-800 text-red-400 rounded-md hover:bg-red-900/50 transition-colors"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: "bg-green-900/50 text-green-400 border-green-700",
    paused: "bg-yellow-900/50 text-yellow-400 border-yellow-700",
    archived: "bg-gray-800 text-gray-400 border-gray-700",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border ${colors[status] || "bg-gray-800 text-gray-400 border-gray-700"}`}>
      {status}
    </span>
  );
}
