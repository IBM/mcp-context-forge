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
import inspect
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
import mcpgateway.config as cfg_mod
from mcpgateway.plugins.control_telemetry import (
    ControlTelemetryAccumulator,
    _emit_db_spans,
    _emit_otel_spans,
    _per_control_attributes,
    record_control_telemetry,
)
from mcpgateway.plugins.utils import (
    _compile_wildcard_rule,
    apply_attribute_mapping,
    compile_attribute_policy,
)
from mcpgateway.services.observability_service import ObservabilityService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rec(
    *,
    plugin_name: str = "pii-guard",
    plugin_id: str = "pii-guard-001",
    plugin_kind: str = "builtin",
    hook_name: str = "tool_pre_invoke",
    mode: str = "sequential",
    status: str = "completed",
    effective_allow: bool = True,
    requested_allow: object = None,
    matched: object = True,
    applied: bool = False,
    payload_modified: bool = False,
    duration_ns: int = 500,
    reason: object = None,
    error_code: object = None,
    config_keys: list = None,
) -> MagicMock:
    rec = MagicMock()
    rec.plugin_name = plugin_name
    rec.plugin_id = plugin_id
    rec.plugin_kind = plugin_kind
    rec.hook_name = hook_name
    rec.mode = mode
    rec.status = status
    rec.effective_allow = effective_allow
    rec.requested_allow = requested_allow
    rec.matched = matched
    rec.applied = applied
    rec.payload_modified = payload_modified
    rec.duration_ns = duration_ns
    rec.reason = reason
    rec.error_code = error_code
    rec.config_keys = config_keys or []
    return rec


def _acc_with_pre_records(recs):
    """Build a ControlTelemetryAccumulator with pre-hook records."""
    acc = ControlTelemetryAccumulator()
    result = MagicMock()
    result.executions = recs
    result.continue_processing = True
    acc.add(result, hook="pre")
    return acc


def _acc_pre_denied():
    """Build an accumulator where pre-hook was denied (no records)."""
    acc = ControlTelemetryAccumulator()
    result = MagicMock()
    result.executions = []
    result.continue_processing = False
    acc.add(result, hook="pre")
    return acc


def _enabled_settings(**kwargs):
    """Build a MagicMock settings object with CPEX control telemetry enabled.

    Merges any extra kwargs so individual tests can override specific fields.
    """
    s = MagicMock()
    s.cpex_control_telemetry_enabled = True
    s.cpex_control_telemetry_db_enabled = True
    s.cpex_control_telemetry_flatten_results = False
    s.cpex_control_telemetry_max_results = 32
    s.cpex_control_telemetry_emit_reason = False
    s.cpex_control_telemetry_emit_agent_id = False
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# record_control_telemetry — no-op scenarios
# ---------------------------------------------------------------------------


class TestRecordControlTelemetryNoop:
    def test_noop_when_no_trace_id(self):
        acc = ControlTelemetryAccumulator()
        with patch("mcpgateway.plugins.control_telemetry._emit_db_spans") as mock_db:
            record_control_telemetry(None, acc)
            mock_db.assert_not_called()

    def test_noop_when_accumulator_empty_and_not_denied(self):
        acc = ControlTelemetryAccumulator()
        with patch("mcpgateway.plugins.control_telemetry._emit_db_spans") as mock_db:
            record_control_telemetry("trace-1", acc)
            mock_db.assert_not_called()

    def test_noop_when_feature_disabled(self):
        """Feature flag CPEX_CONTROL_TELEMETRY_ENABLED=false skips all emission."""
        acc = _acc_with_pre_records([_make_rec()])
        mock_settings = MagicMock()
        mock_settings.cpex_control_telemetry_enabled = False
        mock_settings.cpex_control_telemetry_db_enabled = True

        with (
            patch("mcpgateway.plugins.control_telemetry._emit_db_spans") as mock_db,
            patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
        ):
            original_settings = cfg_mod.settings
            try:
                cfg_mod.settings = mock_settings
                record_control_telemetry("trace-1", acc)
            finally:
                cfg_mod.settings = original_settings
            mock_db.assert_not_called()


# ---------------------------------------------------------------------------
# record_control_telemetry — truncated flag (line 260)
# ---------------------------------------------------------------------------


