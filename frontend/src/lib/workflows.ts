import { get, post, put, del } from "./api";
import type { Workflow } from "./types";

export function listWorkflows(): Promise<Workflow[]> {
  return get<Workflow[]>("/workflows");
}

export function getWorkflow(id: string): Promise<Workflow> {
  return get<Workflow>(`/workflows/${id}`);
}

export function createWorkflow(data: {
  name: string;
  description?: string;
  definition?: Record<string, unknown>;
}): Promise<Workflow> {
  return post<Workflow>("/workflows", data);
}

export function updateWorkflow(
  id: string,
  data: Partial<{ name: string; description: string; definition: Record<string, unknown> }>
): Promise<Workflow> {
  return put<Workflow>(`/workflows/${id}`, data);
}

export function deleteWorkflow(id: string): Promise<void> {
  return del(`/workflows/${id}`);
}

export function executeWorkflow(id: string): Promise<{ execution_id: string }> {
  return post<{ execution_id: string }>(`/workflows/${id}/execute`);
}

export function updateNodeExecutor(
  workflowId: string,
  nodeId: string,
  data: {
    executor_type: string;
    executor_config: Record<string, unknown>;
    provider?: string;
    system_prompt?: string;
  },
): Promise<Workflow> {
  return put<Workflow>(`/workflows/${workflowId}/nodes/${nodeId}/executor`, {
    executor_type: data.executor_type,
    executor_config: data.executor_config,
    provider: data.provider,
    system_prompt: data.system_prompt,
  });
}
