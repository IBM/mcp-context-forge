# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/control_telemetry.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Accumulator and emitter for CPEX control-execution telemetry.

Mirrors the structure of ``record_plugin_metrics()`` in ``plugins/utils.py``
but consumes **trusted** ``ControlExecutionRecord`` fields rather than
untrusted plugin metadata.  All bounds and sanitization follow the same S4
principles.

Architecture
------------
One ``ControlTelemetryAccumulator`` is created per ``invoke_tool()`` call,
collects records from both ``tool_pre_invoke`` and ``tool_post_invoke`` hooks,
and is then flushed via ``record_control_telemetry()`` into two sinks:

  - Internal DB: a ``cpex.control.summary`` span + one ``cpex.control.result``
    child span per record, all batched in a single DB session.
  - OTel SDK: equivalent child spans under the active trace context (no-op
    when OTel is disabled or no context is active).

Feature gate
------------
The feature is a no-op when:

  - ``CPEX_CONTROL_TELEMETRY_ENABLED=false`` (config setting), or
  - the installed CPEX version does not expose ``ControlExecutionRecord``
    (``execution_records_supported()`` returns False).

Existing ``tool.invoke`` spans, ``plugin.metrics.*`` spans, and CPEX
violation/on_error handling are untouched.
"""

# Standard
import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

# First-Party
from mcpgateway.plugins.cpex_compat import execution_records_supported, get_executions
from mcpgateway.plugins.utils import _IDENTIFIER_RE  # re-use the same identifier validator

logger = logging.getLogger(__name__)

# ── Bounds (mirrors _MAX_PLUGIN_KEYS / _MAX_PLUGINS_PER_CALL in utils.py) ──────
_MAX_RECORDS_PER_HOOK = 64  # max ControlExecutionRecords consumed per invoke_hook call
_MAX_RECORDS_PER_CALL = 128  # cap across pre + post combined
_MAX_REASON_LEN = 256  # CPEX already bounds this; enforce again defensively
_MAX_ERROR_CODE_LEN = 256
_MAX_CONFIG_KEYS = 64


# ---------------------------------------------------------------------------
# ControlTelemetryAccumulator
# ---------------------------------------------------------------------------


@dataclass
class ControlTelemetryAccumulator:
    """Invocation-local accumulator for CPEX execution records.

    One instance per ``invoke_tool()`` call.  Never shared across requests.
    Collect pre-hook records first, then post-hook records.

    Usage::

        acc = ControlTelemetryAccumulator()
        ...
        pre_result, _ = await plugin_manager.invoke_hook(TOOL_PRE_INVOKE, ...)
        acc.add(pre_result, hook="pre")
        ...
        post_result, _ = await plugin_manager.invoke_hook(TOOL_POST_INVOKE, ...)
        acc.add(post_result, hook="post")
        ...
        record_control_telemetry(trace_id, acc, tool_name=name, agent_id=...)

    Examples:
        >>> acc = ControlTelemetryAccumulator()
        >>> acc.records
        []
        >>> acc.effective_allowed
        True
    """

    _records: list = field(default_factory=list)
    _pre_denied: bool = False
    _post_denied: bool = False
    _truncated: int = 0  # records dropped due to per-call cap OR per-hook cap
    _export_cap_dropped: int = 0  # records dropped at emit time by the per-invocation export cap

    def add(self, result: Any, *, hook: str) -> None:
        """Consume executions from one ``invoke_hook`` result.

        Args:
            result: ``PluginResult`` from ``invoke_hook`` (may be None on early exit).
            hook: ``"pre"`` or ``"post"`` — enforcement point tag for each record.
        """
        if not execution_records_supported():
            return

        records = get_executions(result)
        hook_count = 0
        for rec in records:
            if hook_count >= _MAX_RECORDS_PER_HOOK:
                # Per-hook cap exceeded — count these as truncated and stop.
                self._truncated += 1
                continue
            hook_count += 1
            if len(self._records) >= _MAX_RECORDS_PER_CALL:
                self._truncated += 1
                continue
            self._records.append((hook, rec))

        # Track denial at each phase independently
        if result is not None and not getattr(result, "continue_processing", True):
            if hook == "pre":
                self._pre_denied = True
            else:
                self._post_denied = True

    def mark_denied(self, *, hook: str) -> None:
        """Explicitly mark a denial when ``violations_as_exceptions=True`` causes
        ``invoke_hook()`` to raise before returning, so ``add()`` is never called.

        Call this from the ``except PluginViolationError`` handler immediately
        after catching the exception and before re-raising.

        Args:
            hook: ``"pre"`` or ``"post"`` — which enforcement point was denied.

        Examples:
            >>> acc = ControlTelemetryAccumulator()
            >>> acc.mark_denied(hook="pre")
            >>> acc.pre_denied
            True
            >>> acc.effective_allowed
            False
        """
        if hook == "pre":
            self._pre_denied = True
        else:
            self._post_denied = True

    @property
    def records(self) -> list:
        """All accumulated ``(hook, ControlExecutionRecord)`` pairs.

        Returns:
            A new list of ``(hook_str, record)`` tuples.
        """
        return list(self._records)

    @property
    def pre_denied(self) -> bool:
        """True when the pre-invoke hook chain produced a denial.

        Returns:
            True if pre-hook denied; False otherwise.
        """
        return self._pre_denied

    @property
    def post_denied(self) -> bool:
        """True when the post-invoke hook chain produced a denial.

        Returns:
            True if post-hook denied; False otherwise.
        """
        return self._post_denied

    @property
    def truncated(self) -> int:
        """Total records dropped across all three truncation tiers:

        - Tier 1: per-hook cap (``_MAX_RECORDS_PER_HOOK``)
        - Tier 2: per-call accumulation cap (``_MAX_RECORDS_PER_CALL``)
        - Tier 3: per-invocation export cap (``CPEX_CONTROL_TELEMETRY_MAX_RESULTS``)

        Tier-3 drops are recorded by ``mark_export_cap_dropped()`` after the
        export cap is applied in ``record_control_telemetry()``.

        Returns:
            Total count of dropped records (0 when no overflow on any tier).
        """
        return self._truncated + self._export_cap_dropped

    def mark_export_cap_dropped(self, count: int) -> None:
        """Record the number of records silently dropped by the export cap.

        Called once per ``record_control_telemetry()`` invocation, after
        ``_get_max_results()`` is applied, so the ``cpex.control.truncated``
        summary attribute reflects all three truncation tiers.

        Args:
            count: Number of records that exceeded ``CPEX_CONTROL_TELEMETRY_MAX_RESULTS``
                   and were not exported to any sink.

        Examples:
            >>> acc = ControlTelemetryAccumulator()
            >>> acc.mark_export_cap_dropped(5)
            >>> acc.truncated
            5
        """
        if count > 0:
            self._export_cap_dropped += count

    @property
    def effective_allowed(self) -> bool:
        """True only if neither the pre nor post hook chain produced a denial.

        Returns:
            True when the overall control chain allowed the invocation.
        """
        return not self._pre_denied and not self._post_denied

    def aggregate(self) -> dict:
        """Compute aggregate scalar attributes from all accumulated records.

        Returns a ``dict`` of ``cpex.control.*`` attributes safe for span
        attachment.  Only uses trusted ``ControlExecutionRecord`` fields —
        never plugin metadata.

        Count semantics:

        - ``invocation_count``: controls that *actually ran* — status in
          ``{completed, error, timeout}``.  Disabled, skipped, and cancelled
          records are excluded (matches CPEX semantics).
        - ``records_received``: total records accumulated before any export
          cap is applied.  Includes disabled/skipped/cancelled.
        - ``results_count``: records that will actually be exported to sinks,
          i.e. ``min(records_received, CPEX_CONTROL_TELEMETRY_MAX_RESULTS)``.
          Downstream operators can derive ``records_dropped = records_received
          - results_count + truncated`` to understand total loss.

        Returns:
            Dictionary of aggregate control telemetry attributes.
        """
        invocation_count = 0
        matched_count = 0
        applied_count = 0
        total_duration_ns = 0
        error_count = 0
        timeout_count = 0

        # Statuses that represent controls that actually ran (exclude disabled/skipped/cancelled).
        _ACTIVE_STATUSES = {"completed", "error", "timeout"}

        for _hook, rec in self._records:
            try:
                status = str(getattr(rec, "status", ""))
                if status in _ACTIVE_STATUSES:
                    invocation_count += 1
                if getattr(rec, "matched", None) is True:
                    matched_count += 1
                if getattr(rec, "applied", False):
                    applied_count += 1
                total_duration_ns += int(getattr(rec, "duration_ns", 0))
                if status == "error":
                    error_count += 1
                elif status == "timeout":
                    timeout_count += 1
            except Exception:  # noqa: BLE001
                logger.debug("Failed to aggregate one ControlExecutionRecord", exc_info=True)

        records_received = len(self._records)
        # results_count = records exported after the per-invocation cap (not raw accumulated count).
        results_count = min(records_received, _get_max_results())

        return {
            "cpex.control.invocation_count": invocation_count,
            "cpex.control.matched_count": matched_count,
            "cpex.control.applied_count": applied_count,
            "cpex.control.records_received": records_received,
            "cpex.control.results_count": results_count,
            "cpex.control.duration_ns": total_duration_ns,  # nanoseconds — OTel unit suffix convention
            "cpex.control.result.allowed": self.effective_allowed,
            "cpex.control.error_count": error_count,
            "cpex.control.timeout_count": timeout_count,
        }


# ---------------------------------------------------------------------------
# record_control_telemetry — public entry point
# ---------------------------------------------------------------------------


def record_control_telemetry(
    trace_id: Optional[str],
    accumulator: "ControlTelemetryAccumulator",
    *,
    tool_name: str = "",
    agent_id: str = "",
    binding_name: str = "",
) -> None:
    """Emit CPEX control-execution telemetry for one tool invocation.

    Best-effort (L4): never raises into the request path.
    Mirrors ``record_plugin_metrics()`` — same sink ordering, same session pattern.

    Args:
        trace_id: Active trace ID from ``current_trace_id.get()``.
        accumulator: Populated ``ControlTelemetryAccumulator`` for this invocation.
        tool_name: Tool name from the CF side (trusted, not from plugin output).
        agent_id: Agent/user identifier from the CF side (trusted).
        binding_name: Gateway/server binding name (trusted).
    """
    if not trace_id:
        return
    if not execution_records_supported():
        return
    if not accumulator.records and not accumulator.pre_denied and not accumulator.post_denied:
        # Nothing ran — no-op, don't emit empty spans
        return

    try:
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

        if not getattr(settings, "cpex_control_telemetry_enabled", True):
            return

        from mcpgateway.services.observability_service import ObservabilityService  # pylint: disable=import-outside-toplevel,cyclic-import

        # Build aggregate attributes — all from trusted CF + CPEX sources
        aggregate = accumulator.aggregate()
        aggregate.update(
            {
                "cpex.control.type": "tool",
                "cpex.control.tool.name": _safe_str(tool_name, 128),
                "cpex.control.agent.id": _safe_str(agent_id, 128),
                "cpex.control.binding.name": _safe_str(binding_name, 128),
                "cpex.control.enforcement_point": _enforcement_point(accumulator),
            }
        )
        # Compute and record export-cap (tier-3) drops before building the summary span.
        # records_received is the count before any export cap; results_count is the cap-bounded
        # export count.  The difference is exactly the number of records the islice will skip.
        records_received = aggregate.get("cpex.control.records_received", 0)
        max_results = _get_max_results()
        export_cap_dropped = max(0, records_received - max_results)
        if export_cap_dropped:
            accumulator.mark_export_cap_dropped(export_cap_dropped)

        # cpex.control.truncated now covers all three tiers (hook cap + call cap + export cap).
        if accumulator.truncated:
            aggregate["cpex.control.truncated"] = accumulator.truncated

        # ── Optional: flattened cpex.control.results.<name>.* attributes ─────
        # Off by default (CPEX_CONTROL_TELEMETRY_FLATTEN_RESULTS=false).
        # Only emit when downstream tooling requires dynamic key names.
        # The fixed-schema child spans remain the internal source of truth.
        if getattr(settings, "cpex_control_telemetry_flatten_results", False):
            flattened = _build_flattened_attributes(accumulator, _get_max_results())
            aggregate.update(flattened)

        service = ObservabilityService()

        # ── Sink 1: internal DB — summary span + per-control child spans ──────
        if getattr(settings, "cpex_control_telemetry_db_enabled", True):
            _emit_db_spans(service, trace_id, aggregate, accumulator)

        # ── Sink 2: OTel SDK — child spans under the active trace context ─────
        _emit_otel_spans(aggregate, accumulator)

    except Exception:  # noqa: BLE001  — L4: best-effort, never raises
        logger.debug("record_control_telemetry failed", exc_info=True)


# ---------------------------------------------------------------------------
# DB sink helper
# ---------------------------------------------------------------------------


def _emit_db_spans(
    service: Any,
    trace_id: str,
    aggregate: dict,
    accumulator: "ControlTelemetryAccumulator",
) -> None:
    """Write summary + per-control DB spans in a single session.

    Args:
        service: ObservabilityService instance.
        trace_id: Active trace identifier.
        aggregate: Pre-built aggregate attribute dict.
        accumulator: Source of per-control records.
    """
    from mcpgateway.db import SessionLocal  # pylint: disable=import-outside-toplevel

    db = None
    try:
        db = SessionLocal()

        # Summary span
        summary_id = service.start_span(
            trace_id=trace_id,
            name="cpex.control.summary",
            kind="internal",
            resource_type="control",
            resource_name="summary",
            attributes=aggregate,
            commit=False,
            obs_db=db,
        )
        service.end_span(summary_id, status="ok", commit=False, obs_db=db)

        # Per-control child spans — linked to summary via parent_span_id so trace
        # UIs render them nested under the summary rather than as siblings.
        max_results = _get_max_results()
        for hook, rec in itertools.islice(accumulator.records, max_results):
            attrs = _per_control_attributes(hook, rec)
            if not attrs:
                continue
            span_id = service.start_span(
                trace_id=trace_id,
                name="cpex.control.result",
                parent_span_id=summary_id,
                kind="internal",
                resource_type="control",
                resource_name=attrs.get("cpex.control.name", ""),
                attributes=attrs,
                commit=False,
                obs_db=db,
            )
            service.end_span(span_id, status="ok", commit=False, obs_db=db)

        db.commit()
    except Exception:  # noqa: BLE001
        logger.debug("Failed to write control telemetry DB spans", exc_info=True)
        if db:
            try:
                db.rollback()
            except Exception:  # nosec B110
                pass
    finally:
        if db:
            try:
                db.close()
            except Exception:  # nosec B110
                pass


# ---------------------------------------------------------------------------
# OTel sink helper
# ---------------------------------------------------------------------------


def _emit_otel_spans(aggregate: dict, accumulator: "ControlTelemetryAccumulator") -> None:
    """Emit control telemetry through the OTel SDK when a trace context is active.

    Args:
        aggregate: Pre-built aggregate attribute dict.
        accumulator: Source of per-control records.
    """
    try:
        from mcpgateway.observability import (  # pylint: disable=import-outside-toplevel
            create_span,
            otel_context_active,
            otel_tracing_enabled,
        )

        if not otel_tracing_enabled() or not otel_context_active():
            return

        with create_span("cpex.control.summary", dict(aggregate)):
            max_results = _get_max_results()
            for hook, rec in itertools.islice(accumulator.records, max_results):
                attrs = _per_control_attributes(hook, rec)
                if attrs:
                    with create_span("cpex.control.result", attrs):
                        pass
    except Exception:  # noqa: BLE001
        logger.debug("OTel control telemetry export failed", exc_info=True)


# ---------------------------------------------------------------------------
# Per-control attribute builder
# ---------------------------------------------------------------------------


def _per_control_attributes(hook: str, rec: Any) -> dict:
    """Build the fixed-schema attribute dict for one ControlExecutionRecord.

    Only uses trusted CPEX record fields.  Never accesses plugin metadata.
    Returns empty dict on any error so callers can skip cleanly.

    Args:
        hook: Enforcement-point tag (``"pre"`` or ``"post"``).
        rec: A ``ControlExecutionRecord`` instance.

    Returns:
        Attribute dict or empty dict on error.
    """
    try:
        attrs: dict = {
            # Identity fields — from trusted CPEX framework PluginRef config
            "cpex.control.name": _safe_str(str(rec.plugin_name), 64),
            "cpex.control.plugin_id": _safe_str(str(rec.plugin_id), 64),
            "cpex.control.plugin_kind": _safe_str(str(rec.plugin_kind), 32),
            "cpex.control.hook_name": _safe_str(str(rec.hook_name), 64),
            "cpex.control.mode": _safe_str(str(rec.mode), 32),
            # Execution outcome fields
            "cpex.control.status": _safe_str(str(rec.status), 32),
            "cpex.control.enforcement_point": hook,
            "cpex.control.result.allowed": bool(rec.effective_allow),
            "cpex.control.duration_ns": int(rec.duration_ns),  # nanoseconds — OTel unit suffix convention
            "cpex.control.matched": rec.matched if rec.matched is not None else False,
            "cpex.control.applied": bool(rec.applied),
            "cpex.control.payload_modified": bool(rec.payload_modified),
        }
        # requested_allow: only emit when present (None means not applicable to this mode)
        if rec.requested_allow is not None:
            attrs["cpex.control.result.requested_allowed"] = bool(rec.requested_allow)
        # Artifact identity — only emit when CPEX record carries them (optional fields)
        artifact_name = getattr(rec, "artifact_name", None)
        if artifact_name:
            attrs["cpex.control.artifact.name"] = _safe_str(artifact_name, 128)
        artifact_id = getattr(rec, "artifact_id", None)
        if artifact_id:
            attrs["cpex.control.artifact.id"] = _safe_str(artifact_id, 128)
        # Optional free-text fields — gated by CPEX_CONTROL_TELEMETRY_EMIT_REASON (default: false).
        # reason and error_code can contain PII, tool argument values, or exception content.
        # They are opt-in until Phase 5 central attribute-policy wiring provides a redaction
        # boundary.  Set CPEX_CONTROL_TELEMETRY_EMIT_REASON=true only in environments where
        # these fields are known safe and the observability sink is appropriately secured.
        if _emit_reason_enabled():
            if rec.reason:
                attrs["cpex.control.result.reason"] = _safe_str(rec.reason, _MAX_REASON_LEN)
            if rec.error_code:
                attrs["cpex.control.result.error_code"] = _safe_str(rec.error_code, _MAX_ERROR_CODE_LEN)
        if rec.config_keys:
            # Key names only (CPEX never includes values); bounded list join
            attrs["cpex.control.config.keys"] = ",".join(rec.config_keys[:_MAX_CONFIG_KEYS])
        return attrs
    except Exception:  # noqa: BLE001
        logger.debug("Failed to build per-control attributes", exc_info=True)
        return {}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _safe_str(value: Any, max_len: int) -> str:
    """Truncate ``value`` to ``max_len`` UTF-8 bytes.  Never raises.

    Args:
        value: Value to stringify and truncate.
        max_len: Maximum byte length of the result.

    Returns:
        String truncated to ``max_len`` bytes (with trailing ``...`` if cut).
    """
    s = str(value) if not isinstance(value, str) else value
    encoded = s.encode("utf-8")
    if len(encoded) <= max_len:
        return s
    return encoded[: max_len - 3].decode("utf-8", errors="ignore") + "..."


def _enforcement_point(acc: "ControlTelemetryAccumulator") -> str:
    """Derive the enforcement-point label from which hooks contributed records.

    Args:
        acc: The populated accumulator.

    Returns:
        One of ``"pre"``, ``"post"``, ``"pre+post"``, or ``"none"``.
    """
    has_pre = any(h == "pre" for h, _ in acc.records)
    has_post = any(h == "post" for h, _ in acc.records)
    if has_pre and has_post:
        return "pre+post"
    if has_pre:
        return "pre"
    if has_post:
        return "post"
    return "none"


def _get_max_results() -> int:
    """Read the configured per-invocation result cap.

    Returns:
        Maximum number of per-control result records to export (default 32).
    """
    try:
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

        return int(getattr(settings, "cpex_control_telemetry_max_results", 32))
    except Exception:  # noqa: BLE001
        return 32


def _emit_reason_enabled() -> bool:
    """Return True when ``result.reason`` and ``result.error_code`` emission is enabled.

    These fields are opt-in (default: False) because they may contain PII, tool argument
    values, or exception content that should not leave the process without passing through
    a redaction boundary.  Enable via ``CPEX_CONTROL_TELEMETRY_EMIT_REASON=true`` only in
    environments where the observability sink is appropriately secured.

    Returns:
        True when ``cpex_control_telemetry_emit_reason`` is set to True in settings.

    Examples:
        >>> isinstance(_emit_reason_enabled(), bool)
        True
    """
    try:
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

        return bool(getattr(settings, "cpex_control_telemetry_emit_reason", False))
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Flattened-results projection helper
# ---------------------------------------------------------------------------


def _build_flattened_attributes(
    accumulator: "ControlTelemetryAccumulator",
    max_results: int,
) -> dict:
    """Build flattened ``cpex.control.results.<name>.*`` attributes (optional projection).

    This is a **projection layer only** — the fixed-schema child spans emitted by
    ``_emit_db_spans`` / ``_emit_otel_spans`` remain the internal source of truth.
    Enabled only when ``CPEX_CONTROL_TELEMETRY_FLATTEN_RESULTS=true``.

    Safety rules (mirrors issue #5785 spec):
    - ``plugin_name`` is validated against ``_IDENTIFIER_RE`` before use in a key.
    - Collisions (two records with the same sanitized name) → both dropped; a bounded
      counter ``cpex.control.results._collision_count`` is emitted instead.
    - Bounded to ``max_results`` records.
    - Never raises.

    Args:
        accumulator: The populated ``ControlTelemetryAccumulator``.
        max_results: Maximum records to flatten.

    Returns:
        Dict of flattened attributes, empty on error or when nothing to flatten.
    """
    try:
        result: dict = {}
        collision_count = 0
        seen_names: set = set()

        for hook, rec in itertools.islice(accumulator.records, max_results):
            try:
                raw_name = str(getattr(rec, "plugin_name", ""))
                # Validate and sanitize the name segment used in the attribute key
                if not _IDENTIFIER_RE.match(raw_name):
                    logger.debug("Skipping flatten for record: plugin_name %r is not a valid identifier", raw_name)
                    continue

                if raw_name in seen_names:
                    # Collision: two records with the same plugin_name — drop both
                    logger.debug("Flatten collision for plugin_name %r — dropping both records", raw_name)
                    # Remove previously written keys for this name
                    to_remove = [k for k in result if k.startswith(f"cpex.control.results.{raw_name}.")]
                    for k in to_remove:
                        del result[k]
                    collision_count += 1
                    continue
                seen_names.add(raw_name)

                prefix = f"cpex.control.results.{raw_name}"
                result[f"{prefix}.name"] = _safe_str(raw_name, 64)
                result[f"{prefix}.status"] = _safe_str(str(getattr(rec, "status", "")), 32)
                result[f"{prefix}.enforcement_point"] = hook
                result[f"{prefix}.result.allowed"] = bool(getattr(rec, "effective_allow", True))
                result[f"{prefix}.duration_ns"] = int(getattr(rec, "duration_ns", 0))  # nanoseconds — OTel unit suffix convention

                artifact_name = getattr(rec, "artifact_name", None)
                if artifact_name:
                    result[f"{prefix}.artifact.name"] = _safe_str(artifact_name, 128)

                artifact_id = getattr(rec, "artifact_id", None)
                if artifact_id:
                    result[f"{prefix}.artifact.id"] = _safe_str(artifact_id, 128)

                config_keys = getattr(rec, "config_keys", None)
                if config_keys:
                    result[f"{prefix}.config.keys"] = ",".join(config_keys[:_MAX_CONFIG_KEYS])

                # reason/error_code gated by CPEX_CONTROL_TELEMETRY_EMIT_REASON (default: false)
                if _emit_reason_enabled():
                    reason = getattr(rec, "reason", None)
                    if reason:
                        result[f"{prefix}.result.reason"] = _safe_str(reason, _MAX_REASON_LEN)

                    error_code = getattr(rec, "error_code", None)
                    if error_code:
                        result[f"{prefix}.result.error_code"] = _safe_str(error_code, _MAX_ERROR_CODE_LEN)
            except Exception:  # noqa: BLE001
                logger.debug("Failed to flatten one ControlExecutionRecord", exc_info=True)

        if collision_count:
            result["cpex.control.results._collision_count"] = collision_count

        return result
    except Exception:  # noqa: BLE001
        logger.debug("_build_flattened_attributes failed", exc_info=True)
        return {}
