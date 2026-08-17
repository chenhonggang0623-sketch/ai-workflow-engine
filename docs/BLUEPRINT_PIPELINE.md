# Blueprint Pipeline — 需求 → PRD → 蓝图 → DAG 架构设计

## 1. 背景与目标

当前 MVP 的执行链路为 `用户需求 → PlannerAgent → DAG → 执行`，存在四个结构性问题：

| # | 问题 | 后果 |
|---|------|------|
| 1 | 模糊需求直接进 LLM 生成 DAG | DAG 质量取决于单次 prompt，无需求澄清环节 |
| 2 | 无架构规划层 | 模块划分、技术栈、接口契约无统一权威记录 |
| 3 | DAG 从需求生成而非架构 | 各节点职责缺乏约束，节点间数据流无契约 |
| 4 | 失败后仅节点级重试 | 无级联重规划，无法"换方案重来"，也无法把决策交还用户 |

本文档定义流水线重构方案：**需求 → PRD → 蓝图(Blueprint) → DAG**，以及执行失败的**级联重规划循环**。

### 已确认决策

1. **失败循环策略**：允许自动重新生成新 DAG；若重规划循环超过 **3 次**仍未解决问题，执行暂停并置为 `blocked`，将问题与决策选项抛回用户。
2. **蓝图持久化 + 版本化**：Blueprint 落库，每次修订生成新版本（`version+1`），旧版本标记 `superseded` 保留。

## 2. 整体架构

```
┌────────────────────────────────────────────────────────────────────┐
│                        Planning Pipeline (规划期)                    │
│                                                                    │
│  用户需求 ──①RequirementAnalyzer──> PRD ──②Architect──> Blueprint vN │
│                                                                    │
│                                                      ┌───────────┐ │
│   Blueprint ──③PlannerAgent──> DAG vN ──> 执行 ──────▶ 质量结果    │ │
│                                                    └─────┬─────┘   │
│                                                          │失败      │
│                 ┌────────────────────────────────────────┘          │
│                 ▼                                                   │
│        重规划循环（上限 3 次）: Architect.revise(Blueprint vN+1)      │
│              └──> PlannerAgent(DAG vN+1) ──> 重新执行                │
│                 │                                                    │
│                 仍失败 ──> Execution.status = blocked                │
│                              └──> 写入 ExecutionDecision ──> 用户决策 │
└────────────────────────────────────────────────────────────────────┘
```

### 分层职责

| 层 | 模块 | 输入 | 输出 | 权威性 |
|----|------|------|------|--------|
| 需求层 | `requirement_analyzer.py` | 用户模糊需求 | 结构化 PRD | 需求定义的唯一来源 |
| 架构层 | `architect.py` | PRD | Blueprint vN（落库） | 架构决策的唯一来源（single source of truth） |
| 编排层 | `planner_agent.py`（改造） | Blueprint | DAG vN | 执行计划的唯一来源（受蓝图约束） |
| 执行层 | `engine/`（现状） | DAG vN | 执行结果 | 不变 |
| 重规划层 | `replan_coordinator.py` | 失败结果 + 蓝图 | blocked / 新蓝图+DAG | 失败收敛的仲裁者 |

## 3. 数据模型

### 3.1 新增 `blueprints` 表（版本化）

```
blueprints
  id                  UUID PK
  workflow_id         UUID FK → workflows.id        (可空，plan 阶段为空，confirm 后回填)
  source_execution_id UUID FK → executions.id       (触发本次蓝图创建的 execution，可空)
  version             Integer default 1             (版本号，每次修订 +1)
  status              String default "active"       (active / superseded)
  content             JSON                          (蓝图内容，见 3.3)
  created_at          DateTime
```

- 同一逻辑蓝图的多代版本：`status=active` 始终只有一条（最新），修订时旧版本置 `superseded`。
- 关联关系：`workflow_id` 指向该蓝图当前服务的 workflow；`source_execution_id` 记录"哪次执行失败催生了这一版"。

### 3.2 表结构变更

- `executions` 增加列 `replan_count Integer default 0` — 级联重规划已执行次数。

### 3.3 新增 `execution_decisions` 表（抛回用户的决策单）

```
execution_decisions
  id              UUID PK
  execution_id    UUID FK → executions.id   NOT NULL
  reason          Text                      (失败原因汇总)
  attempts        Integer default 3         (已消耗的重规划次数)
  options         JSON                      (["retry","revise_blueprint","abandon"])
  blueprint       JSON                      (当前蓝图快照，供用户修订)
  workflow        JSON                      (当前 DAG 快照)
  status          String default "pending"  (pending / resolved)
  resolved_action String
  resolved_at     DateTime
  created_at      DateTime
```

### 3.4 蓝图内容结构（`content`）

