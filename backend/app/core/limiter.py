"""动态上限的异步限流器,语义与 asyncio.Semaphore 一致,但上限可运行时调整。

ResourceMonitor 通过 set_limit 在运行中升降并发预算,不需要重建执行循环。
"""

import asyncio


class AdaptiveLimiter:
    """Event + 计数器实现;检查-清事件-等待之间无 await,单线程事件循环下无丢失唤醒。"""

    def __init__(self, limit: int):
        self._limit = max(1, int(limit))
        self._current = 0
        self._wakeup = asyncio.Event()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def current(self) -> int:
        return self._current

    async def acquire(self) -> None:
        while self._current >= self._limit:
            self._wakeup.clear()
            await self._wakeup.wait()
        self._current += 1

    def release(self) -> None:
        self._current = max(0, self._current - 1)
        if self._current < self._limit:
            self._wakeup.set()

    def set_limit(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        if self._current < self._limit:
            self._wakeup.set()

    async def __aenter__(self) -> "AdaptiveLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *exc_info) -> None:
        self.release()