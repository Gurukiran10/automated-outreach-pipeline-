from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any, TypeVar

import requests

from utils.logger import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def retry(
    max_attempts: int = 3,
    backoff_factor: float = 2.0,
    initial_wait: float = 1.0,
    retryable_exceptions: tuple[type[Exception], ...] = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ChunkedEncodingError,
    ),
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            wait = initial_wait
            last_exc: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    result = func(*args, **kwargs)

                    # Honour Retry-After for rate-limit responses
                    if isinstance(result, requests.Response):
                        if result.status_code == 429:
                            retry_after = float(result.headers.get("Retry-After", wait))
                            logger.warning(
                                "Rate limited by %s. Waiting %.1fs (attempt %d/%d)",
                                func.__name__,
                                retry_after,
                                attempt,
                                max_attempts,
                            )
                            time.sleep(retry_after)
                            wait *= backoff_factor
                            continue

                        if result.status_code in RETRYABLE_STATUS_CODES:
                            logger.warning(
                                "HTTP %d from %s. Retrying in %.1fs (attempt %d/%d)",
                                result.status_code,
                                func.__name__,
                                wait,
                                attempt,
                                max_attempts,
                            )
                            time.sleep(wait)
                            wait *= backoff_factor
                            continue

                    return result

                except retryable_exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    logger.warning(
                        "%s raised %s. Retrying in %.1fs (attempt %d/%d)",
                        func.__name__,
                        type(exc).__name__,
                        wait,
                        attempt,
                        max_attempts,
                    )
                    time.sleep(wait)
                    wait *= backoff_factor

            if last_exc is not None:
                raise last_exc
            raise RuntimeError(f"{func.__name__} failed after {max_attempts} attempts")

        return wrapper  # type: ignore[return-value]

    return decorator
