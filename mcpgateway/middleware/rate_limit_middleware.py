# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/rate_limit_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Team

Redis-backed rate limiting middleware for ContextForge API endpoints.

This middleware provides production-ready rate limiting using Redis sorted sets
for sliding window algorithm, with SecurityLogger integration for audit trails.

Features:
- Redis-backed (with in-memory fallback)
- Endpoint tiers (CRITICAL/HIGH/MEDIUM/LOW)
- Multi-dimensional limiting (IP → User → Team)
- SecurityLogger integration
- Lockout after excessive violations

Examples:
    >>> from mcpgateway.middleware.rate_limit_middleware import RateLimitMiddleware  # doctest: +SKIP
    >>> app.add_middleware(RateLimitMiddleware)  # doctest: +SKIP
"""

# Standard
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import re
import threading
import time
from typing import Any, Dict, List, Tuple
import uuid

# Third-Party
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# First-Party
from mcpgateway import auth
from mcpgateway.config import settings
from mcpgateway.services.security_logger import SecurityEventType, SecurityLogger, SecuritySeverity

logger = logging.getLogger(__name__)

# Thread pool for running sync Redis calls in async middleware
_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# Lua script for atomic sliding-window check+add in Redis.
# Arguments: KEY, window_start, limit, member, ttl
# Returns: 1 if allowed, 0 if blocked
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local window_start = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local score = tonumber(ARGV[3])
local member = ARGV[4]
local ttl = tonumber(ARGV[5])

redis.call('zremrangebyscore', key, 0, window_start)
local count = redis.call('zcard', key)
if count >= limit then
    return 0
end
redis.call('zadd', key, score, member)
redis.call('expire', key, ttl)
return 1
"""


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Redis-backed rate limiting middleware.

    Uses sliding window algorithm with Redis sorted sets.
    Falls back to in-memory if Redis unavailable.

    Limits checked in order: IP → User → Team
    Block if ANY dimension exceeds limit.
    """

    def __init__(self, app):
        """Initialize rate limit middleware."""
        super().__init__(app)
        self.enabled = settings.rate_limiting_enabled
        self.redis_enabled = settings.rate_limiting_redis_enabled
        self.use_redis = False

        self.executor = _EXECUTOR

        self.lockout_enabled = settings.rate_limit_lockout_enabled
        self.lockout_threshold = settings.rate_limit_lockout_threshold
        self.lockout_duration_minutes = settings.rate_limit_lockout_duration_minutes

        self.security_logger = SecurityLogger()

        # Build tiers from config settings
        self.endpoint_tiers = {
            "CRITICAL": {
                "pattern": r"^/auth/email/(login|register|forgot-password|reset-password)$",
                "limit": settings.rate_limit_critical_rpm,
                "burst": settings.rate_limit_critical_burst,
            },
            "CRITICAL_SSO": {
                "pattern": r"^/auth/sso(/|$)",
                "limit": settings.rate_limit_critical_rpm,
                "burst": settings.rate_limit_critical_burst,
            },
            "HIGH": {
                "pattern": r"^/(tokens|oauth|rbac)(/|$)",
                "limit": settings.rate_limit_high_rpm,
                "burst": settings.rate_limit_high_burst,
            },
            "MEDIUM": {
                "pattern": r"^/(mcp|tools|prompts|resources|servers|gateways|llmchat)(/|$)",
                "limit": settings.rate_limit_medium_rpm,
                "burst": settings.rate_limit_medium_burst,
            },
            "LOW": {
                "pattern": r"^/(health|metrics|docs|openapi)(/|$)",
                "limit": settings.rate_limit_low_rpm,
                "burst": settings.rate_limit_low_burst,
            },
        }

        self.redis_client = None
        self._sliding_window_script = None
        self._init_redis()

        self.compiled_tiers = self._compile_tiers()
        self.default_tier = {"limit": settings.rate_limit_low_rpm, "burst": settings.rate_limit_low_burst}

        self._memory_store: Dict[str, List[float]] = {}
        self._violation_counts: Dict[str, int] = {}
        self._violation_expiry: Dict[str, float] = {}
        self._store_lock = threading.Lock()

        logger.info(f"RateLimitMiddleware initialized: enabled={self.enabled}, use_redis={self.use_redis}, lockout={self.lockout_enabled}")

    def _init_redis(self) -> None:
        """Initialize Redis client for rate limiting."""
        if not self.redis_enabled:
            logger.info("Redis rate limiting disabled by config")
            self.use_redis = False
            return

        try:
            # Use dedicated rate limiter Redis client
            client = auth._get_ratelimiter_redis_client()  # pylint: disable=protected-access
            if client is not None:
                # Ping already done in _get_ratelimiter_redis_client()
                self.redis_client = client
                self._sliding_window_script = client.register_script(_SLIDING_WINDOW_LUA)
                self.use_redis = True
                logger.info("Rate limiting Redis client connected")
            else:
                logger.warning("Sync Redis unavailable, using in-memory fallback")
                self.use_redis = False
        except Exception as e:
            logger.warning(f"Sync Redis unavailable: {e}, using in-memory fallback")
            self.use_redis = False

    def _compile_tiers(self) -> List[Tuple[re.Pattern, Dict[str, Any]]]:
        """Pre-compile regex patterns for tier matching."""
        compiled = []
        for _, config in self.endpoint_tiers.items():
            pattern = re.compile(config["pattern"])
            compiled.append((pattern, config))
        return compiled

    def get_endpoint_tier(self, path: str) -> Dict[str, Any]:
        """Get tier config for endpoint."""
        for pattern, config in self.compiled_tiers:
            if pattern.match(path):
                return config
        return self.default_tier

    def _get_client_dimensions(self, request: Request) -> List[str]:
        """Get client ID dimensions in priority order: IP → User → Team."""
        dimensions = []

        client_ip = self._get_client_ip(request)
        dimensions.append(f"ip:{client_ip}")

        user_email = getattr(request.state, "user_email", None)
        if not user_email:
            user = getattr(request.state, "user", None)
            if user is not None:
                user_email = getattr(user, "email", None)
        if user_email:
            dimensions.append(f"user:{user_email}")

        team_id = getattr(request.state, "team_id", None)
        if team_id:
            dimensions.append(f"team:{team_id}")

        return dimensions

    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting."""
        if not self.enabled:
            return await call_next(request)

        tier = self.get_endpoint_tier(request.url.path)
        dimensions = self._get_client_dimensions(request)

        tier_name = self._get_tier_name(request.url.path)

        # Check lockout first — a locked-out dimension blocks regardless of
        # whether the sliding window has cleared.
        locked_out_dims = []
        for dimension in dimensions:
            if await self._should_lockout(dimension, tier_name):
                locked_out_dims.append(dimension)

        if locked_out_dims:
            for dim in locked_out_dims:
                self._log_security_event(
                    request=request,
                    dimension=dim,
                    tier=tier,
                    tier_name=tier_name,
                    is_lockout=True,
                )

            return self._create_rate_limit_response(
                request=request,
                dimensions=locked_out_dims,
                tier=tier,
                tier_name=tier_name,
                is_lockout=True,
            )

        violation_dims = []
        pre_check_results: Dict[str, Tuple[bool, int]] = {}

        for dimension in dimensions:
            allowed, remaining = await self._check_rate_limit(dimension, tier, tier_name)
            pre_check_results[dimension] = (allowed, remaining)
            if not allowed:
                violation_dims.append(dimension)

        if violation_dims:
            for dim in violation_dims:
                self._log_security_event(
                    request=request,
                    dimension=dim,
                    tier=tier,
                    tier_name=tier_name,
                    is_lockout=False,
                )
                await self._increment_violation(dim, tier_name)

            return self._create_rate_limit_response(
                request=request,
                dimensions=violation_dims,
                tier=tier,
                tier_name=tier_name,
                is_lockout=False,
            )

        response = await call_next(request)

        # Use the pre-check result for the first dimension to avoid double-counting.
        first_dim = dimensions[0] if dimensions else "ip:unknown"
        _, remaining = pre_check_results.get(first_dim, (True, 0))
        response.headers["X-RateLimit-Limit"] = str(tier["limit"])
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))

        return response

    def _get_tier_name(self, path: str) -> str:
        """Get tier name for logging."""
        for tier_name, config in self.endpoint_tiers.items():
            if re.match(config["pattern"], path):
                return tier_name
        return "LOW"

    async def _check_rate_limit(self, dimension: str, tier: Dict[str, Any], tier_name: str) -> Tuple[bool, int]:
        """Check rate limit for dimension."""
        limit_key = f"ratelimit:{dimension}:{tier_name}"
        limit = tier["limit"]
        window_seconds = 60

        try:
            loop = asyncio.get_running_loop()
            allowed, remaining = await loop.run_in_executor(
                self.executor,
                self._check_rate_limit_sync,
                limit_key,
                limit,
                window_seconds,
            )
            return allowed, remaining
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            return True, limit

    def _check_rate_limit_sync(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
        """Synchronous rate limit check."""
        now = time.time()
        window_start = now - window_seconds

        if self.use_redis and self.redis_client and self._sliding_window_script is not None:
            try:
                member = f"{now}:{uuid.uuid4()}"
                allowed = self._sliding_window_script(
                    keys=[key],
                    args=[window_start, limit, now, member, window_seconds * 2],
                )
                if allowed == 0:
                    return False, 0
                # Script returns 1 on success; approximate remaining.
                count = self.redis_client.zcard(key)
                return True, max(0, limit - count)
            except Exception as e:
                logger.warning(f"Redis rate limit failed: {e}, falling back to in-memory")

        return self._check_rate_limit_memory(key, limit, window_seconds)

    def _check_rate_limit_memory(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
        """In-memory fallback rate limit check."""
        if not hasattr(self, "_memory_store"):
            self._memory_store: Dict[str, List[float]] = {}

        now = time.time()
        window_start = now - window_seconds

        with self._store_lock:
            if key in self._memory_store:
                self._memory_store[key] = [ts for ts in self._memory_store[key] if ts > window_start]

            count = len(self._memory_store.get(key, []))

            if count >= limit:
                return False, 0

            self._memory_store.setdefault(key, []).append(now)

            return True, limit - count - 1

    async def _should_lockout(self, dimension: str, tier_name: str) -> bool:  # pylint: disable=unused-argument
        """Check if dimension should be locked out."""
        if not self.lockout_enabled:
            return False

        violation_key = f"ratelimit:violations:{dimension}"
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self.executor, self._should_lockout_sync, violation_key, tier_name, dimension)
        except Exception:
            return self._should_lockout_memory(dimension, tier_name)

    def _should_lockout_sync(self, violation_key: str, tier_name: str, dimension: str) -> bool:  # pylint: disable=unused-argument
        """Synchronous lockout check."""
        if not self.use_redis or not self.redis_client:
            return self._should_lockout_memory(dimension, tier_name)

        try:
            count = self.redis_client.get(violation_key)
            return int(count or 0) >= self.lockout_threshold
        except Exception:
            return self._should_lockout_memory(dimension, tier_name)

    def _should_lockout_memory(self, dimension: str, tier_name: str) -> bool:  # pylint: disable=unused-argument
        """In-memory lockout check."""
        if not hasattr(self, "_violation_counts"):
            self._violation_counts: Dict[str, int] = {}
        if not hasattr(self, "_violation_expiry"):
            self._violation_expiry: Dict[str, float] = {}
        with self._store_lock:
            now = time.time()
            expiry = self._violation_expiry.get(dimension, float("inf"))
            if now > expiry:
                self._violation_counts.pop(dimension, None)
                self._violation_expiry.pop(dimension, None)
                return False
            count = self._violation_counts.get(dimension, 0)
            return count >= self.lockout_threshold

    async def _increment_violation(self, dimension: str, tier_name: str) -> None:  # pylint: disable=unused-argument
        """Increment violation counter for a dimension."""
        violation_key = f"ratelimit:violations:{dimension}"
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self.executor, self._increment_violation_sync, violation_key, dimension)
        except Exception:
            self._increment_violation_memory(dimension)

    def _increment_violation_sync(self, violation_key: str, dimension: str) -> None:
        """Synchronous violation increment."""
        if self.use_redis and self.redis_client:
            try:
                self.redis_client.incr(violation_key)
                self.redis_client.expire(violation_key, self.lockout_duration_minutes * 60)
                return
            except Exception as e:
                logger.warning(
                    "Redis violation increment failed for dimension %s, falling back to in-memory: %s",
                    dimension,
                    str(e),
                )
        self._increment_violation_memory(dimension)

    def _increment_violation_memory(self, dimension: str) -> None:
        """In-memory violation increment."""
        with self._store_lock:
            self._violation_counts[dimension] = self._violation_counts.get(dimension, 0) + 1
            self._violation_expiry[dimension] = time.time() + self.lockout_duration_minutes * 60

    def _log_security_event(
        self,
        request: Request,
        dimension: str,
        tier: Dict[str, Any],
        tier_name: str,  # pylint: disable=unused-argument
        is_lockout: bool,
    ) -> None:
        """Log security event."""
        try:
            event_type = SecurityEventType.BRUTE_FORCE_ATTEMPT if is_lockout else SecurityEventType.RATE_LIMIT_EXCEEDED
            severity = SecuritySeverity.HIGH if is_lockout else SecuritySeverity.MEDIUM

            user_id = getattr(request.state, "user_id", None)
            user_email = getattr(request.state, "user_email", None)
            team_id = getattr(request.state, "team_id", None)

            client_ip = self._get_client_ip(request)

            self.security_logger._create_security_event(  # pylint: disable=protected-access
                event_type=event_type,
                severity=severity,
                category="rate_limit",
                user_id=user_id,
                user_email=user_email,
                client_ip=client_ip,
                description=f"Rate limit exceeded for {dimension} on {request.url.path}",
                threat_score=0.8 if is_lockout else 0.5,
                context={
                    "dimension": dimension,
                    "tier": tier_name,
                    "team_id": team_id,
                    "limit": tier["limit"],
                    "endpoint": request.url.path,
                    "method": request.method,
                },
            )
        except Exception as e:
            logger.error(f"Failed to log security event: {e}")

    def _create_rate_limit_response(
        self,
        request: Request,  # pylint: disable=unused-argument
        dimensions: List[str],  # pylint: disable=unused-argument
        tier: Dict[str, Any],
        tier_name: str,
        is_lockout: bool = False,
    ) -> JSONResponse:
        """Create rate limit exceeded response."""
        now = time.time()
        limit = tier["limit"]

        headers = {
            "Retry-After": str(self.lockout_duration_minutes * 60 if is_lockout else 60),
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(now + 60)),
        }

        if is_lockout:
            headers["X-Lockout-Remaining"] = str(self.lockout_duration_minutes * 60)

            return JSONResponse(
                status_code=429,
                content={
                    "error": "Account locked",
                    "message": f"Too many rate limit violations. Account locked for {self.lockout_duration_minutes} minutes. This may indicate suspicious activity on your account.",
                    "lockout_duration_minutes": self.lockout_duration_minutes,
                    "reset_in_seconds": self.lockout_duration_minutes * 60,
                },
                headers=headers,
            )

        return JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded",
                "message": f"Maximum {limit} requests per minute for {tier_name} tier endpoints.",
                "limit": limit,
                "reset_in_seconds": 60,
            },
            headers=headers,
        )

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request.

        Only trusts X-Forwarded-For / X-Real-IP when the deployment is
        configured to trust proxy headers (trust_proxy_auth). Otherwise
        falls back to the direct transport client address to prevent
        IP-spoofing evasion of rate limits.
        """
        if settings.trust_proxy_auth:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()

            real_ip = request.headers.get("X-Real-IP")
            if real_ip:
                return real_ip

        # Use scope client (set by ASGI server) rather than request.client,
        # which can be rewritten by upstream proxy middleware.
        client = request.scope.get("client")
        if client:
            return client[0]

        return "unknown"
