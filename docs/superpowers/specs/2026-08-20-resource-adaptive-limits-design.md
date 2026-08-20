# 资源自适应配置设计(Resource-Adaptive Limits)

日期:2026-08-20
状态:已批准(用户逐节确认)

## 背景与问题

当前节点上限、并行数、CPU 使用均为写死常量,与用户本机配置无关:

- **DAG 校验阈值**:`backend/app/core/config.py` 中 `dag_max_nodes=32`、`dag_max_edges=96`、`dag_max_fan_in=8`、`dag_max_fan_out=6`、`dag_timeout_budget_seconds=3600`;配置页 "DAG Validation Limits" 卡片可覆盖。
- **并行数**:`backend/app/main.py:131` `ExecutionManager(max_concurrency=5)` 硬编码;`_execute_node` 用 `asyncio.Semaphore(5)` 限流。
- **CPU/内存**:完全无检测、无配置项。

低配机器(如 4 核 8GB)跑 32 节点、5 并发 CLI agent 会打爆 CPU 和内存;高配机器(如 64 核)又浪费能力。

## 目标

1. **静态推荐**:启动时检测本机 CPU 核数/内存,自动计算合理的节点上限与并发数推荐值,预填配置页;用户可手动覆盖并持久化。
2. **运行时保护**:执行过程中持续监控 CPU 占用,超标自动降并发预算,恢复后回升。
3. 不改变现有执行语义(每个节点仍是独立任务,通过限流器并发执行)。

## 方案(已确认:方案 1 共享自适应限流器 + 进程内监控)

### 1. 硬件检测模块 `backend/app/core/system_probe.py`(新增)

```python
detect_hardware() -> {cpu_count, memory_gb, memory_bytes, platform}
recommend_limits(hw) -> {
    max_concurrency,          # clamp(cpu_count // 2, 2, 16)
    dag_max_nodes,            # clamp(cpu_count * 8, 16, 64),内存 <8GB→16、<16GB→32
    dag_max_edges,            # dag_max_nodes * 3
    dag_max_fan_in,           # 8(不变)
    dag_max_fan_out,          # 6(不变)
    cpu_usage_cap_percent,    # 75
}
```

- 用 `os.cpu_count()` + psutil;psutil 不可用时降级为只报核数,内存记为 0(不参与公式内存档)。
- 纯函数,便于单测。

### 2. 配置扩展

- `Settings`(`backend/app/core/config.py`)新增:
  - `max_concurrency: int | None = None`(None = 用推荐值)
  - `cpu_usage_cap_percent: int = 75`
- `ConfigStore.DEFAULT_KEYS`(`app_config.py`)增加 `max_concurrency`、`cpu_usage_cap_percent`。
- `PUT /api/config`(`backend/app/api/routes/config.py`)请求体增加两个字段,与既有 DAG 键同样走 `int | None` 处理。

### 3. AdaptiveLimiter `backend/app/core/limiter.py`(新增)

用 `asyncio.Condition` 实现的动态上限信号量,语义与 `asyncio.Semaphore` 一致:

```python
class AdaptiveLimiter:
    def __init__(self, limit: int)          # limit = max(1, limit)
    async def acquire(self)                 # 超过上限时等待
    def release(self)                       # 释放并 notify 一个等待者
    def set_limit(self, n: int)             # 动态调整上限,下限 1
    @property
    def limit(self) -> int
```

- `ExecutionManager.__init__` 增加 `limiter: AdaptiveLimiter | None = None` 参数;None 时自建 `AdaptiveLimiter(max_concurrency)`。
- `execute_workflow` 中 `semaphore = asyncio.Semaphore(self._max_concurrency)` 替换为共享 `self._limiter`。
- `_execute_node` 的 `async with semaphore:` 改为 `async with self._limiter:`。
- `main.py` 构建:`base = config_store.get("max_concurrency") or recommend_limits(hw)["max_concurrency"]`,创建共享 limiter 传给 `ExecutionManager`,并传给 ResourceMonitor。

### 4. ResourceMonitor `backend/app/core/resource_monitor.py`(新增)

挂在 FastAPI lifespan,随 app 启停:

- 每 5s 采样 `psutil.cpu_percent(interval=None)`。
- 规则:
  - CPU% > 上限(`cpu_usage_cap_percent`)→ 预算 -1(下限 1)
  - CPU% < 上限-15 且连续 3 次采样 → 预算 +1(上限 = 基准值)
- 基准值 = 配置值或推荐值;monitor 只调 `limiter.set_limit()`。
- 提供 `current_budget` 属性,便于前端展示或日志。

### 5. API 响应

`GET /api/config` 响应增加(仅展示,不落库):

```json
"hardware": {"cpu_count": 8, "memory_gb": 16.0, "platform": "darwin"},
"recommended": {"max_concurrency": 4, "dag_max_nodes": 32, "dag_max_edges": 96, ...}
```

### 6. 前端 `frontend/src/app/config/page.tsx`

- `frontend/src/lib/config.ts`:`AppConfig` 增加 `max_concurrency?`、`cpu_usage_cap_percent?`、`hardware?`、`recommended?` 字段。
- 新增卡片 **"本机资源与执行预算"**(置于 DAG Validation Limits 上方):
  - 只读展示:CPU 核数、内存、平台。
  - **并行节点数上限**(`max_concurrency`)输入框,placeholder = 推荐值。
  - **CPU 占用上限 %**(`cpu_usage_cap_percent`)输入框,默认 75。
- `handleSave` 提交两个新字段。
- "DAG Validation Limits" 卡片:
  - Max nodes/edges/fan-in/fan-out/timeout 的 placeholder 从写死字符串改为后端 `recommended` 对应值。
  - 卡片 desc 注明"留空 = 使用按本机配置计算的推荐值"。

### 7. 测试

- `backend/tests/test_system_probe.py`:推荐公式各档位(2/4/8/16/64 核 × 4/8/16/32GB),含 clamp、内存档位、psutil 缺失降级。
- `backend/tests/test_limiter.py`:并发上限生效、set_limit 动态降/升、并发 acquire 等待与释放唤醒、下限 1 钳制。
- `backend/tests/test_resource_monitor.py`:mock psutil.cpu_percent → 预算递减/回升/上下限钳制/连续采样条件。
- `backend/tests/test_execution_manager.py`:补 limiter 用例(传入自定义 limiter 验证并行度),现有固定值用例保留。
- 前端无新增测试设施,手工验证。

### 8. 依赖

- `backend/pyproject.toml` 增加 `psutil>=5.9.0`(系统已装 7.2.2)。

## 不做的事(YAGNI)

- 不限制单个 CLI agent 进程的 CPU(renice/cgroup/亲和性)——跨平台成本高,收益低。
- 不改 ensemble_provider 内部候选并行(2),属单节点内部行为。
- 不加内存监控(节点数是内存主控,公式已按内存封顶)。
- 不做"重新检测"按钮——检测在每次页面加载/API 调用时进行。

## 风险与边界

- psutil 安装失败 → 降级只报核数,公式走内存档默认档(封顶 32)。
- 运行时降并发对已在等待的任务不生效(等待者会继续等到有空位),但不再启动新任务。
- `cpu_percent` 首调返回 0.0,monitor 首轮采样忽略。