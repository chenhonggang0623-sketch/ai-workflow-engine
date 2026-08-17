# Skill Prompt Pipeline — 节点提示词 Skill 化方案

## 1. 背景与问题

当前 DAG 角色节点的 `system_prompt` 由规划 LLM 在 `PLAN_PROMPT` 中现场编写（`planner_agent.py`），存在四个问题：

| # | 问题 | 后果 |
|---|------|------|
| 1 | 提示词一次性生成，不可复用 | 每次规划成本高、风格漂移 |
| 2 | 无角色方法论沉淀 | 节点行为质量依赖单次 prompt 质量 |
| 3 | 无兜底角色库 | LLM 输出质量差时无降级手段 |
| 4 | 业务调整无入口 | 只能整体重规划，无法分层微调 |

## 2. 目标与设计原则

```
system_prompt = 确定性层(SKILL.md 角色原型) + 变量层(业务上下文)
```

- **skill = 角色的行为基因**：可复用、版本化、随仓库 git 管理
- **业务变量自动注入**：蓝图模块契约、约束、需求 → 复用 `build_node_prompt` 四段式组装
- **分层调整**：节点级覆盖 > skill 级编辑 > 选择级替换
- **向后兼容**：无 `skill_id` 的节点走原逻辑，行为不变

## 3. Skill 库来源（已落地）

superpowers（MIT license）全部 14 个企业级软件开发全流程 skill 已复制到项目根 `skills/`（51 个文件，保留 SKILL.md + references/scripts 完整目录结构）：

| 域 | skill | 默认映射节点 |
|----|-------|--------------|
| 需求/计划 | brainstorming、writing-plans、executing-plans | 计划/方案节点 |
| 实现/测试 | subagent-driven-development、test-driven-development、dispatching-parallel-agents | 实现/测试节点 |
| 调试/验收 | systematic-debugging、verification-before-completion | 调试/验收节点 |
| 审查/协作 | requesting-code-review、receiving-code-review、using-git-worktrees、finishing-a-development-branch | 审查/收尾节点 |
| 元（兜底） | using-superpowers、writing-skills | 未知类型兜底 |

- **原型**：规划 LLM 从 catalog（frontmatter 摘要）中选择
- **兜底**：LLM 未选/选错时按节点 purpose 关键词映射默认 skill；映射不到 → `using-superpowers`
- **自研改造**：`skills/custom/<name>/` 优先于同名原型（交互式 skill 的自动化适配版）

## 4. 双通道使用方式

| 通道 | 适用节点 | 做法 |
|------|---------|------|
| A. 内联渲染 | `llm_api`（openai 纯推理） | 规划期把 SKILL.md 正文渲染进 system_prompt，烙进 DAG |
| B. 工作区注入 | `local_cli`（opencode_cli/claude_cli） | skill 目录复制到生成项目工作区 `.opencode/skills/` / `.claude/skills/`，CLI 运行时按需加载（渐进披露，省 token） |

## 5. 渲染时机

**规划期为主，执行期兜底**：

- 规划期（`generate_dag` 后）：选 skill → 渲染 → 完整 prompt 烙进 DAG → 前端 confirm 页可见可编辑
- 执行期：保留现有 `PromptTemplate.render(system_prompt, context)`（runtime.py:106 / llm_executor.py:65）渲染运行时变量，与 skill 渲染分层不冲突
- 稳定性：skill 更新不影响已确认 DAG；失败 replan 时用新版重渲染
- 变量语法约定：skill 正文只允许业务变量 `{{var}}`（规划期渲染掉），避免与执行期 context 变量混淆

## 6. 数据模型

**MVP 以 `skills/` 文件系统为权威源**（git 版本化天然管理），不建 DB 表。注意：`skills` 表已被沙箱 `Skill` 模型占用（models/agent.py:25），后续如需 DB 化使用表名 `prompt_skills`。

节点 `config` 增加字段：

```jsonc
{
  "skill_id": "subagent-driven-development",   // 选中的 skill
  "skill_version": "main"                       // 来源版本（git ref）
}
```

## 7. 模块设计

### 7.1 `app/skills/loader.py`（新增，纯函数）

- `scan_skills(skills_root) -> list[SkillMeta]`：扫描 `<skills_root>/*/SKILL.md`
- `parse_frontmatter(text) -> dict`：手写解析 YAML frontmatter（name/description），无 PyYAML 依赖
- `load_skill(skills_root, skill_id) -> SkillMeta | None`
- `SkillMeta`：`name, description, body, directory, files`（附带 references/scripts 文件清单）

### 7.2 `app/skills/registry.py`（新增）

