# AI Agent Workflow Engine — MVP 实施计划（MVP Implementation Plan）

## Goal（目标）
用户输入一句需求 → Planner 自动生成 Workflow → Engine 调度多个 Agent 完成软件项目

## Epics & Dependencies（Epic 及其依赖）

```
Epic 1: Project Foundation（项目基础，无依赖）
  ├── pyproject.toml / requirements.txt
  ├── Docker Compose (PG + Redis + Qdrant)
  ├── Core config + database connection（核心配置 + 数据库连接）
  └── SQLAlchemy models (all tables)（SQLAlchemy 模型，全部数据表）

Epic 2: Workflow Engine（工作流引擎，依赖 Epic 1）
  ├── Workflow definition models (Pydantic)（工作流定义模型）
  ├── DAG Scheduler（DAG 调度器）
  ├── Node Runner (Agent/Tool/Condition/Loop/Human)（节点运行器）
  ├── State Machine（状态机）
  └── Execution Manager（执行管理器）

Epic 3: Context + Artifact（上下文 + 工件，依赖 Epic 1）
  ├── Context Manager（上下文管理器）
  ├── Artifact Manager（工件管理器）
  └── Storage adapter（存储适配器）

Epic 4: Agent Runtime（Agent 运行时，依赖 Epic 1）
  ├── Agent Registry（Agent 注册表）
  ├── LLM Gateway（LLM 网关）
  ├── Prompt Template Engine（提示词模板引擎）
  └── Agent Executor（Agent 执行器）

Epic 5: Task Contract + Comm（任务契约 + 通信，依赖 Epic 3, 4）
  ├── Contract Manager（契约管理器）
  ├── Contract Lifecycle（契约生命周期）
  ├── Communication Broker（通信代理）
  └── Agent Comm Client（Agent 通信客户端）

Epic 6: Evaluation + Supervisor（评估 + 监督，依赖 Epic 4, 5）
  ├── Evaluation Engine（评估引擎）
  ├── Quality Gate（质量门禁）
  ├── Recovery Manager（恢复管理器）
  └── Supervisor Orchestrator（监督编排器）

Epic 7: Planner Agent（规划器 Agent，依赖 Epic 2, 4）
  ├── Planner Agent logic（Planner Agent 逻辑）
  ├── Template library（模板库）
  └── Planning Review Layer（规划审查层）

Epic 8: MCP Tool System（MCP 工具系统，依赖 Epic 1）
  ├── MCP Bridge（MCP 桥接）
  ├── Tool Executor（工具执行器）
  └── Tool Registry（工具注册表）

Epic 9: API Layer + Integration（API 层 + 集成，依赖全部）
  ├── FastAPI routes（FastAPI 路由）
  ├── WebSocket handlers（WebSocket 处理器）
  ├── API schemas（API 模式）
  └── Integration tests（集成测试）
```

## Implementation Order（实施顺序）

```
Week 1（第 1 周）: Epic 1 → Epic 2 → Epic 3
Week 2（第 2 周）: Epic 4 → Epic 5 → Epic 6
Week 3（第 3 周）: Epic 7 → Epic 8 → Epic 9
```

## MVP Scope Reduction（MVP 范围缩减）

为 MVP 考虑，部分 V3 功能被简化：
- 评估（Evaluation）：从 6 个维度缩减为 3 个维度（完整性/正确性/效率）
- 工件（Artifact）：不引入生命周期状态机，仅存储 + 检索
- 多项目管理（Multi-project）：不在范围内
- 成本控制（Cost control）：不在范围内
- 规划审查（Planning Review）：仅做基础复杂度检查