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
from functools import lru_cache
import logging
import os
import sys
from typing import Any

# Third-Party
import jq
import orjson

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.jq_guard import assert_safe_jq_filter
from mcpgateway.utils.sandbox_pool import SandboxBusy, SandboxError, SandboxPool, SandboxTimeout

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


# The pool reads its worker count and timeout through callables so every call
# sees the live settings value, which tests monkeypatch after import.
_SANDBOX = SandboxPool(
    name="jq filter",
    workers_fn=lambda: settings.jq_filter_workers,
    timeout_fn=lambda: settings.jq_filter_timeout_seconds,
    initializer=_worker_init,
)


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
    global _FALLBACK_WARNED  # pylint: disable=global-statement

    if not subprocess_mode_available():
        if not _FALLBACK_WARNED:
            logger.warning(
                "jq filter sandbox is disabled (execution=%s, platform=%s). Tool jsonpath_filter programs will run in-process with no environment scrub and no time limit. This is unsafe outside development.",
                settings.jq_filter_execution,
                sys.platform,
            )
            _FALLBACK_WARNED = True
        return

    _SANDBOX.start()


def shutdown_jq_pool() -> None:
    """Tear down the jq worker pool for this process.

    Kills the pool's worker processes rather than only cancelling queued work.
    ``ProcessPoolExecutor.shutdown(wait=False, cancel_futures=True)`` drops
    *pending* futures but cannot stop a worker already mid-filter, and the
    executor's own ``atexit`` hook then blocks interpreter exit trying to join a
    worker that is running a non-terminating jq program.
    """
    _SANDBOX.shutdown()


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

    try:
        return orjson.loads(_SANDBOX.submit(_apply_filter, jq_filter, orjson.dumps(data)))
    except SandboxTimeout as exc:
        raise JqFilterTimeout("jq filter exceeded the execution time limit") from exc
    except SandboxBusy as exc:
        raise JqFilterBusy("jq filter sandbox has no free worker") from exc
    except SandboxError as exc:
        raise JqFilterError(str(exc)) from exc
