# 方案节点前置的 DAG 生成设计

日期：2026-08-20
状态：已批准（B / B1 / schema / 落点B / 引用A / 范围A 六项决策）

## 背景与目标

当前流程：需求 → PRD（RequirementAnalyzer）→ 蓝图（Architect）→ DAG（PlannerAgent.generate_dag）。
执行时所有 agent 节点直接读 `$.requirement` + 上游模块输出，方案（PRD/蓝图）只存在于规划期产物中。

目标：planner 生成的 DAG 必须以一个**方案节点**（type=planner）开头，该节点在**执行期零 LLM 调用**地将
需求 + PRD + 蓝图组装为结构化方案，写入 context（`$.plan`）并落盘工作区 `PLAN.md`；
后续工作节点以方案为主输入执行。

## 决策记录

| 决策点 | 选择 |
|---|---|
| 方案产生时机 | B：规划期生成 PRD/蓝图，执行期注入 |
| 方案节点运行时行为 | B1：轻量组装，不调 LLM |
| 方案 schema | project_description / features / requirements / constraints / acceptance_criteria |
| 方案落点 | 双落点：context `$.plan` + 工作区文件 `PLAN.md` |
| 工作节点引用方式 | A：整份注入 `$.plan`（target=`plan`），原始需求仍自动附加 |
| 适用范围 | A：仅 planner 生成的 DAG 强制；用户手建 workflow 维持现状 |

## 数据流

```
规划期（不变）:  需求 → PRD → 蓝图 → DAG（generate_dag 内部改造）
执行期（改造）:  initial_context = {requirement, blueprint, project_path}
                ↓
                [方案节点(planner)] ──组装──> $.plan + PLAN.md（工作区）
                ↓
                [工作节点(agent)]  读 $.plan + 上游模块输出 → 执行
```

## 一、方案文档结构与落点

新增 `backend/app/engine/plan_assembler.py`（纯函数，无 LLM、无外部依赖）：

```python
def assemble_plan(requirement: str, blueprint: dict | None) -> dict:
    # project_description ← PRD.summary + 蓝图 architecture 摘要
    # features          ← PRD.features
    # requirements      ← 原始需求原文 + PRD.goals
    # constraints       ← 蓝图 constraints + PRD.non_functional
    # acceptance_criteria ← PRD.acceptance_criteria

def render_plan_markdown(plan: dict) -> str:
    # markdown 渲染，含标题与各节列表
```

无蓝图（用户手建 workflow 路径不生成方案节点，但函数本身可空蓝图调用）时各字段退化为空列表，
requirements 始终含需求原文。

## 二、DAG 生成改造（planner_agent）

### 方案节点模板

```json
{
  "id": "plan_node",
  "type": "planner",
  "label": "方案制定",
  "config": {"role": "planner", "purpose": "分析需求与蓝图，组装执行方案", "timeout_seconds": 120},
  "input_mapping": [{"source": "$.requirement", "target": "requirement"}],
  "output_mapping": [
    {"source": "plan", "target": "$.plan"},
    {"source": "plan_markdown", "target": "$.plan_markdown"}
  ]
}
```

### 1. LLM 路径

PLAN_PROMPT 增加：
- 可用节点类型补充 `planner`：DAG 的第一个节点（无 LLM，组装方案文档）
- 强制规则：第一个节点必须是 planner 类型；每个 agent 节点 input_mapping 必须含
  `{"source": "$.plan", "target": "plan"}`；`$.requirement` 仅允许在方案节点使用

### 2. 确定性兜底 `_ensure_plan_node(workflow, blueprint)`

LLM 生成/修订后调用：若 DAG 无 planner 类型节点，前置插入方案节点模板，
并把「无入边且非 plan_node 的首个节点」与方案节点连边。
幂等：已存在 plan_node 时仅补齐其 input_mapping。

### 3. Fallback 路径（_build_from_modules / _build_from_agents）

两个回退构建器直接产出方案节点开头 + 工作节点含 `$.plan` 映射的 DAG；
随后仍走 _align_contracts（幂等）。

### 4. _align_contracts 改造

- 每个 agent 节点契约对齐后，**强制前置** `{"source": "$.plan", "target": "plan"}`
  input_mapping（已存在则跳过），保证 LLM 路径与 fallback 路径行为一致
- planner 类型节点跳过契约对齐
- 契约字段的填充源维持 `$.requirement` / 上游模块输出（不变）

### 5. revise 路径

