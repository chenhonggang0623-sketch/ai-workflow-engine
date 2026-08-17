"use client";

import { useEffect, useState, use, useCallback } from "react";
import { getWorkflow, executeWorkflow, updateNodeExecutor } from "@/lib/workflows";
import { getWorkflowBlueprint } from "@/lib/blueprints";
import { WorkflowDAG } from "@/components/WorkflowDAG";
import { AgentConfigDialog } from "@/components/AgentConfigDialog";
import type { Workflow, WorkflowNode, WorkflowEdge, Blueprint } from "@/lib/types";

export default function WorkflowDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [blueprint, setBlueprint] = useState<Blueprint | null>(null);
  const [activeSection, setActiveSection] = useState<"dag" | "blueprint">("dag");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [executing, setExecuting] = useState(false);
  const [configNode, setConfigNode] = useState<{ nodeId: string; nodeLabel: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getWorkflow(id);
      setWorkflow(data);
      try {
        setBlueprint(await getWorkflowBlueprint(id));
      } catch {
        setBlueprint(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleExecute() {
    setExecuting(true);
    try {
      const res = await executeWorkflow(id);
      window.open(`/executions/${res.execution_id}`, "_blank");
    } catch {
      alert("Failed to execute");
    } finally {
      setExecuting(false);
    }
  }

  function openConfig(nodeId: string, nodeLabel: string) {
    setConfigNode({ nodeId, nodeLabel });
  }

  async function handleSaveAgentConfig(updates: {
    provider: string;
    executor_type: string;
    executor_config: Record<string, unknown>;
    system_prompt: string;
  }) {
    if (!configNode) return;
    setSaving(true);
    try {
      const updated = await updateNodeExecutor(id, configNode.nodeId, updates);
      setWorkflow(updated);
      setConfigNode(null);
    } catch {
      alert("Failed to update agent config");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="text-gray-400">Loading...</div>;
  if (error) return <div className="bg-red-900/30 border border-red-800 text-red-300 px-4 py-3 rounded-lg text-sm">{error}</div>;
  if (!workflow) return <div className="text-gray-400">Workflow not found</div>;

  const def = workflow.definition;
  const nodes: WorkflowNode[] = (def.nodes || []) as WorkflowNode[];
  const edges: WorkflowEdge[] = (def.edges || []) as WorkflowEdge[];

  return (
    <div>
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-bold text-white">{workflow.name}</h2>
            <StatusBadge status={workflow.status} />
          </div>
          {workflow.description && (
            <p className="text-sm text-gray-400 mt-1">{workflow.description}</p>
          )}
          <p className="text-xs text-gray-500 mt-1">
            v{workflow.version} · Created {new Date(workflow.created_at).toLocaleString()}
          </p>
        </div>
        <button
          onClick={handleExecute}
          disabled={executing}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-500 disabled:opacity-50 transition-colors shrink-0"
        >
          {executing ? "Starting..." : "Run Workflow"}
        </button>
      </div>

      <div className="flex items-center justify-between gap-3 border-b border-gray-700 mb-4">
        <nav className="flex gap-0 -mb-px">
          <button
            onClick={() => setActiveSection("dag")}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeSection === "dag"
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-500"
            }`}
          >
            Workflow DAG
          </button>
          <button
            onClick={() => setActiveSection("blueprint")}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeSection === "blueprint"
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-500"
            }`}
          >
            Blueprint {blueprint ? `v${blueprint.version}` : ""}
          </button>
        </nav>
      </div>

      {activeSection === "dag" ? (
        <>
          <h3 className="text-sm font-medium text-gray-300 mb-2">Workflow DAG</h3>
          <WorkflowDAG
            nodes={nodes}
            edges={edges}
            readonly={false}
            onConfigureExecutor={openConfig}
            onNodeClick={(nodeId) => {
              const node = nodes.find((n) => n.id === nodeId);
              if (node) openConfig(nodeId, node.label || nodeId);
            }}
          />
        </>
      ) : (
        <BlueprintTab blueprint={blueprint} />
      )}

      {/* Agent Config Dialog */}
      {configNode && (
        <AgentConfigDialog
          node={nodes.find((n) => n.id === configNode.nodeId) || null}
          nodeLabel={configNode.nodeLabel}
          onClose={() => setConfigNode(null)}
          onSave={handleSaveAgentConfig}
          saving={saving}
        />
      )}

      <div className="mt-6">
        <h3 className="text-sm font-medium text-gray-300 mb-3">Executions</h3>
        <ExecutionList workflowId={id} />
      </div>
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

function ExecutionList({}: { workflowId: string }) {
  return (
    <div className="text-center py-8 border border-dashed border-gray-700 rounded-lg">
      <p className="text-gray-400 text-sm">Run the workflow to see execution records</p>
      <p className="text-gray-600 text-xs mt-1">
        Executions can be accessed from the detail pages once started
      </p>
    </div>
  );
}

function BlueprintTab({ blueprint }: { blueprint: Blueprint | null }) {
  if (!blueprint) {
    return (
      <div className="text-center py-10 border border-dashed border-gray-700 rounded-lg">
        <p className="text-gray-400 text-sm">No blueprint generated for this workflow yet</p>
        <p className="text-gray-600 text-xs mt-1">
          Blueprints are created when a plan is generated from a requirement
        </p>
      </div>
    );
  }

  const content = blueprint.content;

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <span className="text-xs px-2 py-0.5 rounded-full border border-blue-700 bg-blue-950/40 text-blue-400">
          v{blueprint.version}
        </span>
        <span className="text-xs text-gray-500">
          {blueprint.status} · Created {new Date(blueprint.created_at).toLocaleString()}
        </span>
      </div>

      {/* PRD */}
      <section className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h4 className="text-sm font-semibold text-white mb-2">PRD</h4>
        <p className="text-sm text-gray-300 mb-3">{content.prd?.summary || "—"}</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <div className="text-xs text-gray-500 mb-1.5 font-medium">Goals</div>
            <ul className="space-y-1">
              {(content.prd?.goals || []).map((g, i) => (
                <li key={i} className="text-sm text-gray-300 list-disc ml-4">{g}</li>
              ))}
            </ul>
          </div>
          <div>
            <div className="text-xs text-gray-500 mb-1.5 font-medium">Features</div>
            <ul className="space-y-1">
              {(content.prd?.features || []).map((f, i) => (
                <li key={i} className="text-sm text-gray-300 list-disc ml-4">{f}</li>
              ))}
            </ul>
          </div>
        </div>
        {(content.prd?.acceptance_criteria || []).length > 0 && (
          <div className="mt-3">
            <div className="text-xs text-gray-500 mb-1.5 font-medium">Acceptance Criteria</div>
            <ul className="space-y-1">
              {(content.prd?.acceptance_criteria || []).map((c, i) => (
                <li key={i} className="text-sm text-gray-400 list-disc ml-4">{c}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* Architecture */}
      <section className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h4 className="text-sm font-semibold text-white mb-3">Architecture</h4>
        <div className="grid gap-4 sm:grid-cols-2">
          <ArchField label="Tech Stack" values={content.architecture?.tech_stack} />
          <ArchField label="Directories" values={content.architecture?.directory_structure} />
          <ArchField label="Data Model" values={content.architecture?.data_model} />
          <ArchField label="API Contracts" values={content.architecture?.api_contracts} />
        </div>
      </section>

      {/* Modules */}
      <section className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h4 className="text-sm font-semibold text-white mb-3">
          Modules <span className="text-gray-500 font-normal">({(content.modules || []).length})</span>
        </h4>
        <div className="space-y-2">
          {(content.modules || []).map((m) => {
            const deps = m.depends_on || [];
            const inputs = m.input_contract || [];
            const outputs = m.output_contract || [];
            return (
            <div key={m.id} className="bg-gray-950 border border-gray-800 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-gray-800 text-blue-400">{m.id}</span>
                <span className="text-sm font-medium text-white">{m.name}</span>
                {deps.length > 0 && (
                  <span className="text-xs text-gray-500">depends on: {deps.join(", ")}</span>
                )}
              </div>
              {m.description && <p className="text-xs text-gray-400 mb-2">{m.description}</p>}
              <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
                {inputs.length > 0 && (
                  <span className="text-gray-500">
                    in: <span className="text-gray-300 font-mono">{inputs.join(", ")}</span>
                  </span>
                )}
                {outputs.length > 0 && (
                  <span className="text-gray-500">
                    out: <span className="text-gray-300 font-mono">{outputs.join(", ")}</span>
                  </span>
                )}
              </div>
            </div>
            );
          })}
        </div>
      </section>

      {/* Constraints */}
      {(content.constraints || []).length > 0 && (
        <section className="bg-yellow-950/20 border border-yellow-900/40 rounded-lg p-4">
          <h4 className="text-sm font-semibold text-yellow-300 mb-2">Constraints</h4>
          <ul className="space-y-1">
            {(content.constraints || []).map((c, i) => (
              <li key={i} className="text-sm text-yellow-200/80 list-disc ml-4">{c}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function ArchField({ label, values }: { label: string; values?: string[] }) {
  if (!values || values.length === 0) {
    return (
      <div>
        <div className="text-xs text-gray-500 mb-1 font-medium">{label}</div>
        <div className="text-sm text-gray-600">—</div>
      </div>
    );
  }
  return (
    <div>
      <div className="text-xs text-gray-500 mb-1 font-medium">{label}</div>
      <ul className="space-y-0.5">
        {values.map((v, i) => (
          <li key={i} className="text-sm text-gray-300 font-mono">{v}</li>
        ))}
      </ul>
    </div>
  );
}
