"""Location: ./plugins/apiconnect_fam/utils/retry.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

Retry Logic with Exponential Backoff.
Provides retry mechanisms for handling transient failures.
"""

# Standard
import asyncio
import logging
from typing import Any, Callable, Optional, TypeVar

# Third-Party
from pydantic import BaseModel, Field

# Local
from .errors import RetryExhaustedError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryConfig(BaseModel):
    """Configuration for retry logic.

    Attributes:
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff calculation
        jitter: Add random jitter to delays (0.0 to 1.0)
    """

    max_attempts: int = Field(default=3, ge=1, le=10)
    initial_delay: float = Field(default=1.0, ge=0.1, le=60.0)
    max_delay: float = Field(default=60.0, ge=1.0, le=300.0)
    exponential_base: float = Field(default=2.0, ge=1.1, le=10.0)
    jitter: float = Field(default=0.1, ge=0.0, le=1.0)


def exponential_backoff(attempt: int, config: RetryConfig) -> float:
    """Calculate exponential backoff delay.

    Args:
        attempt: Current attempt number (0-based)
        config: Retry configuration

    Returns:
        Delay in seconds
    """
    # Standard
    import random

    # Calculate base delay
    delay = min(config.initial_delay * (config.exponential_base**attempt), config.max_delay)

    # Add jitter
    if config.jitter > 0:
        jitter_amount = delay * config.jitter
        delay += random.uniform(-jitter_amount, jitter_amount)

    return max(0.1, delay)  # Minimum 0.1 seconds


async def with_retry(func: Callable[..., T], *args: Any, retry_config: Optional[RetryConfig] = None, operation_name: str = "operation", **kwargs: Any) -> T:
    """Execute function with retry logic.

    Retries on any exception with exponential backoff.

    Args:
        func: Function to execute (can be sync or async)
        *args: Positional arguments for func
        retry_config: Retry configuration (uses defaults if None)
        operation_name: Name of operation for logging
        **kwargs: Keyword arguments for func

    Returns:
        Result from successful function execution

    Raises:
        RetryExhaustedError: If all retry attempts fail
    """
    if retry_config is None:
        retry_config = RetryConfig()

    last_error: Optional[Exception] = None

    for attempt in range(retry_config.max_attempts):
        try:
            # Execute function (handle both sync and async)
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            # Success
            if attempt > 0:
                logger.info(f"{operation_name} succeeded on attempt {attempt + 1}/{retry_config.max_attempts}")
            return result

        except Exception as e:
            last_error = e

            # Log the failure
            if attempt < retry_config.max_attempts - 1:
                delay = exponential_backoff(attempt, retry_config)
                logger.warning(f"{operation_name} failed (attempt {attempt + 1}/{retry_config.max_attempts}): {e}. " f"Retrying in {delay:.2f}s...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"{operation_name} failed after {retry_config.max_attempts} attempts: {e}", exc_info=True)

    # All attempts exhausted
    raise RetryExhaustedError(f"{operation_name} failed after {retry_config.max_attempts} attempts", attempts=retry_config.max_attempts, last_error=last_error)


class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance.

    Prevents cascading failures by temporarily blocking requests
    after a threshold of failures is reached.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Failures exceeded threshold, requests blocked
    - HALF_OPEN: Testing if service recovered

    Attributes:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds to wait before trying again
        success_threshold: Successes needed to close circuit from half-open
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0, success_threshold: int = 2):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
            success_threshold: Successes to close from half-open
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def _should_attempt(self) -> bool:
        """Check if request should be attempted.

        Returns:
            True if request should proceed
        """
        # Standard
        import time

        if self._state == "CLOSED":
            return True

        if self._state == "OPEN":
            # Check if recovery timeout elapsed
            if self._last_failure_time is not None:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    logger.info("Circuit breaker entering HALF_OPEN state")
                    self._state = "HALF_OPEN"
                    self._success_count = 0
                    return True
            return False

        # HALF_OPEN state
        return True

    def record_success(self) -> None:
        """Record successful operation."""
        if self._state == "HALF_OPEN":
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                logger.info("Circuit breaker closing after successful recovery")
                self._state = "CLOSED"
                self._failure_count = 0
                self._success_count = 0
        elif self._state == "CLOSED":
            # Reset failure count on success
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record failed operation."""
        # Standard
        import time

        self._last_failure_time = time.time()

        if self._state == "HALF_OPEN":
            logger.warning("Circuit breaker opening after failure in HALF_OPEN state")
            self._state = "OPEN"
            self._failure_count = 0
            self._success_count = 0
        elif self._state == "CLOSED":
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                logger.warning(f"Circuit breaker opening after {self._failure_count} failures")
                self._state = "OPEN"

    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function with circuit breaker protection.

        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result from function

        Raises:
            Exception: If circuit is open or function fails
        """
        if not self._should_attempt():
            raise Exception(f"Circuit breaker is OPEN (state: {self._state})")

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            self.record_success()
            return result

        except Exception as e:
            self.record_failure()
            raise e
