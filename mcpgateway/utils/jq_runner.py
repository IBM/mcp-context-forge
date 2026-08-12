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

The pool is added in the next commit; this module currently executes in-process.
"""

# Future
from __future__ import annotations

# Standard
from functools import lru_cache
import logging
from typing import Any

# Third-Party
import jq
import orjson

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)

__all__ = ["JqFilterError", "JqFilterTimeout", "run_jq_filter"]


class JqFilterError(Exception):
    """Raised when a jq filter cannot be compiled or executed."""


class JqFilterTimeout(JqFilterError):
    """Raised when a jq filter exceeds its wall-clock limit."""


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

    Task 5 adds the sandboxed pool behind this same signature. Until then, every
    mode runs in-process — there is exactly one code path, not a branch that
    happens to agree with itself.

    Args:
        jq_filter: The jq filter source.
        data: The input document. Must be JSON-serializable.

    Returns:
        The filter result as plain Python data.

    Raises:
        JqFilterError: If compilation or execution fails.
        JqFilterTimeout: If the filter exceeds its wall-clock limit.
    """
    return _run_inprocess(jq_filter, data)
