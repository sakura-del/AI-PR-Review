"""基于 token bucket + asyncio.Semaphore 的全局限流器

设计要点：
- Semaphore 初始容量 = rate，同时作为并发上限与令牌补充速率
- 后台协程每 1/rate 秒补充 1 个令牌（不超过最大容量，避免溢出）
- acquire 超出限流时排队等待，永不抛错
- 支持 async with 上下文管理器与显式 release
- 模块级单例 get_rate_limiter()
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """基于 token bucket + asyncio.Semaphore 的全局限流器

    Args:
        rate: 每秒最大调用数（同时作为并发上限与令牌补充速率），必须为正整数
    """

    def __init__(self, rate: int = 5):
        if rate <= 0:
            raise ValueError("rate 必须为正整数")
        self._rate: int = rate
        # 最大容量 = rate，用于限制令牌补充不溢出
        self._max_capacity: int = rate
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(rate)
        self._refill_task: Optional[asyncio.Task] = None
        self._closed: bool = False

    @property
    def rate(self) -> int:
        """每秒最大调用数"""
        return self._rate

    @property
    def max_capacity(self) -> int:
        """令牌桶最大容量"""
        return self._max_capacity

    @property
    def current_available(self) -> int:
        """当前可用令牌数（用于测试观测）

        注意：访问 asyncio.Semaphore._value 是 CPython 实现细节，
        在 CPython 3.8+ 中稳定可用，用于令牌补充前的溢出检查。
        """
        return self._semaphore._value

    def start(self) -> None:
        """启动后台令牌补充任务

        通常无需手动调用：首次 acquire 时会懒启动。
        """
        if self._closed:
            return
        # 任务不存在或已结束时（重新）创建
        if self._refill_task is None or self._refill_task.done():
            self._refill_task = asyncio.create_task(self._refill_loop())

    async def _refill_loop(self) -> None:
        """后台循环：每 1/rate 秒补充 1 个令牌，不超过最大容量"""
        interval = 1.0 / self._rate
        try:
            while not self._closed:
                await asyncio.sleep(interval)
                # 检查当前可用量，避免超过最大容量导致令牌溢出
                if self._semaphore._value < self._max_capacity:
                    self._semaphore.release()
        except asyncio.CancelledError:
            # 被取消时正常退出
            raise

    async def acquire(self) -> None:
        """获取一个令牌，超出限流时排队等待（永不抛错）

        首次调用时懒启动后台补充任务。
        """
        if self._closed:
            return
        # 懒启动：首次调用时启动后台补充任务
        if self._refill_task is None or self._refill_task.done():
            self.start()
        await self._semaphore.acquire()

    def release(self) -> None:
        """显式释放一个令牌（与 acquire 配对使用）"""
        if self._closed:
            return
        self._semaphore.release()

    async def __aenter__(self) -> "RateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

    async def close(self) -> None:
        """关闭限流器，取消后台补充任务"""
        self._closed = True
        if self._refill_task is not None and not self._refill_task.done():
            self._refill_task.cancel()
            try:
                await self._refill_task
            except asyncio.CancelledError:
                pass
            self._refill_task = None

    def __del__(self):
        """对象销毁时取消后台任务（同步上下文，尽力而为）"""
        try:
            if self._refill_task is not None and not self._refill_task.done():
                self._refill_task.cancel()
        except Exception:
            # __del__ 中吞掉所有异常，避免 GC 时报错
            pass


# ===== 模块级单例 =====

_global_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter(rate: Optional[int] = None) -> RateLimiter:
    """获取全局 RateLimiter 单例

    首次调用创建实例（可用 rate 参数指定速率），
    后续调用返回同一实例（忽略 rate 参数）。

    Args:
        rate: 首次调用时指定的每秒最大调用数，默认 5

    Returns:
        全局 RateLimiter 实例
    """
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = RateLimiter(rate if rate is not None else 5)
    return _global_rate_limiter
