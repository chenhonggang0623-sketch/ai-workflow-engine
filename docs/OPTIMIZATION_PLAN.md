# Agent Workflow 引擎五大优化设计方案

> 本文档定义 ai-workflow-engine 从"可运行"到"生产可靠"的五个核心优化点的详细设计方案与实施顺序。
> 对应问题（2026-08-09）：
> 1. 生成 DAG 图的严谨性
> 2. DAG 任务节点不同 agent provider 之间的上下文共享
> 3. 单节点多 provider 并发出方案 + 评审择优
> 4. 多 provider 代码审计
> 5. 生成 DAG 时每个节点 agent 提示词的科学性

---

## 0. 优先级与依赖总览

五个问题并非并列，存在依赖关系：

```
P0 ── ① DAG 严谨性（执行前静态校验）        ← 问题1
  │
  └─ ② 跨 provider 上下文共享（归一化层）    ← 问题2
         │
P1 ── ③ 提示词工厂（契约驱动生成节点 prompt）← 问题5（依赖 ② 的契约归一化）
         │
P2 ── ④ 多 provider 择优评审（ensemble）    ← 问题3（依赖 ②③）
         │
      └─ ⑤ 多 provider 代码审计             ← 问题4（复用 ④ 的评审框架）
```

**原则**：先修"看不见的正确性"（校验、上下文），再上"看得见的花活"（评审、审计）。每个阶段独立可验证、可回滚。

---

## 1. DAG 严谨性（P0，问题 1）

### 1.1 现状与缺口

现状 `PlannerAgent` 已具备：
- LLM 生成 → `PlanningReview.review()`（结构校验：无环/去重/规模/单根单终）
- `PlanningReview.review_against_blueprint`（模块覆盖率 / module_id 合规 / 契约字段越界）
- 校验失败回退 `_build_from_modules`（确定性拓扑放置）

**缺口**（生成后、执行前的**静态校验**，零 LLM 成本）：

| # | 缺口 | 后果 |
|---|------|------|
| A | **契约数据流闭合校验**：上游节点 output_mapping 产出的字段，下游 input_mapping 是否真有来源 | 节点拿到 `None` 输入，LLM 瞎编 |
| B | **孤立/死节点检测**：无入边也无出边的节点（仅允许单节点工作流） | 白跑一轮、浪费 token |
| C | **扇入/扇出风暴**：单节点入度/出度无上限 | 上下文爆炸 / 串行瓶颈 |
| D | **超时预算缺失**：全 DAG 总耗时无预算概念 | 无法预估成本与排期 |

### 1.2 设计

新增 `app/engine/dag_validator.py`（纯函数模块，无 IO）：

```python
class DAGIssue(BaseModel):
    code: str            # e.g. "ORPHAN_NODE" / "INPUT_NO_SOURCE"
    level: str           # "error" | "warning"
    node_id: str | None
    message: str

class ValidationReport(BaseModel):
    approved: bool
    errors: list[DAGIssue]
    warnings: list[DAGIssue]
    suggestions: list[str]

def validate_dag(workflow: dict) -> ValidationReport
```

校验规则：

| 规则 | 级别 | 逻辑 |
|------|------|------|
| `NO_CYCLE` | error | networkx 循环检测 |
| `HAS_START` | error | 至少一个入度 0 节点 |
| `HAS_END` | error | 至少一个出度 0 节点 |
| `NODE_SIZE_LIMIT` | error | nodes ≤ 32, edges ≤ 96 |
| `INPUT_NO_SOURCE` | error | input_mapping.source 必须命中 `$.requirement` 或某上游节点 output_mapping.target |
| `OUTPUT_UNCONSUMED` | warning | 节点输出字段无下游消费（末端节点除外） |
| `ORPHAN_NODE` | warning | 既无入边也无出边（多节点 DAG 时） |
| `FAN_IN_LIMIT` | warning | 入度 > 8 |
| `FAN_OUT_LIMIT` | warning | 出度 > 6 |
| `TIMEOUT_BUDGET` | warning | Σ节点 timeout × 串行深度 > 全局预算（默认 60min） |

接入点：
- `PlannerAgent.generate_dag`：LLM 生成后 → `validate_dag` → 有 error 打回重生成（与现有 cycle 一致）。
- 执行入口 `POST /api/workflows/{id}/execute`：执行前兜底校验，error 级直接 400。

### 1.3 验证

```
backend/tests/test_dag_validator.py
  - 正常 DAG → approved
  - 有环 → error NO_CYCLE
  - input source 无上游产出 → error INPUT_NO_SOURCE
  - 孤立节点 → warning ORPHAN_NODE
  - 扇入 10 → warning FAN_IN_LIMIT
```
---

