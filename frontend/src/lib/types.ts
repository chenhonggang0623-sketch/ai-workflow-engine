export interface Workflow {
  id: string;
  name: string;
  description: string;
  version: string;
  status: string;
  definition: WorkflowDefinition;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowDefinition {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  [key: string]: unknown;
}

export interface WorkflowNode {
  id: string;
  type: string;
  label: string;
  config?: Record<string, unknown>;
  input_mapping?: { source: string; target: string }[];
  output_mapping?: { source: string; target: string }[];
  position?: { x: number; y: number };
}

export type ExecutorType = "llm_api" | "local_cli" | "local_model" | "mcp" | "human";

export type AgentProviderName = "openai" | "opencode_cli" | "claude_cli" | "codex_cli" | "local_model" | "ensemble";

export interface ExecutorConfig {
  executor_type: ExecutorType;
  executor_config?: Record<string, unknown>;
}

export interface WorkflowEdge {
  id?: string;
  source: string;
  target: string;
  label?: string;
  condition?: string;
}

export interface Execution {
  id: string;
  workflow_id: string;
  status: ExecutionStatus;
  context: Record<string, unknown>;
  replan_count: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface ExecutionListItem {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: ExecutionStatus;
  replan_count: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export type ExecutionStatus = "pending" | "running" | "paused" | "succeeded" | "failed" | "cancelled" | "blocked";

export interface NodeExecution {
  id: string;
  execution_id: string;
  node_execution_id: string | null;
  node_id: string;
  node_type: string;
  status: NodeStatus;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
  retry_count: number;
  started_at: string | null;
  finished_at: string | null;
  slow?: boolean;
  slow_elapsed_seconds?: number | null;
}

export type NodeInterventionAction = "wait" | "switch_model" | "terminate";

export interface NodeIntervention {
  node_id: string;
  action: NodeInterventionAction;
  provider?: string;
  model?: string;
}

export type NodeStatus = "pending" | "ready" | "running" | "waiting" | "succeeded" | "failed" | "skipped" | "cancelled";

export interface ExecutionLog {
  id: string;
  level: string;
  message: string;
  metadata: Record<string, unknown> | null;
  node_execution_id: string | null;
  created_at: string;
}

export interface Artifact {
  id: string;
  name: string;
  type: string;
  mime_type: string | null;
  size: number;
  version: number;
  status: string;
  tags: string[];
  created_at: string;
}

export interface Evaluation {
  id: string;
  agent_id: string;
  evaluator: string;
  scores: Record<string, number>;
  weighted_score: number;
  summary: string;
  passed: boolean;
  severity: string;
  created_at: string;
}

export interface PlanResponse {
  plan: WorkflowDefinition;
  blueprint: BlueprintPayload | null;
  explanation: string;
  estimated_duration_seconds: number | null;
}

export interface BlueprintPayload {
  id?: string;
  version?: number;
  content: BlueprintContent;
}

export interface BlueprintModule {
  id: string;
  name: string;
  description?: string;
  depends_on?: string[];
  input_contract?: string[];
  output_contract?: string[];
}

export interface BlueprintContent {
  prd: {
    summary: string;
    goals: string[];
    features: string[];
    non_functional: string[];
    acceptance_criteria: string[];
    assumptions: string[];
    open_questions: string[];
  };
  architecture: {
    tech_stack: string[];
    directory_structure: string[];
    data_model: string[];
    api_contracts: string[];
  };
  modules: BlueprintModule[];
  constraints: string[];
}

export interface Blueprint {
  id: string;
  workflow_id: string | null;
  source_execution_id: string | null;
  version: number;
  status: string;
  content: BlueprintContent;
  created_at: string;
}

export interface ExecutionDecision {
  id: string;
  execution_id: string;
  reason: string | null;
  attempts: number;
  options: string[];
  blueprint: BlueprintContent | null;
  workflow: Record<string, unknown> | null;
  status: string;
  resolved_action: string | null;
  created_at: string;
}

export interface PlanConfirmResponse {
  workflow_id: string;
  execution_id: string;
  status: string;
  project_path?: string;
}

export interface ProjectFile {
  path: string;
  type: "file" | "dir";
  size: number;
}

export interface ExecutionFilesResponse {
  execution_id: string;
  project_path: string | null;
  files: ProjectFile[];
}

export interface EnsembleScore {
  index: number;
  provider?: string;
  correctness?: number;
  completeness?: number;
  executability?: number;
  style?: number;
  score?: number;
  total?: number;
  rationale?: string;
  success?: boolean;
  error?: string | null;
}

export interface EnsembleFinding {
  severity?: string;
  location?: string;
  issue?: string;
  suggestion?: string;
  reviewer?: string;
}

export interface EnsembleInfo {
  mode?: "best" | "concatenate" | "audit";
  winner_index?: number;
  winner_provider?: string;
  rationale?: string;
  scores?: EnsembleScore[];
  candidates?: EnsembleScore[];
  findings?: EnsembleFinding[];
  critical_count?: number;
  recommend_rerun?: boolean;
  reviewers?: string[];
}

export interface RerunRecommendation {
  node_id: string;
  critical_count: number;
  findings_count: number;
  reviewers: string[];
}
