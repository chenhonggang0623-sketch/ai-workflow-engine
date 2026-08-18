# 执行链路问题清单(实测发现)

> 时间:2026-08-18
> 背景:首次真实端到端执行(需求 → 规划 → Confirm → opencode 执行)后,逐层排查定位的问题。
> 与 `PROJECT_REVIEW.md`(静态代码审查)互补;本文档是**动态实测**暴露的问题,集中在"真正让 agent 干活"这条从未被验证过的链路上。

---

## 结论先行

**节点显示"成功",但 opencode 实际上什么也没干** —— 输出为空、工作目录零文件。这不是偶发,是 Windows 上的确定性 bug:平台把多行 Prompt 作为命令行参数传给 opencode,被 cmd.exe 截断,opencode 只收到 2 个字符。

---

## 问题清单

### P0-1【严重】多行 Prompt 在 Windows 被 cmd.exe 截断 → opencode 空转

- **现象**:节点 8 秒内"completed successfully",但 `output`/`stdout` 均为空,工作目录无任何项目文件
- **根因**:平台在 `opencode.py` 把完整多行系统 Prompt 作为 `opencode run <prompt>` 的命令行参数传入;`opencode` 在 Windows 是 `.CMD` 批处理文件,cmd.exe 解析参数时**在第一个换行符处截断参数**。opencode 实际只收到 `# 角色`(2 字符),回复"消息不完整请补充"后被平台当作成功空输出
- **证据**:
  - 后端日志 `Executing CLI: ...opencode.CMD run # 角色 ...`(仅首行)
  - 用 Python `create_subprocess_exec` 完全复刻平台调用 → 复现,opencode 输出:"你的消息只写了 `# 角色`,内容不完整"
  - 同 prompt 去掉命令行传参(改 stdin)→ 正常,opencode 能写文件
- **影响**:Windows 上**所有 opencode 节点**执行必空转;claude/codex 的 `.CMD` shim 同理
- **修复方案(已验证)**:opencode 支持 stdin 读消息。改 `base_cli.py` 把 prompt 写入进程 stdin(替代 DEVNULL),`opencode.py` 不再把 prompt 塞进 `run` 参数。跨平台通用
- **状态**:已修复(`base_cli.py` 新增 `prompt_via_stdin`,opencode 开启;stdin 写入放后台任务避免管道死锁)

### P0-2【严重】平台把"空输出"标记为成功

- **现象**:opencode 只回了句"请补充",平台直接记 success,用户看到绿色成功但没有任何产物
- **根因**:`base_cli.py` 只判断 `returncode == 0` 即成功,不校验 stdout 是否为空、是否有 `tool_use`/产物、是否真的响应了任务
- **影响**:任何"静默失败"(空回复、模型没干活)都会伪装成成功,用户无法区分
- **建议**:成功判定至少增加"非空输出"校验;更优是要求出现 `tool_use` 事件或产物文件,否则标记 failed 并给原因
- **状态**:已修复(`base_cli.py` 新增 `require_output` + `_validate_output`;opencode 要求至少出现 text/tool_use 事件,只回 error 事件判失败并透传)

### P1-1【中】`/api/executions/{id}/report` 接口 500(MissingGreenlet)

- **现象**:执行详情页反复请求 report 接口,稳定返回 500;后端日志 `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called...`
- **根因**:supervisor 路由的 `_build_orchestrator` / `get_progress` 在异步上下文里做了同步/错误的 DB 访问(SQLAlchemy async 用法错误),属 supervisor"半死路径"遗留
- **影响**:report 能力不可用(详情页部分功能失效)
- **状态**:已修复(`orchestrator._load_execution` 用 `selectinload(Execution.workflow)` 显式 eager load;另修正 `execution.workflow.nodes`→`workflow.definition["nodes"]` 的潜在 AttributeError)

### P1-2【中】同一 workflow 多次执行共用同一工作目录

- **现象**:两次执行(66ef832c、367dad94)同一个 workflow,都用 `project_66ef832c` 作为工作目录
- **根因**:`working_directory` 挂在 workflow/node 上,不随 execution 变化;`generated_projects/project_<workflow_id>` 被复跑复用
- **影响**:多次执行的产物互相污染、覆盖,无法追溯"哪次执行产出了什么";并发执行同 workflow 会互相踩
- **建议**:工作目录按 execution_id 生成,或至少每次执行前清理
- **状态**:已修复(`workspace.py` 新增 `strip_workspace`;`planner/confirm` 不再把注入路径烘焙进 `workflow.definition`;`workflows/{id}/execute` 每次执行生成独立目录并注入)

### P2-1【中】opencode 把上游 401 包装成不透明错误,难排查

