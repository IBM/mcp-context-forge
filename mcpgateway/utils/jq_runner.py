# -*- coding: utf-8 -*-
"""Sandboxed execution of user-supplied jq filters.

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

logger = logging.getLogger(__name__)

__all__ = ["JqFilterError", "JqFilterTimeout", "run_jq_filter", "start_jq_pool", "shutdown_jq_pool", "subprocess_mode_available"]


class JqFilterError(Exception):
    """Raised when a jq filter cannot be compiled or executed."""


class JqFilterTimeout(JqFilterError):
    """Raised when a jq filter exceeds its wall-clock limit."""


_POOL: Optional[ProcessPoolExecutor] = None
_POOL_PID: Optional[int] = None
_POOL_LOCK = threading.Lock()
_FALLBACK_WARNED = False


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
        The new executor.
    """
    return ProcessPoolExecutor(
        max_workers=settings.jq_filter_workers,
        mp_context=multiprocessing.get_context("fork"),
        initializer=_worker_init,
    )


def start_jq_pool() -> None:
    """Create the jq worker pool for this process.

    Call from application startup, after any fork performed by the server, so
    that each gateway worker owns its own pool.
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
            pool.submit(_apply_filter, ".", b"null").result(timeout=settings.jq_filter_timeout_seconds)
        except Exception:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        _POOL = pool
        _POOL_PID = os.getpid()
        logger.info("jq filter sandbox started with %s worker(s)", settings.jq_filter_workers)


def shutdown_jq_pool() -> None:
    """Tear down the jq worker pool for this process."""
    global _POOL, _POOL_PID  # pylint: disable=global-statement

    with _POOL_LOCK:
        if _POOL is None:
            return
        if _POOL_PID != os.getpid():
            # Inherited from a parent via fork; this process never owned these
            # workers, so drop the reference without touching the parent's pool.
            _POOL = None
            _POOL_PID = None
            return
        _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = None
        _POOL_PID = None


def _kill_pool_workers() -> None:
    """Kill every worker in the current pool and drop it.

    ``ProcessPoolExecutor`` cannot cancel a task that is already running, and
    the public ``terminate_workers``/``kill_workers`` methods are Python 3.14
    while this project targets 3.12. The private ``_processes`` mapping is the
    only route; it is read defensively and pinned by a test.
    """
    global _POOL, _POOL_PID  # pylint: disable=global-statement

    pool = _POOL
    if pool is None:
        return
    with _POOL_LOCK:
        if _POOL is not pool:
            # Another thread already rebuilt or dropped the pool; leave it alone.
            return
        if _POOL_PID != os.getpid():
            # Inherited from a parent via fork; these Process objects reference
            # the parent's workers. Never kill processes we don't own.
            _POOL = None
            _POOL_PID = None
            return
        for process in list(getattr(pool, "_processes", {}).values()):
            try:
                process.kill()
            except Exception:  # pylint: disable=broad-except
                logger.warning("Failed to kill a jq worker process", exc_info=True)
        pool.shutdown(wait=False, cancel_futures=True)
        _POOL = None
        _POOL_PID = None


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
        JqFilterError: If compilation or execution fails, or the sandbox is unavailable.
        JqFilterTimeout: If the filter exceeds its wall-clock limit.
    """
    if not subprocess_mode_available():
        return _run_inprocess(jq_filter, data)

    pool = _ensure_pool()
    try:
        future = pool.submit(_apply_filter, jq_filter, orjson.dumps(data))
        return orjson.loads(future.result(timeout=settings.jq_filter_timeout_seconds))
    except FutureTimeoutError as exc:
        logger.warning("jq filter exceeded %ss limit; killing worker", settings.jq_filter_timeout_seconds)
        _kill_pool_workers()
        raise JqFilterTimeout("jq filter exceeded the execution time limit") from exc
    except JqFilterError:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise JqFilterError(str(exc)) from exc
