"""运行时资源监控:采样 CPU 占用,动态调整并发预算。

预算规则(对 limiter.set_limit 生效):
- CPU% > 上限(cpu_usage_cap_percent)→ 预算 -1(下限 1)
- CPU% < 上限 - 15 且连续 3 次采样 → 预算 +1(上限 = 基准值)
- 其余区间维持不变
"""

import asyncio
import logging
from typing import Any

from app.core.limiter import AdaptiveLimiter

logger = logging.getLogger(__name__)

try:
    import psutil
except ImportError:  # pragma: no cover - 依赖缺失降级路径
    psutil = None  # type: ignore[assignment]


class ResourceMonitor:
    def __init__(
        self,
        limiter: AdaptiveLimiter,
        base_budget: int,
        cpu_cap_percent: int = 75,
        interval_seconds: float = 5.0,
        hysteresis_percent: int = 15,
        samples_to_recover: int = 3,
    ):
        self._limiter = limiter
        self._base_budget = max(1, int(base_budget))
        self._cpu_cap = max(1, min(100, int(cpu_cap_percent)))
        self._interval = interval_seconds
        self._hysteresis = hysteresis_percent
        self._recover_samples = samples_to_recover

        self._task: asyncio.Task | None = None
        self._low_streak = 0
        self._first_sample = True
        self.cpu_usage: float = 0.0

    @property
    def current_budget(self) -> int:
        return self._limiter.limit

    async def start(self) -> None:
        if psutil is None:
            logger.warning("ResourceMonitor: psutil unavailable, runtime throttling disabled")
            return
        if self._task is None:
            self._task = asyncio.ensure_future(self._loop())
            logger.info(
                "ResourceMonitor started: base=%d cap=%d%% interval=%.1fs",
                self._base_budget, self._cpu_cap, self._interval,
            )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval)
                try:
                    await self._tick()
                except Exception:
                    logger.exception("ResourceMonitor tick failed")
        except asyncio.CancelledError:
            raise

    async def _tick(self) -> None:
        cpu = psutil.cpu_percent(interval=None)
        if self._first_sample:
            # cpu_percent 首次调用返回 0.0,无统计意义
            self._first_sample = False
            return
        self.cpu_usage = cpu

        if cpu > self._cpu_cap:
            self._low_streak = 0
            self._set_budget(max(1, self._limiter.limit - 1), cpu)
            return

        if cpu < self._cpu_cap - self._hysteresis:
            self._low_streak += 1
            if self._low_streak >= self._recover_samples:
                self._low_streak = 0
                self._set_budget(min(self._base_budget, self._limiter.limit + 1), cpu)
            return

        self._low_streak = 0

    def _set_budget(self, budget: int, cpu: float) -> None:
        if budget != self._limiter.limit:
            logger.info(
                "ResourceMonitor: CPU %.0f%% -> budget %d", cpu, budget
            )
        self._limiter.set_limit(budget)