## 2. 跨 provider 上下文共享（P0，问题 2）

### 2.1 现状与缺口（代码已确认）

- `_apply_input_mapping`：按节点 input_mapping 从全局 context 提取字段 → `node_input`（只取声明字段）。
- `NodeRunner._run_agent`（`app/engine/node_runner.py:146-155`）：`ExecutionRequest(task=node_input, context={}, ...)` —— **context 恒为 `{}`**！
- 各 executor（llm_gateway / LocalCLIProvider / OpenAIProvider）拿到的 context 就是空 dict。

**直接后果**：
1. 下游 LLM 看不见上游任何输出（除非 input_mapping 显式声明过）。
2. 多 provider 并行/评审时每个候选只有孤立输入，评审无全局信息。
3. `ExecutionRequest.context` 结构预留了但从未被填 —— 逻辑没接。

### 2.2 设计

新增 `app/engine/context_service.py`：

```python
class ContextService:
    def __init__(self, max_context_chars: int = 64_000,
                 max_node_output_chars: int = 50_000): ...

    def build_agent_input(self, node, node_input: dict, ctx: dict) -> dict:
        # input_mapping 结果 + 全局必填字段（requirement / workflow_meta）合成请求 task

    def select_context(self, ctx: dict, include_keys: list[str] | None) -> str:
        # 用 input_mapping.target 名在 ctx 中检索并拼成紧凑文本（截断保护）

    def write_output(self, ctx: dict, node_id: str, out: dict, output_mappings) -> None:
        # 归一化后写入 ctx + 记录 _context_audit 摘要

    def normalize_output(self, provider: str, raw: dict) -> dict:
        # 异构 provider 输出 → 统一契约 {"output", "structured", "provider",
        #                                       "empty", "truncated"}
```

改动点：

| 位置 | 改动 |
|------|------|
| `node_runner.py:_run_agent` | `context={}` → `context_service.select_context(...)` 实际注入上游数据 |
| `execution_manager.py` | 每次节点输出归一化后写回 ctx；ctx 上限保护 |
| `llm_executor.py` / `local_cli_executor.py` | 收到 `request.context` 非空时拼入 prompt 尾部 `Context: ...` |

归一化规则（`normalize_output`）：
- `llm_api`（结构化 `{content,...}`）→ `text=content`，其余键进 `structured`。
- `local_cli`（`{output: 文本}`）→ `text=output`。
- 空 dict → `empty=True`（下游可感知）。
- 超 `max_node_output_chars` → 截断 + 追加 `(truncated...)` 标记。

### 2.3 验证

```
backend/tests/test_context.py
  - select_context 注入上游字段到 task
  - normalize_output 各 provider 归一化正确
  - 超长输出截断带标记
  - 上下文总量限长不超预算
```

---

## 3. 提示词工厂（P1，问题 5 —— 用户判定最重要）

### 3.1 现状与缺口

现状 `PLAN_PROMPT` 让 LLM 自由生成 `system_prompt`（回到 prompt 只有一句话"implement module X following constraints"，无结构）。
- 没有输入/输出 schema 说明
- 没有"上游产出在哪"的指针
- 没有上下文来源、输出格式要求
- fallback `_build_from_modules` 的模板同样单薄

### 3.2 设计

新增 `app/agent/prompt_factory.py`，纯函数，三段式组装：

```python
def build_system_prompt(role: str, purpose: str,
                        input_fields: list[str],      # input_mapping.targets + 全局字段
                        output_fields: list[str],     # output_mapping.targets 及 schema
                        constraints: list[str] | None,
                        base_prompt: str | None = None) -> str
```

模板结构：

```
# 角色
{role} —— {purpose}

# 可用的输入字段
- $.requirement（原始需求）
- {input_fields 逐项}

# 输出要求
必须生成以下字段，并放入输出映射对应键：{output_fields 逐项}
{若 output_schema 存在：输出必须为符合 schema 的 JSON 结构}

# 约束
- {constraints 逐条}
{base_prompt 追加在此（用户/LLM 自定义部分）}
```

接入点：
- `planner_agent._build_from_modules` / `_build_from_agents`：fallback 的 system_prompt 改走 `build_system_prompt`。
- `PLAN_PROMPT` 增加一条硬性规则："每个 agent 节点 system_prompt 必须为 `#角色 / 可输入字段 / 输出要求 / 约束` 四段式"，并给出模板示例。
- `NodeRunner._run_agent` 执行前兜底：若节点 system_prompt 缺失 → 用 `build_system_prompt` 现场生成（保证任何手工建的 workflow 也有合格 prompt）。

