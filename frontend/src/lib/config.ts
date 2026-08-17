import { get, put, post } from "./api";

export interface AppConfig {
  openai_api_key: string;
  has_openai_api_key: boolean;
  openai_base_url: string;
  default_llm_model: string;
  default_llm_provider: string;
  agent_default_provider: string;
  opencode_path: string;
  claude_code_path: string;
  codex_path: string;
  dag_max_nodes?: number;
  dag_max_edges?: number;
  dag_max_fan_in?: number;
  dag_max_fan_out?: number;
  dag_timeout_budget_seconds?: number;
  loaded_from: string;
}

export interface LLMTestResult {
  ok: boolean;
  error?: string;
  model?: string;
  base_url?: string;
  reply?: string;
}

export function getConfig(): Promise<AppConfig> {
  return get<AppConfig>("/config");
}

export function updateConfig(body: Partial<AppConfig>): Promise<AppConfig> {
  return put<AppConfig>("/config", body);
}

export function testLLM(body: {
  base_url?: string;
  api_key?: string;
  model?: string;
}): Promise<LLMTestResult> {
  return post<LLMTestResult>("/config/test-llm", body);
}