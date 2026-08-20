"use client";

import { useCallback, useEffect, useState } from "react";
import { getConfig, updateConfig, testLLM, getProviders, type AppConfig, type LLMTestResult, type ProviderStatus } from "@/lib/config";

const AGENT_PROVIDERS = [
  { value: "opencode_cli", label: "OpenCode CLI", desc: "本地 OpenCode 命令行 Agent（默认）" },
  { value: "claude_cli", label: "Claude Code CLI", desc: "本地 Claude Code 命令行 Agent" },
  { value: "codex_cli", label: "Codex CLI", desc: "本地 OpenAI Codex 命令行 Agent" },
  { value: "openai", label: "LLM API", desc: "直接调用大模型 API（OpenAI 兼容）" },
];

const PLANNING_PROVIDERS = [
  { value: "opencode_cli", label: "OpenCode CLI", desc: "用本地 OpenCode 跑需求解析与 DAG 生成（免 API Key，推荐）" },
  { value: "claude_cli", label: "Claude Code CLI", desc: "用本地 Claude Code 跑需求解析与 DAG 生成" },
  { value: "codex_cli", label: "Codex CLI", desc: "用本地 Codex CLI 跑需求解析与 DAG 生成" },
  { value: "openai", label: "LLM API", desc: "走下方 OpenAI 兼容 API（需有效 Key）" },
];

const LLM_PROVIDERS = [
  { value: "openai", label: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  { value: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  { value: "moonshot", label: "Moonshot Kimi", base_url: "https://api.moonshot.cn/v1", model: "kimi-k2" },
  { value: "openrouter", label: "OpenRouter", base_url: "https://openrouter.ai/api/v1", model: "openai/gpt-4o-mini" },
  { value: "agnes", label: "Agnes", base_url: "https://apihub.agnes-ai.com/v1", model: "agnes-2.5-flash" },
  { value: "ollama", label: "Ollama (本地)", base_url: "http://localhost:11434/v1", model: "qwen2.5:14b" },
  { value: "vllm", label: "vLLM (自建)", base_url: "http://localhost:8000/v1", model: "" },
  { value: "custom", label: "自定义", base_url: "", model: "" },
];

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-gray-300">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-gray-600">{hint}</span>}
    </label>
  );
}

const inputCls =
  "mt-1 w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:border-blue-500 focus:outline-none";

function Card({
  title,
  desc,
  children,
}: {
  title: string;
  desc?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-5">
      <h2 className="text-base font-semibold text-white">{title}</h2>
      {desc && <p className="mt-1 text-sm text-gray-500">{desc}</p>}
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  );
}

