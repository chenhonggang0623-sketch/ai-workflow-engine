import { get } from "./api";
import type { Evaluation } from "./types";

export function listEvaluations(agentId?: string): Promise<Evaluation[]> {
  const qs = agentId ? `?agent_id=${agentId}` : "";
  return get<Evaluation[]>(`/evaluations${qs}`);
}

export function getExecutionGates(executionId: string): Promise<{
  execution_id: string;
  gates: { id: string; agent_id: string; score: number; passed: boolean; severity: string }[];
}> {
  return get(`/executions/${executionId}/gates`);
}

export function getExecutionReport(executionId: string): Promise<{
  progress: unknown;
  evaluations: {
    id: string;
    agent_id: string;
    weighted_score: number;
    passed: boolean;
    summary: string;
    created_at: string;
  }[];
}> {
  return get(`/executions/${executionId}/report`);
}
