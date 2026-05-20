"""Location: ./plugins/apiconnect_fam/circuit_breaker.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

Circuit Breaker Pattern for FAM API.
Implements the Circuit Breaker pattern to prevent cascading failures
when FAM API is unavailable or experiencing issues.
States:
- CLOSED: Normal operation, requests pass through
- OPEN: Failures exceeded threshold, requests fail fast
- HALF_OPEN: Testing if service recovered, limited requests allowed
"""

# Standard
import asyncio
from enum import Enum
import logging
import time
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""

    pass


class CircuitBreaker:
    """Circuit breaker for FAM API calls.

    Prevents cascading failures by failing fast when FAM API is unavailable.

    Attributes:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds to wait before attempting recovery
        success_threshold: Successful calls needed to close circuit
        timeout: Request timeout in seconds
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0, success_threshold: int = 2, timeout: float = 30.0):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Consecutive failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
            success_threshold: Successes needed to close circuit from half-open
            timeout: Request timeout in seconds
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.timeout = timeout

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count

    @property
    def success_count(self) -> int:
        """Get current success count (in half-open state)."""
        return self._success_count

    @property
    def last_failure_time(self) -> Optional[float]:
        """Get timestamp of last failure."""
        return self._last_failure_time

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (failing fast)."""
        return self._state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing recovery)."""
        return self._state == CircuitState.HALF_OPEN

    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function with circuit breaker protection.

        Args:
            func: Async function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Function result

        Raises:
            CircuitBreakerError: If circuit is open
            Exception: If function raises exception
        """
        async with self._lock:
            # Check if we should attempt recovery
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    logger.info("Circuit breaker: Attempting recovery (OPEN -> HALF_OPEN)")
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                else:
                    raise CircuitBreakerError(f"Circuit breaker is OPEN. " f"Will retry in {self._time_until_retry():.1f}s")

        # Execute function with timeout
        try:
            result = await asyncio.wait_for(func(*args, **kwargs), timeout=self.timeout)
            await self._on_success()
            return result

        except asyncio.TimeoutError as e:
            await self._on_failure()
            raise TimeoutError(f"Request timeout after {self.timeout}s") from e

        except Exception as e:
            await self._on_failure()
            raise

    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            self._failure_count = 0

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                logger.debug(f"Circuit breaker: Success in HALF_OPEN state " f"({self._success_count}/{self.success_threshold})")

                if self._success_count >= self.success_threshold:
                    logger.info("Circuit breaker: Recovery successful (HALF_OPEN -> CLOSED)")
                    self._state = CircuitState.CLOSED
                    self._success_count = 0

    async def _on_failure(self) -> None:
        """Handle failed call."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                logger.warning("Circuit breaker: Failure in HALF_OPEN state (HALF_OPEN -> OPEN)")
                self._state = CircuitState.OPEN
                self._success_count = 0

            elif self._state == CircuitState.CLOSED:
                logger.warning(f"Circuit breaker: Failure count {self._failure_count}/{self.failure_threshold}")

                if self._failure_count >= self.failure_threshold:
                    logger.error(f"Circuit breaker: Failure threshold exceeded (CLOSED -> OPEN). " f"Will retry in {self.recovery_timeout}s")
                    self._state = CircuitState.OPEN

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self._last_failure_time is None:
            return True
        return time.time() - self._last_failure_time >= self.recovery_timeout

    def _time_until_retry(self) -> float:
        """Calculate seconds until next retry attempt."""
        if self._last_failure_time is None:
            return 0.0
        elapsed = time.time() - self._last_failure_time
        return max(0.0, self.recovery_timeout - elapsed)

    async def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        async with self._lock:
            logger.info("Circuit breaker: Manual reset to CLOSED state")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None

    def get_stats(self) -> dict:
        """Get circuit breaker statistics.

        Returns:
            Dictionary with current state and counters
        """
        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "failure_threshold": self.failure_threshold,
            "success_threshold": self.success_threshold,
            "recovery_timeout": self.recovery_timeout,
            "time_until_retry": self._time_until_retry() if self._state == CircuitState.OPEN else 0.0,
        }
