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
import uuid
from typing import Any, Optional

# Third-Party
from filelock import FileLock, Timeout

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.primary_worker import _lock_path as _default_lock_path  # canonical port-scoped lock path

logger = logging.getLogger(__name__)

# Atomic compare-and-renew: extend TTL only if we still own the key.
_RENEW_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end"
# Atomic if-owner release.
_RELEASE_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


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
        # Use ``is None`` (not ``or``) so an explicit 0/"" is honored rather than
        # silently replaced by the settings default.
        self._backend = backend if backend is not None else settings.primary_worker_election_backend
        self._redis_url = redis_url if redis_url is not None else settings.redis_url
        self._redis_key = redis_key if redis_key is not None else settings.primary_worker_redis_key
        self._lease_ttl = lease_ttl if lease_ttl is not None else settings.primary_worker_lease_ttl
        self._heartbeat = heartbeat_interval if heartbeat_interval is not None else settings.primary_worker_heartbeat_interval
        self._policy = unavailable_policy if unavailable_policy is not None else settings.primary_worker_redis_unavailable_policy
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
        """Run the initial election (and launch the redis maintenance loop).

        Idempotent: a second call is a no-op. Re-running the redis path would
        re-issue ``SET NX`` (which fails because we already own the key) and
        wrongly demote us, and would create a second maintenance task that
        orphans the first.
        """
        if self._started:
            return
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
            except Exception as exc:  # best-effort: don't let a task error break the shutdown sequence
                logger.warning("elector maintenance task raised on cancel: %s", exc)
            self._task = None
        if self._redis is not None:
            try:
                if self._is_primary:
                    await self._redis.eval(_RELEASE_LUA, 1, self._redis_key, self._instance_id)
                if self._owns_redis:
                    await self._redis.aclose()
            except Exception as exc:  # best-effort cleanup
                logger.warning("elector stop cleanup failed: %s", exc)
            finally:
                # Drop the client we own so a repeat stop() doesn't touch a closed
                # one; keep an injected client (tests) since we didn't open it.
                if self._owns_redis:
                    self._redis = None
        self._is_primary = False
        self._started = False

    # --- filelock backend (passive) -----------------------------------------

    def _acquire_filelock(self) -> None:
        """Try to grab the per-host file lock (held for process lifetime).

        Idempotent: reuses a single ``FileLock`` and short-circuits when the lock
        is already held, so the maintenance loop can call it every heartbeat
        during a Redis outage without churning (re-creating/releasing) the lock.
        """
        if self._filelock is None:
            self._filelock = FileLock(self._lock_path or _default_lock_path())
        elif self._filelock.is_locked:
            self._is_primary = True
            return
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
                # A heartbeat/acquire error means we can no longer prove we hold
                # the lease, so never keep a stale Redis-primary flag (the lease
                # expires unrenewed and a follower would take it -> two primaries).
                # Apply the same policy as the initial connect: fail_closed demotes;
                # filelock_fallback re-elects per host (and demotes if it can't).
                logger.warning("election maintenance error pid=%d: %s", os.getpid(), exc)
                self._handle_redis_unavailable(exc)


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