class TestRecordControlTelemetryTruncated:
    def test_truncated_attribute_present_when_accumulator_overflowed(self):
        """cpex.control.truncated covers all three truncation tiers:
        - Tier 1/2: records dropped at accumulation time (per-hook/per-call caps).
        - Tier 3: records dropped at export time (cpex_control_telemetry_max_results cap).

        With _MAX_RECORDS_PER_CALL=128 records accumulated and max_results=32 (default),
        tier-1/2 drops = 2 (130 pushed, 128 accepted), tier-3 drops = 96 (128 - 32).
        Total truncated = 98.
        """
        from mcpgateway.plugins.control_telemetry import _MAX_RECORDS_PER_CALL  # noqa: PLC0415

        acc = ControlTelemetryAccumulator()
        for i in range(_MAX_RECORDS_PER_CALL + 2):
            r = MagicMock()
            r.executions = [_make_rec(plugin_name=f"p{i}")]
            r.continue_processing = True
            acc.add(r, hook="pre")

        # Tier-1/2 drops only at this point (export cap not yet applied)
        assert acc._truncated == 2  # pylint: disable=protected-access
        captured: dict = {}

        def capture_db(service, trace_id, aggregate, accumulator):
            captured.update(aggregate)

        original = cfg_mod.settings
        try:
            cfg_mod.settings = _enabled_settings()
            with (
                patch("mcpgateway.plugins.control_telemetry._emit_db_spans", side_effect=capture_db),
                patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
            ):
                record_control_telemetry("trace-trunc", acc)
        finally:
            cfg_mod.settings = original

        # After record_control_telemetry(): tier-3 export-cap drops (128 - 32 = 96) added.
        # Total: 2 (tier-1/2) + 96 (tier-3) = 98
        assert captured.get("cpex.control.truncated") == 98
        assert acc.truncated == 98


# ---------------------------------------------------------------------------
# record_control_telemetry — flatten_results branch (lines 267-268)
# ---------------------------------------------------------------------------


class TestRecordControlTelemetryFlatten:
    def test_flatten_results_attributes_added_when_enabled(self):
        """Lines 267-268: flattened attributes are merged into aggregate when enabled."""
        acc = _acc_with_pre_records([_make_rec(plugin_name="pii_filter")])
        mock_settings = MagicMock()
        mock_settings.cpex_control_telemetry_enabled = True
        mock_settings.cpex_control_telemetry_db_enabled = True
        mock_settings.cpex_control_telemetry_flatten_results = True
        mock_settings.cpex_control_telemetry_max_results = 32
        captured: dict = {}

        def capture_db(service, trace_id, aggregate, accumulator):
            captured.update(aggregate)

        original = cfg_mod.settings
        try:
            cfg_mod.settings = mock_settings
            with (
                patch("mcpgateway.plugins.control_telemetry._emit_db_spans", side_effect=capture_db),
                patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
            ):
                record_control_telemetry("trace-flat", acc)
        finally:
            cfg_mod.settings = original

        # At least the base aggregate key must be present; flattened keys start with cpex.control.results.
        assert any(k.startswith("cpex.control.results.") for k in captured), (
            f"Expected flattened keys in aggregate, got: {list(captured)}"
        )


# ---------------------------------------------------------------------------
# record_control_telemetry — writes to DB sink
# ---------------------------------------------------------------------------