### 3.3 验证

```
tests/test_prompt_factory.py
  - 四段式结构完整、字段齐全
  - 带 base_prompt 时保留原内容
  - 无约束时省略约束段
  - 空输入字段时给出 $.requirement 兜底
```

---

## 4. 单节点多 provider 择优评审（P2，问题 3）

### 4.1 设计

新节点配置（`config.executor_config`）：

```json
{
  "provider": "multiple",
  "executor_type": "ensemble",
  "executor_config": {
    "candidates": ["openai", "codex_cli", "claude_cli"],
    "strategy": "best",            // best | concatenate
    "dedupe": true
  }
}
```

新增 `app/agent/executor/ensemble_executor.py`：

```python
class EnsembleExecutor(BaseExecutor):
    def __init__(self, router: ExecutorRouter, reviewer: ...): ...

    async def execute(self, request):
        # 1. 对每个 candidate 构造同任务/同上下文请求，串行执行（可控并发 2）
        # 2. 全部完成后调用评审（AgentReviewer）选最优
        # 3. 返回 winner 输出 + metadata["ensemble"] = 全部候选结果与分数
```

新增 `app/agent/providers/reviewer.py`（评审 agent）：
- 用 `config_store` 默认 LLM 对候选输出打分：正确性 / 完整性 / 可执行性 / 风格。
- 返回 `{"winner": idx, "scores": [..], "rationale": str}`。
- fallback：无 API key / 评审失败 → 取第一个成功的候选（确定性兜底）。

### 4.2 集成

- `ExecutorRouter.execute`：`provider == "evaluated" || executor_type == "ensemble"` → 分发给 EnsembleExecutor。
- `AgentProviderRegistry` 注册 `ensemble` provider（名字待定，如 `ensemble`）。
- 前端节点编辑器:provider 下拉增加 `ensemble`，出现 `candidates` multi-select。

### 4.3 验证

```
tests/test_ensemble_executor.py
  - 2 候选全成功 → 评审选最优，metadata 含 scores
  - 1 成功 1 失败 → 回退成功者
  - 全失败 → 聚合错误
  - 无评审可用 → 内存兜底（选长度最长或首个）
```

---

## 5. 多 provider 代码审计（P2，问题 4）

### 5.1 设计

复用 EnsembleExecutor 骨架，追加"评审→报告"语义，作为 `agent` 节点的审计模式：

```json
{
  "provider": "ensemble",
  "executor_config": {
    "mode": "audit",                 // 关键差异：审计模式
    "candidates": ["claude_cli", "openai"],
    "audit_target": "working_directory"  // 或 context 键名
  }
}
```

扩展 `EnsembleExecutor.execute`：`mode=audit` 时——
1. 各候选以**审计者角色**跑同一段输入（源码/输出），输出发现清单；
2. ReviewerAgent 合并为统一报告：

```json
{
  "findings": [{"severity": "critical|major|minor", "location": "...", "issue": "...", "suggestion": "..."}],
  "critical_count": 0,
  "recommend_rerun": false
}
```

- `recommend_rerun=true` → NodeResult 标记 `requires_rerun`（不自动重跑，交给上层/replan 决策）。
- fallback 与 ensemble 一致。

### 5.2 验证

```
tests/test_audit_executor.py
  - 双 reviewer 输出合并统一报告
  - critical=0 → recommend_rerun=false
  - critical>0 → 报告直出，不自动重跑
  - 无评审 → 单项 select 结果
```

---

## 6. 实施顺序与里程碑

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 (P0) | dag_validator + context 共享（含归一化） | `test_dag_validator.py` + `test_context.py` 全绿 |
| M2 (P1) | prompt_factory（fallback + 执行前兜底 + PLAN_PROMPT 规则） | `test_prompt_factory.py` + planner 测试更新 |
| M3 (P2) | EnsembleExecutor + ReviewerAgent + 审计模式 | `test_ensemble_executor.py` + `test_audit_executor.py` |
| M4 | 前端节点编辑器支持 ensemble / audit | `npm run lint` + `npm run build` |
| M5 | 全链路回归 | 全套 pytest + 手工执行一条带 ensemble 的 workflow |

## 7. 测试策略

- 单元测试沿用 pytest-asyncio，LLM 调用全部 FakeLLM / 回退路径覆盖，不依赖真实 API。
- 校验器、prompt factory、context 归一化均为纯函数，M1/M2 主要靠单测。
- Ensemble/Audit 做两层：无评审兜底路径（确定性）+ 有评审（FakeLLM 打分）。
- 每个里程碑跑 `pytest -q` + `npm run tsc/lint/build` 防回归。
