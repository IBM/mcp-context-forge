# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/utils.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Gateway-side plugin utilities.
"""

# Standard
import itertools
import logging
import re
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
#   - plugin_name and metric keys must match _IDENTIFIER_RE (bounded length,
#     restricted charset) before they're allowed to flow into DB span/metric
#     names, resource ids, or OTel span/attribute names -- these are
#     plugin-controlled and otherwise unvalidated.
#   - Only scalar values (str, int, float, bool) are recorded as-is; strings
#     must additionally be within _MAX_STRING_LENGTH and match
#     _SAFE_STRING_VALUE_RE (a low-cardinality, no-free-text charset).
#     Overlong values are rejected outright, not truncated -- truncation alone
#     would bound size but not the sensitivity of what's exported (e.g. a
#     truncated secret/token fragment is still a secret/token fragment).
#   - A list[str] value (e.g. ["email", "ssn"]) is special-cased: joined into
#     a single comma-separated string (OTel span attributes don't nest), then
#     subject to the same string-value validation as any other string value.
#   - Any other type (dict, mixed/non-str list, None, etc.) is dropped.
#   - At most _MAX_PLUGIN_KEYS keys survive per plugin's metadata dict, and
#     only the first _MAX_PLUGIN_KEYS items of the raw dict are ever inspected
#     (via itertools.islice) -- not just accepted -- so a huge untrusted dict,
#     even one front-loaded with invalid keys, can't force a full scan.
#   - At most _MAX_PLUGINS_PER_CALL plugin namespaces are processed per call
#     (result.metadata can in principle carry entries from every plugin that
#     ran in the hook chain); the cap is applied before the full item list is
#     materialized.
#   - list[str] values are only checked for str-ness and per-item length
#     within the first _MAX_LIST_ITEMS items, so an oversized untrusted list
#     can't force a full scan or an unbounded join before it's bounded.
# On drop, only the key name and a short reason are logged -- never the value
# itself, since it may be malformed/oversized/adversarial plugin output.
_MAX_PLUGIN_KEYS = 32
_MAX_STRING_LENGTH = 64
_MAX_PLUGINS_PER_CALL = 16
_MAX_LIST_ITEMS = 32

# Identifier contract for plugin_name / metric field names: these flow into DB
# span/metric names, resource ids, and OTel span/attribute names, so they're
# restricted to a short, safe charset rather than trusted as-is.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

# Low-cardinality value contract for string metadata values: truncation alone
# bounds size, not sensitivity, so free text (arbitrary PII, spaces, quotes,
# etc.) is rejected outright rather than truncated. This intentionally only
# admits short enum/status/type-name-like tokens.
_SAFE_STRING_VALUE_RE = re.compile(r"^[A-Za-z0-9_.,:=/-]*$")


def _is_valid_identifier(name: Any) -> bool:
    """Check whether a plugin name or metric field name is safe to use as an identifier.

    Args:
        name: Candidate identifier (plugin name or metric field name); treated as untrusted.

    Returns:
        True if ``name`` is a string matching the bounded, restricted-charset
        identifier contract; False otherwise.
    """
    return isinstance(name, str) and bool(_IDENTIFIER_RE.match(name))


def _validate_string_value(value: str) -> Optional[str]:
    """Validate a single string metadata value (S4).

    Args:
        value: Candidate string value.

    Returns:
        ``value`` unchanged if it is within ``_MAX_STRING_LENGTH`` and matches
        the low-cardinality safe-value charset, otherwise ``None`` (reject).
        Overlong values are rejected outright rather than truncated -- a
        truncated secret/token/hash fragment is still sensitive, so length is
        checked before the charset is even considered.
    """
    if len(value) > _MAX_STRING_LENGTH:
        return None
    if not _SAFE_STRING_VALUE_RE.match(value):
        return None
    return value


def _sanitize_plugin_metrics(plugin_name: str, raw_metrics: Any) -> Dict[str, Any]:
    """Validate and bound a single plugin's ``result.metadata[<plugin>]`` dict (S4).

    Untrusted plugin output: only scalar (``str``/``int``/``float``/``bool``) values
    survive as-is; a ``list[str]`` value is joined into a single bounded string;
    everything else is dropped. Key names, key count, and string values are all
    validated/capped. Dropped values are never logged -- only the key name and a
    short reason.

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
    # Bound the scan itself (not just the accepted count): only the first
    # _MAX_PLUGIN_KEYS items of the raw dict are ever inspected, so a dict
    # front-loaded with invalid/dropped keys can't force an unbounded scan.
    for key, value in itertools.islice(raw_metrics.items(), _MAX_PLUGIN_KEYS):
        if not _is_valid_identifier(key):
            logger.debug("Dropped a plugin metric key for %r: key is not a valid identifier", plugin_name)
            continue

        if isinstance(value, bool):
            sanitized[key] = value
        elif isinstance(value, (int, float)):
            sanitized[key] = value
        elif isinstance(value, str):
            validated = _validate_string_value(value)
            if validated is not None:
                sanitized[key] = validated
            else:
                logger.debug("Dropped plugin metric %r for %r: string value not in safe low-cardinality contract", key, plugin_name)
        elif isinstance(value, list):
            prefix = value[:_MAX_LIST_ITEMS]
            # Reject any oversized item before joining, so the join itself
            # (and the subsequent regex match) is always bounded by
            # _MAX_LIST_ITEMS * _MAX_STRING_LENGTH, not by attacker input.
            if all(isinstance(item, str) and len(item) <= _MAX_STRING_LENGTH for item in prefix):
                joined = ",".join(prefix)
                validated = _validate_string_value(joined)
                if validated is not None:
                    sanitized[key] = validated
                else:
                    logger.debug("Dropped plugin metric %r for %r: joined list value not in safe low-cardinality contract", key, plugin_name)
            else:
                logger.debug("Dropped plugin metric %r for %r: list contains non-string or oversized items", key, plugin_name)
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
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel
        from mcpgateway.db import SessionLocal  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.observability_service import ObservabilityService  # pylint: disable=import-outside-toplevel,cyclic-import

        # Bounded iteration: cap applied via islice over the dict's own view rather than
        # materializing a full list of every entry first (result_metadata is untrusted).
        if len(result_metadata) > _MAX_PLUGINS_PER_CALL:
            logger.debug("Dropping %d plugin metadata entries beyond the per-call limit", len(result_metadata) - _MAX_PLUGINS_PER_CALL)
        plugin_items = itertools.islice(result_metadata.items(), _MAX_PLUGINS_PER_CALL)

        sanitized_by_plugin: Dict[str, Dict[str, Any]] = {}
        for plugin_name, raw_metrics in plugin_items:
            if not _is_valid_identifier(plugin_name):
                logger.debug("Dropped a plugin metadata entry: plugin name is not a valid identifier")
                continue
            sanitized = _sanitize_plugin_metrics(plugin_name, raw_metrics)
            if sanitized:
                sanitized_by_plugin[plugin_name] = sanitized

        if not sanitized_by_plugin:
            return

        service = ObservabilityService()

        # Primary: span attributes. Batch all plugins' spans into a single DB session.
        # Independently toggleable from the numeric-metric-row and OTel export sinks below
        # (DB growth, numeric-row amplification, and external-collector export are separate
        # operational trade-offs).
        if settings.plugin_metrics_db_spans_enabled:
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

        # Secondary (optional): numeric fields also recorded as metrics. Each write opens its
        # own independent session (record_metric() doesn't accept an external session), so this
        # is additionally capped per-call (across all plugins) to bound DB write amplification,
        # and can be disabled entirely via settings.
        if settings.plugin_metrics_db_numeric_rows_enabled:
            numeric_rows_written = 0
            max_numeric = settings.plugin_metrics_max_numeric_per_call
            for plugin_name, sanitized in sanitized_by_plugin.items():
                if numeric_rows_written >= max_numeric:
                    break
                for field_name, value in sanitized.items():
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        continue
                    if numeric_rows_written >= max_numeric:
                        logger.debug("Dropping remaining numeric plugin metrics beyond the per-call cap of %d", max_numeric)
                        break
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
                        numeric_rows_written += 1
                    except Exception:  # noqa: BLE001 - one metric's failure must not affect the others
                        logger.debug("Failed to record numeric metric %r for plugin %r", field_name, plugin_name, exc_info=True)

        # G2: optional OTel-SDK export sink. Gateway is the export authority; this
        # re-emits the ALREADY-sanitized metrics through the gateway's existing OTel
        # exporter. No-op when OTel tracing is unconfigured (create_span -> nullcontext),
        # and also no-op when there's no active OTel context, so a configured-but-unused
        # tracer doesn't turn these into orphan root spans.
        try:
            from mcpgateway.observability import create_span, otel_context_active, otel_tracing_enabled  # pylint: disable=import-outside-toplevel

            if otel_tracing_enabled() and otel_context_active():
                for plugin_name, sanitized in sanitized_by_plugin.items():
                    try:
                        with create_span(f"plugin.metrics.{plugin_name}", dict(sanitized)):
                            pass  # attributes set on enter; span exported on exit
                    except Exception:  # noqa: BLE001 - one plugin's export must not affect others
                        logger.debug("Failed to export OTel span for plugin %r", plugin_name, exc_info=True)
        except Exception:  # noqa: BLE001 - L4: export is best-effort, never raises into the request path
            logger.debug("OTel plugin-metrics export sink failed", exc_info=True)
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
