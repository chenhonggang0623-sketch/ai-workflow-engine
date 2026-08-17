"use client";

import { useEffect, useRef } from "react";
import type { ExecutionLog } from "@/lib/types";

export function LogViewer({ logs }: { logs: ExecutionLog[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  const levelColors: Record<string, string> = {
    DEBUG: "text-gray-400",
    INFO: "text-blue-300",
    WARN: "text-yellow-300",
    ERROR: "text-red-300",
  };

  return (
    <div className="bg-gray-900 text-gray-100 font-mono text-xs rounded-lg overflow-hidden">
      <div className="px-3 py-1.5 bg-gray-800 text-gray-400 text-xs font-semibold uppercase tracking-wider border-b border-gray-700">
        Agent Logs
      </div>
      <div className="h-80 overflow-y-auto p-3 space-y-0.5">
        {logs.length === 0 ? (
          <div className="text-gray-500 italic">No logs yet...</div>
        ) : (
          logs.map((log) => (
            <div key={log.id} className="flex gap-2">
              <span className="text-gray-500 shrink-0 w-14 text-right">
                {new Date(log.created_at).toLocaleTimeString()}
              </span>
              <span className={`shrink-0 w-12 ${levelColors[log.level] || "text-gray-400"}`}>
                [{log.level}]
              </span>
              <span className="break-all">{log.message}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
