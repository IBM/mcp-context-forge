# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/leader_election.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Primary-worker elector with two backends.

- ``filelock`` (passive): one primary per host; the OS releases the lock on exit.
- ``redis`` (active): one primary across instances sharing a Redis, via a lease
  (``SET NX EX``) renewed by an atomic compare-and-renew Lua and released by an
  if-owner Lua, with a follower loop that re-acquires on expiry.

Surface: ``start()`` / ``stop()`` / ``is_primary``; ``is_primary_worker()`` reads
the cached flag for the redis backend.
"""

# Standard
import asyncio
import logging
import os
import tempfile
import uuid
from typing import Any, Optional

# Third-Party
from filelock import FileLock, Timeout

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)

# Atomic compare-and-renew: extend TTL only if we still own the key.
_RENEW_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end"
# Atomic if-owner release.
_RELEASE_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


def _default_lock_path() -> str:
    """Port-scoped temp lock path (mirrors mcpgateway.utils.primary_worker).

    Returns:
        Absolute path to the file-lock.
    """
    return settings.primary_worker_lock_path or os.path.join(tempfile.gettempdir(), f"mcpgw_plugin_primary_{settings.port}.lock")


class PrimaryWorkerElector:
    """Elects one primary worker via a file lock (per host) or Redis (per cluster)."""

    def __init__(
        self,
        *,
        backend: Optional[str] = None,
        redis_url: Optional[str] = None,
        redis_key: Optional[str] = None,
        lease_ttl: Optional[int] = None,
        heartbeat_interval: Optional[int] = None,
        unavailable_policy: Optional[str] = None,
        lock_path: Optional[str] = None,
        redis_client: Optional[Any] = None,
    ) -> None:
        """Build an elector, defaulting unset options from settings.

        Args:
            backend: ``"filelock"`` or ``"redis"``.
            redis_url: Redis URL for the redis backend.
            redis_key: Lease key name.
            lease_ttl: Lease TTL in seconds.
            heartbeat_interval: Seconds between lease renewals.
            unavailable_policy: ``"fail_closed"`` or ``"filelock_fallback"``.
            lock_path: Override file-lock path (filelock backend / fallback).
            redis_client: Pre-built async Redis client (used by tests); when
                omitted the redis backend builds one from ``redis_url``.
        """
        self._backend = backend or settings.primary_worker_election_backend
        self._redis_url = redis_url or settings.redis_url
        self._redis_key = redis_key or settings.primary_worker_redis_key
        self._lease_ttl = lease_ttl or settings.primary_worker_lease_ttl
        self._heartbeat = heartbeat_interval or settings.primary_worker_heartbeat_interval
        self._policy = unavailable_policy or settings.primary_worker_redis_unavailable_policy
        self._lock_path = lock_path
        self._instance_id = str(uuid.uuid4())
        self._is_primary = False
        self._started = False
        self._redis: Any = redis_client
        self._owns_redis = redis_client is None
        self._task: Optional["asyncio.Task[None]"] = None
        self._filelock: Optional[FileLock] = None

    @property
    def started(self) -> bool:
        """Whether ``start()`` has completed.

        Returns:
            True once started.
        """
        return self._started

    @property
    def is_primary(self) -> bool:
        """Whether this process currently holds primary status.

        Returns:
            True if primary.
        """
        return self._is_primary

    @property
    def instance_id(self) -> str:
        """Unique id for this elector instance.

        Returns:
            The instance id.
        """
        return self._instance_id

    async def start(self) -> None:
        """Run the initial election (and launch the redis maintenance loop)."""
        if self._backend == "redis":
            await self._start_redis()
        else:
            self._acquire_filelock()
        self._started = True
        logger.info("primary-worker elector started backend=%s primary=%s pid=%d", self._backend, self._is_primary, os.getpid())

    async def stop(self) -> None:
        """Cancel maintenance and release the lease if we own it."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._redis is not None:
            try:
                if self._is_primary:
                    await self._redis.eval(_RELEASE_LUA, 1, self._redis_key, self._instance_id)
                if self._owns_redis:
                    await self._redis.aclose()
            except Exception as exc:  # best-effort cleanup
                logger.warning("elector stop cleanup failed: %s", exc)
        self._is_primary = False
        self._started = False

    # --- filelock backend (passive) -----------------------------------------

    def _acquire_filelock(self) -> None:
        """Try to grab the per-host file lock (held for process lifetime)."""
        self._filelock = FileLock(self._lock_path or _default_lock_path())
        try:
            self._filelock.acquire(timeout=0)
            self._is_primary = True
        except (Timeout, OSError):
            self._is_primary = False

    # --- redis backend (active lease) ---------------------------------------

    async def _start_redis(self) -> None:
        """Acquire the lease and start the maintenance loop."""
        try:
            if self._redis is None:
                # Third-Party
                import redis.asyncio as aioredis  # pylint: disable=import-outside-toplevel

                self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            won = await self._redis.set(self._redis_key, self._instance_id, nx=True, ex=self._lease_ttl)
            self._is_primary = bool(won)
            self._task = asyncio.create_task(self._maintain())
        except Exception as exc:
            self._handle_redis_unavailable(exc)

    def _handle_redis_unavailable(self, exc: Exception) -> None:
        """Apply the configured policy when Redis can't be reached."""
        if self._policy == "filelock_fallback":
            logger.warning("redis unavailable (%s); falling back to per-host filelock", exc)
            self._acquire_filelock()
        else:
            logger.warning("redis unavailable (%s); failing closed (non-primary)", exc)
            self._is_primary = False

    async def _maintain(self) -> None:
        """Renew the lease while primary; otherwise retry to take over."""
        ttl_ms = self._lease_ttl * 1000
        while True:
            await asyncio.sleep(self._heartbeat)
            try:
                if self._is_primary:
                    renewed = await self._redis.eval(_RENEW_LUA, 1, self._redis_key, self._instance_id, ttl_ms)
                    if not renewed:
                        logger.info("lost primary lease pid=%d", os.getpid())
                        self._is_primary = False
                else:
                    won = await self._redis.set(self._redis_key, self._instance_id, nx=True, ex=self._lease_ttl)
                    if won:
                        logger.info("acquired primary lease via follower loop pid=%d", os.getpid())
                        self._is_primary = True
            except Exception as exc:
                if self._policy == "fail_closed":
                    self._is_primary = False
                logger.warning("election maintenance error pid=%d: %s", os.getpid(), exc)


# Module singleton — created/started in the FastAPI lifespan, read by
# ``mcpgateway.utils.primary_worker.is_primary_worker`` for the redis backend.
_elector: Optional[PrimaryWorkerElector] = None


def get_primary_worker_elector() -> Optional[PrimaryWorkerElector]:
    """Return the started elector singleton, or ``None`` if not started.

    Returns:
        The elector or None.
    """
    return _elector


async def start_primary_worker_elector(redis_client: Optional[object] = None) -> PrimaryWorkerElector:
    """Create and start the singleton elector (awaits the initial election).

    Args:
        redis_client: Optional pre-built async Redis client to reuse.

    Returns:
        The started elector.
    """
    global _elector  # pylint: disable=global-statement
    if _elector is None:
        _elector = PrimaryWorkerElector(redis_client=redis_client)
    await _elector.start()
    return _elector


async def stop_primary_worker_elector() -> None:
    """Stop and clear the singleton elector."""
    global _elector  # pylint: disable=global-statement
    if _elector is not None:
        await _elector.stop()
        _elector = None
