# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/cpex_compat.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

CPEX version compatibility helpers.

Feature-detects ``ControlExecutionRecord`` availability rather than pinning
a hard import, so the gateway degrades gracefully against older CPEX builds
that do not yet expose execution records.

The minimum supported CPEX version for control-execution telemetry is 0.1.2.
``execution_records_supported()`` is the single guard that all consumption
sites must check before accessing ``PluginResult.executions``.

Examples:
    >>> # When cpex 0.1.2+ is installed:
    >>> from mcpgateway.plugins.cpex_compat import execution_records_supported, get_executions
    >>> isinstance(execution_records_supported(), bool)
    True
    >>> get_executions(None)
    []
"""

# Standard
from typing import Any, List, Optional

_EXECUTION_RECORDS_SUPPORTED: Optional[bool] = None


def execution_records_supported() -> bool:
    """Return True if the installed CPEX version exposes ControlExecutionRecord.

    Result is cached after the first call — config is frozen after startup.
    Safe to call from any thread; the cache write is idempotent.

    Returns:
        True when ``cpex.framework.ControlExecutionRecord`` can be imported,
        False otherwise (older CPEX build or CPEX not installed).

    Examples:
        >>> isinstance(execution_records_supported(), bool)
        True
    """
    global _EXECUTION_RECORDS_SUPPORTED  # pylint: disable=global-statement
    if _EXECUTION_RECORDS_SUPPORTED is None:
        try:
            from cpex.framework import ControlExecutionRecord, ControlExecutionStatus  # noqa: F401  # pylint: disable=import-outside-toplevel
            _EXECUTION_RECORDS_SUPPORTED = True
        except ImportError:
            _EXECUTION_RECORDS_SUPPORTED = False
    return _EXECUTION_RECORDS_SUPPORTED


def get_executions(result: Any) -> List[Any]:
    """Safely extract the executions list from a PluginResult.

    Returns an empty list if the field is absent (older CPEX), the result is
    None, or any unexpected error occurs.  Never raises.

    Args:
        result: PluginResult returned by ``invoke_hook()`` (may be None).

    Returns:
        A new list containing the ``ControlExecutionRecord`` entries, or ``[]``.

    Examples:
        >>> get_executions(None)
        []
    """
    if result is None:
        return []
    try:
        return list(getattr(result, "executions", None) or [])
    except Exception:  # noqa: BLE001
        return []