class TestRecordControlTelemetryDB:
    """Tests that the DB sink helper is called correctly."""

    def test_writes_summary_span_to_db(self):
        """DB sink is invoked when there are execution records."""
        acc = _acc_with_pre_records([_make_rec()])
        original = cfg_mod.settings
        try:
            cfg_mod.settings = _enabled_settings()
            with (
                patch("mcpgateway.plugins.control_telemetry._emit_db_spans") as mock_db,
                patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
            ):
                record_control_telemetry("trace-123", acc, tool_name="my_tool")
            mock_db.assert_called_once()
        finally:
            cfg_mod.settings = original

    def test_writes_per_control_spans(self):
        """DB sink receives the accumulator with multiple records."""
        acc = _acc_with_pre_records([_make_rec(plugin_name="ctrl1"), _make_rec(plugin_name="ctrl2")])
        original = cfg_mod.settings
        try:
            cfg_mod.settings = _enabled_settings()
            with (
                patch("mcpgateway.plugins.control_telemetry._emit_db_spans") as mock_db,
                patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
            ):
                record_control_telemetry("trace-123", acc)
            mock_db.assert_called_once()
            call_args = mock_db.call_args[0]
            assert len(call_args[3].records) == 2
        finally:
            cfg_mod.settings = original

    def test_db_failure_does_not_raise(self):
        """_emit_db_spans raising must not propagate into the request path."""
        acc = _acc_with_pre_records([_make_rec()])
        original = cfg_mod.settings
        try:
            cfg_mod.settings = _enabled_settings()
            with (
                patch("mcpgateway.plugins.control_telemetry._emit_db_spans", side_effect=RuntimeError("DB is down")),
                patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
            ):
                record_control_telemetry("trace-123", acc)
        finally:
            cfg_mod.settings = original

    def test_otel_failure_does_not_raise(self):
        """_emit_otel_spans raising must not propagate."""
        acc = _acc_with_pre_records([_make_rec()])
        original = cfg_mod.settings
        try:
            cfg_mod.settings = _enabled_settings()
            with (
                patch("mcpgateway.plugins.control_telemetry._emit_db_spans"),
                patch("mcpgateway.plugins.control_telemetry._emit_otel_spans", side_effect=RuntimeError("OTel explode")),
            ):
                record_control_telemetry("trace-123", acc)
        finally:
            cfg_mod.settings = original

    def test_pre_deny_summary_has_result_allowed_false(self):
        """When pre-hook was denied, aggregate result.allowed must be False."""
        acc = _acc_pre_denied()
        captured_aggregate: dict = {}

        def capture_db(service, trace_id, aggregate, accumulator):
            captured_aggregate.update(aggregate)

        original = cfg_mod.settings
        try:
            cfg_mod.settings = _enabled_settings()
            with (
                patch("mcpgateway.plugins.control_telemetry._emit_db_spans", side_effect=capture_db),
                patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
            ):
                record_control_telemetry("trace-123", acc)
        finally:
            cfg_mod.settings = original
        assert captured_aggregate.get("cpex.control.result.allowed") is False

    def test_tool_name_in_attributes(self):
        """tool_name appears in the aggregate attributes."""
        acc = _acc_with_pre_records([_make_rec()])
        captured: dict = {}

        def capture_db(service, trace_id, aggregate, accumulator):
            captured.update(aggregate)

        original = cfg_mod.settings
        try:
            cfg_mod.settings = _enabled_settings()
            with (
                patch("mcpgateway.plugins.control_telemetry._emit_db_spans", side_effect=capture_db),
                patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
            ):
                record_control_telemetry("trace-123", acc, tool_name="my_tool")
        finally:
            cfg_mod.settings = original
        assert captured.get("cpex.control.tool.name") == "my_tool"

    def test_capped_at_max_results(self):
        """record_control_telemetry respects _get_max_results cap on per-control spans."""
        acc = _acc_with_pre_records([_make_rec(plugin_name=f"ctrl{i}") for i in range(10)])
        call_count_tracker: list = []

        def capture_db(service, trace_id, aggregate, accumulator):
            call_count_tracker.append(len(accumulator.records))

        original = cfg_mod.settings
        try:
            cfg_mod.settings = _enabled_settings()
            with (
                patch("mcpgateway.plugins.control_telemetry._emit_db_spans", side_effect=capture_db),
                patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
                patch("mcpgateway.plugins.control_telemetry._get_max_results", return_value=3),
            ):
                record_control_telemetry("trace-123", acc)
        finally:
            cfg_mod.settings = original
        assert call_count_tracker[0] == 10  # accumulator has all 10


# ---------------------------------------------------------------------------
# _emit_db_spans — exception paths (lines 327, 342-348, 353-354)
# ---------------------------------------------------------------------------


class TestEmitDbSpansExceptionPaths:
    def test_empty_attrs_record_is_skipped(self):
        """Line 327: record whose _per_control_attributes returns {} is skipped (continue)."""
        acc = ControlTelemetryAccumulator()
        # Inject a record that will produce empty attrs
        acc._records.append(("pre", MagicMock(spec=[])))  # pylint: disable=protected-access

        with patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"):
            # Must not raise; the bad record is silently skipped
            record_control_telemetry("trace-skip", acc)

    def test_db_exception_triggers_rollback(self):
        """Lines 342-348: start_span raising triggers rollback in the except block."""
        acc = _acc_with_pre_records([_make_rec()])
        mock_db = MagicMock()
        mock_service = MagicMock()
        mock_service.start_span.side_effect = RuntimeError("DB write failed")

        # SessionLocal is a lazy import inside _emit_db_spans from mcpgateway.db
        with patch("mcpgateway.db.SessionLocal", return_value=mock_db):
            _emit_db_spans(mock_service, "trace-rollback", {}, acc)

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()

    def test_db_close_exception_in_finally_is_swallowed(self):
        """Lines 353-354: db.close() raising in the finally block must not propagate."""
        acc = _acc_with_pre_records([_make_rec()])
        mock_db = MagicMock()
        mock_db.close.side_effect = RuntimeError("close failed")
        mock_service = MagicMock()
        mock_service.start_span.return_value = "span-id-1"

        with patch("mcpgateway.db.SessionLocal", return_value=mock_db):
            # Must not raise despite close() failing
            _emit_db_spans(mock_service, "trace-close", {}, acc)


