"use client";

import { useState, useRef } from "react";
import { generatePlan, confirmPlan } from "@/lib/planner";
import { WorkflowDAG } from "@/components/WorkflowDAG";
import { AgentConfigDialog } from "@/components/AgentConfigDialog";
import type { WorkflowNode, WorkflowEdge, BlueprintContent } from "@/lib/types";

export default function CreateWorkflowPage() {
  const [requirement, setRequirement] = useState("");
  const [constraints, setConstraints] = useState("");
  const [planning, setPlanning] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const planningRef = useRef(false);
  const confirmingRef = useRef(false);
  const [blueprintId, setBlueprintId] = useState<string | null>(null);
  const [blueprint, setBlueprint] = useState<BlueprintContent | null>(null);
  const [planResult, setPlanResult] = useState<{
    nodes: WorkflowNode[];
    edges: WorkflowEdge[];
    explanation: string;
    estimatedDuration: number | null;
  } | null>(null);
  const [configNode, setConfigNode] = useState<{ nodeId: string; nodeLabel: string } | null>(null);

  async function handleGeneratePlan() {
    if (planningRef.current || !requirement.trim()) return;
    planningRef.current = true;
    setPlanning(true);
    setError(null);
    setPlanResult(null);
    setBlueprint(null);
    setBlueprintId(null);
    setConfigNode(null);
    try {
      const parsedConstraints = constraints.trim() ? { text: constraints } : {};
      const res = await generatePlan(requirement, parsedConstraints);
      const plan = res.plan;
      setPlanResult({
        nodes: (plan.nodes || []) as WorkflowNode[],
        edges: (plan.edges || []) as WorkflowEdge[],
        explanation: res.explanation,
        estimatedDuration: res.estimated_duration_seconds,
      });
      setBlueprintId(res.blueprint?.id || null);
      setBlueprint(res.blueprint?.content || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Planning failed");
    } finally {
      planningRef.current = false;
      setPlanning(false);
    }
  }

  async function handleConfirm() {
    if (confirmingRef.current || !planResult) return;
    confirmingRef.current = true;
    setConfirming(true);
    setError(null);
    try {
      const res = await confirmPlan({
        name: requirement.slice(0, 100),
        description: requirement,
        nodes: planResult.nodes,
        edges: planResult.edges,
        blueprint_id: blueprintId || undefined,
      });
      window.location.href = `/executions/${res.execution_id}/live`;
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Confirmation failed";
      setError(msg);
      confirmingRef.current = false;
      setConfirming(false);
      console.error("Confirm failed:", e);
    }
  }

  async function handleSaveAgentConfig(updates: {
    provider: string;
    executor_type: string;
    executor_config: Record<string, unknown>;
    system_prompt: string;
  }) {
    if (!configNode || !planResult) return;
    setPlanResult((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        nodes: prev.nodes.map((n) =>
          n.id === configNode.nodeId
            ? { ...n, config: { ...n.config, ...updates } }
            : n
        ),
      };
    });
    setConfigNode(null);
  }

  return (
    <div className="max-w-3xl">
      <h2 className="text-xl font-bold text-white mb-1">New Project</h2>
      <p className="text-sm text-gray-400 mb-6">Describe your requirements and let AI plan the workflow.</p>

      {error && (
        <div className="bg-red-900/30 border border-red-800 text-red-300 px-4 py-3 rounded-lg text-sm mb-4">{error}</div>
      )}

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1.5">Requirements</label>
          <textarea
            value={requirement}
            onChange={(e) => setRequirement(e.target.value)}
            placeholder="e.g., Build a REST API for user management with CRUD operations, authentication, and email notifications..."
            rows={5}
            className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-gray-100 text-sm placeholder-gray-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none resize-none"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1.5">
            Constraints <span className="text-gray-500">(optional)</span>
          </label>
          <textarea
            value={constraints}
            onChange={(e) => setConstraints(e.target.value)}
            placeholder="e.g., Use PostgreSQL, Python, FastAPI. Must handle 1000 req/s."
            rows={3}
            className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-gray-100 text-sm placeholder-gray-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none resize-none"
          />
        </div>

        <button
          onClick={handleGeneratePlan}
          disabled={planning || !requirement.trim()}
          className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {planning ? "Planning..." : "Generate Workflow Plan"}
        </button>
        {planning && (
          <p className="text-xs text-gray-400">
            正在分析需求并生成 DAG，通常需要 1-3 分钟，请耐心等待…
          </p>
        )}
      </div>

      {planResult && (
        <div className="mt-8 space-y-4">
          <h3 className="text-lg font-semibold text-white">Generated Plan</h3>

          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <p className="text-sm text-gray-300 whitespace-pre-wrap">{planResult.explanation}</p>
            {planResult.estimatedDuration && (
              <p className="text-xs text-gray-500 mt-2">
                Estimated duration: {Math.round(planResult.estimatedDuration / 60)} minutes
              </p>
            )}
          </div>

          <div>
            <h4 className="text-sm font-medium text-gray-300 mb-2">Workflow DAG</h4>
            <p className="text-xs text-gray-500 mb-2">点击节点可查看/修改 Provider 与 System Prompt</p>
            <WorkflowDAG
              nodes={planResult.nodes}
              edges={planResult.edges}
              readonly={false}
              onNodeClick={(nodeId) => {
                const node = planResult.nodes.find((n) => n.id === nodeId);
                if (node) setConfigNode({ nodeId, nodeLabel: node.label || nodeId });
              }}
            />
          </div>

          {blueprint && (
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <h4 className="text-sm font-medium text-gray-300">Blueprint Modules</h4>
                <span className="text-xs text-gray-500">({(blueprint.modules || []).length})</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {(blueprint.modules || []).map((m) => {
                  const deps = m.depends_on || [];
                  return (
                    <span key={m.id} className="text-xs px-2 py-1 rounded-md bg-gray-800 text-blue-300 border border-gray-700">
                      {m.id}
                      {deps.length > 0 && (
                        <span className="text-gray-500"> → {deps.join(", ")}</span>
                      )}
                    </span>
                  );
                })}
              </div>
              {(blueprint.constraints || []).length > 0 && (
                <div className="mt-3">
                  <div className="text-xs text-gray-500 mb-1">Constraints</div>
                  <ul className="space-y-0.5">
                    {(blueprint.constraints || []).map((c, i) => (
                      <li key={i} className="text-xs text-yellow-200/70 list-disc ml-4">{c}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <div className="flex gap-3">
            <button
              onClick={handleConfirm}
              disabled={confirming}
              className="px-5 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {confirming ? "Starting execution..." : "Confirm & Execute"}
            </button>
            {confirming && (
              <span className="text-xs text-gray-400 self-center">
                Creating execution — you will be redirected to the live progress view
              </span>
            )}
            <button
              onClick={() => {
                setPlanResult(null);
                setConfigNode(null);
              }}
              className="px-5 py-2 bg-gray-800 text-gray-300 text-sm font-medium rounded-lg hover:bg-gray-700 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {configNode && planResult && (
        <AgentConfigDialog
          node={planResult.nodes.find((n) => n.id === configNode.nodeId) || null}
          nodeLabel={configNode.nodeLabel}
          onClose={() => setConfigNode(null)}
          onSave={handleSaveAgentConfig}
        />
      )}
    </div>
  );
}
