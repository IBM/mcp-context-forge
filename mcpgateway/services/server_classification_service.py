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
    from mcpgateway.services.session_affinity import SessionAffinity

logger = logging.getLogger(__name__)


@dataclass
class ClassificationMetadata:
    """Metadata about a classification run."""

    total_servers: int
    hot_cap: int
    hot_actual: int
    eligible_count: int  # Servers with recent-use signal (currently always 0 post-#4205)
    timestamp: float
    underutilized_reason: Optional[str] = None


@dataclass
class ClassificationResult:
    """Result of server classification."""

    hot_servers: List[str]
    cold_servers: List[str]
    metadata: ClassificationMetadata


class ServerClassificationService:
    """Manages hot/cold server classification for gated auto-refresh polling.

    Classification historically used per-URL usage metrics from the upstream
    session pool to pick the top 20% of most-recently-used servers as "hot"
    (auto-refreshed more aggressively). The pool is gone as of #4205; its
    replacement ``UpstreamSessionRegistry`` keys by downstream-session id
    rather than URL, so the old signal is no longer directly extractable.

    Until the classification logic is rewritten against registry metrics +
    audit data, ``_classify_servers_from_pool`` is a stub that marks every
    server as cold, which degrades to "poll all gateways on the normal
    schedule" — the conservative, no-regression fallback.

    Multi-worker coordination via Redis (leader election, result publish)
    still works; it just publishes an empty-hot / all-cold result each run.
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
            from mcpgateway.services.session_affinity import get_session_affinity

            try:
                pool = get_session_affinity()
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

    def _classify_servers_from_pool(
        self, pool: SessionAffinity, all_gateway_urls: List[str], gateway_url_map: Optional[Dict[str, str]] = None
    ) -> ClassificationResult:  # pylint: disable=unused-argument
        """Classify servers — currently returns "everything cold" (#4205 follow-up).

        Historically this aggregated per-URL usage from the pool's internal
        ``_pools`` and ``_active`` dicts. Those dicts disappeared when the
        upstream-session pool was replaced by ``UpstreamSessionRegistry``;
        the registry keys by ``(downstream_session_id, gateway_id)`` rather
        than URL, so the old per-URL recency/use-count signal is no longer
        directly available.

        This stub preserves the caller contract (every registered URL ends
        up in ``cold_servers``) so hot/cold-gated polling degrades to
        "always poll", rather than silently raising and stalling classification.
        A rebuild against ``RegistrySnapshot`` plus gateway audit data is
        tracked separately.

        Args:
            pool: Session-affinity service. Currently unused — left in the
                signature to preserve the caller contract and to make the
                follow-up re-wire easier.
            all_gateway_urls: All registered gateway URLs.
            gateway_url_map: Optional gateway_id → URL mapping; unused here.

        Returns:
            ClassificationResult with an empty hot set and every URL marked cold.
        """
        total_servers = len(all_gateway_urls)
        return ClassificationResult(
            hot_servers=[],
            cold_servers=list(all_gateway_urls),
            metadata=ClassificationMetadata(
                total_servers=total_servers,
                hot_cap=floor(0.20 * total_servers),
                hot_actual=0,
                eligible_count=0,
                timestamp=time.time(),
                underutilized_reason="pool classification disabled post-#4205; rebuild against UpstreamSessionRegistry pending",
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
