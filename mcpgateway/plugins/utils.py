# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/utils.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Gateway-side plugin utilities.
"""

# Standard
import logging
from typing import Any, Dict, Optional

# Third-Party
from cpex.framework.extensions import Extensions, RequestExtension

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# G1: plugin result.metadata -> observability consumption
# ---------------------------------------------------------------------------
#
# S4 bounds (untrusted plugin output). These are deliberately conservative,
# defensible defaults -- not a contract mandated by any single plugin:
#   - Only scalar values (str, int, float, bool) are recorded as-is.
#   - A list[str] value (e.g. ["email", "ssn"]) is special-cased: joined into
#     a single comma-separated string (OTel span attributes don't nest), then
#     subject to the same string-length cap as any other string value.
#   - Any other type (dict, mixed/non-str list, None, etc.) is dropped.
#   - At most _MAX_PLUGIN_KEYS keys survive per plugin's metadata dict.
#   - At most _MAX_PLUGINS_PER_CALL plugin namespaces are processed per call
#     (result.metadata can in principle carry entries from every plugin that
#     ran in the hook chain).
#   - String values (including the joined list form) are truncated to
#     _MAX_STRING_LENGTH characters rather than dropped.
# On drop, only the key name and a short reason are logged -- never the value
# itself, since it may be malformed/oversized/adversarial plugin output.
_MAX_PLUGIN_KEYS = 32
_MAX_STRING_LENGTH = 256
_MAX_PLUGINS_PER_CALL = 16
_MAX_LIST_ITEMS = 32


def _truncate_str(value: str) -> str:
    """Truncate a string to the S4 bounded length.

    Args:
        value: The string to (possibly) truncate.

    Returns:
        The original string if within bounds, otherwise truncated to
        ``_MAX_STRING_LENGTH`` characters.
    """
    if len(value) <= _MAX_STRING_LENGTH:
        return value
    return value[:_MAX_STRING_LENGTH]


def _sanitize_plugin_metrics(plugin_name: str, raw_metrics: Any) -> Dict[str, Any]:
    """Validate and bound a single plugin's ``result.metadata[<plugin>]`` dict (S4).

    Untrusted plugin output: only scalar (``str``/``int``/``float``/``bool``) values
    survive as-is; a ``list[str]`` value is joined into a single bounded string;
    everything else is dropped. Key count and string length are capped. Dropped
    values are never logged -- only the key name and a short reason.

    Args:
        plugin_name: Namespacing key this metadata was reported under (e.g. "pii_filter").
        raw_metrics: The raw value at ``result.metadata[plugin_name]`` -- expected to be
            a ``dict[str, Any]`` but treated as untrusted (may be any type).

    Returns:
        A bounded dict containing only the validated/sanitized entries. Empty if
        ``raw_metrics`` is not a dict or nothing survives validation.
    """
    if not isinstance(raw_metrics, dict):
        logger.debug("Dropped plugin metadata for %r: value is not a dict", plugin_name)
        return {}

    sanitized: Dict[str, Any] = {}
    for key, value in raw_metrics.items():
        if not isinstance(key, str):
            logger.debug("Dropped a plugin metric key for %r: key is not a string", plugin_name)
            continue
        if len(sanitized) >= _MAX_PLUGIN_KEYS:
            logger.debug("Dropped plugin metric %r for %r: key limit exceeded", key, plugin_name)
            continue

        if isinstance(value, bool):
            sanitized[key] = value
        elif isinstance(value, (int, float)):
            sanitized[key] = value
        elif isinstance(value, str):
            sanitized[key] = _truncate_str(value)
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            joined = ",".join(value[:_MAX_LIST_ITEMS])
            sanitized[key] = _truncate_str(joined)
        else:
            logger.debug("Dropped plugin metric %r for %r: type not allowed", key, plugin_name)

    return sanitized


def record_plugin_metrics(trace_id: Optional[str], result_metadata: Optional[Dict[str, Any]]) -> None:
    """Consume ``PluginResult.metadata`` from a completed ``invoke_hook`` call into observability.

    For each ``result_metadata[<plugin>]`` entry, validates the value (S4 -- see module docstring
    for the exact bounds), then records the validated metrics:

      - Primary: attaches the validated key/value pairs as attributes on a small, dedicated,
        short-lived span (``plugin.metrics.<plugin_name>``) rooted at the active trace. This
        span exists purely to carry the attributes -- it does not represent real work -- because
        by the time this function runs, both the hook-chain span (owned by the CPEX framework)
        and any per-call-site span have typically already been closed, so there is no live span
        left to attach attributes to in place. All spans created for a single call to this
        function share one DB session (P-3 batching): ``start_span``/``end_span`` both accept an
        external ``obs_db`` session, so the whole primary path commits once.
      - Secondary (optional): for each *numeric* (``int``/``float``, excluding ``bool``) validated
        field, also records an ``ObservabilityMetric`` row via ``record_metric()`` so plugin
        counters (e.g. ``total_detections``) are queryable as metrics, not just span attributes.
        ``record_metric()`` does not accept an external session (unlike start_span/end_span), so
        each call opens its own independent short-lived session -- this mirrors the existing
        "issue #3883" independent-session pattern used throughout ``ObservabilityService`` and is
        an accepted, documented limitation of batching this secondary path.

    This is deliberately best-effort (L4): it must never raise into the request path. Any
    unexpected failure (missing trace, DB error, malformed plugin metadata, etc.) is logged at
    debug level and swallowed. No-op if ``trace_id`` or ``result_metadata`` is falsy/absent.

    Args:
        trace_id: The active trace identifier (typically ``current_trace_id.get()``). If falsy,
            this function is a no-op (there is nothing to correlate the metrics with).
        result_metadata: ``PluginResult.metadata`` as returned by ``invoke_hook()`` -- expected to
            be a ``dict`` mapping plugin name -> that plugin's own metadata dict. Falsy/non-dict
            values are a no-op.
    """
    if not trace_id or not result_metadata or not isinstance(result_metadata, dict):
        return

    try:
        # First-Party (deferred to avoid a circular import with mcpgateway.services.__init__,
        # mirroring build_request_extensions() above).
        from mcpgateway.db import SessionLocal  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.observability_service import ObservabilityService  # pylint: disable=import-outside-toplevel,cyclic-import

        plugin_items = list(result_metadata.items())
        if len(plugin_items) > _MAX_PLUGINS_PER_CALL:
            logger.debug("Dropping %d plugin metadata entries beyond the per-call limit", len(plugin_items) - _MAX_PLUGINS_PER_CALL)
            plugin_items = plugin_items[:_MAX_PLUGINS_PER_CALL]

        sanitized_by_plugin: Dict[str, Dict[str, Any]] = {}
        for plugin_name, raw_metrics in plugin_items:
            if not isinstance(plugin_name, str):
                logger.debug("Dropped a plugin metadata entry: plugin name is not a string")
                continue
            sanitized = _sanitize_plugin_metrics(plugin_name, raw_metrics)
            if sanitized:
                sanitized_by_plugin[plugin_name] = sanitized

        if not sanitized_by_plugin:
            return

        service = ObservabilityService()

        # Primary: span attributes. Batch all plugins' spans into a single DB session.
        db = None
        try:
            db = SessionLocal()
            for plugin_name, sanitized in sanitized_by_plugin.items():
                try:
                    span_id = service.start_span(
                        trace_id=trace_id,
                        name=f"plugin.metrics.{plugin_name}",
                        kind="internal",
                        resource_type="plugin",
                        resource_name=plugin_name,
                        attributes=sanitized,
                        commit=False,
                        obs_db=db,
                    )
                    service.end_span(span_id, status="ok", commit=False, obs_db=db)
                except Exception:  # noqa: BLE001 - one plugin's failure must not affect the others
                    logger.debug("Failed to record span attributes for plugin %r", plugin_name, exc_info=True)
            db.commit()
        except Exception:  # noqa: BLE001
            logger.debug("Failed to batch-commit plugin metric spans", exc_info=True)
            if db is not None:
                try:
                    db.rollback()
                except Exception:  # nosec B110
                    pass
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:  # nosec B110
                    pass

        # Secondary (optional): numeric fields also recorded as metrics.
        for plugin_name, sanitized in sanitized_by_plugin.items():
            for field_name, value in sanitized.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                try:
                    service.record_metric(
                        name=f"plugin.{plugin_name}.{field_name}",
                        value=float(value),
                        metric_type="gauge",
                        resource_type="plugin",
                        resource_id=plugin_name,
                        trace_id=trace_id,
                        attributes={"plugin": plugin_name, "field": field_name},
                    )
                except Exception:  # noqa: BLE001 - one metric's failure must not affect the others
                    logger.debug("Failed to record numeric metric %r for plugin %r", field_name, plugin_name, exc_info=True)
    except Exception:  # noqa: BLE001 - L4: best-effort, must never raise into the request path
        logger.debug("record_plugin_metrics failed", exc_info=True)


def build_request_extensions() -> Optional[Extensions]:
    """Build a CPEX ``Extensions`` object carrying the currently active trace context.

    Reads the active trace_id/span_id from the observability ContextVars
    (``current_trace_id`` / ``current_span_id`` in ``mcpgateway.services.observability_service``,
    set by ``ObservabilityMiddleware`` for the lifetime of the request) and wraps them in a
    CPEX ``RequestExtension`` so plugin hook invocations (``invoke_hook(..., extensions=...)``)
    can correlate their execution with the originating HTTP request's trace/span.

    This is deliberately best-effort: it must never raise into the request path. If no trace
    is currently active (e.g. observability is disabled, or the call happens outside of a
    traced request such as a background task or test), or if anything unexpected goes wrong
    while building the extensions, ``None`` is returned so callers can pass it straight through
    to ``invoke_hook(extensions=...)`` without any special-casing.

    Note: the import of ``mcpgateway.services.observability_service`` is deliberately deferred
    to inside this function (rather than at module level) to avoid a circular import: that
    service module's package (``mcpgateway.services``) eagerly imports ``tool_service`` /
    ``prompt_service`` in its ``__init__.py``, both of which import this helper.

    Returns:
        An ``Extensions`` instance with a populated ``request`` field when a trace_id is
        active, otherwise ``None``.
    """
    try:
        # First-Party (deferred to avoid a circular import with mcpgateway.services.__init__)
        from mcpgateway.services.observability_service import current_span_id, current_trace_id  # pylint: disable=import-outside-toplevel

        trace_id = current_trace_id.get()
        if not trace_id:
            return None
        span_id = current_span_id.get()
        return Extensions(request=RequestExtension(trace_id=trace_id, span_id=span_id))
    except Exception:  # noqa: BLE001 - best-effort helper, must never raise into the request path
        logger.debug("Failed to build CPEX request Extensions from active trace context", exc_info=True)
        return None


def apply_attribute_mapping(attributes: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """Apply attribute name mapping (renaming) to a dictionary of attributes.

    Args:
        attributes: Dictionary of attributes to rename.
        mapping: Dictionary mapping old attribute names to new names.

    Returns:
        New dictionary with renamed attributes.

    Example:
        >>> attrs = {"tool.name": "weather", "tool.version": "1.0"}
        >>> mapping = {"tool.name": "controls.artifact.name"}
        >>> apply_attribute_mapping(attrs, mapping)
        {'controls.artifact.name': 'weather', 'tool.version': '1.0'}
    """
    if not mapping:
        return dict(attributes)

    renamed_attributes = {}
    for old_name, value in attributes.items():
        new_name = mapping.get(old_name, old_name)
        renamed_attributes[new_name] = value

    logger.debug("Applied %d attribute name mappings", len(mapping))
    return renamed_attributes
