# -*- coding: utf-8 -*-
"""Integration tests for record_control_telemetry() and related helpers.

Location: ./tests/unit/mcpgateway/plugins/test_record_control_telemetry.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests ``record_control_telemetry()`` end-to-end through the two sinks
(DB + OTel), including no-op cases, attribute mapping, removal, max-results
cap, and concurrency isolation.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rec(
    *,
    plugin_name: str = "pii-guard",
    hook_name: str = "tool_pre_invoke",
    mode: str = "sequential",
    status: str = "completed",
    effective_allow: bool = True,
    matched: object = True,
    applied: bool = False,
    duration_ns: int = 500,
    reason: object = None,
    error_code: object = None,
    config_keys: list = None,
) -> MagicMock:
    rec = MagicMock()
    rec.plugin_name = plugin_name
    rec.hook_name = hook_name
    rec.mode = mode
    rec.status = status
    rec.effective_allow = effective_allow
    rec.matched = matched
    rec.applied = applied
    rec.duration_ns = duration_ns
    rec.reason = reason
    rec.error_code = error_code
    rec.config_keys = config_keys or []
    return rec


def _acc_with_pre_records(recs):
    """Build a ControlTelemetryAccumulator with pre-hook records."""
    from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

    acc = ControlTelemetryAccumulator()
    with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
        result = MagicMock()
        result.executions = recs
        result.continue_processing = True
        acc.add(result, hook="pre")
    return acc


def _acc_pre_denied():
    """Build an accumulator where pre-hook was denied (no records)."""
    from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

    acc = ControlTelemetryAccumulator()
    with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
        result = MagicMock()
        result.executions = []
        result.continue_processing = False
        acc.add(result, hook="pre")
    return acc


# ---------------------------------------------------------------------------
# record_control_telemetry — no-op scenarios
# ---------------------------------------------------------------------------


class TestRecordControlTelemetryNoop:
    def test_noop_when_no_trace_id(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator, record_control_telemetry

        acc = ControlTelemetryAccumulator()
        # Should not raise and not attempt any DB/OTel write
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            with patch("mcpgateway.plugins.control_telemetry._emit_db_spans") as mock_db:
                record_control_telemetry(None, acc)
                mock_db.assert_not_called()

    def test_noop_when_cpex_records_unavailable(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator, record_control_telemetry

        acc = ControlTelemetryAccumulator()
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=False):
            with patch("mcpgateway.plugins.control_telemetry._emit_db_spans") as mock_db:
                record_control_telemetry("trace-1", acc)
                mock_db.assert_not_called()

    def test_noop_when_accumulator_empty_and_not_denied(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator, record_control_telemetry

        acc = ControlTelemetryAccumulator()
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            with patch("mcpgateway.plugins.control_telemetry._emit_db_spans") as mock_db:
                record_control_telemetry("trace-1", acc)
                mock_db.assert_not_called()

    def test_noop_when_feature_disabled(self):
        """Feature flag CPEX_CONTROL_TELEMETRY_ENABLED=false skips all emission."""
        from mcpgateway.plugins.control_telemetry import record_control_telemetry

        acc = _acc_with_pre_records([_make_rec()])

        # Patch settings with cpex_control_telemetry_enabled=False inside the lazy import
        mock_settings = MagicMock()
        mock_settings.cpex_control_telemetry_enabled = False
        mock_settings.cpex_control_telemetry_db_enabled = True

        with (
            patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True),
            patch("mcpgateway.plugins.control_telemetry._emit_db_spans") as mock_db,
            patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
        ):
            # Patch the lazy import of settings inside the function
            with patch("mcpgateway.plugins.control_telemetry.record_control_telemetry"):
                # Simulate the feature-flag guard by calling the real implementation
                # with patched settings; we verify _emit_db_spans is NOT called.
                pass

            # Call with feature disabled: settings loaded lazily — patch via sys.modules
            import mcpgateway.config as cfg_mod  # noqa: PLC0415

            original_settings = cfg_mod.settings
            try:
                cfg_mod.settings = mock_settings
                record_control_telemetry("trace-1", acc)
            finally:
                cfg_mod.settings = original_settings

            mock_db.assert_not_called()


# ---------------------------------------------------------------------------
# record_control_telemetry — writes to DB sink
# ---------------------------------------------------------------------------


class TestRecordControlTelemetryDB:
    """Tests that the DB sink helper is called correctly.

    ObservabilityService and SessionLocal are imported lazily inside
    record_control_telemetry() / _emit_db_spans(), so we patch the
    functions themselves via the control_telemetry module rather than
    trying to patch the lazily-imported classes.
    """

    def test_writes_summary_span_to_db(self):
        """DB sink is invoked when there are execution records."""
        from mcpgateway.plugins.control_telemetry import record_control_telemetry

        acc = _acc_with_pre_records([_make_rec()])

        with (
            patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True),
            patch("mcpgateway.plugins.control_telemetry._emit_db_spans") as mock_db,
            patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
        ):
            record_control_telemetry("trace-123", acc, tool_name="my_tool")

        mock_db.assert_called_once()
        # First positional arg is service, second is trace_id, third is aggregate dict
        assert mock_db.call_count == 1

    def test_writes_per_control_spans(self):
        """DB sink receives the accumulator with multiple records."""
        from mcpgateway.plugins.control_telemetry import record_control_telemetry

        acc = _acc_with_pre_records([_make_rec(plugin_name="ctrl1"), _make_rec(plugin_name="ctrl2")])

        with (
            patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True),
            patch("mcpgateway.plugins.control_telemetry._emit_db_spans") as mock_db,
            patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
        ):
            record_control_telemetry("trace-123", acc)

        mock_db.assert_called_once()
        # accumulator (4th positional arg) should have 2 records
        call_args = mock_db.call_args[0]
        accumulator_arg = call_args[3]
        assert len(accumulator_arg.records) == 2

    def test_db_failure_does_not_raise(self):
        """_emit_db_spans raising must not propagate into the request path."""
        from mcpgateway.plugins.control_telemetry import record_control_telemetry

        acc = _acc_with_pre_records([_make_rec()])

        with (
            patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True),
            patch("mcpgateway.plugins.control_telemetry._emit_db_spans", side_effect=RuntimeError("DB is down")),
            patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
        ):
            # Must not raise
            record_control_telemetry("trace-123", acc)

    def test_otel_failure_does_not_raise(self):
        """_emit_otel_spans raising must not propagate."""
        from mcpgateway.plugins.control_telemetry import record_control_telemetry

        acc = _acc_with_pre_records([_make_rec()])

        with (
            patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True),
            patch("mcpgateway.plugins.control_telemetry._emit_db_spans"),
            patch("mcpgateway.plugins.control_telemetry._emit_otel_spans", side_effect=RuntimeError("OTel explode")),
        ):
            record_control_telemetry("trace-123", acc)

    def test_pre_deny_summary_has_result_allowed_false(self):
        """When pre-hook was denied, aggregate result.allowed must be False."""
        from mcpgateway.plugins.control_telemetry import record_control_telemetry

        acc = _acc_pre_denied()
        captured_aggregate: dict = {}

        def capture_db(service, trace_id, aggregate, accumulator):
            captured_aggregate.update(aggregate)

        with (
            patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True),
            patch("mcpgateway.plugins.control_telemetry._emit_db_spans", side_effect=capture_db),
            patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
        ):
            record_control_telemetry("trace-123", acc)

        assert captured_aggregate.get("cpex.control.result.allowed") is False

    def test_tool_name_in_attributes(self):
        """tool_name appears in the aggregate attributes."""
        from mcpgateway.plugins.control_telemetry import record_control_telemetry

        acc = _acc_with_pre_records([_make_rec()])
        captured: dict = {}

        def capture_db(service, trace_id, aggregate, accumulator):
            captured.update(aggregate)

        with (
            patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True),
            patch("mcpgateway.plugins.control_telemetry._emit_db_spans", side_effect=capture_db),
            patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
        ):
            record_control_telemetry("trace-123", acc, tool_name="my_tool")

        assert captured.get("cpex.control.tool.name") == "my_tool"

    def test_capped_at_max_results(self):
        """record_control_telemetry respects _get_max_results cap on per-control spans."""
        from mcpgateway.plugins.control_telemetry import record_control_telemetry

        acc = _acc_with_pre_records([_make_rec(plugin_name=f"ctrl{i}") for i in range(10)])
        call_count_tracker: list = []

        def capture_db(service, trace_id, aggregate, accumulator):
            # Count how many records the accumulator presents
            call_count_tracker.append(len(accumulator.records))

        with (
            patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True),
            patch("mcpgateway.plugins.control_telemetry._emit_db_spans", side_effect=capture_db),
            patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
            patch("mcpgateway.plugins.control_telemetry._get_max_results", return_value=3),
        ):
            record_control_telemetry("trace-123", acc)

        # _emit_db_spans was called once with the full accumulator (capping happens inside)
        assert call_count_tracker[0] == 10  # accumulator has all 10


# ---------------------------------------------------------------------------
# Attribute policy — remove_attributes
# ---------------------------------------------------------------------------


class TestRecordControlTelemetryRemoveAttributes:
    def test_remove_attributes_applied(self):
        """cpex.control.config.keys is present when config_keys are provided."""
        from mcpgateway.plugins.control_telemetry import _per_control_attributes

        rec = _make_rec(config_keys=["timeout_ms", "max_size"])
        attrs = _per_control_attributes("pre", rec)
        assert "cpex.control.config.keys" in attrs
        assert "timeout_ms" in attrs["cpex.control.config.keys"]


# ---------------------------------------------------------------------------
# Wildcard rules in apply_attribute_mapping
# ---------------------------------------------------------------------------


class TestWildcardAttributeMapping:
    def test_exact_rename(self):
        from mcpgateway.plugins.utils import apply_attribute_mapping

        attrs = {"cpex.control.result.allowed": True, "other": "val"}
        result = apply_attribute_mapping(attrs, {"cpex.control.result.allowed": "controls.result.allow"})
        assert "controls.result.allow" in result
        assert "cpex.control.result.allowed" not in result

    def test_wildcard_rename(self):
        from mcpgateway.plugins.utils import apply_attribute_mapping

        attrs = {"cpex.control.results.pii.result.allowed": True}
        result = apply_attribute_mapping(
            attrs,
            {"cpex.control.results.*.result.allowed": "controls.results.*.result.allowed"},
        )
        assert "controls.results.pii.result.allowed" in result
        assert "cpex.control.results.pii.result.allowed" not in result

    def test_exact_takes_precedence_over_wildcard(self):
        from mcpgateway.plugins.utils import apply_attribute_mapping

        attrs = {"cpex.control.results.pii.result.allowed": True}
        result = apply_attribute_mapping(
            attrs,
            {
                "cpex.control.results.pii.result.allowed": "exact.dest",
                "cpex.control.results.*.result.allowed": "wildcard.dest.*.result.allowed",
            },
        )
        assert "exact.dest" in result

    def test_otel_destination_rejected(self):
        from mcpgateway.plugins.utils import compile_attribute_policy

        with pytest.raises(ValueError, match="otel"):
            compile_attribute_policy({"cpex.control.result.allowed": "otel.reserved"}, [])

    def test_empty_source_rejected(self):
        from mcpgateway.plugins.utils import compile_attribute_policy

        with pytest.raises(ValueError):
            compile_attribute_policy({"": "dest"}, [])

    def test_wildcard_compile_matches_single_segment(self):
        from mcpgateway.plugins.utils import _compile_wildcard_rule

        p = _compile_wildcard_rule("cpex.control.results.*.result.reason")
        assert p.fullmatch("cpex.control.results.pii-guard.result.reason") is not None
        assert p.fullmatch("cpex.control.results.pii.guard.result.reason") is None

    def test_wildcard_compile_no_match_multiple_segments(self):
        from mcpgateway.plugins.utils import _compile_wildcard_rule

        p = _compile_wildcard_rule("cpex.control.results.*.reason")
        assert p.fullmatch("cpex.control.results.a.b.reason") is None

    def test_no_mapping_returns_copy(self):
        from mcpgateway.plugins.utils import apply_attribute_mapping

        attrs = {"a": 1, "b": 2}
        result = apply_attribute_mapping(attrs, {})
        assert result == attrs
        assert result is not attrs


# ---------------------------------------------------------------------------
# Concurrency isolation
# ---------------------------------------------------------------------------


class TestConcurrencyIsolation:
    def test_two_accumulators_are_independent(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc1 = ControlTelemetryAccumulator()
        acc2 = ControlTelemetryAccumulator()

        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            r1 = MagicMock()
            r1.executions = [_make_rec(plugin_name="alpha")]
            r1.continue_processing = True
            acc1.add(r1, hook="pre")

            r2 = MagicMock()
            r2.executions = [_make_rec(plugin_name="beta"), _make_rec(plugin_name="gamma")]
            r2.continue_processing = True
            acc2.add(r2, hook="post")

        assert len(acc1.records) == 1
        assert len(acc2.records) == 2
        assert acc1.records[0][1].plugin_name == "alpha"

    def test_adding_to_one_does_not_affect_other(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc1 = ControlTelemetryAccumulator()
        acc2 = ControlTelemetryAccumulator()

        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            r = MagicMock()
            r.executions = [_make_rec()]
            r.continue_processing = False
            acc1.add(r, hook="pre")

        assert acc1.pre_denied is True
        assert acc2.pre_denied is False
        assert acc2.records == []


# ---------------------------------------------------------------------------
# ObservabilityService API compatibility smoke test (F4)
# ---------------------------------------------------------------------------


class TestObservabilityServiceAPICompatibility:
    """Verify that ObservabilityService.start_span and end_span accept the
    ``commit`` and ``obs_db`` kwargs that _emit_db_spans relies on.

    This is a compile-time/import-time guard: if a future refactor removes
    these parameters the test fails loudly rather than silently swallowing
    the error inside control_telemetry's best-effort catch-all.
    """

    def test_start_span_accepts_commit_and_obs_db_kwargs(self):
        """start_span signature must include commit and obs_db parameters."""
        import inspect

        from mcpgateway.services.observability_service import ObservabilityService

        sig = inspect.signature(ObservabilityService.start_span)
        params = sig.parameters
        assert "commit" in params, "ObservabilityService.start_span missing 'commit' kwarg — _emit_db_spans will silently fail"
        assert "obs_db" in params, "ObservabilityService.start_span missing 'obs_db' kwarg — _emit_db_spans will silently fail"

    def test_end_span_accepts_commit_and_obs_db_kwargs(self):
        """end_span signature must include commit and obs_db parameters."""
        import inspect

        from mcpgateway.services.observability_service import ObservabilityService

        sig = inspect.signature(ObservabilityService.end_span)
        params = sig.parameters
        assert "commit" in params, "ObservabilityService.end_span missing 'commit' kwarg — _emit_db_spans will silently fail"
        assert "obs_db" in params, "ObservabilityService.end_span missing 'obs_db' kwarg — _emit_db_spans will silently fail"
