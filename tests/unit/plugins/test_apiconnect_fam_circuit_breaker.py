# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_apiconnect_fam_circuit_breaker.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

Unit tests for IBM API Connect Federated API Management Circuit Breaker.
Tests the circuit breaker pattern implementation for IBM API Connect Federated API Management API calls.
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock

from plugins.apiconnect_fam.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerError,
)


class TestCircuitBreakerStates:
    """Test circuit breaker state transitions."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker with test configuration."""
        return CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=5.0,
            success_threshold=2,
            timeout=1.0,
        )

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self, breaker):
        """Test circuit breaker starts in closed state."""
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed is True
        assert breaker.is_open is False
        assert breaker.is_half_open is False

    @pytest.mark.asyncio
    async def test_successful_call_in_closed_state(self, breaker):
        """Test successful call in closed state."""
        async def success_func():
            return "success"
        
        result = await breaker.call(success_func)
        
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self, breaker):
        """Test circuit opens after failure threshold."""
        async def failing_func():
            raise Exception("API error")
        
        # Trigger failures up to threshold
        for _ in range(3):
            with pytest.raises(Exception):
                await breaker.call(failing_func)
        
        # Circuit should now be open
        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 3

    @pytest.mark.asyncio
    async def test_rejects_calls_when_open(self, breaker):
        """Test circuit rejects calls when open."""
        # Force circuit to open state
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = time.time()
        
        async def any_func():
            return "should not execute"
        
        with pytest.raises(CircuitBreakerError, match="Circuit breaker is OPEN"):
            await breaker.call(any_func)

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self, breaker):
        """Test circuit transitions to half-open after recovery timeout."""
        # Force circuit to open state with old failure time
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = time.time() - 10.0  # 10 seconds ago
        breaker._failure_count = 5
        
        async def success_func():
            return "success"
        
        result = await breaker.call(success_func)
        
        assert result == "success"
        # After one successful call in half-open, it needs success_threshold (2) successes to close
        # So it should still be in half-open state after just one success
        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.success_count == 1
        
        # Second successful call should close the circuit
        result2 = await breaker.call(success_func)
        assert result2 == "success"
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_closes_after_successful_probes_in_half_open(self, breaker):
        """Test circuit closes after success threshold in half-open state."""
        # Force circuit to half-open state
        breaker._state = CircuitState.HALF_OPEN
        breaker._success_count = 1  # One success already
        
        async def success_func():
            return "success"
        
        # One more success should close the circuit (threshold is 2)
        result = await breaker.call(success_func)
        
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_reopens_on_failure_in_half_open(self, breaker):
        """Test circuit reopens immediately on failure in half-open state."""
        # Force circuit to half-open state
        breaker._state = CircuitState.HALF_OPEN
        breaker._success_count = 1
        
        async def failing_func():
            raise Exception("Still failing")
        
        with pytest.raises(Exception):
            await breaker.call(failing_func)
        
        assert breaker.state == CircuitState.OPEN
        assert breaker.success_count == 0


class TestCircuitBreakerTimeout:
    """Test timeout handling."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker with short timeout."""
        return CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=5.0,
            success_threshold=2,
            timeout=0.1,  # 100ms timeout
        )

    @pytest.mark.asyncio
    async def test_timeout_counts_as_failure(self, breaker):
        """Test timeout is counted as failure."""
        async def slow_func():
            await asyncio.sleep(1.0)  # Longer than timeout
            return "too slow"
        
        with pytest.raises(TimeoutError):
            await breaker.call(slow_func)
        
        assert breaker.failure_count == 1

    @pytest.mark.asyncio
    async def test_opens_on_timeout_failures(self, breaker):
        """Test circuit opens after timeout failures."""
        async def slow_func():
            await asyncio.sleep(1.0)
            return "too slow"
        
        # Trigger timeouts up to threshold
        for _ in range(2):
            with pytest.raises(TimeoutError):
                await breaker.call(slow_func)
        
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerReset:
    """Test manual reset functionality."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker."""
        return CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=5.0,
            success_threshold=2,
            timeout=1.0,
        )

    @pytest.mark.asyncio
    async def test_manual_reset_to_closed(self, breaker):
        """Test manual reset returns circuit to closed state."""
        # Force circuit to open state
        breaker._state = CircuitState.OPEN
        breaker._failure_count = 5
        breaker._last_failure_time = time.time()
        
        await breaker.reset()
        
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0
        assert breaker.last_failure_time is None


class TestCircuitBreakerStatistics:
    """Test statistics and monitoring."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker."""
        return CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            success_threshold=3,
            timeout=10.0,
        )

    def test_get_stats_returns_correct_info(self, breaker):
        """Test get_stats returns correct information."""
        stats = breaker.get_stats()
        
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert stats["success_count"] == 0
        assert stats["failure_threshold"] == 5
        assert stats["success_threshold"] == 3
        assert stats["recovery_timeout"] == 60.0
        assert stats["time_until_retry"] == 0.0

    def test_get_stats_shows_time_until_retry_when_open(self, breaker):
        """Test get_stats shows time until retry when circuit is open."""
        # Force circuit to open state
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = time.time()
        
        stats = breaker.get_stats()
        
        assert stats["state"] == "open"
        assert stats["time_until_retry"] > 0
        assert stats["time_until_retry"] <= 60.0

    @pytest.mark.asyncio
    async def test_failure_count_increments_on_errors(self, breaker):
        """Test failure count increments on errors."""
        async def failing_func():
            raise Exception("Error")
        
        initial_count = breaker.failure_count
        
        with pytest.raises(Exception):
            await breaker.call(failing_func)
        
        assert breaker.failure_count == initial_count + 1

    @pytest.mark.asyncio
    async def test_failure_count_resets_on_success(self, breaker):
        """Test failure count resets on successful call."""
        # Set some failures
        breaker._failure_count = 3
        
        async def success_func():
            return "success"
        
        await breaker.call(success_func)
        
        assert breaker.failure_count == 0


class TestCircuitBreakerProperties:
    """Test circuit breaker properties."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker."""
        return CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=30.0,
            success_threshold=2,
            timeout=5.0,
        )

    def test_properties_return_correct_values(self, breaker):
        """Test all properties return correct values."""
        assert breaker.failure_threshold == 3
        assert breaker.recovery_timeout == 30.0
        assert breaker.success_threshold == 2
        assert breaker.timeout == 5.0
        
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0
        assert breaker.last_failure_time is None

    def test_state_check_properties(self, breaker):
        """Test state check properties."""
        # Closed state
        breaker._state = CircuitState.CLOSED
        assert breaker.is_closed is True
        assert breaker.is_open is False
        assert breaker.is_half_open is False
        
        # Open state
        breaker._state = CircuitState.OPEN
        assert breaker.is_closed is False
        assert breaker.is_open is True
        assert breaker.is_half_open is False
        
        # Half-open state
        breaker._state = CircuitState.HALF_OPEN
        assert breaker.is_closed is False
        assert breaker.is_open is False
        assert breaker.is_half_open is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])