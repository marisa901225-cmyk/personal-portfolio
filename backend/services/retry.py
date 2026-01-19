import logging
import asyncio
from typing import TypeVar, Callable, Any
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Reusable retry decorators
# Default policy: 3 attempts, exponential backoff (2, 4, 8s), retry on transient exceptions
standard_retry_policy = {
    "stop": stop_after_attempt(3),
    "wait": wait_exponential(multiplier=2, min=2, max=10),
    "before_sleep": before_sleep_log(logger, logging.WARNING),
    "reraise": True,
}

def sync_retry(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator for synchronous functions"""
    return retry(**standard_retry_policy)(func)

def async_retry(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator for asynchronous functions"""
    return retry(**standard_retry_policy)(func)