REVISE_PROMPT 增加「必须保留第一个方案节点」规则；输出后同样执行
`_ensure_plan_node` + `_inject_plan_mapping` 兜底。

## 三、校验层适配

- `dag_validator.validate_dag`：无需改动。方案节点 output_mapping 声明 `$.plan`，
  工作节点 `$.plan` 源经 producers/ancestors 解析通过；删掉方案节点后 `$.plan`
  无生产者 → INPUT_NO_SOURCE 明确报错（期望行为）
- `planning_review._check_contract_fields`：input 字段豁免条件
  `source != "$.requirement"` 扩展为 `source not in ("$.requirement", "$.plan")`，
  因为 `$.plan` 同为全局 context 键、不属于模块契约

## 四、执行期改造

### 1. workflows.py `POST /{id}/execute`

```python
blueprint_row = await Architect.get_latest(db, id)  # 或等价直查
if blueprint_row:
    initial_context = {**initial_context, "blueprint": blueprint_row.content}
initial_context = {**initial_context, "project_path": project_path}
```

### 2. replan_coordinator

两处 initial_context（line ~69 与 ~156）追加 `"blueprint": current_blueprint`
（replan 后 blueprint 已更新，直接取当前值）。

### 3. node_runner._run_planner 真实实现

```python
async def _run_planner(self, node, node_input, ctx, log_sink=None) -> dict:
    requirement = node_input.get("requirement") or ctx.get("requirement") or ""
    blueprint = ctx.get("blueprint") or {}
    plan = assemble_plan(requirement, blueprint)
    markdown = render_plan_markdown(plan)
    project_path = ctx.get("project_path") or node.config.working_directory
    if project_path:
        # 写 {project_path}/PLAN.md（幂等，异常仅告警不阻断执行）
    return {"plan": plan, "plan_markdown": markdown}
```

方案节点是 DAG 首节点、无入边依赖，天然先于工作节点调度；工作节点经
`build_agent_context` 按 input_mapping 取到 `plan`（target 为 `plan`，
与全局 `requirement` 键无冲突），原始需求仍自动附加。

## 五、边界

- 用户手建 workflow：无蓝图 → 无方案节点，维持现状（读 `$.requirement`）
- 用户在编辑器删除方案节点：工作节点 `$.plan` 源校验失败，执行被拒绝并给出明确错误
- 无 PRD 字段（空蓝图）：assemble_plan 产出空列表字段，仅 requirements 含原文
- PLAN.md 写入失败：仅告警，不阻断执行（context 仍有 `$.plan`）

## 六、测试计划

- `test_plan_assembler.py`：assemble_plan 字段映射 / 空蓝图退化 / render_plan_markdown 结构
- `test_node_runner.py` 扩展：_run_planner 组装 + PLAN.md 写入（含 project_path 缺失分支）
- `test_planner.py` 扩展：LLM 路径 DAG 首节点为 planner / LLM 丢节点时 _ensure_plan_node 兜底 /
  fallback 路径含方案节点 / revise 保留方案节点
- `test_dag_validator.py` 扩展：`$.plan` 源在方案节点上游时通过；无方案节点时报 INPUT_NO_SOURCE
- `test_planning_review_blueprint.py` 扩展：`$.plan` 源不触发契约字段告警
- `test_replan_coordinator.py` 扩展：initial_context 含 blueprint
- `test_execution_manager.py` 新增：E2E plan_node → agent，验证 `$.plan` 落 context 并进入 agent node_input
- 回归：既有测试全绿（全量 452 通过，仅 4 个历史基线失败）

## 七、实现状态

- [x] `plan_assembler.py`：assemble_plan + render_plan_markdown（纯函数，无 LLM）
- [x] `node_runner.py`：`_run_planner` 真实实现 + PLAN.md 幂等写入
- [x] `planner_agent.py`：PLAN_PROMPT 规则、PLAN_NODE_TEMPLATE、`_ensure_plan_node`/`_inject_plan_mapping`，
      接入 generate_dag（LLM 与 fallback 两条路径）与 revise；`_inject_plan_mapping` 先于 `_apply_skills`，
      使 llm_api 节点的 system_prompt 列出 `$.plan` 输入
- [x] `workflows.py` execute 路由：注入 active blueprint + project_path 到 initial_context
- [x] `replan_coordinator.py`：两处 initial_context 注入 blueprint
- [x] `planning_review.py`：契约检查豁免 `$.plan`
- [x] 前端 WorkflowDAG.tsx：planner 节点类型渲染已存在，无需改动
- [x] 测试全绿（452 passed / 4 baseline failed）
