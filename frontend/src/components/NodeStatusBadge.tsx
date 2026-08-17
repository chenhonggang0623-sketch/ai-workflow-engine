import type { NodeStatus } from "@/lib/types";

const colors: Record<NodeStatus, string> = {
  pending: "bg-gray-500",
  ready: "bg-blue-500",
  running: "bg-yellow-500 animate-pulse",
  waiting: "bg-purple-500",
  succeeded: "bg-green-500",
  failed: "bg-red-500",
  skipped: "bg-gray-400",
  cancelled: "bg-orange-500",
};

export function NodeStatusBadge({ status, label }: { status: NodeStatus; label?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium text-white ${colors[status] || "bg-gray-500"}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-white/60" />
      {label || status}
    </span>
  );
}
