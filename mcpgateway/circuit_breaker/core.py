from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Callable, Any
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    """Circuit breaker states following the classic pattern."""
    CLOSED = "closed"           # Normal operation
    OPEN = "open"               # Failing, reject all requests  
    HALF_OPEN = "half_open"     # Testing recovery with limited requests

@dataclass
class CircuitBreakerConfig:
    """Configuration for a circuit breaker instance."""
    failure_threshold: int = 3
    reset_timeout: float = 60.0  # seconds
    half_open_max_calls: int = 3
    half_open_timeout: float = 30.0  # seconds
    success_threshold: int = 1  # successes needed to close from half-open
    
    # Advanced configuration
    failure_rate_threshold: float = 0.5  # 50% failure rate triggers opening
    minimum_requests: int = 10  # minimum requests before failure rate calculation
    sliding_window_size: int = 100  # requests to track for failure rate

@dataclass 
class CircuitBreakerState:
    """Current state of a circuit breaker."""
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    consecutive_successes: int = 0
    last_failure_time: Optional[datetime] = None
    state_changed_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    trial_requests_count: int = 0
    manual_override: bool = False
    
    # Sliding window for failure rate calculation
    recent_requests: List[bool] = field(default_factory=list)  # True=success, False=failure

class CircuitBreakerError(Exception):
    """Base exception for circuit breaker errors."""
    pass

class CircuitOpenError(CircuitBreakerError):
    """Raised when circuit is open and requests are rejected."""
    def __init__(self, server_id: str, next_attempt_time: datetime):
        self.server_id = server_id
        self.next_attempt_time = next_attempt_time
        super().__init__(f"Circuit breaker is OPEN for server {server_id}. Next attempt at {next_attempt_time}")

class CircuitHalfOpenLimitError(CircuitBreakerError):
    """Raised when half-open circuit has reached trial request limit."""
    def __init__(self, server_id: str, current_trials: int, max_trials: int):
        self.server_id = server_id
        self.current_trials = current_trials
        self.max_trials = max_trials
        super().__init__(f"Circuit breaker HALF_OPEN limit reached for server {server_id} ({current_trials}/{max_trials})")