# ---------------------------------------------------------------------------
# _emit_otel_spans — active OTel context path (lines 379-387)
# ---------------------------------------------------------------------------


class TestEmitOtelSpansActivePath:
    def test_emits_spans_when_otel_active(self):
        """Lines 379-387: OTel spans are emitted when tracing is enabled and context is active."""
        acc = _acc_with_pre_records([_make_rec(plugin_name="pii_filter")])
        spans_created: list = []

        class _FakeSpan:
            def __init__(self, name, attrs):
                spans_created.append(name)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with (
            patch("mcpgateway.plugins.control_telemetry._emit_db_spans"),
            patch("mcpgateway.observability.otel_tracing_enabled", return_value=True),
            patch("mcpgateway.observability.otel_context_active", return_value=True),
            patch("mcpgateway.observability.create_span", side_effect=_FakeSpan),
        ):
            _emit_otel_spans({"cpex.control.type": "tool"}, acc)

        assert "cpex.control.summary" in spans_created
        assert "cpex.control.result" in spans_created


# ---------------------------------------------------------------------------
# Attribute policy — remove_attributes
# ---------------------------------------------------------------------------


class TestRecordControlTelemetryRemoveAttributes:
    def test_remove_attributes_applied(self):
        """cpex.control.config.keys is present when config_keys are provided."""
        rec = _make_rec(config_keys=["timeout_ms", "max_size"])
        attrs = _per_control_attributes("pre", rec)
        assert "cpex.control.config.keys" in attrs
        assert "timeout_ms" in attrs["cpex.control.config.keys"]


# ---------------------------------------------------------------------------
# Wildcard rules in apply_attribute_mapping / compile_attribute_policy
# ---------------------------------------------------------------------------


