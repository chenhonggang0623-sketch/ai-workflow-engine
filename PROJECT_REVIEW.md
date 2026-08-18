# AI Workflow Engine — 代码审查报告

> 审查日期:2026-08-18
> 方式:源码通读 + 本地运行实测 + 全量测试(444 个)
> 范围:后端 `backend/`、前端 `frontend/`、`docs/`

---

## 〇、总体判断

- 代码量:后端约 7,300 行 + 前端约 1.5 万行(含类型),38 个测试文件
- **修复前:项目无法启动**(见第一节);修复后:**444 个测试全绿**,端到端流程(规划 → DAG → 前端渲染)实测通过
- 工程质量:规划器多层校验、契约对齐、上下文归一化等设计扎实;但存在两套并行执行架构、`eval()` 安全风险、执行状态不持久等问题
- 上游 2026-08-17 新增 4 个 commit:`b157e52`(强制 DAG 连通 + 实时节点状态)、`57ebd72`(清理 generated_projects)、`84e35c1`(清理 opencode CLI 输出)、`f26a2cb`(nullable description)。其中 **b157e52 修复了我之前报告的"fallback DAG 无边"问题**,57ebd72 清理了我报告的仓库卫生问题。**但启动级 bug 一个都没修。**

---

## 一、阻断启动的代码缺陷(本次已修复)

这些 bug 导致项目**从未能真正启动过**。README 声称 439 个测试通过,但测试只做模块级导入、不加载完整应用,缺陷从未暴露。

### 1.1 `list` 方法遮蔽内置类型(最严重,共 5 处)

类里定义名为 `list` 的方法后,类体内后续所有方法注解里的 `list[...]` 会解析到该方法而非内置类型,导入即抛 `TypeError: 'function' object is not subscriptable`。

| 文件 | 位置 | 原方法 | 改为 |
|---|---|---|---|
| `app/mcp/tool_registry.py` | :38 | `def list` | `list_tools` |
| `app/contract/contract_manager.py` | :65 | `async def list` | `list_contracts` |
| `app/agent/registry.py` | :58 | `async def list` | `list_agents` |
| `app/artifact/manager.py` | :103 | `async def list` | `list_artifacts` |
| `app/skill/executor.py` | :52 | `def list` | `list_skills` |

调用方同步更新:`runtime.py`、`llm_executor.py`、`agents.py`、`contracts.py`、`artifacts.py`、`recovery.py`,及 6 个测试文件的对应 mock/调用。

**教训**:`list`/`dict`/`str` 等内置名作方法名是类定义里的隐性炸弹,一旦后续方法出现 `list[...]` 注解必炸。建议 CI 加静态检查:`grep -E "def (list|dict|str|set|type)("`。

### 1.2 f-string 表达式内反斜杠(Python 版本不兼容)

`app/agent/executor/providers/base_cli.py:211`:

```python
error=f"CLI exited with code {proc.returncode}: {'\n'.join(stderr_lines)}",
```

f-string 表达式内反斜杠是 **Python 3.12 才允许**的语法,而 `pyproject.toml` 声明 `requires-python = ">=3.11"`。3.11 上直接 `SyntaxError`。修复:先算出 `stderr_text` 变量。

### 1.3 pytest 配置引用不存在的属性

`backend/pyproject.toml` 的 `filterwarnings` 引用 `starlette.exceptions.StarletteDeprecationWarning`,实际安装的 starlette(1.0.1)没有该属性,**pytest 一启动就崩**。已删除该行。属失效配置。

---

## 二、Windows 跨平台缺陷(本次已修复)

项目按 macOS/Linux 开发(DEV_LOG 路径 `/Library/workfile/...`),Windows 上 4 处问题。