```jsonc
{
  "prd": {
    "summary": "一句话目标",
    "goals": ["业务目标"],
    "features": ["功能清单"],
    "non_functional": ["非功能需求"],
    "acceptance_criteria": ["验收标准"],
    "assumptions": ["假设"],
    "open_questions": ["未决疑问"]
  },
  "architecture": {
    "tech_stack": ["技术栈"],
    "directory_structure": ["目录布局"],
    "data_model": ["数据实体"],
    "api_contracts": ["接口契约"]
  },
  "modules": [
    {
      "id": "唯一模块 id",
      "name": "模块名",
      "description": "职责",
      "depends_on": ["依赖的模块 id"],
      "input_contract": ["允许的输入字段"],
      "output_contract": ["承诺的输出字段"]
    }
  ],
  "constraints": ["蓝图约束，如：所有代码必须遵守模块划分；技术栈必须为 X"]
}
```

## 4. 模块设计

### 4.1 需求分析层 `app/planner/requirement_analyzer.py`（新增）

```python
class RequirementAnalyzer:
    def __init__(self, llm_gateway): ...
    async def analyze(self, requirement: str) -> dict:  # → PRD dict
```

- 流程：LLM 生成结构化 PRD（`REQUIREMENT_PROMPT`）→ 解析失败时走**关键词回退**（复用 `ComplexityAnalyzer` 的启发式：按长度/关键词生成基础 PRD），保证无 API key 也可用。
- 与现有 `PlannerAgent._build_fallback_workflow` 相同的容错哲学。

### 4.2 架构规划层 `app/planner/architect.py`（新增）

```python
class Architect:
    def __init__(self, llm_gateway): ...
    async def design(self, prd: dict) -> dict:          # PRD → Blueprint dict
    async def revise(self, blueprint: dict, failure: str,
                     extra_context: dict | None = None) -> dict:  # 蓝图修订 → 新内容
    async def save(self, content: dict, db, *,
                   workflow_id=None, source_execution_id=None) -> Blueprint  # 落库 + 版本化
```

- `design`：LLM 依据 PRD 生成模块划分、技术栈、数据模型、接口契约、约束；失败回退到**模板模块拆分**（按功能词拆分：auth/user/admin 等）。
- `revise`：把上次执行失败原因（失败节点 + 错误信息 + 相关上下文）注入 prompt，要求调整模块划分或契约；同样带回退。
- `save`：事务内查找该 workflow 的 active 蓝图 → 旧版置 `superseded` → 插入 `version+1` 的新记录。

### 4.3 编排层改造 `app/planner/planner_agent.py`

- `plan(requirement, constraints)` 内部改为三段式：`RequirementAnalyzer.analyze → Architect.design/save → generate_dag(blueprint)`。
- 新增 `generate_dag(blueprint: dict) -> dict`：输入蓝图，输出 DAG JSON。`PLAN_PROMPT` 重写为"按蓝图模块展开"：
  - 每个蓝图模块 → 至少一个节点，节点 `config.module_id` 必须为模块 id；
  - 节点 input/output mapping 必须取自模块契约字段；
  - DAG 必须覆盖蓝图全部模块；
  - `module_id` 相同的节点可串行拆分为"实现→自测"两步。
- `plan()` 返回值扩展：增加 `blueprint`（含 id/version/content）供前端展示与 confirm 关联。

### 4.4 蓝图一致性校验 `app/planner/planning_review.py`（升级）

保留现有结构校验（无环/去重/规模/单根单终），新增静态方法：

```python
@staticmethod
def review_against_blueprint(workflow: dict, blueprint: dict) -> dict:
    # 1. 覆盖率：每个蓝图模块至少一个节点（按 config.module_id）
    # 2. 合规性：agent 节点必须有 module_id，且 module_id 存在于蓝图
    # 3. 数据流：节点 input/output mapping 的字段名 ⊆ 该模块契约
    # 返回 {"approved": bool, "warnings": [...], "suggestions": [...]}
```

- `approved=False` 时，PlannerAgent 打回重新生成（与现有 cycle 处理一致）。

### 4.5 重规划协调器 `app/planner/replan_coordinator.py`（新增）

```python
MAX_REPLAN = 3

class ReplanCoordinator:
    def __init__(self, planner, architect, analyzer,
                 exec_mgr, db_factory): ...

    async def run(self, *, requirement, blueprint, workflow_def,
                  execution_id, project_path) -> dict:
        for attempt in range(MAX_REPLAN + 1):
            result = await exec_mgr.execute_workflow(workflow_def, execution_id,
                                                     db_factory, initial_context={...})
            if result.status == SUCCEEDED:
                return {...成功}
            if result.status in (CANCELLED, PAUSED):
                return {...原样}
            if attempt >= MAX_REPLAN:
                return self._block(execution_id, result, blueprint, workflow_def)
            # 级联重规划
            blueprint_content = await architect.revise(blueprint, 失败原因)
            blueprint = await architect.save(blueprint_content, source_execution_id=execution_id)
            workflow_def = await planner.generate_dag(blueprint_content)
            workflow_def = inject_workspace(workflow_def, project_path)  # 保留同一工作区
            replan_count += 1
```

关键规则：