class MCPCircuitBreaker:
    """Circuit breaker implementation for MCP servers."""
    
    def __init__(self, server_id: str, config: CircuitBreakerConfig):
        self.server_id = server_id
        self.config = config
        self.state = CircuitBreakerState()
        self._lock = asyncio.Lock()
        
        # Metrics callbacks
        self._metrics_callbacks: List[Callable] = []
        
    async def can_execute(self) -> bool:
        """Check if request can be executed based on current circuit state."""
        async with self._lock:
            current_time = datetime.now(timezone.utc)
            
            if self.state.state == CircuitState.CLOSED:
                return True
                
            elif self.state.state == CircuitState.OPEN:
                # Check if timeout has elapsed to transition to half-open
                time_since_open = current_time - self.state.state_changed_time
                if time_since_open.total_seconds() >= self.config.reset_timeout:
                    await self._transition_to_half_open()
                    return True
                return False
                
            elif self.state.state == CircuitState.HALF_OPEN:
                # Allow limited trial requests
                if self.state.trial_requests_count < self.config.half_open_max_calls:
                    self.state.trial_requests_count += 1
                    return True
                return False
                
            return False
    
    async def record_success(self) -> None:
        """Record successful operation and update circuit state."""
        async with self._lock:
            current_time = datetime.now(timezone.utc)
            
            # Add to sliding window
            self.state.recent_requests.append(True)
            if len(self.state.recent_requests) > self.config.sliding_window_size:
                self.state.recent_requests.pop(0)
            
            if self.state.state == CircuitState.HALF_OPEN:
                self.state.consecutive_successes += 1
                if self.state.consecutive_successes >= self.config.success_threshold:
                    await self._transition_to_closed()
            elif self.state.state == CircuitState.CLOSED:
                # Reset failure count on success
                self.state.failure_count = 0
                self.state.consecutive_successes += 1
                
            await self._emit_metric("success_recorded")
            logger.debug(f"Circuit breaker {self.server_id}: Success recorded, state={self.state.state.value}")
    
    async def record_failure(self, error: str = "") -> None:
        """Record failed operation and update circuit state."""
        async with self._lock:
            current_time = datetime.now(timezone.utc)
            
            # Add to sliding window
            self.state.recent_requests.append(False)
            if len(self.state.recent_requests) > self.config.sliding_window_size:
                self.state.recent_requests.pop(0)
            
            self.state.failure_count += 1
            self.state.consecutive_successes = 0
            self.state.last_failure_time = current_time
            
            if self.state.state == CircuitState.CLOSED:
                # Check if we should open the circuit
                if await self._should_open_circuit():
                    await self._transition_to_open()
            elif self.state.state == CircuitState.HALF_OPEN:
                # Any failure in half-open immediately returns to open
                await self._transition_to_open()
                
            await self._emit_metric("failure_recorded", {"error": error})
            logger.warning(f"Circuit breaker {self.server_id}: Failure recorded ({self.state.failure_count}), state={self.state.state.value}")
    
    async def _should_open_circuit(self) -> bool:
        """Determine if circuit should be opened based on failure criteria."""
        # Simple threshold-based
        if self.state.failure_count >= self.config.failure_threshold:
            return True
            
        # Failure rate-based (if we have enough samples)
        if len(self.state.recent_requests) >= self.config.minimum_requests:
            failure_rate = 1 - (sum(self.state.recent_requests) / len(self.state.recent_requests))
            if failure_rate >= self.config.failure_rate_threshold:
                return True
                
        return False
    
    async def _transition_to_open(self) -> None:
        """Transition circuit to OPEN state."""
        old_state = self.state.state
        self.state.state = CircuitState.OPEN
        self.state.state_changed_time = datetime.now(timezone.utc)
        self.state.trial_requests_count = 0
        
        next_attempt = self.state.state_changed_time + timedelta(seconds=self.config.reset_timeout)
        await self._emit_metric("state_transition", {
            "from_state": old_state.value,
            "to_state": "open",
            "next_attempt_time": next_attempt.isoformat()
        })
        
        logger.error(f"Circuit breaker {self.server_id}: OPENED - rejecting requests until {next_attempt}")
    
    async def _transition_to_half_open(self) -> None:
        """Transition circuit to HALF_OPEN state."""
        old_state = self.state.state
        self.state.state = CircuitState.HALF_OPEN
        self.state.state_changed_time = datetime.now(timezone.utc)
        self.state.trial_requests_count = 0
        self.state.consecutive_successes = 0
        
        await self._emit_metric("state_transition", {
            "from_state": old_state.value,
            "to_state": "half_open"
        })
        
        logger.info(f"Circuit breaker {self.server_id}: HALF_OPEN - testing recovery with max {self.config.half_open_max_calls} trials")
    
    async def _transition_to_closed(self) -> None:
        """Transition circuit to CLOSED state."""
        old_state = self.state.state
        self.state.state = CircuitState.CLOSED
        self.state.state_changed_time = datetime.now(timezone.utc)
        self.state.failure_count = 0
        self.state.trial_requests_count = 0
        self.state.consecutive_successes = 0
        self.state.manual_override = False
        
        await self._emit_metric("state_transition", {
            "from_state": old_state.value,
            "to_state": "closed"
        })
        
        logger.info(f"Circuit breaker {self.server_id}: CLOSED - normal operation resumed")
    
    async def force_open(self, reason: str = "manual_override") -> None:
        """Manually force circuit to OPEN state."""
        async with self._lock:
            self.state.manual_override = True
            await self._transition_to_open()
            await self._emit_metric("manual_override", {"action": "force_open", "reason": reason})
    
    async def reset(self, reason: str = "manual_reset") -> None:
        """Manually reset circuit to CLOSED state."""
        async with self._lock:
            await self._transition_to_closed()
            await self._emit_metric("manual_override", {"action": "reset", "reason": reason})
    
    def get_state_info(self) -> Dict[str, Any]:
        """Get comprehensive state information for monitoring."""
        current_time = datetime.now(timezone.utc)
        time_in_state = current_time - self.state.state_changed_time
        
        failure_rate = None
        if len(self.state.recent_requests) > 0:
            failure_rate = 1 - (sum(self.state.recent_requests) / len(self.state.recent_requests))
        
        next_attempt_time = None
        if self.state.state == CircuitState.OPEN:
            next_attempt_time = self.state.state_changed_time + timedelta(seconds=self.config.reset_timeout)
        
        return {
            "server_id": self.server_id,
            "state": self.state.state.value,
            "failure_count": self.state.failure_count,
            "consecutive_successes": self.state.consecutive_successes,
            "trial_requests_count": self.state.trial_requests_count,
            "time_in_current_state_seconds": time_in_state.total_seconds(),
            "last_failure_time": self.state.last_failure_time.isoformat() if self.state.last_failure_time else None,
            "next_attempt_time": next_attempt_time.isoformat() if next_attempt_time else None,
            "failure_rate": failure_rate,
            "manual_override": self.state.manual_override,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "reset_timeout": self.config.reset_timeout,
                "half_open_max_calls": self.config.half_open_max_calls,
                "success_threshold": self.config.success_threshold,
                "failure_rate_threshold": self.config.failure_rate_threshold
            }
        }
    
    def add_metrics_callback(self, callback: Callable) -> None:
        """Add callback for metrics emission."""
        self._metrics_callbacks.append(callback)
    
    async def _emit_metric(self, event_type: str, data: Dict[str, Any] = None) -> None:
        """Emit metric event to registered callbacks."""
        metric_data = {
            "server_id": self.server_id,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "state": self.state.state.value,
            **(data or {})
        }
        
        for callback in self._metrics_callbacks:
            try:
                await callback(metric_data)
            except Exception as e:
                logger.error(f"Error in metrics callback: {e}")


