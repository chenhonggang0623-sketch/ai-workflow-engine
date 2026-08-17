"use client";

import { useState } from "react";
import type { WorkflowNode, AgentProviderName } from "@/lib/types";

const PROVIDER_OPTIONS: { value: AgentProviderName; label: string; description: string }[] = [
  { value: "openai", label: "OpenAI API", description: "云端 LLM API（分析、规划类任务）" },
  { value: "opencode_cli", label: "OpenCode CLI", description: "本地 OpenCode CLI Agent（编码、测试、代码审查）" },
  { value: "claude_cli", label: "Claude CLI", description: "本地 Claude Code CLI Agent" },
  { value: "codex_cli", label: "Codex CLI", description: "本地 OpenAI Codex CLI Agent" },
  { value: "local_model", label: "Local Model", description: "本地模型（Ollama、vLLM 等）" },
  { value: "ensemble", label: "Ensemble", description: "多 Agent 择优 / 审计（评审选优或多 provider 交叉审计）" },
];

const PROVIDER_TO_EXECUTOR: Record<AgentProviderName, string> = {
  openai: "llm_api",
  opencode_cli: "local_cli",
  claude_cli: "local_cli",
  codex_cli: "local_cli",
  local_model: "local_model",
  ensemble: "llm_api",
};

const ENSEMBLE_CANDIDATE_OPTIONS: AgentProviderName[] = [
  "openai",
  "opencode_cli",
  "claude_cli",
  "codex_cli",
  "local_model",
];

const PROVIDER_TO_CLI: Record<string, string> = {
  opencode_cli: "opencode",
  claude_cli: "claude",
  codex_cli: "codex",
};

function providerFromNode(node: WorkflowNode | undefined): AgentProviderName {
  const config = (node?.config || {}) as Record<string, unknown>;
  const provider = config.provider as string | undefined;
  if (provider && provider in PROVIDER_TO_EXECUTOR) return provider as AgentProviderName;
  const ec = (config.executor_config || {}) as Record<string, unknown>;
  const executorType = (config.executor_type as string) || "llm_api";
  if (executorType === "local_cli") {
    const cli = ec.provider as string | undefined;
    if (cli === "claude" || cli === "claude-code") return "claude_cli";
    if (cli === "codex") return "codex_cli";
    return "opencode_cli";
  }
  if (executorType === "local_model") return "local_model";
  return "openai";
}

export interface AgentConfigSave {
  provider: AgentProviderName;
  executor_type: string;
  executor_config: Record<string, unknown>;
  system_prompt: string;
}