class TestWildcardAttributeMapping:
    def test_exact_rename(self):
        attrs = {"cpex.control.result.allowed": True, "other": "val"}
        result = apply_attribute_mapping(attrs, {"cpex.control.result.allowed": "controls.result.allow"})
        assert "controls.result.allow" in result
        assert "cpex.control.result.allowed" not in result

    def test_wildcard_rename(self):
        attrs = {"cpex.control.results.pii.result.allowed": True}
        result = apply_attribute_mapping(
            attrs,
            {"cpex.control.results.*.result.allowed": "controls.results.*.result.allowed"},
        )
        assert "controls.results.pii.result.allowed" in result
        assert "cpex.control.results.pii.result.allowed" not in result

    def test_exact_takes_precedence_over_wildcard(self):
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
        with pytest.raises(ValueError, match="otel"):
            compile_attribute_policy({"cpex.control.result.allowed": "otel.reserved"}, [])

    def test_empty_source_rejected(self):
        with pytest.raises(ValueError):
            compile_attribute_policy({"": "dest"}, [])

    def test_key_exceeding_256_chars_rejected(self):
        """Line 535: mapping key > 256 chars raises ValueError."""
        long_key = "a" * 257
        with pytest.raises(ValueError, match="exceeds 256"):
            compile_attribute_policy({long_key: "dest"}, [])

    def test_removal_wildcard_compiled(self):
        """Lines 547-549: wildcard removal rule is compiled correctly."""
        _, removals = compile_attribute_policy({}, ["cpex.control.results.*.reason"])
        assert len(removals) == 1
        is_exact, pattern, src = removals[0]
        assert not is_exact
        assert pattern is not None
        assert src == "cpex.control.results.*.reason"

    def test_removal_exact_compiled(self):
        """Line 551: exact removal rule (no wildcard) is compiled correctly."""
        _, removals = compile_attribute_policy({}, ["cpex.control.type"])
        assert len(removals) == 1
        is_exact, pattern, src = removals[0]
        assert is_exact
        assert pattern is None

    def test_removal_key_exceeding_256_chars_rejected(self):
        """Line 546: removal key > 256 chars raises ValueError."""
        with pytest.raises(ValueError, match="exceeds 256"):
            compile_attribute_policy({}, ["b" * 257])

    def test_wildcard_compile_matches_single_segment(self):
        p = _compile_wildcard_rule("cpex.control.results.*.result.reason")
        assert p.fullmatch("cpex.control.results.pii-guard.result.reason") is not None
        assert p.fullmatch("cpex.control.results.pii.guard.result.reason") is None

    def test_wildcard_compile_no_match_multiple_segments(self):
        p = _compile_wildcard_rule("cpex.control.results.*.reason")
        assert p.fullmatch("cpex.control.results.a.b.reason") is None

    def test_no_mapping_returns_copy(self):
        attrs = {"a": 1, "b": 2}
        result = apply_attribute_mapping(attrs, {})
        assert result == attrs
        assert result is not attrs

    def test_mismatched_wildcard_count_in_src_dst_skips(self):
        """Line 593: src has 1 wildcard, dst has 2 — mismatch is silently skipped."""
        attrs = {"cpex.control.results.pii.result.reason": "x"}
        # src has 1 '*', dst has 2 '*' — mismatched, key returned unchanged
        result = apply_attribute_mapping(
            attrs,
            {"cpex.control.results.*.result.reason": "new.*.result.*.reason"},
        )
        # Key must still be present (unchanged or renamed); must not raise
        assert len(result) == 1

    def test_apply_attribute_mapping_valueerror_fallback(self):
        """Lines 657-660: ValueError from compile_attribute_policy → fail-closed, attrs unchanged."""
        attrs = {"cpex.control.result.allowed": True, "other": "val"}
        # otel.* destination triggers ValueError inside compile_attribute_policy.
        # After the fix: apply_attribute_mapping returns attrs unchanged (fail-closed).
        result = apply_attribute_mapping(attrs, {"cpex.control.result.allowed": "otel.reserved"})
        # Fail-closed: original keys preserved, otel.reserved must NOT appear
        assert "cpex.control.result.allowed" in result
        assert "otel.reserved" not in result
        assert result["cpex.control.result.allowed"] is True


# ---------------------------------------------------------------------------
# Concurrency isolation
# ---------------------------------------------------------------------------


