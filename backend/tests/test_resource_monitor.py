import asyncio
from unittest.mock import patch

import pytest

from app.core.limiter import AdaptiveLimiter
from app.core.resource_monitor import ResourceMonitor


@pytest.mark.asyncio
async def test_high_cpu_reduces_budget():
    limiter = AdaptiveLimiter(4)
    monitor = ResourceMonitor(
        limiter, base_budget=4, cpu_cap_percent=75,
        interval_seconds=0.01, samples_to_recover=3,
    )
    with patch("app.core.resource_monitor.psutil.cpu_percent", return_value=95.0):
        await monitor._tick()  # 首采样被忽略
        await monitor._tick()
    assert limiter.limit == 3


@pytest.mark.asyncio
async def test_budget_floor_one():
    limiter = AdaptiveLimiter(1)
    monitor = ResourceMonitor(
        limiter, base_budget=1, cpu_cap_percent=75, interval_seconds=0.01,
    )
    with patch("app.core.resource_monitor.psutil.cpu_percent", return_value=99.0):
        await monitor._tick()
        await monitor._tick()
        await monitor._tick()
    assert limiter.limit == 1


@pytest.mark.asyncio
async def test_low_cpu_recovers_after_streak():
    limiter = AdaptiveLimiter(2)
    monitor = ResourceMonitor(
        limiter, base_budget=4, cpu_cap_percent=75,
        interval_seconds=0.01, samples_to_recover=3,
    )

    with patch("app.core.resource_monitor.psutil.cpu_percent", return_value=99.0):
        await monitor._tick()
        await monitor._tick()  # 预算 2 → 1
        await monitor._tick()  # 预算 1 → 1(下限)

    with patch("app.core.resource_monitor.psutil.cpu_percent", return_value=30.0):
        await monitor._tick()  # streak=1
        await monitor._tick()  # streak=2
        await monitor._tick()  # streak=3 → 预算 1 → 2
    assert limiter.limit == 2


@pytest.mark.asyncio
async def test_recovery_capped_at_base():
    limiter = AdaptiveLimiter(3)
    monitor = ResourceMonitor(
        limiter, base_budget=3, cpu_cap_percent=75,
        interval_seconds=0.01, samples_to_recover=3,
    )
    with patch("app.core.resource_monitor.psutil.cpu_percent", return_value=20.0):
        for _ in range(6):
            await monitor._tick()
    assert limiter.limit == 3  # 不超基准


@pytest.mark.asyncio
async def test_mid_zone_holds_budget():
    limiter = AdaptiveLimiter(3)
    monitor = ResourceMonitor(
        limiter, base_budget=3, cpu_cap_percent=75, interval_seconds=0.01,
    )
    with patch("app.core.resource_monitor.psutil.cpu_percent", return_value=65.0):
        for _ in range(6):
            await monitor._tick()
    assert limiter.limit == 3  # 60-75 区间维持


@pytest.mark.asyncio
async def test_first_sample_ignored():
    limiter = AdaptiveLimiter(4)
    monitor = ResourceMonitor(
        limiter, base_budget=4, cpu_cap_percent=75, interval_seconds=0.01,
    )
    with patch("app.core.resource_monitor.psutil.cpu_percent", return_value=99.0):
        await monitor._tick()
    assert limiter.limit == 4


@pytest.mark.asyncio
async def test_streak_reset_on_high_cpu():
    limiter = AdaptiveLimiter(2)
    monitor = ResourceMonitor(
        limiter, base_budget=4, cpu_cap_percent=75, interval_seconds=0.01,
    )
    with patch("app.core.resource_monitor.psutil.cpu_percent", return_value=30.0):
        await monitor._tick()  # streak=1
        await monitor._tick()  # streak=2
    with patch("app.core.resource_monitor.psutil.cpu_percent", return_value=95.0):
        await monitor._tick()  # 高负载,streak 清零,预算 2→1
    with patch("app.core.resource_monitor.psutil.cpu_percent", return_value=30.0):
        await monitor._tick()  # streak=1
        await monitor._tick()  # streak=2
        await monitor._tick()  # streak=3 → 预算 1→2
    assert limiter.limit == 2


@pytest.mark.asyncio
async def test_start_stop_loop():
    limiter = AdaptiveLimiter(2)
    monitor = ResourceMonitor(
        limiter, base_budget=2, cpu_cap_percent=75,
        interval_seconds=0.01, samples_to_recover=1,
    )
    with patch("app.core.resource_monitor.psutil.cpu_percent", return_value=90.0):
        await monitor.start()
        await asyncio.sleep(0.05)
        await monitor.stop()
    assert limiter.limit == 1  # 循环内 tick 生效
    assert monitor._task is None


def test_current_budget_property():
    limiter = AdaptiveLimiter(3)
    monitor = ResourceMonitor(limiter, base_budget=3)
    assert monitor.current_budget == 3