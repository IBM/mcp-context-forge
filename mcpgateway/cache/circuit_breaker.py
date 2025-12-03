# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/circuit_breaker.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Circuit Breaker Pattern Implementation for Session Pools.

This module provides circuit breaker functionality to prevent cascading failures
by automatically disabling failing pools and allowing them to recover.
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failures detected, blocking requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """Circuit breaker for pool operations.
    
    Implements the circuit breaker pattern to prevent cascading failures
    by tracking failures and automatically opening the circuit when a
    threshold is reached.
    
    States:
        - CLOSED: Normal operation, requests pass through
        - OPEN: Too many failures, requests are blocked
        - HALF_OPEN: Testing recovery, limited requests allowed
    
    Attributes:
        failure_threshold: Number of failures before opening circuit
        timeout: Seconds to wait before attempting recovery
        half_open_max_calls: Maximum calls allowed in half-open state
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: int = 60,
        half_open_max_calls: int = 3,
        name: str = "circuit_breaker"
    ):
        """Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of consecutive failures before opening
            timeout: Seconds to wait in open state before trying half-open
            half_open_max_calls: Max calls to allow in half-open state
            name: Name for logging purposes
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.half_open_max_calls = half_open_max_calls
        self.name = name
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
        
        logger.info(
            f"Initialized circuit breaker '{name}' "
            f"(threshold={failure_threshold}, timeout={timeout}s)"
        )

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        return self._state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing recovery)."""
        return self._state == CircuitState.HALF_OPEN

    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection.
        
        Args:
            func: Async function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result of func if successful
            
        Raises:
            CircuitBreakerOpenError: If circuit is open
            Exception: Any exception raised by func
        """
        if not await self.can_attempt():
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is open"
            )
        
        try:
            result = await func(*args, **kwargs)
            await self.record_success()
            return result
        except Exception as e:
            await self.record_failure()
            raise

    async def can_attempt(self) -> bool:
        """Check if an operation can be attempted.
        
        Returns:
            True if operation can proceed, False otherwise
        """
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            
            if self._state == CircuitState.OPEN:
                # Check if timeout has elapsed
                if self._last_failure_time and \
                   time.time() - self._last_failure_time >= self.timeout:
                    # Transition to half-open
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info(f"Circuit breaker '{self.name}' transitioning to HALF_OPEN")
                    return True
                return False
            
            if self._state == CircuitState.HALF_OPEN:
                # Allow limited calls in half-open state
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False
            
            return False

    async def record_success(self) -> None:
        """Record a successful operation."""
        async with self._lock:
            self._success_count += 1
            
            if self._state == CircuitState.HALF_OPEN:
                # If we've had enough successes in half-open, close the circuit
                if self._success_count >= self.half_open_max_calls:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._half_open_calls = 0
                    logger.info(f"Circuit breaker '{self.name}' closed after recovery")
            
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    async def record_failure(self) -> None:
        """Record a failed operation."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                # Failure in half-open state, go back to open
                self._state = CircuitState.OPEN
                self._success_count = 0
                self._half_open_calls = 0
                logger.warning(
                    f"Circuit breaker '{self.name}' reopened after failure in HALF_OPEN"
                )
            
            elif self._state == CircuitState.CLOSED:
                # Check if we've hit the failure threshold
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._success_count = 0
                    logger.warning(
                        f"Circuit breaker '{self.name}' opened after "
                        f"{self._failure_count} failures"
                    )

    async def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._last_failure_time = None
            logger.info(f"Circuit breaker '{self.name}' manually reset")

    async def force_open(self) -> None:
        """Manually force the circuit breaker to open state."""
        async with self._lock:
            self._state = CircuitState.OPEN
            self._last_failure_time = time.time()
            logger.warning(f"Circuit breaker '{self.name}' manually opened")

    def get_stats(self) -> dict:
        """Get circuit breaker statistics.
        
        Returns:
            Dictionary with current state and counters
        """
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "failure_threshold": self.failure_threshold,
            "timeout": self.timeout,
            "last_failure_time": self._last_failure_time,
        }


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and blocking requests."""
    pass

# Made with Bob
