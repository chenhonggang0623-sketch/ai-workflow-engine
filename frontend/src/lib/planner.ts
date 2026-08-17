import { get, post } from "./api";
import type { PlanResponse, PlanConfirmResponse } from "./types";

export function generatePlan(requirement: string, constraints?: Record<string, unknown>): Promise<PlanResponse> {
  return post<PlanResponse>("/planner/plan", { requirement, constraints: constraints || {} });
}

export function confirmPlan(modifications: Record<string, unknown>): Promise<PlanConfirmResponse> {
  return post<PlanConfirmResponse>("/planner/confirm", { approved: true, modifications });
}

export function listTemplates(): Promise<{ categories: unknown[] }> {
  return get("/planner/templates");
}