1. **同一 execution 实例延续**：不新建 Execution 记录，`replan_count` 递增，DAG 节点 id 追加 `_r{n}` 后缀以区分重规划代际（NodeExecution 天然可追溯）。
2. **工作区保留**：重规划后同一 `project_path` 继续注入，上一轮产物保留为上下文（`context` 中含历史结果）。
3. **失败原因注入**：`architect.revise` 的输入包含失败节点 id、错误信息、已产出的 context 快照。
4. **阈值**：`replan_count >= 3` 仍失败 → 置 `blocked` + 写入 `execution_decisions`。

### 4.6 状态与语义

- `ExecutionStatus` 枚举新增 `BLOCKED = "blocked"`（engine/types.py）。
- blocked 语义：执行永久暂停等待用户裁决，不属于终态（与 FAILED 区分——用户还可从中恢复执行）。

## 5. API 设计

### 5.1 改造

| 端点 | 变更 |
|------|------|
| `POST /api/planner/plan` | 响应增加 `blueprint` 字段：`{id, version, content}` |
| `POST /api/planner/confirm` | 请求增加可选 `blueprint_id`；创建 workflow 后回填 blueprint 关联；执行改为 `ReplanCoordinator.run` |

### 5.2 新增

| 端点 | 说明 |
|------|------|
| `GET /api/blueprints/{workflow_id}` | 该 workflow 的最新 active 蓝图（含版本列表摘要） |
| `GET /api/blueprints/{workflow_id}/versions` | 蓝图全版本列表 |
| `POST /api/blueprints/{blueprint_id}/revise` | body: `{feedback}` → 生成新版本蓝图（人工修订入口，不自动重新执行） |
| `GET /api/executions/{id}/decision` | 该 execution 的 pending decision（blocked 时返回） |
| `POST /api/executions/{id}/resolve` | body: `{action, feedback?, blueprint?}`，action ∈ retry / revise_blueprint / abandon |

### 5.3 resolve 语义

| action | 行为 |
|--------|------|
| `retry` | 用当前蓝图 + 当前 DAG 重新执行（replan_count 重置为 0），工作区保留 |
| `revise_blueprint` | 用户提交修订后的蓝图 content（或 feedback 让 Architect 修订）→ 生成新版本 → 重新生成 DAG → 重新执行 |
| `abandon` | execution 置 `cancelled`，decision 置 `resolved`，流程终止 |

## 6. 前端设计

### 6.1 Workflow 详情页（`workflows/[id]/page.tsx`）

- 新增 **Blueprint** tab：展示 PRD 摘要、模块清单（含依赖关系）、接口契约、约束列表，版本号显示 `v{n}`。

### 6.2 执行详情页（`executions/[id]/page.tsx`）

- 状态 `blocked` 高亮（红色）。
- 轮询发现 blocked → 展示**决策面板**（覆盖层）：
  - 失败原因（来自 decision.reason）
  - 三个按钮：重试当前方案 / 修改蓝图重跑（弹出可编辑的蓝图 JSON 文本域，或留 feedback 文本域）/ 放弃
  - 提交后调 `POST /api/executions/{id}/resolve`，刷新页面。

## 7. 实施顺序

| 步骤 | 内容 | 验证 |
|------|------|------|
| 1 | 数据层：Blueprint / ExecutionDecision 模型 + Execution.replan_count + create_all 注册 | `test_blueprint_models.py` |
| 2 | PRD 层：RequirementAnalyzer（LLM + 回退） | `test_requirement_analyzer.py` |
| 3 | 蓝图层：Architect（design/revise/save，版本化） | `test_architect.py` |
| 4 | DAG 生成改造 + 蓝图一致性校验 | `test_planning_review_blueprint.py`、`test_planner.py` 更新 |
| 5 | 重规划协调器 + blocked + resolve API + ExecutionStatus.BLOCKED | `test_replan_coordinator.py`、`test_api.py` 更新 |
| 6 | 前端 Blueprint tab + 决策面板 | `npm run lint`、`npm run build` |
| 7 | 全链路集成验证（扩展 test.sh） | 全套 pytest + 页面手工走查 |

## 8. 测试策略

- 单元测试沿用 pytest-asyncio auto 模式，LLM 调用全部用 `FakeLLM`/关键词回退路径覆盖，不依赖真实 API。
- 重规划协调器测试要点：
  - 成功路径：第一次执行成功 → 不触发重规划；
  - 失败 1 次后第 2 次成功 → replan_count=1，最终 succeeded；
  - 连续失败 3 次 → blocked + decision 落库；
  - resolve=retry 后可再次执行；
  - 蓝图版本化：每次 revise 生成 version+1，旧版 superseded。
- 蓝图一致性校验测试要点：模块未覆盖 / module_id 不存在 / 契约字段越界 → 校验拒绝。

## 9. 风险与权衡

| 风险 | 缓解 |
|------|------|
| LLM 生成蓝图不稳定 | 关键词回退 + 蓝图一致性校验兜底；校验失败打回重生成 |
| 重规划丢进度 | 工作区保留 + 同一 execution 延续 + 代际节点 id 后缀 |
| 决策面板过度阻塞用户 | 只在 3 次自动重规划后触发，平时全自动 |
| 蓝图编辑自由度过大 | resolve 的 revise 分支校验仍过 PlanningReview.review_against_blueprint |