class CircuitBreakerManager:
    """Manages circuit breakers for all MCP servers."""
    
    def __init__(self, default_config: CircuitBreakerConfig = None):
        self.default_config = default_config or CircuitBreakerConfig()
        self._circuit_breakers: Dict[str, MCPCircuitBreaker] = {}
        self._server_configs: Dict[str, CircuitBreakerConfig] = {}
        self._lock = asyncio.Lock()
        
        # Metrics tracking
        self.metrics = CircuitBreakerMetrics()
    
    def configure_server(self, server_id: str, config: CircuitBreakerConfig) -> None:
        """Configure circuit breaker for specific server."""
        self._server_configs[server_id] = config
        
        # Update existing circuit breaker if it exists
        if server_id in self._circuit_breakers:
            self._circuit_breakers[server_id].config = config
    
    async def get_circuit_breaker(self, server_id: str) -> MCPCircuitBreaker:
        """Get or create circuit breaker for server."""
        if server_id not in self._circuit_breakers:
            async with self._lock:
                if server_id not in self._circuit_breakers:
                    config = self._server_configs.get(server_id, self.default_config)
                    circuit_breaker = MCPCircuitBreaker(server_id, config)
                    
                    # Add metrics callback
                    circuit_breaker.add_metrics_callback(self.metrics.record_event)
                    
                    self._circuit_breakers[server_id] = circuit_breaker
        
        return self._circuit_breakers[server_id]
    
    async def can_execute_request(self, server_id: str) -> bool:
        """Check if request can be executed for server."""
        circuit_breaker = await self.get_circuit_breaker(server_id)
        can_execute = await circuit_breaker.can_execute()
        
        if not can_execute:
            await self.metrics.record_event({
                "server_id": server_id,
                "event_type": "request_rejected",
                "state": circuit_breaker.state.state.value,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        
        return can_execute
    
    async def record_request_result(self, server_id: str, success: bool, error: str = "") -> None:
        """Record the result of a request."""
        circuit_breaker = await self.get_circuit_breaker(server_id)
        
        if success:
            await circuit_breaker.record_success()
        else:
            await circuit_breaker.record_failure(error)
    
    async def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """Get state information for all circuit breakers."""
        states = {}
        for server_id, circuit_breaker in self._circuit_breakers.items():
            states[server_id] = circuit_breaker.get_state_info()
        return states
    
    async def force_open_circuit(self, server_id: str, reason: str = "manual") -> None:
        """Manually force a circuit breaker to OPEN state."""
        circuit_breaker = await self.get_circuit_breaker(server_id)
        await circuit_breaker.force_open(reason)
        logger.info(f"Circuit breaker {server_id} manually forced OPEN: {reason}")
    
    async def reset_circuit(self, server_id: str, reason: str = "manual") -> None:
        """Manually reset a circuit breaker to CLOSED state."""
        circuit_breaker = await self.get_circuit_breaker(server_id)
        await circuit_breaker.reset(reason)
        logger.info(f"Circuit breaker {server_id} manually reset to CLOSED: {reason}")
    
    async def get_metrics_summary(self) -> Dict[str, Any]:
        """Get comprehensive metrics summary."""
        return await self.metrics.get_summary()


class CircuitBreakerMetrics:
    """Metrics collection and aggregation for circuit breakers."""
    
    def __init__(self):
        self.events: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        
        # Prometheus-style metrics (counters, gauges, histograms)
        self.state_transitions = {}  # server_id -> {from_state -> to_state -> count}
        self.failure_counts = {}     # server_id -> count
        self.fast_failures = {}      # server_id -> count
        self.trial_requests = {}     # server_id -> {success -> count, failure -> count}
        
    async def record_event(self, event_data: Dict[str, Any]) -> None:
        """Record a circuit breaker event."""
        async with self._lock:
            self.events.append(event_data)
            
            # Update aggregated metrics
            server_id = event_data["server_id"]
            event_type = event_data["event_type"]
            
            if event_type == "state_transition":
                if server_id not in self.state_transitions:
                    self.state_transitions[server_id] = {}
                
                from_state = event_data["from_state"]
                to_state = event_data["to_state"]
                
                key = f"{from_state}->{to_state}"
                self.state_transitions[server_id][key] = self.state_transitions[server_id].get(key, 0) + 1
                
            elif event_type == "failure_recorded":
                self.failure_counts[server_id] = self.failure_counts.get(server_id, 0) + 1
                
            elif event_type == "request_rejected":
                self.fast_failures[server_id] = self.fast_failures.get(server_id, 0) + 1
    
    async def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary for monitoring."""
        async with self._lock:
            return {
                "total_events": len(self.events),
                "state_transitions": self.state_transitions,
                "failure_counts": self.failure_counts,
                "fast_failures": self.fast_failures,
                "trial_requests": self.trial_requests,
                "recent_events": self.events[-10:] if self.events else []
            }
    
    def get_prometheus_metrics(self) -> str:
        """Generate Prometheus-formatted metrics."""
        metrics = []
        
        # Circuit breaker state gauge
        for server_id, cb in self._circuit_breakers.items():
            state_value = {"closed": 0, "open": 1, "half_open": 2}[cb.state.state.value]
            metrics.append(f'circuit_breaker_state{{server_id="{server_id}"}} {state_value}')
        
        # State transition counters
        for server_id, transitions in self.state_transitions.items():
            for transition, count in transitions.items():
                from_state, to_state = transition.split('->')
                metrics.append(f'circuit_breaker_transitions_total{{server_id="{server_id}",from_state="{from_state}",to_state="{to_state}"}} {count}')
        
        # Failure counters
        for server_id, count in self.failure_counts.items():
            metrics.append(f'circuit_breaker_failures_total{{server_id="{server_id}"}} {count}')
        
        # Fast failure counters
        for server_id, count in self.fast_failures.items():
            metrics.append(f'circuit_breaker_fast_failures_total{{server_id="{server_id}"}} {count}')
        
        return '\n'.join(metrics)