export default function ConfigPage() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<LLMTestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [apiKeyDirty, setApiKeyDirty] = useState(false);

  const [llmProvider, setLlmProvider] = useState("custom");
  const [planningProvider, setPlanningProvider] = useState("opencode_cli");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [defaultProvider, setDefaultProvider] = useState("opencode_cli");
  const [opencodePath, setOpencodePath] = useState("opencode");
  const [claudePath, setClaudePath] = useState("claude");
  const [codexPath, setCodexPath] = useState("codex");
  const [dagMaxNodes, setDagMaxNodes] = useState("");
  const [dagMaxEdges, setDagMaxEdges] = useState("");
  const [dagMaxFanIn, setDagMaxFanIn] = useState("");
  const [dagMaxFanOut, setDagMaxFanOut] = useState("");
  const [dagTimeoutBudget, setDagTimeoutBudget] = useState("");
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [effectiveDefault, setEffectiveDefault] = useState("");

  const load = useCallback(async () => {
    try {
      const cfg = await getConfig();
      setConfig(cfg);
      setBaseUrl(cfg.openai_base_url);
      setApiKey(cfg.openai_api_key);
      setModel(cfg.default_llm_model);
      setDefaultProvider(cfg.agent_default_provider);
      setPlanningProvider(cfg.default_llm_provider || "opencode_cli");
      setOpencodePath(cfg.opencode_path || "opencode");
      setClaudePath(cfg.claude_code_path || "claude");
      setCodexPath(cfg.codex_path || "codex");
      setDagMaxNodes(cfg.dag_max_nodes != null ? String(cfg.dag_max_nodes) : "");
      setDagMaxEdges(cfg.dag_max_edges != null ? String(cfg.dag_max_edges) : "");
      setDagMaxFanIn(cfg.dag_max_fan_in != null ? String(cfg.dag_max_fan_in) : "");
      setDagMaxFanOut(cfg.dag_max_fan_out != null ? String(cfg.dag_max_fan_out) : "");
      setDagTimeoutBudget(
        cfg.dag_timeout_budget_seconds != null
          ? String(cfg.dag_timeout_budget_seconds)
          : ""
      );
      const known = LLM_PROVIDERS.find(
        (p) => p.value !== "custom" && p.base_url === cfg.openai_base_url
      );
      setLlmProvider(known ? known.value : "custom");
    } catch {
      setSaveMsg("Failed to load config");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const loadProviders = useCallback(async () => {
    try {
      const payload = await getProviders();
      setProviders(payload.providers);
      setEffectiveDefault(payload.default_provider);
    } catch {
      // provider 列表加载失败不阻塞页面
    }
  }, []);

  useEffect(() => {
    loadProviders();
  }, [loadProviders]);

  async function setDefaultProviderViaApi(name: string) {
    try {
      await updateConfig({ agent_default_provider: name });
      setDefaultProvider(name);
      await loadProviders();
      setSaveMsg(`Default agent provider set to ${name}`);
    } catch (e) {
      setSaveMsg(`Failed to set default provider: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  function handleProviderPreset(value: string) {
    setLlmProvider(value);
    const preset = LLM_PROVIDERS.find((p) => p.value === value);
    if (preset && value !== "custom") {
      setBaseUrl(preset.base_url);
      if (preset.model) setModel(preset.model);
    }
  }

  async function handleSave() {
    setSaving(true);
    setSaveMsg(null);
    try {
      const body: Partial<AppConfig> = {
        openai_base_url: baseUrl.trim(),
        default_llm_model: model.trim(),
        default_llm_provider: planningProvider,
        agent_default_provider: defaultProvider,
        opencode_path: opencodePath.trim(),
        claude_code_path: claudePath.trim(),
        codex_path: codexPath.trim(),
      };
      const intOrUndefined = (s: string) => (s.trim() === "" ? undefined : parseInt(s, 10));
      const maxNodes = intOrUndefined(dagMaxNodes);
      const maxEdges = intOrUndefined(dagMaxEdges);
      const maxFanIn = intOrUndefined(dagMaxFanIn);
      const maxFanOut = intOrUndefined(dagMaxFanOut);
      const timeoutBudget = intOrUndefined(dagTimeoutBudget);
      if (maxNodes !== undefined) body.dag_max_nodes = maxNodes;
      if (maxEdges !== undefined) body.dag_max_edges = maxEdges;
      if (maxFanIn !== undefined) body.dag_max_fan_in = maxFanIn;
      if (maxFanOut !== undefined) body.dag_max_fan_out = maxFanOut;
      if (timeoutBudget !== undefined) body.dag_timeout_budget_seconds = timeoutBudget;
      if (apiKeyDirty && apiKey.trim()) {
        body.openai_api_key = apiKey.trim();
      }
      const saved = await updateConfig(body);
      setConfig(saved);
      setApiKeyDirty(false);
      setSaveMsg("Saved. Applied immediately to new executions.");
    } catch (e) {
      setSaveMsg(`Save failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const body: { base_url?: string; api_key?: string; model?: string } = {
        base_url: baseUrl.trim(),
        model: model.trim(),
      };
      if (apiKeyDirty && apiKey.trim()) body.api_key = apiKey.trim();
      setTestResult(await testLLM(body));
    } catch (e) {
      setTestResult({
        ok: false,
        error: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setTesting(false);
    }
  }

  if (loading) {
    return <div className="text-sm text-gray-500">Loading…</div>;
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Config</h1>
        <p className="mt-1 text-sm text-gray-500">
          Model &amp; agent provider settings. Saved values override{" "}
          <code className="rounded bg-gray-900 px-1.5 py-0.5 text-xs">backend/.env</code>.
        </p>
      </div>

      <Card title="LLM API" desc="Planner / direct-LLM agents use this endpoint (OpenAI-compatible).">
        <div>
          <span className="text-sm font-medium text-gray-300">Provider preset</span>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {LLM_PROVIDERS.map((p) => (
              <button
                key={p.value}
                onClick={() => handleProviderPreset(p.value)}
                className={`rounded-md border px-3 py-2 text-sm transition-colors ${
                  llmProvider === p.value
                    ? "border-blue-500 bg-blue-500/10 text-blue-300"
                    : "border-gray-700 bg-gray-900 text-gray-400 hover:border-gray-600"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
        <Field label="Base URL" hint="OpenAI-compatible endpoint, e.g. https://api.deepseek.com/v1">
          <input
            className={inputCls}
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.openai.com/v1"
          />
        </Field>
        <Field label="API Key" hint="Keep it empty to reuse the saved key.">
          <input
            className={inputCls}
            type="password"
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value);
              setApiKeyDirty(true);
            }}
            placeholder={config?.has_openai_api_key ? "•••••••• (saved key in use)" : "sk-…"}
            autoComplete="off"
          />
        </Field>
        <Field label="Model">
          <input
            className={inputCls}
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="gpt-4o-mini / deepseek-chat / kimi-k2 …"
          />
        </Field>
        <div className="flex items-center gap-3">
          <button
            onClick={handleTest}
            disabled={testing}
            className="rounded-md border border-gray-700 bg-gray-900 px-4 py-2 text-sm text-gray-300 hover:border-gray-600 disabled:opacity-50"
          >
            {testing ? "Testing…" : "Test connection"}
          </button>
          {testResult && (
            <span
              className={`text-sm ${
                testResult.ok ? "text-emerald-400" : "text-red-400"
              }`}
            >
              {testResult.ok
                ? `Connected ✓ (${testResult.model}) → ${testResult.reply}`
                : `Failed: ${testResult.error}`}
            </span>
          )}
        </div>
      </Card>

      <Card title="Planner Provider" desc="Used for requirement parsing, blueprint design and DAG generation.">
        <div className="space-y-2">
          {PLANNING_PROVIDERS.map((p) => (
            <label
              key={p.value}
              className={`flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2.5 transition-colors ${
                planningProvider === p.value
                  ? "border-blue-500 bg-blue-500/10"
                  : "border-gray-700 bg-gray-900 hover:border-gray-600"
              }`}
            >
              <input
                type="radio"
                name="planning-provider"
                className="mt-1 accent-blue-500"
                checked={planningProvider === p.value}
                onChange={() => setPlanningProvider(p.value)}
              />
              <span>
                <span className="block text-sm font-medium text-gray-200">{p.label}</span>
                <span className="block text-xs text-gray-500">{p.desc}</span>
              </span>
            </label>
          ))}
        </div>
      </Card>

      <Card title="Provider 列表" desc="自动探测本地 CLI 与 API Key 的可用性；不可用的项会提示配置方式。">
        <div className="space-y-2">
          {providers.length === 0 && (
            <p className="text-sm text-gray-500">加载中…</p>
          )}
          {providers.map((p) => (
            <div
              key={p.name}
              className={`flex items-center gap-3 rounded-md border px-3 py-2.5 ${
                p.enabled
                  ? "border-gray-700 bg-gray-900"
                  : "border-amber-900/40 bg-amber-950/10"
              }`}
            >
              <span
                className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${
                  p.enabled ? "bg-green-500" : "bg-amber-500"
                }`}
                title={p.enabled ? "已启用" : "未启用"}
              />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-200">{p.label}</span>
                  <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-gray-400">
                    {p.kind}
                  </span>
                  {p.default && (
                    <span className="rounded bg-blue-500/15 px-1.5 py-0.5 text-[10px] text-blue-300">
                      默认
                    </span>
                  )}
                </span>
                <span className="block truncate text-xs text-gray-500">{p.reason}</span>
              </span>
              {p.enabled && !p.default && (
                <button
                  onClick={() => setDefaultProviderViaApi(p.name)}
                  className="shrink-0 rounded-md border border-gray-700 px-2.5 py-1 text-xs text-gray-300 transition-colors hover:border-blue-500 hover:text-blue-300"
                >
                  设为默认
                </button>
              )}
            </div>
          ))}
        </div>
      </Card>

      <Card title="Default Agent Provider" desc="Used when a workflow node doesn't specify one.">
        <div className="space-y-2">
          {AGENT_PROVIDERS.map((p) => (
            <label
              key={p.value}
              className={`flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2.5 transition-colors ${
                defaultProvider === p.value
                  ? "border-blue-500 bg-blue-500/10"
                  : "border-gray-700 bg-gray-900 hover:border-gray-600"
              }`}
            >
              <input
                type="radio"
                name="default-provider"
                className="mt-1 accent-blue-500"
                checked={defaultProvider === p.value}
                onChange={() => setDefaultProvider(p.value)}
              />
              <span>
                <span className="block text-sm font-medium text-gray-200">{p.label}</span>
                <span className="block text-xs text-gray-500">{p.desc}</span>
              </span>
            </label>
          ))}
        </div>
      </Card>

      <Card title="Local CLI Paths" desc="Executables used by the CLI providers above.">
        <Field label="OpenCode CLI" hint="opencode_cli provider">
          <input className={inputCls} value={opencodePath} onChange={(e) => setOpencodePath(e.target.value)} />
        </Field>
        <Field label="Claude Code CLI" hint="claude_cli provider">
          <input className={inputCls} value={claudePath} onChange={(e) => setClaudePath(e.target.value)} />
        </Field>
        <Field label="Codex CLI" hint="codex_cli provider">
          <input className={inputCls} value={codexPath} onChange={(e) => setCodexPath(e.target.value)} />
        </Field>
      </Card>

      <Card
        title="DAG Validation Limits"
        desc="Thresholds for pre-execution DAG checks. Empty = defaults (32 nodes / 96 edges / fan-in 8 / fan-out 6 / 3600s)."
      >
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Field label="Max nodes" hint="dag_max_nodes">
            <input
              className={inputCls}
              inputMode="numeric"
              value={dagMaxNodes}
              onChange={(e) => setDagMaxNodes(e.target.value)}
              placeholder="32"
            />
          </Field>
          <Field label="Max edges" hint="dag_max_edges">
            <input
              className={inputCls}
              inputMode="numeric"
              value={dagMaxEdges}
              onChange={(e) => setDagMaxEdges(e.target.value)}
              placeholder="96"
            />
          </Field>
          <Field label="Max fan-in" hint="dag_max_fan_in">
            <input
              className={inputCls}
              inputMode="numeric"
              value={dagMaxFanIn}
              onChange={(e) => setDagMaxFanIn(e.target.value)}
              placeholder="8"
            />
          </Field>
          <Field label="Max fan-out" hint="dag_max_fan_out">
            <input
              className={inputCls}
              inputMode="numeric"
              value={dagMaxFanOut}
              onChange={(e) => setDagMaxFanOut(e.target.value)}
              placeholder="6"
            />
          </Field>
          <Field label="Timeout budget (s)" hint="dag_timeout_budget_seconds">
            <input
              className={inputCls}
              inputMode="numeric"
              value={dagTimeoutBudget}
              onChange={(e) => setDagTimeoutBudget(e.target.value)}
              placeholder="3600"
            />
          </Field>
        </div>
      </Card>

      <div className="flex items-center gap-4">
        <button
          onClick={handleSave}
          disabled={saving}
          className="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {saveMsg && <span className="text-sm text-gray-400">{saveMsg}</span>}
      </div>
    </div>
  );
}