| 文件 | 问题 | 修复 |
|---|---|---|
| `app/skills/loader.py:108` | `os.path.relpath` 产出 `\`,skill 文件清单 `references\guide.md` 与预期 `references/guide.md` 不符 | `.replace("\\","/")` |
| `app/api/routes/executions.py:71` | 同上,`_walk_project` 的 `path` 字段带反斜杠 | 同上 |
| `tests/test_tool_registry.py:58` | 临时文件句柄未关就 `os.unlink`,Windows `PermissionError: [WinError 32]` | unlink 前 `f.close()` |
| `tests/test_agent_providers.py:187` | 断言命令以 `opencode` 结尾,Windows 上是 `opencode.CMD` | 改为 `basename(...).startswith("opencode")` |

---

## 三、架构 / 设计问题(已定位,未修复)

### 3.1 两套并行执行架构,supervisor 执行引擎是死代码(高优先)

- **主执行路径**:planner → `POST /api/workflows/{id}/execute` → `ExecutionManager` → `NodeRunner` → `ExecutorRouter` → providers。前端用的就是这条。
- **监督执行路径**:`SupervisorOrchestrator.supervise()`(质量门禁 / 契约管理 / 恢复策略 / 评估引擎),**全仓库无任何调用点**。supervisor 路由(`/executions/{id}/gates`、`/report`、`/evaluations`)虽挂载,但只暴露只读查询,从不触发 `supervise()`。

即质量门禁、恢复策略、契约这套逻辑**从未在真实执行中被驱动**。两套状态机、两套节点执行、两套上下文管理,重复代码多、心智负担重。建议二选一。

### 3.2 `eval()` 执行节点表达式(安全风险,高优先)

`app/engine/node_runner.py:201`:

```python
result = eval(expr, {"__builtins__": {}}, {**node_input, **(ctx or {})})
```

虽禁了 `__builtins__`,但注入的 `node_input`/context 可经 `().__class__.__bases__[0].__subclasses__()` 属性链逃逸构造任意代码执行。workflow 可由 LLM 规划生成(不可信来源),一旦有用户可提交 workflow 即为 RCE。建议 AST 白名单求值或限定只读布尔逻辑。

### 3.3 执行控制面全在进程内存

`ExecutionManager` 的 `_state_machines` / `_cancel_events` / `_interventions` / `_slow_since` 全是进程内 dict;`_cancelled` 集合(:31)只增不减,长跑有内存泄漏倾向。后端重启后,进行中执行的干预/慢节点标记全部丢失(节点结果已入库)。Redis 只做启动初始化,未用于执行控制面。

### 3.4 零鉴权 + CORS 全开

`main.py`:`allow_origins=["*"]` + `allow_credentials=True`,无任何认证中间件;docker-compose 三件套全默认口令。本地工具可接受,不建议对外部署。

### 3.5 声明了但未使用的依赖

| 依赖 | 状态 |
|---|---|
| Qdrant | `config.py` 声明 `qdrant_url`,**全代码零调用** |
| Celery | `pyproject.toml` 声明,**全代码零调用** |
| Redis | 仅 supervisor 死路径(`context/manager.py`、`communication_broker.py`)使用;主流程不碰 |

建议删除 Qdrant/Celery 依赖与对应 docker-compose 服务。

### 3.6 仓库卫生

- 残留 `backend/app/task-brief-*.md`(18 个)是开发过程中间产物,不应入库
- 3 个 commit 全部集中在一天;初始 commit 即含全量代码,无渐进历史(现已 7 个 commit,仍在 2 天内)
- 上游已清理 `generated_projects`(commit 57ebd72)✅,此问题闭环

### 3.7 文档与代码不一致

| 不一致 | 说明 |
|---|---|
| README 声称 439 个测试 | 实测(修复后)444 个(含上游新增 5 个);数字从未全绿验证过 |
| DEV_LOG 声称 367 passed(08-08) | 与 README 对不上,中途快照 |
| DEV_LOG 自认 ensemble/audit 从未端到端验证 | README 却描述为已完成特性 |
| README 架构目录与实际 | `app/skills/` 与 `app/skill/` 两个目录并存,职责重叠 |

### 3.8 其他小问题

- **`main.py` 启动 `try/except pass`**:建表、Redis 初始化、配置加载失败全部静默吞掉;PG 未就绪时后端仍"成功"启动,后续数据库操作才报错,排障困难。
- **`app/skills/` 与 `app/skill/` 并存**:技能执行器 vs 技能注册表/加载器,职责边界模糊。
- **executor 输出约定靠口头**:`node_runner._run_agent` 对输出做 `output["_executor_metadata"]=...`,新 provider 返回裸字符串即 TypeError(DEV_LOG 自记的坑)。无类型约束/协议。
- **本轮新 commit 观察**:`b157e52` 的 `ensure_dag_connected` 在生成后自动把孤立组件串进主链,同时 `validate_dag` 增加 `DISCONNECTED` 规则——方向正确,但自动改链(补边)可能掩盖规划器结构问题,建议把"自动修正"与"显式告警"分开,让修正可审计。

---

## 四、验证状态(修复后,最新代码)

- 后端测试:**444 passed, 0 failed**
- 后端:`/health`、`/api/agents`(数据库读写正常)、离线规划(`/api/planner/plan` 返回 5 模块蓝图 + 5 节点 + **4 条串联边**,connected DAG 生效)✅
- 前端:Next.js 启动、代理转发、首页渲染 ✅
- 未验证:节点真实执行(需本地 CLI / API key 驱动 opencode)

---

## 五、后续优先级建议

| 优先级 | 事项 |
|---|---|
| P0 | 确认 supervisor 执行引擎去留(死代码或转正) |
| P0 | `node_runner` 的 `eval()` 改 AST 白名单求值 |
| P0 | 补一条真实端到端执行(用本地 opencode 跑一个节点)——DEV_LOG 自认的最优先待办,仍未闭环 |
| P1 | 执行状态持久化(`_cancelled`/干预/慢节点标记接管到 Redis 或 DB) |
| P1 | 删除 Qdrant/Celery 依赖与容器;清理 `task-brief-*` |
| P2 | 启动失败不再静默(`try/except pass` → 显式告警) |
| P2 | `app/skills/` vs `app/skill/` 合并 |
| P2 | 为 executor 输出定义统一协议,消除裸字符串隐患 |
