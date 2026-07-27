"""HTTP 重试与指数退避工具

设计目标：
- 统一 GitHub / GitLab / AI API 的重试策略
- 区分业务错误（4xx 除 429/408/425）和瞬时错误（429/5xx/网络）
- 尊重服务端 Retry-After 头（GitHub secondary rate limit 会返回）
- 暴露 on_retry 回调用于 metrics 埋点

使用示例：
    result = await retry_async(
        lambda: client.get(url),
        on_retry=lambda attempt, err: metrics.counter("http_retries_total", labels=("status",)).inc(status=str(err)),
    )
"""
import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")


# 瞬时错误：429 / 5xx / 网络异常
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)


@dataclass
class RetryConfig:
    """重试配置

    字段：
    - max_retries: 最大重试次数（不含首次尝试）；默认 3
    - base_delay: 初始退避秒数；默认 1.0
    - max_delay: 单次最大退避秒数；默认 30.0
    - jitter: 是否加随机抖动（0.5x ~ 1.5x）；默认 True
    """
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: bool = True


def _parse_retry_after(headers) -> Optional[float]:
    """解析 Retry-After 头（秒数）

    支持数值形式（Retry-After: 30）；HTTP-date 形式暂不处理（GitHub 用数值）。
    """
    if headers is None:
        return None
    retry_after = None
    if hasattr(headers, "get"):
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after:
        try:
            return float(retry_after)
        except (ValueError, TypeError):
            return None
    return None


def _calc_delay(attempt: int, config: RetryConfig, retry_after: Optional[float] = None) -> float:
    """计算第 attempt 次重试前的等待时间

    优先级：Retry-After > 指数退避（受 max_delay 限制，可选 jitter）
    """
    if retry_after is not None and retry_after >= 0:
        return min(retry_after, config.max_delay)
    delay = config.base_delay * (2 ** attempt)
    delay = min(delay, config.max_delay)
    if config.jitter:
        delay *= (0.5 + random.random())  # 0.5x ~ 1.5x
    return delay


async def retry_async(
    func: Callable[[], Awaitable[T]],
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[int, object], None]] = None,
) -> T:
    """异步函数重试包装

    Args:
        func: 异步无参可调用（用 lambda/functools.partial 绑定参数）
        config: 重试配置（默认 RetryConfig()）
        on_retry: 每次重试前回调（attempt index + error/code），用于 metrics 埋点

    Returns:
        func() 成功结果

    Raises:
        最后一次失败的异常（业务错误立即抛，瞬时错误重试 max_retries 次后抛）
    """
    if config is None:
        config = RetryConfig()
    last_error: Optional[BaseException] = None
    total_attempts = config.max_retries + 1  # 首次 + 重试

    for attempt in range(total_attempts):
        try:
            return await func()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status not in RETRYABLE_STATUS_CODES:
                raise  # 业务错误（如 401/403/404），不重试
            last_error = e
            if attempt >= config.max_retries:
                logger.error(f"HTTP {status} after {total_attempts} attempts, giving up")
                raise
            retry_after = _parse_retry_after(e.response.headers)
            delay = _calc_delay(attempt, config, retry_after)
            logger.warning(
                f"HTTP {status} on attempt {attempt + 1}/{total_attempts}, retrying in {delay:.2f}s"
            )
            if on_retry:
                try:
                    on_retry(attempt, status)
                except Exception as cb_err:  # on_retry 回调失败不应阻断重试
                    logger.warning(f"on_retry callback failed: {cb_err}")
            await asyncio.sleep(delay)
        except RETRYABLE_EXCEPTIONS as e:
            last_error = e
            if attempt >= config.max_retries:
                logger.error(f"{type(e).__name__} after {total_attempts} attempts, giving up")
                raise
            delay = _calc_delay(attempt, config)
            logger.warning(
                f"{type(e).__name__} on attempt {attempt + 1}/{total_attempts}, retrying in {delay:.2f}s"
            )
            if on_retry:
                try:
                    on_retry(attempt, type(e).__name__)
                except Exception as cb_err:
                    logger.warning(f"on_retry callback failed: {cb_err}")
            await asyncio.sleep(delay)

    # 理论上不会到这里（成功会 return，所有异常都会被 raise）
    if last_error is not None:
        raise last_error
    raise RuntimeError("retry_async exited loop without success or error")


def retry_sync(
    func: Callable[[], T],
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[int, object], None]] = None,
) -> T:
    """同步版本重试包装

    与 retry_async 行为一致，但用于同步函数（如 PyGithub 调用）。
    """
    if config is None:
        config = RetryConfig()
    last_error: Optional[BaseException] = None
    total_attempts = config.max_retries + 1

    for attempt in range(total_attempts):
        try:
            return func()
        except Exception as e:
            # 同步场景简化：仅对网络异常与显式 Retryable 异常重试
            if not isinstance(e, RETRYABLE_EXCEPTIONS):
                raise
            last_error = e
            if attempt >= config.max_retries:
                raise
            delay = _calc_delay(attempt, config)
            logger.warning(
                f"{type(e).__name__} on attempt {attempt + 1}/{total_attempts}, retrying in {delay:.2f}s"
            )
            if on_retry:
                try:
                    on_retry(attempt, type(e).__name__)
                except Exception as cb_err:
                    logger.warning(f"on_retry callback failed: {cb_err}")
            import time
            time.sleep(delay)

    if last_error is not None:
        raise last_error
    raise RuntimeError("retry_sync exited loop without success or error")