- `SkillRegistry`：基于 loader 的目录扫描 + 进程内缓存
- `list_active() -> list[SkillMeta]`（catalog 用）
- `get(skill_id) -> SkillMeta | None`
- `match_by_purpose(purpose) -> SkillMeta | None`：关键词映射兜底（implement→subagent-driven-development / test→test-driven-development / debug→systematic-debugging / review→requesting-code-review / plan→writing-plans / verify→verification-before-completion / 兜底→using-superpowers）

### 7.3 `app/skills/renderer.py`（新增，纯函数）

- `render_skill_prompt(skill: SkillMeta, *, role, purpose, input_fields, output_fields, output_schema, constraints, business_vars) -> str`
  - 输出**标准四段式**（`# 角色 / # 可用的输入字段 / # 输出要求 / # 约束`）+ `## 工作方法（Skill: <name>）` + skill 正文 + 业务变量替换（`{{module_name}}` 等）
  - 四段式头部保证与 `build_node_prompt` 幂等检查（`# 角色`）兼容

### 7.4 `app/skills/catalog.py`（新增，纯函数）

- `build_catalog(skills) -> str`：frontmatter 摘要（name + description），渐进披露 L1，注入 PLAN_PROMPT

### 7.5 `prompt_factory.py`（改造）

- `build_node_prompt` 增加 `skill` 参数（SkillMeta 可选）：有 skill → 调 `render_skill_prompt`；无 → 原逻辑
- 幂等检查不变（渲染结果含 `# 角色`）

### 7.6 `planner_agent.py`（改造）

- `PLAN_PROMPT` 增加 `<skill_catalog>` 段：`__SKILL_CATALOG__` 占位符
- 节点 config 规则增加：`skill_id`（可选，从 catalog 中选择）
- `generate_dag` 之后新增 `_apply_skills(workflow, blueprint)`：
  1. LLM 已给 `skill_id` → 校验存在；不存在 → 关键词映射兜底
  2. 无 `skill_id` → 关键词映射兜底（按 purpose）
  3. 通道 A（llm_api）：渲染进 `system_prompt`（烙进）
  4. 通道 B（local_cli）：保留 `skill_id`，正文不烙进（工作区注入）
- `_build_from_modules` fallback 同步应用映射兜底（fallback 节点获得 skill_id）

### 7.7 `workspace.py`（改造）

- `inject_workspace` 增加 `skills_root` 参数：对 local_cli 节点，若 `config.skill_id` 存在 → 复制 `skills/<skill_id>/` 到 `<project_path>/.opencode/skills/<skill_id>/`（claude_cli → `.claude/skills/`）
- 幂等：已存在则跳过

## 8. API 变更

- `POST /api/planner/plan` 响应不变（DAG 内节点 config 新增 `skill_id` 字段自然透出）
- 无新端点（MVP）

## 9. 实施步骤

| 步骤 | 内容 | 验证 |
|------|------|------|
| 1 | ~~Skill 库落地~~（已完成：`skills/` 目录） | — |
| 2 | `app/skills/loader.py` + `registry.py` | `test_skill_loader.py` |
| 3 | `app/skills/renderer.py` + `catalog.py` | `test_skill_renderer.py` |
| 4 | `prompt_factory` 集成 skill | `test_prompt_factory.py` 更新 |
| 5 | `planner_agent` 改造（catalog 注入 + skill 选择 + 兜底） | `test_skill_pipeline.py` |
| 6 | `workspace.py` 注入 skill 目录 | `test_workspace.py` 更新 |
| 7 | 全量回归 | 全套 pytest |

## 10. 测试策略

- 纯函数全用真实文件/构造 SkillMeta，不依赖 DB、不依赖 LLM
- planner 测试用 FakeLLM（沿用现有模式）：
  - LLM 输出带 `skill_id` → 验证 system_prompt 渲染结果含 skill 正文
  - LLM 输出无 `skill_id` → 验证关键词兜底映射生效
  - LLM 输出非法 `skill_id` → 验证回退映射 + 不崩溃
- workspace 注入：临时目录验证 skill 目录复制 + 幂等

## 11. 风险与权衡

| 风险 | 缓解 |
|------|------|
| skill 正文过长撑爆 prompt | 通道 A 仅 llm_api 节点；通道 B 渐进披露；渲染时截断可选 |
| LLM 选错 skill | catalog description 质量 + 关键词映射兜底 + 校验 |
| 交互式 skill（brainstorming 等）在无人值守下失效 | 后续 `skills/custom/` 自研自动化版覆盖 |
| frontmatter 解析无 YAML 库 | superpowers frontmatter 仅 name/description，手写解析足够 |
| `skills` 表名冲突 | 使用文件系统权威源，DB 化时用 `prompt_skills` |