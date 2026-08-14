# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/jq_runner.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Sandboxed execution of user-supplied jq filters.

Tool ``jsonpath_filter`` programs are attacker-influenced input. python-jq
offers no timeout and holds the GIL for the duration of a run, so a filter that
does not terminate freezes the whole gateway worker. jq also exposes built-ins
that read the process environment.

Filters therefore run in a forked worker whose environment has been cleared,
under a wall-clock limit, with the worker killed and replaced if it overruns.
The static gate in :mod:`mcpgateway.utils.jq_guard` runs first; the scrubbed
worker is the backstop for anything the gate misses.
"""

# Future
from __future__ import annotations

# Standard
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from concurrent.futures.process import BrokenProcessPool
from functools import lru_cache
import logging
import multiprocessing
import os
import sys
import threading
from typing import Any, Optional

# Third-Party
import jq
import orjson

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.jq_guard import assert_safe_jq_filter

logger = logging.getLogger(__name__)

__all__ = ["JqFilterBusy", "JqFilterError", "JqFilterTimeout", "run_jq_filter", "start_jq_pool", "shutdown_jq_pool", "subprocess_mode_available"]


class JqFilterError(Exception):
    """Raised when a jq filter cannot be compiled or executed."""


class JqFilterTimeout(JqFilterError):
    """Raised when a jq filter exceeds its wall-clock limit.

    Only raised for a submission that is known to have started running
    immediately (the submit gate guarantees a free worker was available), so
    this always reflects a filter that is genuinely still executing past its
    budget, never queueing pressure from ordinary concurrent load.
    """


class JqFilterBusy(JqFilterError):
    """Raised when every worker is already busy running another filter.

    Distinct from :class:`JqFilterTimeout`: no filter has overrun anything,
    there simply wasn't a free worker slot for this call right now. Safe to
    retry, and does not indicate a hostile or hung filter, so it never kills
    the pool.
    """


_POOL: Optional[ProcessPoolExecutor] = None
_POOL_PID: Optional[int] = None
_POOL_LOCK = threading.Lock()
_FALLBACK_WARNED = False

# Attribute stamped on each executor with the PID that built it. Ownership has
# to be decidable from the pool object alone: a pool can be replaced (or its
# global reference cleared by ``shutdown_jq_pool``) while one of its workers is
# still running a hostile filter, and that worker must still be killable.
_OWNER_PID_ATTR = "_mcpgateway_owner_pid"

# Attribute stamped on each executor with a Semaphore sized to that pool's own
# worker count. ``ProcessPoolExecutor.submit()`` queues a task the moment a
# free work slot doesn't exist -- ``Future.result(timeout=...)`` then times
# queue wait and execution together, and a task that never even started
# running is indistinguishable from a genuine runaway once the timeout fires.
# Gating admission at this semaphore keeps every submission that actually
# reaches the pool guaranteed to start immediately, so a timeout on it is a
# real signal a filter is hung -- not queueing pressure from ordinary
# concurrent load. Stamped on the pool object, not read fresh from settings,
# so it always matches the worker count that pool was actually built with.
_GATE_ATTR = "_mcpgateway_submit_gate"

# Lower bound on how long ``start_jq_pool`` waits for the warm-up filter. The
# per-filter timeout is only validated as ``gt=0``, so an aggressively short
# value must not also shrink the startup budget and turn a boot into a failure.
_WARMUP_MIN_SECONDS = 10.0


def subprocess_mode_available() -> bool:
    """Report whether the forked sandbox can be used on this platform.

    The sandbox requires the ``fork`` start method. ``spawn`` and ``forkserver``
    re-import the parent's main module, which is unsafe under a preloaded
    gunicorn master, and ``fork`` itself is unsafe on Darwin.

    Returns:
        True when the sandbox should be used.
    """
    if settings.jq_filter_execution != "subprocess":
        return False
    return sys.platform.startswith("linux")


def _worker_init() -> None:
    """Clear the inherited environment inside a jq worker process.

    jq captures the process environment when a program is compiled, so this must
    run before any filter is compiled in this process.
    """
    os.environ.clear()


def _build_pool() -> ProcessPoolExecutor:
    """Create a forked worker pool with a scrubbed environment.

    Returns:
        The new executor, stamped with the PID that created it.
    """
    pool = ProcessPoolExecutor(
        max_workers=settings.jq_filter_workers,
        mp_context=multiprocessing.get_context("fork"),
        initializer=_worker_init,
    )
    setattr(pool, _OWNER_PID_ATTR, os.getpid())
    setattr(pool, _GATE_ATTR, threading.Semaphore(settings.jq_filter_workers))
    return pool


def _pool_is_owned(pool: ProcessPoolExecutor) -> bool:
    """Report whether this process forked the given pool's workers.

    Args:
        pool: The executor to test.

    Returns:
        True when the pool was built by this process, so killing its worker
        processes is safe. False for a pool inherited across a fork, whose
        ``Process`` objects reference the parent's children.
    """
    return getattr(pool, _OWNER_PID_ATTR, None) == os.getpid()


def _kill_workers(pool: ProcessPoolExecutor) -> None:
    """Kill every worker process belonging to a pool this process owns.

    ``ProcessPoolExecutor`` cannot cancel a task that is already running, and
    the public ``terminate_workers``/``kill_workers`` methods are Python 3.14
    while this project targets 3.12. The private ``_processes`` mapping is the
    only route; it is read defensively and pinned by a test.

    Args:
        pool: The executor whose workers should be killed. Callers must have
            confirmed ownership via :func:`_pool_is_owned` first.
    """
    # ``shutdown`` sets ``_processes`` to None to release file descriptors, so a
    # pool that has already been shut down elsewhere must not blow up here.
    for process in list((getattr(pool, "_processes", None) or {}).values()):
        try:
            process.kill()
        except Exception:  # pylint: disable=broad-except
            logger.warning("Failed to kill a jq worker process", exc_info=True)
    pool.shutdown(wait=False, cancel_futures=True)


def start_jq_pool() -> None:
    """Create the jq worker pool for this process.

    Call from application startup, after any fork performed by the server, so
    that each gateway worker owns its own pool.

    Raises:
        Exception: Whatever the warm-up submit raises when the sandbox cannot be
            brought up (``BrokenProcessPool``, ``TimeoutError``, ``OSError``).
            This is deliberately left to propagate: on Linux with subprocess
            mode a pool that will not start is a hard startup failure, since the
            alternative is booting a gateway whose filter sandbox is absent.
    """
    global _POOL, _POOL_PID, _FALLBACK_WARNED  # pylint: disable=global-statement

    if not subprocess_mode_available():
        if not _FALLBACK_WARNED:
            logger.warning(
                "jq filter sandbox is disabled (execution=%s, platform=%s). Tool jsonpath_filter programs will run in-process with no environment scrub and no time limit. This is unsafe outside development.",
                settings.jq_filter_execution,
                sys.platform,
            )
            _FALLBACK_WARNED = True
        return

    with _POOL_LOCK:
        if _POOL is not None and _POOL_PID == os.getpid():
            return
        pool = _build_pool()
        # ProcessPoolExecutor with the fork start method spawns workers lazily on
        # first submit, not at construction. Force that fork to happen now, while
        # the process still has the fewest threads, rather than mid-request on the
        # first attacker-triggered filter. This also proves the initializer (the
        # environment scrub) actually ran before we call the pool ready.
        try:
            pool.submit(_apply_filter, ".", b"null").result(timeout=max(_WARMUP_MIN_SECONDS, settings.jq_filter_timeout_seconds))
        except Exception:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        _POOL = pool
        _POOL_PID = os.getpid()
        logger.info("jq filter sandbox started with %s worker(s)", settings.jq_filter_workers)


def shutdown_jq_pool() -> None:
    """Tear down the jq worker pool for this process.

    Kills the pool's worker processes rather than only cancelling queued work.
    ``ProcessPoolExecutor.shutdown(wait=False, cancel_futures=True)`` drops
    *pending* futures but cannot stop a worker already mid-filter, and the
    executor's own ``atexit`` hook then blocks interpreter exit trying to join a
    worker that is running a non-terminating jq program.
    """
    _discard_pool(None)


def _discard_pool(pool: Optional[ProcessPoolExecutor]) -> None:
    """Kill a pool's workers and clear the module globals if they still name it.

    Killing is decided per pool object, not from the global ``_POOL`` pointer.
    A pool whose worker is running a hostile filter must stay killable even if
    another thread (application shutdown, a concurrent rebuild) has already
    moved ``_POOL`` on to something else — otherwise the runaway worker is
    orphaned and wedges interpreter exit. Conversely, a pool inherited across a
    fork is never killed: its ``Process`` objects belong to the parent.

    Args:
        pool: The executor to discard, or None to discard whichever pool
            ``_POOL`` currently names.
    """
    global _POOL, _POOL_PID  # pylint: disable=global-statement

    with _POOL_LOCK:
        target = pool if pool is not None else _POOL
        if target is None:
            return
        if _pool_is_owned(target):
            _kill_workers(target)
        # Only stand down the shared globals if they still point at the exact
        # pool just handled; a newer pool built by another thread is left alone.
        if _POOL is target:
            _POOL = None
            _POOL_PID = None


def _kill_pool_workers(pool: Optional[ProcessPoolExecutor] = None) -> None:
    """Kill the workers of a pool that overran its limit and drop it.

    Args:
        pool: The executor the overrunning filter was submitted to. Defaults to
            whichever pool ``_POOL`` currently names.
    """
    _discard_pool(pool)


def _ensure_pool() -> ProcessPoolExecutor:
    """Return a live pool for this process, creating one if needed.

    Returns:
        The executor owned by this process.

    Raises:
        JqFilterError: If the pool cannot be created.
    """
    global _POOL, _POOL_PID  # pylint: disable=global-statement

    with _POOL_LOCK:
        if _POOL is not None and _POOL_PID == os.getpid():
            return _POOL
        try:
            _POOL = _build_pool()
            _POOL_PID = os.getpid()
        except Exception as exc:  # pylint: disable=broad-except
            _POOL = None
            _POOL_PID = None
            raise JqFilterError(f"jq filter sandbox unavailable: {exc}") from exc
        return _POOL


@lru_cache(maxsize=256)
def _compile_jq_filter(jq_filter: str):
    """Compile and cache a jq program.

    Args:
        jq_filter: The jq filter source.

    Returns:
        The compiled jq program.
    """
    # pylint: disable=c-extension-no-member
    return jq.compile(jq_filter)


def _apply_filter(jq_filter: str, data_bytes: bytes) -> bytes:
    """Apply a jq filter to serialized JSON and return serialized output.

    This is the worker entry point. It must stay importable without pulling in
    the rest of the application, and it must not touch the database, the
    settings object, or the logger.

    Args:
        jq_filter: The jq filter source.
        data_bytes: The input document, serialized with orjson.

    Returns:
        The filter result, serialized with orjson.
    """
    data = orjson.loads(data_bytes)
    return orjson.dumps(_compile_jq_filter(jq_filter).input(data).all())


def _run_inprocess(jq_filter: str, data: Any) -> Any:
    """Apply a jq filter in the current process.

    Args:
        jq_filter: The jq filter source.
        data: The input document.

    Returns:
        The filter result.

    Raises:
        JqFilterError: If compilation or execution fails.
    """
    try:
        return orjson.loads(_apply_filter(jq_filter, orjson.dumps(data)))
    except Exception as exc:  # pylint: disable=broad-except
        raise JqFilterError(str(exc)) from exc


def run_jq_filter(jq_filter: str, data: Any) -> Any:
    """Apply a jq filter to a document under the configured execution mode.

    Args:
        jq_filter: The jq filter source.
        data: The input document. Must be JSON-serializable.

    Returns:
        The filter result as plain Python data.

    Raises:
        ValueError: If the filter uses a restricted jq built-in.
        JqFilterError: If compilation or execution fails, or the sandbox is unavailable.
        JqFilterBusy: If every worker is already running another filter.
        JqFilterTimeout: If the filter exceeds its wall-clock limit.
    """
    # Defence in depth. This module's contract is that the static gate has
    # already run, which is true today only because ``extract_using_jq`` is the
    # sole caller. Re-asserting it here keeps that contract true for any future
    # caller of this exported function. ValueError is left to propagate
    # unchanged so callers see the same exception the gate always raised.
    assert_safe_jq_filter(jq_filter)

    if not subprocess_mode_available():
        return _run_inprocess(jq_filter, data)

    pool = _ensure_pool()
    gate = getattr(pool, _GATE_ATTR)

    # ProcessPoolExecutor queues a task the instant every worker is busy, and
    # future.result(timeout=...) below cannot tell "still queued" apart from
    # "running past its budget" -- both look like a timeout. Reserving a slot
    # here first means a submission only ever reaches the pool when a worker
    # is actually free, so a timeout on it is never queueing pressure.
    if not gate.acquire(blocking=False):
        raise JqFilterBusy("jq filter sandbox has no free worker")

    try:
        try:
            future = pool.submit(_apply_filter, jq_filter, orjson.dumps(data))
            return orjson.loads(future.result(timeout=settings.jq_filter_timeout_seconds))
        except FutureTimeoutError as exc:
            logger.warning("jq filter exceeded %ss limit; killing worker", settings.jq_filter_timeout_seconds)
            _kill_pool_workers(pool)
            raise JqFilterTimeout("jq filter exceeded the execution time limit") from exc
        except BrokenProcessPool as exc:
            # A worker died without the timeout firing — the kernel OOM-killing a
            # filter that allocated without bound is the realistic trigger, and
            # nothing here bounds worker memory. The executor is permanently broken
            # afterwards: every later submit() raises. Drop it so the next call
            # rebuilds, instead of bricking filtering for this whole process.
            logger.warning("jq worker pool broke (worker died abnormally); discarding it so the next filter rebuilds")
            _discard_pool(pool)
            raise JqFilterError(str(exc)) from exc
        except JqFilterError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            raise JqFilterError(str(exc)) from exc
    finally:
        gate.release()