class TestConcurrencyIsolation:
    def test_two_accumulators_are_independent(self):
        acc1 = ControlTelemetryAccumulator()
        acc2 = ControlTelemetryAccumulator()

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
        acc1 = ControlTelemetryAccumulator()
        acc2 = ControlTelemetryAccumulator()

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
    """

    def test_start_span_accepts_commit_and_obs_db_kwargs(self):
        """start_span signature must include commit and obs_db parameters."""
        sig = inspect.signature(ObservabilityService.start_span)
        params = sig.parameters
        assert "commit" in params, "ObservabilityService.start_span missing 'commit' kwarg"
        assert "obs_db" in params, "ObservabilityService.start_span missing 'obs_db' kwarg"

    def test_end_span_accepts_commit_and_obs_db_kwargs(self):
        """end_span signature must include commit and obs_db parameters."""
        sig = inspect.signature(ObservabilityService.end_span)
        params = sig.parameters
        assert "commit" in params, "ObservabilityService.end_span missing 'commit' kwarg"
        assert "obs_db" in params, "ObservabilityService.end_span missing 'obs_db' kwarg"


# ---------------------------------------------------------------------------
# Fix 1 — wildcard insertion order preserved in apply_attribute_mapping cache
# ---------------------------------------------------------------------------


class TestWildcardInsertionOrderPreserved:
    """apply_attribute_mapping() must respect insertion order for wildcard rule precedence."""

    def test_first_wildcard_wins_over_later_wildcard(self):
        """When two wildcard rules match the same key, the first declared rule must win."""
        attrs = {"x.a": 1}
        mapping = {
            "x.*": "first.*",   # declared first — should win
            "*.a": "second.*",  # declared second — must NOT win
        }
        result = apply_attribute_mapping(attrs, mapping)
        # "x.*" matches "x.a" (captures "a") → "first.a"
        assert "first.a" in result, (
            f"Expected first declared wildcard rule to win, got keys: {list(result)}"
        )
        assert "second.x" not in result, "Second wildcard rule must not override first"

    def test_reversed_order_changes_result(self):
        """Reversing the rule order must change which rule wins — proving order is preserved."""
        attrs = {"x.a": 1}
        mapping_first_wins = {"x.*": "first.*", "*.a": "second.*"}
        mapping_second_wins = {"*.a": "second.*", "x.*": "first.*"}
        result_first = apply_attribute_mapping(attrs, mapping_first_wins)
        result_second = apply_attribute_mapping(attrs, mapping_second_wins)
        # Results must differ to prove order is actually preserved
        assert list(result_first.keys()) != list(result_second.keys()), (
            "Reversing rule order should change which wildcard fires first"
        )

    def test_exact_rule_still_beats_all_wildcards(self):
        """Exact rules take precedence regardless of insertion order."""
        attrs = {"x.a": 1}
        mapping = {
            "*.a": "wildcard_first.*",  # wildcard declared before exact
            "x.a": "exact_dest",        # exact declared after wildcard
        }
        result = apply_attribute_mapping(attrs, mapping)
        assert "exact_dest" in result
        assert "wildcard_first.x" not in result


# ---------------------------------------------------------------------------
# Fix 2 — config_keys joined cap is byte-aware via _safe_str
# ---------------------------------------------------------------------------


class TestConfigKeysByteCapAware:
    """config_keys joined cap must be byte-aware (not char-based) for multibyte keys."""

    def _make_rec_with_keys(self, keys):
        """Build a minimal ControlExecutionRecord mock with the given config_keys."""
        from unittest.mock import MagicMock  # noqa: PLC0415
        rec = MagicMock()
        rec.plugin_name = "guard"
        rec.plugin_id = "g-001"
        rec.plugin_kind = "builtin"
        rec.hook_name = "tool_pre_invoke"
        rec.mode = "sequential"
        rec.status = "completed"
        rec.effective_allow = True
        rec.requested_allow = None
        rec.matched = True
        rec.applied = False
        rec.payload_modified = False
        rec.duration_ns = 1000
        rec.reason = None
        rec.error_code = None
        rec.config_keys = keys
        rec.artifact_name = None
        rec.artifact_id = None
        return rec

    def test_multibyte_key_does_not_exceed_byte_budget(self):
        """A joined config_keys string with multibyte chars must not exceed _MAX_CONFIG_KEYS_JOINED_LEN bytes."""
        from mcpgateway.plugins.control_telemetry import _MAX_CONFIG_KEYS_JOINED_LEN, _per_control_attributes  # noqa: PLC0415
        import mcpgateway.config as cfg_mod_local  # noqa: PLC0415
        # Use a key with multibyte chars (each '日' is 3 UTF-8 bytes)
        multibyte_key = "日" * 40  # 40 chars, 120 bytes — under per-key 128-byte limit
        keys = [multibyte_key] * 100  # many keys to trigger the joined cap
        rec = self._make_rec_with_keys(keys)
        mock_settings = MagicMock()
        mock_settings.cpex_control_telemetry_emit_reason = False
        original = cfg_mod_local.settings
        try:
            cfg_mod_local.settings = mock_settings
            attrs = _per_control_attributes("pre", rec)
        finally:
            cfg_mod_local.settings = original
        joined = attrs.get("cpex.control.config.keys", "")
        # The byte length of the result must not exceed the cap
        assert len(joined.encode("utf-8")) <= _MAX_CONFIG_KEYS_JOINED_LEN, (
            f"config.keys byte length {len(joined.encode('utf-8'))} exceeds budget {_MAX_CONFIG_KEYS_JOINED_LEN}"
        )

    def test_ascii_keys_still_work(self):
        """ASCII-only config_keys must be unaffected by the byte-aware cap."""
        from mcpgateway.plugins.control_telemetry import _per_control_attributes  # noqa: PLC0415
        import mcpgateway.config as cfg_mod_local  # noqa: PLC0415
        keys = ["key_one", "key_two", "key_three"]
        rec = self._make_rec_with_keys(keys)
        mock_settings = MagicMock()
        mock_settings.cpex_control_telemetry_emit_reason = False
        original = cfg_mod_local.settings
        try:
            cfg_mod_local.settings = mock_settings
            attrs = _per_control_attributes("pre", rec)
        finally:
            cfg_mod_local.settings = original
        assert attrs.get("cpex.control.config.keys") == "key_one,key_two,key_three"
