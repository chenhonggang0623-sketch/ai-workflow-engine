"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { listExecutions } from "@/lib/executions";
import type { ExecutionListItem, ExecutionStatus } from "@/lib/types";

const TERMINAL: ExecutionStatus[] = ["succeeded", "failed", "cancelled", "blocked"];

export default function ExecutionsPage() {
  const [executions, setExecutions] = useState<ExecutionListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listExecutions({ limit: 100 });
      setExecutions(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [load]);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-white">Executions</h2>
          <p className="text-sm text-gray-400 mt-1">Track running progress of all projects</p>
        </div>
      </div>

      {loading && <div className="text-gray-400 py-8 text-center">Loading...</div>}
      {error && (
        <div className="bg-red-900/30 border border-red-800 text-red-300 px-4 py-3 rounded-lg text-sm">{error}</div>
      )}

      {!loading && !error && executions.length === 0 && (
        <div className="text-center py-16 border border-dashed border-gray-700 rounded-lg">
          <p className="text-gray-400">No executions yet</p>
          <Link
            href="/workflows/create"
            className="inline-block mt-3 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-500 transition-colors"
          >
            Create your first project
          </Link>
        </div>
      )}

      {executions.length > 0 && (
        <div className="grid gap-2">
          {executions.map((exe) => (
            <div
              key={exe.id}
              className="bg-gray-900 border border-gray-800 rounded-lg p-4 hover:border-gray-700 transition-colors"
            >
              <div className="flex items-center justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-semibold text-white truncate">
                      {exe.workflow_name}
                    </span>
                    <ExeStatusBadge status={exe.status} />
                  </div>
                  <p className="text-xs text-gray-500 mt-1.5">
                    Created {new Date(exe.created_at).toLocaleString()}
                    {exe.started_at && ` · Started ${new Date(exe.started_at).toLocaleTimeString()}`}
                    {exe.finished_at && ` · Finished ${new Date(exe.finished_at).toLocaleString()}`}
                  </p>
                </div>
                <div className="flex gap-2 shrink-0">
                  {!TERMINAL.includes(exe.status) && (
                    <Link
                      href={`/executions/${exe.id}/live`}
                      className="px-3 py-1.5 text-xs bg-green-700 text-white rounded-md hover:bg-green-600 transition-colors"
                    >
                      Live progress
                    </Link>
                  )}
                  <Link
                    href={`/executions/${exe.id}`}
                    className="px-3 py-1.5 text-xs bg-gray-800 text-gray-300 rounded-md hover:bg-gray-700 transition-colors"
                  >
                    Detail
                  </Link>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ExeStatusBadge({ status }: { status: ExecutionStatus }) {
  const colors: Record<ExecutionStatus, string> = {
    running: "bg-yellow-900/50 text-yellow-400 border-yellow-700",
    pending: "bg-gray-800 text-gray-400 border-gray-700",
    paused: "bg-yellow-900/50 text-yellow-400 border-yellow-700",
    succeeded: "bg-green-900/50 text-green-400 border-green-700",
    failed: "bg-red-900/50 text-red-400 border-red-700",
    cancelled: "bg-orange-900/50 text-orange-400 border-orange-700",
    blocked: "bg-red-900/50 text-red-500 border-red-700",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border ${colors[status] || colors.pending}`}>
      {status}
    </span>
  );
}
