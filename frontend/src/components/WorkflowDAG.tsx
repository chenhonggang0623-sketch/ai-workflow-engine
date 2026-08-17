"use client";

import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  type NodeProps,
  useNodesState,
  useEdgesState,
} from "@xyflow/react";
import "@xyflow/react/dist/base.css";
import { useMemo, useState, useCallback, useRef, useEffect } from "react";
import type { WorkflowNode, WorkflowEdge, NodeStatus } from "@/lib/types";

const nodeTypeColors: Record<string, string> = {
  agent: "#3b82f6",
  tool: "#8b5cf6",
  condition: "#f59e0b",
  loop: "#ec4899",
  human: "#10b981",
  planner: "#6366f1",
};

const executorLabels: Record<string, string> = {
  llm_api: "LLM API",
  local_cli: "CLI Agent",
  local_model: "Local Model",
  mcp: "MCP Tool",
  human: "Human",
};

const providerLabels: Record<string, string> = {
  openai: "OpenAI API",
  opencode_cli: "OpenCode CLI",
  claude_cli: "Claude CLI",
  codex_cli: "Codex CLI",
  local_model: "Local Model",
  ensemble: "Ensemble",
};

function DagNode({ data }: NodeProps) {
  const status = data.status as NodeStatus | undefined;
  const nodeType = data.nodeType as string;
  const error = data.error as string | undefined;
  const label = data.label as string;
  const executorType = data.executorType as string | undefined;
  const provider = data.provider as string | undefined;
  const slowElapsed = data.slowElapsed as number | undefined;
  const color = nodeTypeColors[nodeType] || "#6b7280";

  const statusDot: Record<string, string> = {
    running: "bg-yellow-400 animate-pulse",
    succeeded: "bg-green-400",
    failed: "bg-red-400",
    pending: "bg-gray-500",
    ready: "bg-blue-400",
    waiting: "bg-purple-400",
    skipped: "bg-gray-400",
    cancelled: "bg-orange-400",
  };

  return (
    <div
      className="rounded-lg border-2 bg-gray-900 px-4 py-2.5 shadow-lg"
      style={{
        borderColor: status === "running" ? "#fbbf24" : color,
        boxShadow: status === "running" ? "0 0 12px rgba(251,191,36,0.35)" : undefined,
      }}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-500" />
      <div className="flex items-center gap-2">
        <span
          className={`w-2 h-2 rounded-full ${statusDot[status || "pending"] || "bg-gray-500"}`}
        />
        <span className="text-xs font-bold text-gray-300 uppercase">{nodeType}</span>
        {status === "running" && slowElapsed !== undefined && (
          <span className="text-[10px] font-bold text-orange-300 bg-orange-900/40 border border-orange-700 px-1.5 py-px rounded animate-pulse">
            SLOW {Math.floor(slowElapsed / 60)}m{Math.floor(slowElapsed % 60)}s
          </span>
        )}
        {status === "running" && (
          <span className="text-[10px] font-bold text-yellow-300 bg-yellow-900/40 border border-yellow-700 px-1.5 py-px rounded animate-pulse">
            RUNNING
          </span>
        )}
        {status === "succeeded" && (
          <span className="text-[10px] font-bold text-green-400">✓</span>
        )}
        {status === "failed" && (
          <span className="text-[10px] font-bold text-red-400">✗</span>
        )}
      </div>
      <div className="text-sm font-medium text-white mt-0.5">{label}</div>
      {executorType && (
        <div className="text-[10px] text-gray-500 mt-0.5">{executorLabels[executorType] || executorType}</div>
      )}
      {provider && (
        <div className="text-[10px] text-gray-500 mt-0.5">
          <span className="inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400/70" />
            {providerLabels[provider] || provider}
          </span>
        </div>
      )}
      {error && (
        <div className="text-xs text-red-400 mt-1 max-w-40 truncate">{error}</div>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-gray-500" />
    </div>
  );
}

const nodeTypes = { dagNode: DagNode };

export function WorkflowDAG({
  nodes: rawNodes,
  edges: rawEdges,
  nodeStatuses,
  slowElapsedByNode,
  readonly = false,
  onConfigureExecutor,
  onNodeClick,
}: {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  nodeStatuses?: Map<string, NodeStatus>;
  slowElapsedByNode?: Map<string, number>;
  readonly?: boolean;
  onConfigureExecutor?: (nodeId: string, nodeLabel: string) => void;
  onNodeClick?: (nodeId: string) => void;
}) {
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    nodeId: string;
    nodeLabel: string;
  } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const initialNodes = useMemo(
    () =>
      rawNodes.map((n, i) => ({
        id: n.id,
        type: "dagNode",
        position: n.position || { x: 150 + (i % 3) * 250, y: 80 + Math.floor(i / 3) * 150 },
        data: {
          label: n.label,
          nodeType: n.type,
          status: nodeStatuses?.get(n.id),
          error: null,
          executorType: n.config?.executor_type as string | undefined,
          provider: n.config?.provider as string | undefined,
          slowElapsed: slowElapsedByNode?.get(n.id),
        },
      })),
    [rawNodes, nodeStatuses, slowElapsedByNode]
  );

  const initialEdges = useMemo(
    () =>
      rawEdges.map((e) => ({
        id: e.id || `e_${e.source}_${e.target}`,
        source: e.source,
        target: e.target,
        label: e.label,
        animated: true,
        style: { stroke: "#4b5563", strokeWidth: 2 },
        labelStyle: { fill: "#9ca3af", fontSize: 11 },
      })),
    [rawEdges]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    setNodes((nds) =>
      nds.map((n) => {
        const raw = rawNodes.find((r) => r.id === n.id);
        return {
          ...n,
          data: {
            ...n.data,
            label: raw?.label ?? n.data.label,
            nodeType: raw?.type ?? n.data.nodeType,
            status: nodeStatuses?.get(n.id),
            executorType: raw?.config?.executor_type as string | undefined,
            provider: raw?.config?.provider as string | undefined,
            slowElapsed: slowElapsedByNode?.get(n.id),
          },
        };
      })
    );
  }, [rawNodes, nodeStatuses, slowElapsedByNode, setNodes]);

  useEffect(() => {
    const handler = () => setContextMenu(null);
    window.addEventListener("scroll", handler, true);
    return () => window.removeEventListener("scroll", handler, true);
  }, []);

  const onNodeContextMenu = useCallback(
    (event: React.MouseEvent, node: { id: string; data: { label: string } }) => {
      event.preventDefault();
      if (readonly) return;
      setContextMenu({ x: event.clientX, y: event.clientY, nodeId: node.id, nodeLabel: node.data.label });
    },
    [readonly]
  );

  const onPaneClick = useCallback(() => {
    setContextMenu(null);
  }, []);

  const handleNodeClick = useCallback(
    (_e: React.MouseEvent, node: { id: string }) => {
      onNodeClick?.(node.id);
    },
    [onNodeClick]
  );

  return (
    <div className="w-full h-[500px] rounded-lg border border-gray-700 bg-gray-950/50 relative" ref={containerRef}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={readonly ? undefined : onNodesChange}
        onEdgesChange={readonly ? undefined : onEdgesChange}
        onNodeContextMenu={onConfigureExecutor ? onNodeContextMenu : undefined}
        onPaneClick={onPaneClick}
        onNodeClick={handleNodeClick}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#374151" gap={20} />
        <Controls />
        <MiniMap
          style={{ background: "#111827" }}
          nodeColor="#3b82f6"
          maskColor="rgba(0,0,0,0.6)"
        />
      </ReactFlow>

      {contextMenu && onConfigureExecutor && (
        <div
          className="fixed z-50 bg-gray-800 border border-gray-700 rounded-lg shadow-xl py-1 min-w-[180px]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            className="w-full text-left px-3 py-2 text-sm text-gray-200 hover:bg-gray-700 transition-colors flex items-center gap-2"
            onClick={() => {
              onConfigureExecutor(contextMenu.nodeId, contextMenu.nodeLabel);
              setContextMenu(null);
            }}
          >
            <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            配置 Agent
          </button>
        </div>
      )}
    </div>
  );
}
