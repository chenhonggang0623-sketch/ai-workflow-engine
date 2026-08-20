import asyncio

import pytest

from app.core.limiter import AdaptiveLimiter


@pytest.mark.asyncio
async def test_acquire_release_basic():
    limiter = AdaptiveLimiter(2)
    await limiter.acquire()
    await limiter.acquire()
    assert limiter.current == 2
    limiter.release()
    assert limiter.current == 1


@pytest.mark.asyncio
async def test_blocks_when_full():
    limiter = AdaptiveLimiter(1)
    await limiter.acquire()

    acquired = asyncio.Event()

    async def waiter():
        await limiter.acquire()
        acquired.set()

    task = asyncio.ensure_future(waiter())
    await asyncio.sleep(0.05)
    assert not acquired.is_set()

    limiter.release()
    await asyncio.wait_for(task, timeout=1)
    assert acquired.is_set()
    assert limiter.current == 1


@pytest.mark.asyncio
async def test_set_limit_reduces_blocks_extra_acquire():
    limiter = AdaptiveLimiter(3)
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()
    assert limiter.current == 3

    limiter.set_limit(1)
    assert limiter.limit == 1

    acquired = asyncio.Event()

    async def waiter():
        await limiter.acquire()
        acquired.set()

    task = asyncio.ensure_future(waiter())
    await asyncio.sleep(0.05)
    assert not acquired.is_set()

    limiter.release()
    limiter.release()
    limiter.release()  # current 3→0,出现空位才唤醒
    await asyncio.wait_for(task, timeout=1)
    assert acquired.is_set()


@pytest.mark.asyncio
async def test_set_limit_increase_wakes_waiters():
    limiter = AdaptiveLimiter(1)
    await limiter.acquire()

    acquired = asyncio.Event()

    async def waiter():
        await limiter.acquire()
        acquired.set()

    task = asyncio.ensure_future(waiter())
    await asyncio.sleep(0.05)
    assert not acquired.is_set()

    limiter.set_limit(2)
    await asyncio.wait_for(task, timeout=1)
    assert acquired.is_set()


def test_set_limit_floor_one():
    limiter = AdaptiveLimiter(4)
    limiter.set_limit(0)
    assert limiter.limit == 1
    limiter.set_limit(-5)
    assert limiter.limit == 1


def test_init_floor_one():
    limiter = AdaptiveLimiter(0)
    assert limiter.limit == 1


@pytest.mark.asyncio
async def test_concurrent_acquires_respect_limit():
    limiter = AdaptiveLimiter(2)
    running = 0
    peak = 0

    async def worker():
        nonlocal running, peak
        await limiter.acquire()
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        limiter.release()

    await asyncio.gather(*[worker() for _ in range(8)])
    assert peak <= 2


@pytest.mark.asyncio
async def test_async_context_manager():
    limiter = AdaptiveLimiter(1)
    async with limiter:
        assert limiter.current == 1
    assert limiter.current == 0