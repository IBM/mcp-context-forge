# -*- coding: utf-8 -*-
"""
Server Classification Service.

Manages hot/cold server classification based on MCP session pool usage patterns.
Provides staggered polling to optimize resource allocation and reduce polling overhead.

Classification is based ONLY on upstream MCP pooled session state (gateway -> MCP servers).

Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from dataclasses import asdict, dataclass
import hashlib
import logging
from math import floor
import time
from typing import Dict, List, Literal, Optional, TYPE_CHECKING

# Third-Party
import orjson

# First-Party
from mcpgateway.config import settings

if TYPE_CHECKING:
    # Third-Party
    from redis.asyncio import Redis

    # First-Party
    from mcpgateway.services.mcp_session_pool import MCPSessionPool

logger = logging.getLogger(__name__)


@dataclass
class ServerUsageMetrics:
    """Aggregated usage metrics for a single server from pooled sessions."""

    url: str
    server_last_used: float = 0.0  # max(last_used) across all pooled sessions
    active_session_count: int = 0  # Count from _active dict
    total_use_count: int = 0  # Sum of use_count from all sessions
    pooled_session_count: int = 0  # Total pooled sessions for this server


@dataclass
class ClassificationMetadata:
    """Metadata about classification run."""

    total_servers: int  # Total servers
    hot_cap: int  # Maximum hot servers (20% of total_servers)
    hot_actual: int  # Actual hot servers selected
    eligible_count: int  # Servers with pooled sessions
    timestamp: float  # Classification timestamp
    underutilized_reason: Optional[str] = None  # Why hot < 20% (if applicable)


@dataclass
class ClassificationResult:
    """Result of server classification."""

    hot_servers: List[str]  # URLs of hot servers
    cold_servers: List[str]  # URLs of cold servers
    metadata: ClassificationMetadata


class ServerClassificationService:
    """
    Manages hot/cold server classification based on MCP session pool state.

    Classification Logic:
        1. Scope: Uses only upstream MCP pooled session state
        2. Hot cap: floor(20% * total_servers)
        3. Eligibility: Server must have pooled session with valid last_used
        4. Ranking: server_last_used descending (newest first)
        5. Tie-breakers: active_count, use_count, URL (deterministic)
        6. Hot selection: Top min(hot_cap, eligible_count)
        7. Cold: All remaining servers
        8. Guarantees: No overlap, full coverage, deterministic

    Thread-safe for multi-worker deployments via Redis state management.
    Falls back to local-only operation when Redis unavailable.
    """

    # Redis key templates
    CLASSIFICATION_HOT_KEY = "mcpgateway:server_classification:hot"
    CLASSIFICATION_COLD_KEY = "mcpgateway:server_classification:cold"
    CLASSIFICATION_METADATA_KEY = "mcpgateway:server_classification:metadata"
    CLASSIFICATION_TIMESTAMP_KEY = "mcpgateway:server_classification:timestamp"
    POLL_STATE_KEY_TEMPLATE = "mcpgateway:server_poll_state:{scope_hash}:last_{poll_type}"
    LEADER_KEY = "mcpgateway:server_classification:leader"

    # Lua script for atomic leader lock acquire-or-renew.
    # Executes as a single atomic operation in Redis, preventing the race where
    # the key expires between a GET and EXPIRE in separate round-trips.
    _LEADER_LOCK_SCRIPT = """
    if redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]), 'NX') then
        return 1
    end
    if redis.call('GET', KEYS[1]) == ARGV[1] then
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
        return 1
    end
    return 0
    """

    def __init__(self, redis_client: Optional[Redis] = None):
        """Initialize classification service.

        Args:
            redis_client: Redis client for state management (optional for single-worker)
        """
        self._redis = redis_client
        self._classification_task: Optional[asyncio.Task] = None
        self._instance_id = f"classifier_{id(self)}"
        # TTL = 3x interval gives ample margin for classification + sleep.
        # Classification is idempotent (deterministic algorithm), so even if the lock
        # expires and a second worker classifies concurrently, the result is identical.
        self._leader_ttl = int(settings.gateway_auto_refresh_interval * 3)
        self._running = False
        self._error_backoff_seconds: float = 30.0  # Back off duration on loop errors (override in tests)
        self._leader_lock_sha: Optional[str] = None  # Cached SHA for leader lock Lua script

    async def start(self) -> None:
        """Start background classification loop (if enabled)."""
        if not settings.hot_cold_classification_enabled:
            logger.info("Hot/cold classification disabled")
            return

        if self._running:
            logger.warning("Classification service already running")
            return

        self._running = True
        self._classification_task = asyncio.create_task(self._run_classification_loop())
        self._classification_task.add_done_callback(self._on_classification_task_done)
        logger.info(f"Server classification service started " f"(instance={self._instance_id}, redis={'enabled' if self._redis else 'disabled'})")

    def _on_classification_task_done(self, task: asyncio.Task) -> None:
        """Callback when the classification background task exits unexpectedly."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(f"Classification background task died: {exc}", exc_info=exc)
        self._running = False

    async def stop(self) -> None:
        """Stop background classification."""
        self._running = False
        if self._classification_task:
            self._classification_task.cancel()
            try:
                await self._classification_task
            except asyncio.CancelledError:
                logger.info("Classification task cancelled")
            except Exception as e:
                # Task already died with an error — don't let it crash shutdown
                logger.warning(f"Classification task had failed: {e}")

    async def _run_classification_loop(self) -> None:
        """Background loop: classify servers periodically with leader election."""
        while self._running:
            try:
                # Leader election (Redis-based for multi-worker, local-only otherwise)
                is_leader = await self._try_acquire_leader_lock()

                if is_leader:
                    logger.debug(f"Classification leader acquired (instance={self._instance_id})")
                    # Classification is idempotent (deterministic algorithm on shared pool state),
                    # so concurrent execution by multiple workers produces identical results.
                    # Leader election reduces redundant work; it is not a correctness requirement.
                    # Timeout prevents unbounded runs from holding the loop.
                    try:
                        await asyncio.wait_for(self._perform_classification(), timeout=self._leader_ttl * 0.8)
                    except asyncio.TimeoutError:
                        logger.warning(f"Classification timed out after {self._leader_ttl * 0.8:.0f}s, skipping this cycle")
                    # Renew lock after classification to keep it alive during sleep
                    await self._try_acquire_leader_lock()
                else:
                    logger.debug(f"Not classification leader, skipping (instance={self._instance_id})")

                await asyncio.sleep(settings.gateway_auto_refresh_interval)

            except asyncio.CancelledError:
                logger.info("Classification loop cancelled")
                break
            except Exception as e:
                logger.error(f"Classification loop error: {e}", exc_info=True)
                await asyncio.sleep(self._error_backoff_seconds)  # Back off on error

    async def _try_acquire_leader_lock(self) -> bool:
        """Try to acquire or renew leader lock for classification.

        Uses an atomic Lua script that either acquires a new lock (SET NX)
        or renews the TTL if this instance already holds it. The script
        runs as a single Redis transaction, preventing the race where the
        key expires between a GET and EXPIRE in separate round-trips.

        Returns:
            True if this instance is leader, False otherwise
        """
        if not self._redis:
            # Single-worker mode (no Redis), always leader
            return True

        try:
            # Load Lua script on first call (cached by Redis server via SHA)
            if self._leader_lock_sha is None:
                self._leader_lock_sha = await self._redis.script_load(self._LEADER_LOCK_SCRIPT)

            try:
                result = await self._redis.evalsha(self._leader_lock_sha, 1, self.LEADER_KEY, self._instance_id, str(self._leader_ttl))
            except Exception as evalsha_err:
                # Handle NOSCRIPT (Redis restarted / SCRIPT FLUSH) by re-registering
                if "NOSCRIPT" in str(evalsha_err):
                    logger.debug("Lua script evicted, re-registering")
                    self._leader_lock_sha = await self._redis.script_load(self._LEADER_LOCK_SCRIPT)
                    result = await self._redis.evalsha(self._leader_lock_sha, 1, self.LEADER_KEY, self._instance_id, str(self._leader_ttl))
                else:
                    raise
            return result == 1
        except Exception as e:
            logger.warning(f"Failed to acquire leader lock: {e}")
            return False  # Fail safe: don't classify on error

    async def _perform_classification(self) -> None:
        """Perform classification and publish to Redis (if available)."""
        try:
            # Get MCP session pool
            # First-Party
            from mcpgateway.services.mcp_session_pool import get_mcp_session_pool

            try:
                pool = get_mcp_session_pool()
            except RuntimeError:
                logger.debug("MCP session pool not initialized, skipping classification")
                return

            # Get gateway_id → canonical URL mapping from database
            gateway_url_map = await self._get_gateway_url_map()
            if not gateway_url_map:
                logger.debug("No gateways found, skipping classification")
                return

            # Deduplicate: multiple gateways may share the same upstream URL
            # (different credentials/scopes). Classification operates on unique servers.
            all_gateway_urls = list(dict.fromkeys(gateway_url_map.values()))

            # Perform classification
            result = self._classify_servers_from_pool(pool, all_gateway_urls, gateway_url_map)

            # Publish to Redis (if available)
            if self._redis:
                await self._publish_classification_to_redis(result)

            logger.info(
                f"Classification completed: {len(result.hot_servers)} hot, " f"{len(result.cold_servers)} cold (N={result.metadata.total_servers}, " f"eligible={result.metadata.eligible_count})"
            )

            if result.metadata.underutilized_reason:
                logger.debug(f"Underutilization: {result.metadata.underutilized_reason}")

        except Exception as e:
            logger.error(f"Classification failed: {e}", exc_info=True)

    def _resolve_canonical_url(self, pool_key: tuple, gateway_url_map: Dict[str, str]) -> Optional[str]:
        """Resolve the canonical gateway URL for a pool key.

        Pool keys may contain auth-mutated URLs (e.g. with query-param secrets).
        Use gateway_id from the pool key to look up the canonical Gateway.url,
        preventing secret leakage into classification Redis sets.

        Args:
            pool_key: PoolKey tuple (user_identity, url, identity_hash, transport_type, gateway_id)
            gateway_url_map: Mapping of gateway_id → canonical URL from database

        Returns:
            Canonical URL if gateway_id resolves, else None
        """
        gateway_id = pool_key[4] if len(pool_key) > 4 else ""
        if gateway_id and gateway_id in gateway_url_map:
            return gateway_url_map[gateway_id]
        return None

    def _classify_servers_from_pool(self, pool: MCPSessionPool, all_gateway_urls: List[str], gateway_url_map: Optional[Dict[str, str]] = None) -> ClassificationResult:
        """Classify servers based on pooled session state.

        Algorithm (deterministic):
            1. Get total servers N
            2. Calculate hot_cap = floor(0.20 * N)
            3. Extract server metrics from pooled sessions (idle + active)
            4. Filter eligible (has valid last_used or active sessions)
            5. Sort by (server_last_used desc, active_count desc, use_count desc, url asc)
            6. Select top min(hot_cap, eligible_count) as hot
            7. Remaining servers are cold

        Args:
            pool: MCP session pool
            all_gateway_urls: All registered gateway URLs
            gateway_url_map: Optional mapping of gateway_id → canonical URL for URL normalization

        Returns:
            ClassificationResult with hot/cold servers and metadata
        """
        total_servers = len(all_gateway_urls)
        hot_cap = floor(0.20 * total_servers)
        canonical_url_set = set(all_gateway_urls)

        # Step 3: Extract server usage from pooled sessions
        server_metrics: Dict[str, ServerUsageMetrics] = {}

        # Helper to accumulate metrics from a single PooledSession
        def _accumulate_session(url: str, session: object) -> None:
            """Accumulate metrics from a single pooled session into server_metrics.

            Args:
                url: Server URL
                session: PooledSession object with last_used and use_count attributes
            """

            if url not in server_metrics:
                server_metrics[url] = ServerUsageMetrics(url=url)
            if hasattr(session, "last_used") and session.last_used > 0:
                server_metrics[url].server_last_used = max(server_metrics[url].server_last_used, session.last_used)
                server_metrics[url].total_use_count += getattr(session, "use_count", 0)
                server_metrics[url].pooled_session_count += 1

        # Iterate over pool._pools (Dict[PoolKey, Queue[PooledSession]])
        # PoolKey = (user_identity, url, identity_hash, transport_type, gateway_id)
        for pool_key, session_queue in pool._pools.items():  # pylint: disable=protected-access
            # Resolve canonical URL: prefer gateway_id lookup, fall back to raw pool URL
            url = (self._resolve_canonical_url(pool_key, gateway_url_map) if gateway_url_map else None) or pool_key[1]

            # Only track URLs that correspond to known gateways
            if url not in canonical_url_set:
                continue

            if url not in server_metrics:
                server_metrics[url] = ServerUsageMetrics(url=url)

            # Process each idle session in the queue
            try:
                if hasattr(session_queue, "_queue"):
                    sessions_list = list(session_queue._queue)  # pylint: disable=protected-access
                else:
                    sessions_list = []

                for session in sessions_list:
                    _accumulate_session(url, session)
            except Exception as e:
                logger.warning(f"Error extracting idle metrics for {url}: {e}")
                continue

        # Process active sessions (checked-out from the pool)
        # This ensures busy servers with all sessions in use are still eligible.
        for pool_key, active_set in pool._active.items():  # pylint: disable=protected-access
            url = (self._resolve_canonical_url(pool_key, gateway_url_map) if gateway_url_map else None) or pool_key[1]

            if url not in canonical_url_set:
                continue

            if url not in server_metrics:
                server_metrics[url] = ServerUsageMetrics(url=url)

            server_metrics[url].active_session_count += len(active_set)

            # Extract last_used / use_count from active sessions too
            for session in active_set:
                try:
                    _accumulate_session(url, session)
                except Exception as active_err:
                    logger.debug(f"Skipping active session metric for {url}: {active_err}")
                    continue

        # Step 4: Filter eligible servers (has valid last_used)
        eligible_servers = [metrics for metrics in server_metrics.values() if metrics.server_last_used > 0.0]
        eligible_count = len(eligible_servers)

        # Step 5: Sort by recency (newer first), then tie-breakers
        eligible_servers.sort(
            key=lambda m: (
                -m.server_last_used,  # Primary: most recent first (descending)
                -m.active_session_count,  # Tie-breaker 1: more active sessions
                -m.total_use_count,  # Tie-breaker 2: higher use count
                m.url,  # Tie-breaker 3: deterministic (ascending)
            )
        )

        # Step 6: Select hot servers (up to hot_cap, no backfill)
        hot_actual = min(hot_cap, eligible_count)
        hot_servers = [m.url for m in eligible_servers[:hot_actual]]

        # Step 7: Cold servers = all remaining
        hot_set = set(hot_servers)
        cold_servers = [url for url in all_gateway_urls if url not in hot_set]

        # Step 8: Build metadata
        underutilized_reason = None
        if eligible_count < hot_cap:
            underutilized_reason = f"Only {eligible_count} servers have pooled sessions, " f"below hot_cap={hot_cap}"

        return ClassificationResult(
            hot_servers=hot_servers,
            cold_servers=cold_servers,
            metadata=ClassificationMetadata(
                total_servers=total_servers, hot_cap=hot_cap, hot_actual=hot_actual, eligible_count=eligible_count, timestamp=time.time(), underutilized_reason=underutilized_reason
            ),
        )

    async def _get_gateway_url_map(self) -> Dict[str, str]:
        """Get mapping of gateway_id → canonical URL for all enabled gateways.

        Returns:
            Dict mapping gateway ID to its canonical URL
        """
        # Third-Party
        from sqlalchemy import select

        # First-Party
        from mcpgateway.db import Gateway, SessionLocal

        try:
            with SessionLocal() as db:
                result = db.execute(select(Gateway.id, Gateway.url).where(Gateway.enabled.is_(True)))
                return {str(row[0]): row[1] for row in result}
        except Exception as e:
            logger.error(f"Failed to get gateway URL map: {e}")
            return {}

    async def _publish_classification_to_redis(self, result: ClassificationResult) -> None:
        """Publish classification result to Redis atomically.

        Args:
            result: Classification result to publish
        """
        if not self._redis:
            return

        try:
            # Atomic pipeline for transactional updates
            async with self._redis.pipeline(transaction=True) as pipe:
                # Clear old classification
                await pipe.delete(self.CLASSIFICATION_HOT_KEY, self.CLASSIFICATION_COLD_KEY)

                # Set new classification
                # Set TTL on classification sets to prevent stale data after worker crash
                ttl = int(settings.gateway_auto_refresh_interval * 2)

                if result.hot_servers:
                    await pipe.sadd(self.CLASSIFICATION_HOT_KEY, *result.hot_servers)

                if result.cold_servers:
                    await pipe.sadd(self.CLASSIFICATION_COLD_KEY, *result.cold_servers)

                # Expire classification sets regardless of whether they had members
                await pipe.expire(self.CLASSIFICATION_HOT_KEY, ttl)
                await pipe.expire(self.CLASSIFICATION_COLD_KEY, ttl)

                # Store metadata (expire after 2x classification interval)
                metadata_json = orjson.dumps(asdict(result.metadata))
                await pipe.set(self.CLASSIFICATION_METADATA_KEY, metadata_json, ex=ttl)

                await pipe.set(self.CLASSIFICATION_TIMESTAMP_KEY, result.metadata.timestamp, ex=ttl)

                await pipe.execute()

            logger.debug("Classification published to Redis successfully")

        except Exception as e:
            logger.error(f"Failed to publish classification to Redis: {e}")

    async def get_server_classification(self, url: str) -> Optional[str]:
        """Get classification for a server (hot/cold).

        Args:
            url: Server URL

        Returns:
            "hot", "cold", or None if not classified
        """
        if not self._redis:
            return None  # No Redis, classification not available

        try:
            is_hot = await self._redis.sismember(self.CLASSIFICATION_HOT_KEY, url)
            if is_hot:
                return "hot"

            is_cold = await self._redis.sismember(self.CLASSIFICATION_COLD_KEY, url)
            if is_cold:
                return "cold"

            return None  # Not yet classified
        except Exception as e:
            logger.warning(f"Failed to get classification for {url}: {e}")
            return None  # Fail open

    def _poll_state_key(self, url: str, poll_type: str, gateway_id: str = "") -> str:
        """Build the Redis key for poll-state tracking.

        Includes gateway_id when provided so that distinct gateways sharing the
        same upstream URL track their refresh schedules independently.
        """
        scope = f"{url}\0{gateway_id}" if gateway_id else url
        scope_hash = hashlib.sha256(scope.encode()).hexdigest()[:32]
        return self.POLL_STATE_KEY_TEMPLATE.format(scope_hash=scope_hash, poll_type=poll_type)

    async def should_poll_server(self, url: str, poll_type: Literal["health", "tool_discovery"], gateway_id: str = "") -> bool:
        """Determine if server should be polled now based on classification.

        Args:
            url: Server URL
            poll_type: Type of poll (health or tool_discovery)
            gateway_id: Optional gateway ID for per-gateway poll tracking

        Returns:
            True if should poll now, False otherwise
        """
        if not settings.hot_cold_classification_enabled:
            return True  # Feature disabled, always poll

        if not self._redis:
            return True  # No Redis, always poll (single-worker mode)

        try:
            classification = await self.get_server_classification(url)
            if classification is None:
                return True  # Not yet classified, poll anyway

            last_poll_key = self._poll_state_key(url, poll_type, gateway_id)
            last_poll_str = await self._redis.get(last_poll_key)

            if last_poll_str is None:
                # Never polled, should poll now (caller must call mark_poll_completed after)
                return True

            last_poll = float(last_poll_str)
            now = time.time()
            if not 0 < last_poll <= now + 60:
                last_poll = 0.0  # treat as never polled; prevents manipulation via future timestamps
            elapsed = now - last_poll

            # Determine interval based on classification
            interval = settings.hot_server_check_interval if classification == "hot" else settings.cold_server_check_interval

            should_poll = elapsed >= interval

            return should_poll

        except Exception as e:
            logger.warning(f"Error checking poll status for {url}: {e}")
            return True  # Fail open: poll on error

    async def mark_poll_completed(self, url: str, poll_type: Literal["health", "tool_discovery"], gateway_id: str = "") -> None:
        """Record that a poll was actually performed.

        Call this AFTER the poll/refresh succeeds, not at decision time.
        This prevents wasting poll slots when downstream throttling skips the refresh.

        Args:
            url: Server URL
            poll_type: Type of poll
            gateway_id: Optional gateway ID for per-gateway poll tracking
        """
        if not self._redis:
            return

        try:
            classification = await self.get_server_classification(url)
            interval = settings.hot_server_check_interval if classification == "hot" else settings.cold_server_check_interval

            last_poll_key = self._poll_state_key(url, poll_type, gateway_id)
            await self._redis.set(last_poll_key, time.time(), ex=int(interval * 2))  # Expire after 2x interval
        except Exception as e:
            logger.warning(f"Failed to update poll timestamp for {url}: {e}")
