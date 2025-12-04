# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/rate_limiter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Rate Limiter Implementation for Session Pools.

This module provides rate limiting functionality to prevent pool exhaustion
and implement backpressure during traffic spikes.
"""

# Standard
import asyncio
from collections import deque
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class PoolRateLimiter:
    """Rate limiter for pool acquisitions.

    Implements a sliding window rate limiter to prevent pool exhaustion
    during traffic spikes. Tracks requests within a time window and
    blocks new requests when the limit is reached.

    Attributes:
        max_requests: Maximum requests allowed per window
        window_seconds: Time window in seconds
        name: Name for logging purposes
    """

    def __init__(self, max_requests: int = 1000, window_seconds: int = 60, name: str = "rate_limiter"):
        """Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed per window
            window_seconds: Time window in seconds
            name: Name for logging purposes
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.name = name

        self._requests: deque = deque()  # Timestamps of requests
        self._lock = asyncio.Lock()
        self._blocked_count = 0
        self._allowed_count = 0

        logger.info(f"Initialized rate limiter '{name}' " f"({max_requests} requests per {window_seconds}s)")

    async def acquire(self, timeout: Optional[int] = None) -> bool:
        """Acquire a rate limit token.

        Args:
            timeout: Maximum time to wait for a token (seconds)

        Returns:
            True if token acquired, False if timeout or limit exceeded
        """
        start_time = time.time()

        while True:
            async with self._lock:
                now = time.time()

                # Remove old requests outside the window
                while self._requests and self._requests[0] < now - self.window_seconds:
                    self._requests.popleft()

                # Check if under limit
                if len(self._requests) < self.max_requests:
                    self._requests.append(now)
                    self._allowed_count += 1
                    return True

                # Calculate wait time for next available slot
                if self._requests:
                    oldest_request = self._requests[0]
                    wait_time = (oldest_request + self.window_seconds) - now
                else:
                    wait_time = 0

            # Check timeout
            if timeout is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    self._blocked_count += 1
                    logger.warning(f"Rate limiter '{self.name}' timeout after {elapsed:.2f}s")
                    return False

                # Don't wait longer than remaining timeout
                wait_time = min(wait_time, timeout - elapsed)

            # Wait for slot to become available
            if wait_time > 0:
                await asyncio.sleep(min(wait_time, 0.1))  # Check every 100ms
            else:
                # No wait time but still at limit, small delay before retry
                await asyncio.sleep(0.01)

    async def try_acquire(self) -> bool:
        """Try to acquire a token without waiting.

        Returns:
            True if token acquired, False if limit reached
        """
        async with self._lock:
            now = time.time()

            # Remove old requests outside the window
            while self._requests and self._requests[0] < now - self.window_seconds:
                self._requests.popleft()

            # Check if under limit
            if len(self._requests) < self.max_requests:
                self._requests.append(now)
                self._allowed_count += 1
                return True

            self._blocked_count += 1
            return False

    async def reset(self) -> None:
        """Reset the rate limiter, clearing all tracked requests."""
        async with self._lock:
            self._requests.clear()
            self._blocked_count = 0
            self._allowed_count = 0
            logger.info(f"Rate limiter '{self.name}' reset")

    def get_current_rate(self) -> int:
        """Get current number of requests in the window.

        Returns:
            Number of requests in current window
        """
        now = time.time()
        # Remove old requests
        while self._requests and self._requests[0] < now - self.window_seconds:
            self._requests.popleft()
        return len(self._requests)

    def get_remaining_capacity(self) -> int:
        """Get remaining capacity in current window.

        Returns:
            Number of additional requests that can be made
        """
        return max(0, self.max_requests - self.get_current_rate())

    def get_stats(self) -> dict:
        """Get rate limiter statistics.

        Returns:
            Dictionary with current state and counters
        """
        current_rate = self.get_current_rate()
        return {
            "name": self.name,
            "max_requests": self.max_requests,
            "window_seconds": self.window_seconds,
            "current_rate": current_rate,
            "remaining_capacity": self.max_requests - current_rate,
            "utilization": current_rate / self.max_requests if self.max_requests > 0 else 0,
            "allowed_count": self._allowed_count,
            "blocked_count": self._blocked_count,
            "block_rate": self._blocked_count / (self._allowed_count + self._blocked_count) if (self._allowed_count + self._blocked_count) > 0 else 0,
        }


class AdaptiveRateLimiter(PoolRateLimiter):
    """Adaptive rate limiter that adjusts limits based on system load.

    Extends PoolRateLimiter with adaptive behavior that increases or
    decreases the rate limit based on success/failure rates.
    """

    def __init__(
        self, initial_max_requests: int = 1000, window_seconds: int = 60, min_requests: int = 100, max_requests_limit: int = 10000, adjustment_factor: float = 0.1, name: str = "adaptive_rate_limiter"
    ):
        """Initialize adaptive rate limiter.

        Args:
            initial_max_requests: Initial maximum requests per window
            window_seconds: Time window in seconds
            min_requests: Minimum allowed requests per window
            max_requests_limit: Maximum allowed requests per window
            adjustment_factor: Factor for adjusting limits (0.0-1.0)
            name: Name for logging purposes
        """
        super().__init__(initial_max_requests, window_seconds, name)

        self.min_requests = min_requests
        self.max_requests_limit = max_requests_limit
        self.adjustment_factor = adjustment_factor
        self._success_count = 0
        self._failure_count = 0

    async def record_success(self) -> None:
        """Record a successful operation."""
        async with self._lock:
            self._success_count += 1

            # Increase limit if success rate is high
            total = self._success_count + self._failure_count
            if total >= 100:  # Adjust after 100 operations
                success_rate = self._success_count / total
                if success_rate > 0.95:  # >95% success rate
                    new_limit = int(self.max_requests * (1 + self.adjustment_factor))
                    if new_limit <= self.max_requests_limit:
                        self.max_requests = new_limit
                        logger.info(f"Rate limiter '{self.name}' increased limit to {new_limit} " f"(success rate: {success_rate:.2%})")

                # Reset counters
                self._success_count = 0
                self._failure_count = 0

    async def record_failure(self) -> None:
        """Record a failed operation."""
        async with self._lock:
            self._failure_count += 1

            # Decrease limit if failure rate is high
            total = self._success_count + self._failure_count
            if total >= 100:  # Adjust after 100 operations
                failure_rate = self._failure_count / total
                if failure_rate > 0.1:  # >10% failure rate
                    new_limit = int(self.max_requests * (1 - self.adjustment_factor))
                    if new_limit >= self.min_requests:
                        self.max_requests = new_limit
                        logger.warning(f"Rate limiter '{self.name}' decreased limit to {new_limit} " f"(failure rate: {failure_rate:.2%})")

                # Reset counters
                self._success_count = 0
                self._failure_count = 0

    def get_stats(self) -> dict:
        """Get adaptive rate limiter statistics.

        Returns:
            Dictionary with current state and counters
        """
        stats = super().get_stats()
        stats.update(
            {
                "adaptive": True,
                "min_requests": self.min_requests,
                "max_requests_limit": self.max_requests_limit,
                "adjustment_factor": self.adjustment_factor,
                "success_count": self._success_count,
                "failure_count": self._failure_count,
            }
        )
        return stats


# Made with Bob