export function AgentConfigDialog({
  node,
  nodeLabel,
  onClose,
  onSave,
  saving,
}: {
  node: WorkflowNode | null;
  nodeLabel: string;
  onClose: () => void;
  onSave: (updates: AgentConfigSave) => void;
  saving?: boolean;
}) {
  const config = (node?.config || {}) as Record<string, unknown>;
  const ec = (config.executor_config || {}) as Record<string, unknown>;
  const [provider, setProvider] = useState<AgentProviderName>(() => providerFromNode(node || undefined));
  const [systemPrompt, setSystemPrompt] = useState((config.system_prompt as string) || "");
  const [ensembleCandidates, setEnsembleCandidates] = useState<AgentProviderName[]>(
    (ec.candidates as AgentProviderName[]) || ["opencode_cli", "claude_cli"]
  );
  const [ensembleStrategy, setEnsembleStrategy] = useState<"best" | "concatenate">(
    (ec.strategy as "best" | "concatenate") || "best"
  );
  const [ensembleMode, setEnsembleMode] = useState<"normal" | "audit">(
    (ec.mode as "normal" | "audit") || "normal"
  );

  function handleSave() {
    const executorConfig = { ...(config.executor_config as Record<string, unknown> || {}) };
    if (provider === "ensemble") {
      executorConfig.candidates = ensembleCandidates;
      executorConfig.strategy = ensembleStrategy;
      executorConfig.mode = ensembleMode;
      delete executorConfig.provider;
    } else if (PROVIDER_TO_CLI[provider]) {
      executorConfig.provider = PROVIDER_TO_CLI[provider];
      delete executorConfig.candidates;
      delete executorConfig.strategy;
      delete executorConfig.mode;
    }
    onSave({
      executor_type: PROVIDER_TO_EXECUTOR[provider],
      executor_config: executorConfig,
      provider,
      system_prompt: systemPrompt,
    });
  }

  const nodeMeta = {
    role: (config.role as string) || "",
    purpose: (config.purpose as string) || "",
    moduleId: (config.module_id as string) || "",
    executorType: (config.executor_type as string) || "",
    skillId: (config.skill_id as string) || "",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700">
          <h3 className="text-base font-semibold text-white">配置 Agent</h3>
          <span className="text-sm text-gray-400">{nodeLabel}</span>
        </div>

        <div className="px-5 py-4 space-y-4">
          {(nodeMeta.role || nodeMeta.purpose || nodeMeta.moduleId || nodeMeta.skillId) && (
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 bg-gray-950/60 border border-gray-800 rounded-lg p-3 text-xs">
              {nodeMeta.moduleId && (
                <span className="text-gray-400">
                  module: <span className="text-blue-400 font-mono">{nodeMeta.moduleId}</span>
                </span>
              )}
              {nodeMeta.role && (
                <span className="text-gray-400">
                  role: <span className="text-gray-200">{nodeMeta.role}</span>
                </span>
              )}
              {nodeMeta.executorType && (
                <span className="text-gray-400">
                  executor: <span className="text-gray-200">{nodeMeta.executorType}</span>
                </span>
              )}
              {nodeMeta.skillId && (
                <span className="text-gray-400">
                  skill: <span className="text-purple-400 font-mono">{nodeMeta.skillId}</span>
                </span>
              )}
              {nodeMeta.purpose && (
                <span className="col-span-2 text-gray-400">
                  purpose: <span className="text-gray-200">{nodeMeta.purpose}</span>
                </span>
              )}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">Provider</label>
            <div className="space-y-2">
              {PROVIDER_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                    provider === opt.value
                      ? "border-blue-500 bg-blue-950/40"
                      : "border-gray-700 bg-gray-800/50 hover:border-gray-600"
                  }`}
                >
                  <input
                    type="radio"
                    name="provider"
                    value={opt.value}
                    checked={provider === opt.value}
                    onChange={() => setProvider(opt.value)}
                    className="mt-0.5 accent-blue-500"
                  />
                  <span>
                    <span className="block text-sm text-white">{opt.label}</span>
                    <span className="block text-xs text-gray-400 mt-0.5">{opt.description}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>

          {provider === "ensemble" && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1.5">
                  候选 Providers（Ensemble）
                </label>
                <div className="space-y-1.5">
                  {ENSEMBLE_CANDIDATE_OPTIONS.map((opt) => {
                    const label = PROVIDER_OPTIONS.find((p) => p.value === opt)?.label || opt;
                    return (
                      <label key={opt} className="flex items-center gap-2.5 p-2 rounded-lg border border-gray-700 bg-gray-800/50 hover:border-gray-600 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={ensembleCandidates.includes(opt)}
                          onChange={(e) => {
                            setEnsembleCandidates((prev) =>
                              e.target.checked
                                ? [...prev, opt]
                                : prev.filter((c) => c !== opt)
                            );
                          }}
                          className="accent-blue-500"
                        />
                        <span className="text-sm text-white">{label}</span>
                      </label>
                    );
                  })}
                </div>
                {ensembleCandidates.length === 0 && (
                  <p className="text-xs text-red-400 mt-1">至少选择一个候选 provider</p>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1.5">策略</label>
                  <select
                    value={ensembleStrategy}
                    onChange={(e) => setEnsembleStrategy(e.target.value as "best" | "concatenate")}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="best">best - 评审选优</option>
                    <option value="concatenate">concatenate - 拼接</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1.5">模式</label>
                  <select
                    value={ensembleMode}
                    onChange={(e) => setEnsembleMode(e.target.value as "normal" | "audit")}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="normal">normal - 正常执行</option>
                    <option value="audit">audit - 多 provider 审计</option>
                  </select>
                </div>
              </div>
            </>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1.5">
              System Prompt
            </label>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={5}
              placeholder="例如：你是一个前端开发工程师，负责创建 HTML/CSS/JS 页面..."
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
              spellCheck={false}
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 px-5 py-4 border-t border-gray-700">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-300 hover:text-white transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-500 disabled:opacity-50 transition-colors"
          >
            {saving ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}