- **现象**:火山引擎 key 失效时,opencode 只返回 `UnknownError / "Unexpected server error" / ref: err_xxx`,不显示 HTTP 401 和"key 无效"
- **影响**:用户误以为是平台问题(实际平台调用是成功的);排查要靠直接 curl 上游接口
- **建议**:平台侧把 CLI 的完整 stderr/JSON 错误透传给前端;opencode 侧属上游行为,无法改
- **状态**:已缓解(非零退出透传 stderr,stderr 为空时附 stdout 尾部;opencode 的 error 事件解析为 `[error]` 行并纳入失败原因)

### P2-2【低】完整 Prompt(含需求)明文写入后端日志

- **现象**:`base_cli` 用 `logger.info` 把整条 `Executing CLI: ... <完整prompt> ...` 打印到日志,需求描述、系统提示词全量落盘
- **影响**:需求若含敏感信息(业务机密、API key 文案等)会留在日志里
- **建议**:日志只打命令头 + prompt 截断(如前 200 字符)
- **状态**:已修复(`base_cli` 日志截断为前 300 字符,完整 prompt 不再落盘)

### P2-3【信息】核心执行链路首次实测即连环暴露问题 —— 印证"从未端到端验证"

- DEV_LOG(08-08)自认"ensemble/audit 从未端到端验证",并把"端到端手工验证"列为最优先待办;README 却把执行描述为已完成
- 本次首次真实执行,立刻暴露 P0-1/P0-2/P1-1 三个问题。说明**"能跑通"和"真正能用"之间存在未跨过的鸿沟**
- **建议**:把"真实端到端执行"作为验收硬门槛,而不是可选项
- **状态**:已于 2026-08-18 在本机 macOS 完成首次真实端到端复验(见下方"端到端复验记录")

---

## 端到端复验记录(2026-08-18,本机 macOS)

环境:macOS + opencode 1.18.18 + docker(postgres/redis)+ agnes 供应商(OpenAI 兼容)。

| 链路 | 结果 | 证据 |
|---|---|---|
| 需求 → 规划 → Confirm → opencode 执行 | ✅ | 单 agent 节点(provider=opencode_cli),真实执行约 14 分钟 |
| P0-1 prompt stdin 传参 | ✅ | opencode 收到完整多行系统提示词:产出 30+ 文件(含中英双语 README、start.sh/end.sh、web/index.html),tool_use 事件实时流入日志 |
| P0-2 成功判定 | ✅ | 节点输出含 tool_use/text 事件,success 为真实产物;此前"8 秒空转假成功"未再出现 |
| P1-1 /report 接口 | ✅ | HTTP 200(此前稳定 500 MissingGreenlet),progress 正常返回 |
| P1-2 工作目录隔离 | ✅ | 复跑同一 workflow → 新目录 `planned-workflow_f227408a`,与首次 `planned-workflow_5fcfbef0` 完全隔离;workflow 存储 definition 为干净版本(无烘焙路径) |
| P2-2 日志脱敏 | ✅ | 后端日志仅 `Executing CLI: ...opencode run --format json --dir <wd> --auto`,完整 prompt 未落盘 |

未复验:Windows 平台(本机为 macOS,stdin 方案本身跨平台);P2-1 的上游 401 场景(需失效 key)。

---

## 优先级汇总

| 级别 | 编号 | 问题 | 一句话 | 状态 |
|---|---|---|---|---|
| P0 | P0-1 | Prompt 被截断 | Windows 上所有节点空转,修复方案已验证 | 已修复 |
| P0 | P0-2 | 空输出算成功 | 静默失败伪装成功,用户无感知 | 已修复 |
| P1 | P1-1 | /report 500 | MissingGreenlet,详情页功能坏 | 已修复 |
| P1 | P1-2 | 工作目录复用 | 复跑产物污染,无法追溯 | 已修复 |
| P2 | P2-1 | 错误不透明 | opencode 包装 401,排查成本高 | 已缓解 |
| P2 | P2-2 | Prompt 落日志 | 敏感信息泄露风险 | 已修复 |
| 信息 | P2-3 | 执行链路从未验证 | 与"真正能用"的鸿沟 | 待端到端复验 |

---

## 修复建议顺序

1. **P0-1**(opencode stdin 传参)—— 已验证方案,一改,执行就能真正出活 ✅ 已实现
2. **P0-2**(空输出判失败)—— 与 P0-1 联动,避免再次静默失败 ✅ 已实现
3. **P1-1**(/report MissingGreenlet) ✅ 已实现
4. **P1-2**(工作目录按 execution 隔离) ✅ 已实现
5. P2 按需 ✅ P2-1 已缓解 / P2-2 已实现
