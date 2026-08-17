import { get, post } from "./api";
import type { Execution, ExecutionListItem, ExecutionLog, NodeExecution, ExecutionFilesResponse, ExecutionDecision, NodeIntervention } from "./types";

export function listExecutions(params?: {
  workflow_id?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<ExecutionListItem[]> {
  const qs = new URLSearchParams();
  if (params?.workflow_id) qs.set("workflow_id", params.workflow_id);
  if (params?.status) qs.set("status", params.status);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const query = qs.toString();
  return get<ExecutionListItem[]>(`/executions${query ? `?${query}` : ""}`);
}

export function getExecution(id: string): Promise<Execution> {
  return get<Execution>(`/executions/${id}`);
}

export function getExecutionDecision(id: string): Promise<ExecutionDecision | null> {
  return get<ExecutionDecision | null>(`/executions/${id}/decision`);
}

export function resolveExecution(
  id: string,
  action: "retry" | "revise_blueprint" | "abandon",
  payload?: { feedback?: string; blueprint?: Record<string, unknown> }
): Promise<{ status: string; action: string; execution_id: string }> {
  return post<{ status: string; action: string; execution_id: string }>(`/executions/${id}/resolve`, {
    action,
    feedback: payload?.feedback,
    blueprint: payload?.blueprint,
  });
}

export function getExecutionFiles(id: string): Promise<ExecutionFilesResponse> {
  return get<ExecutionFilesResponse>(`/executions/${id}/files`);
}

export function getExecutionLogs(id: string): Promise<ExecutionLog[]> {
  return get<ExecutionLog[]>(`/executions/${id}/logs`);
}

export function getExecutionNodes(id: string): Promise<NodeExecution[]> {
  return get<NodeExecution[]>(`/executions/${id}/nodes`);
}

export function pauseExecution(id: string): Promise<{ status: string; execution_id: string }> {
  return post(`/executions/${id}/pause`);
}

export function resumeExecution(id: string): Promise<{ status: string; execution_id: string }> {
  return post(`/executions/${id}/resume`);
}

export function cancelExecution(id: string): Promise<{ status: string; execution_id: string }> {
  return post(`/executions/${id}/cancel`);
}

export function interveneExecution(
  id: string,
  payload: NodeIntervention
): Promise<{ status: string; execution_id: string }> {
  return post(`/executions/${id}/intervene`, payload);
}
