import { get, post } from "./api";
import type { Blueprint } from "./types";

export function getWorkflowBlueprint(workflowId: string): Promise<Blueprint> {
  return get<Blueprint>(`/blueprints/${workflowId}`);
}

export function listBlueprintVersions(workflowId: string): Promise<{ workflow_id: string; versions: Blueprint[] }> {
  return get<{ workflow_id: string; versions: Blueprint[] }>(`/blueprints/${workflowId}/versions`);
}

export function reviseBlueprint(blueprintId: string, feedback: string): Promise<Blueprint> {
  return post<Blueprint>(`/blueprints/${blueprintId}/revise`, { feedback });
}
