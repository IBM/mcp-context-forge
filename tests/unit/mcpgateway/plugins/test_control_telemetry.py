# -*- coding: utf-8 -*-
"""Unit tests for mcpgateway/plugins/control_telemetry.py.

Location: ./tests/unit/mcpgateway/plugins/test_control_telemetry.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Covers:
  - ControlTelemetryAccumulator: empty init, add pre/post, caps, truncated, denied flags,
    effective_allowed, aggregate() semantics.
  - ControlTelemetryAccumulator.mark_denied(): pre/post explicit denial, effective_allowed.
  - ControlTelemetryAccumulator.mark_export_cap_dropped(): tier-3 export-cap truncation.
  - add() per-hook cap contributes to truncated counter (item 4 / item 6 fix).
  - _per_control_attributes: completed allow/deny, error/timeout/faf, optional field omission,
    reason truncation, config_keys bounded, artifact_name/artifact_id fields.
  - _safe_str: within-limit unchanged, truncated with ellipsis.
  - _enforcement_point: pre/post/pre+post/none.
  - _build_flattened_attributes: basic (duration_ns key), collision, reason, error_code,
    bounded, artifact fields, config_keys field, name field, edge cases.
  - aggregate() exception path, _get_max_results exception path.
  - record_control_telemetry(): tier-3 export-cap drops emitted in cpex.control.truncated.
"""

# Standard
from unittest.mock import MagicMock, patch

# First-Party
import mcpgateway.config as cfg_mod
from mcpgateway.plugins.control_telemetry import (
    _MAX_CONFIG_KEYS,
    _MAX_RECORDS_PER_CALL,
    ControlTelemetryAccumulator,
    _build_flattened_attributes,
    _enforcement_point,
    _get_max_results,
    _per_control_attributes,
    _safe_str,
    _sanitize_config_key,
    record_control_telemetry,
)


# ---------------------------------------------------------------------------
# Fixtures
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
    duration_ns: int = 1000,
    reason: object = None,
    error_code: object = None,
    config_keys: list = None,
) -> MagicMock:
    """Create a minimal ControlExecutionRecord mock."""
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


def _make_result(records=None, *, continue_processing=True) -> MagicMock:
    """Create a minimal PluginResult mock."""
    r = MagicMock()
    r.executions = records or []
    r.continue_processing = continue_processing
    return r


# ---------------------------------------------------------------------------
# ControlTelemetryAccumulator — basic
# ---------------------------------------------------------------------------


class TestAccumulatorInit:
    def test_empty_on_init(self):
        acc = ControlTelemetryAccumulator()
        assert acc.records == []
        assert acc.truncated == 0
        assert acc.pre_denied is False
        assert acc.post_denied is False
        assert acc.effective_allowed is True

    def test_aggregate_all_zeros_when_empty(self):
        acc = ControlTelemetryAccumulator()
        agg = acc.aggregate()
        assert agg["cpex.control.invocation_count"] == 0
        assert agg["cpex.control.matched_count"] == 0
        assert agg["cpex.control.applied_count"] == 0
        assert agg["cpex.control.duration_ns"] == 0
        assert agg["cpex.control.result.allowed"] is True
        assert agg["cpex.control.error_count"] == 0
        assert agg["cpex.control.timeout_count"] == 0


class TestAccumulatorAdd:
    def test_add_pre_only(self):
        acc = ControlTelemetryAccumulator()
        result = _make_result([_make_rec()])
        acc.add(result, hook="pre")
        assert len(acc.records) == 1
        assert acc.records[0][0] == "pre"

    def test_add_post_only(self):
        acc = ControlTelemetryAccumulator()
        result = _make_result([_make_rec()])
        acc.add(result, hook="post")
        assert len(acc.records) == 1
        assert acc.records[0][0] == "post"

    def test_add_pre_and_post(self):
        acc = ControlTelemetryAccumulator()
        acc.add(_make_result([_make_rec()]), hook="pre")
        acc.add(_make_result([_make_rec()]), hook="post")
        assert len(acc.records) == 2

    def test_noop_on_none_result(self):
        acc = ControlTelemetryAccumulator()
        acc.add(None, hook="pre")
        assert acc.records == []

    def test_noop_when_executions_raises(self):
        """add() must never propagate if the executions property raises."""

        class Boom:
            continue_processing = True

            @property
            def executions(self):
                raise RuntimeError("unexpected error")

        acc = ControlTelemetryAccumulator()
        acc.add(Boom(), hook="pre")  # must not raise
        assert acc.records == []

    def test_noop_when_executions_not_iterable(self):
        """add() returns [] without raising when executions is truthy but non-iterable."""
        import types

        result = types.SimpleNamespace(executions=42, continue_processing=True)
        acc = ControlTelemetryAccumulator()
        acc.add(result, hook="pre")  # list(42) would raise TypeError — must be swallowed
        assert acc.records == []

    def test_noop_when_continue_processing_raises(self):
        """add() must not propagate if the continue_processing property raises."""

        class BoomDenied:
            executions = []

            @property
            def continue_processing(self):
                raise RuntimeError("descriptor error")

        acc = ControlTelemetryAccumulator()
        acc.add(BoomDenied(), hook="pre")  # must not raise
        # Denial is not recorded when the read itself fails (safe default: not denied)
        assert acc.pre_denied is False
        assert acc.records == []


class TestAccumulatorCap:
    def test_cap_enforced_at_max_records_per_call(self):
        acc = ControlTelemetryAccumulator()
        for _ in range(_MAX_RECORDS_PER_CALL + 5):
            acc.add(_make_result([_make_rec()]), hook="pre")
        assert len(acc.records) == _MAX_RECORDS_PER_CALL
        assert acc.truncated == 5

    def test_truncated_counter(self):
        acc = ControlTelemetryAccumulator()
        for _ in range(_MAX_RECORDS_PER_CALL + 3):
            acc.add(_make_result([_make_rec()]), hook="pre")
        assert acc.truncated == 3


class TestAccumulatorDenied:
    def test_pre_denied_flag(self):
        acc = ControlTelemetryAccumulator()
        result = _make_result([], continue_processing=False)
        acc.add(result, hook="pre")
        assert acc.pre_denied is True
        assert acc.post_denied is False

    def test_post_denied_flag(self):
        acc = ControlTelemetryAccumulator()
        result = _make_result([], continue_processing=False)
        acc.add(result, hook="post")
        assert acc.post_denied is True
        assert acc.pre_denied is False

    def test_effective_allowed_when_neither_denied(self):
        acc = ControlTelemetryAccumulator()
        assert acc.effective_allowed is True

    def test_effective_allowed_false_when_pre_denied(self):
        acc = ControlTelemetryAccumulator()
        result = _make_result([], continue_processing=False)
        acc.add(result, hook="pre")
        assert acc.effective_allowed is False

    def test_effective_allowed_false_when_post_denied(self):
        acc = ControlTelemetryAccumulator()
        result = _make_result([], continue_processing=False)
        acc.add(result, hook="post")
        assert acc.effective_allowed is False


# ---------------------------------------------------------------------------
# ControlTelemetryAccumulator.aggregate()
# ---------------------------------------------------------------------------


class TestAggregate:
    def _make_acc_with_records(self, recs):
        acc = ControlTelemetryAccumulator()
        for hook, rec in recs:
            acc.add(_make_result([rec]), hook=hook)
        return acc

    def test_invocation_count(self):
        acc = self._make_acc_with_records([("pre", _make_rec()), ("pre", _make_rec())])
        assert acc.aggregate()["cpex.control.invocation_count"] == 2

    def test_invocation_count_excludes_skipped_disabled_cancelled(self):
        """invocation_count only counts completed/error/timeout — not skipped/disabled/cancelled."""
        completed = _make_rec(status="completed")
        skipped = _make_rec(status="skipped")
        disabled = _make_rec(status="disabled")
        cancelled = _make_rec(status="cancelled")
        acc = self._make_acc_with_records([
            ("pre", completed), ("pre", skipped), ("pre", disabled), ("pre", cancelled),
        ])
        assert acc.aggregate()["cpex.control.invocation_count"] == 1  # only completed counts

    def test_matched_count(self):
        r1 = _make_rec(matched=True)
        r2 = _make_rec(matched=False)
        r3 = _make_rec(matched=None)
        acc = self._make_acc_with_records([("pre", r1), ("pre", r2), ("pre", r3)])
        assert acc.aggregate()["cpex.control.matched_count"] == 1

    def test_applied_count(self):
        r1 = _make_rec(applied=True)
        r2 = _make_rec(applied=False)
        acc = self._make_acc_with_records([("pre", r1), ("pre", r2)])
        assert acc.aggregate()["cpex.control.applied_count"] == 1

    def test_duration_sum(self):
        r1 = _make_rec(duration_ns=1000)
        r2 = _make_rec(duration_ns=2000)
        acc = self._make_acc_with_records([("pre", r1), ("post", r2)])
        assert acc.aggregate()["cpex.control.duration_ns"] == 3000

    def test_error_count(self):
        r1 = _make_rec(status="error")
        r2 = _make_rec(status="completed")
        acc = self._make_acc_with_records([("pre", r1), ("pre", r2)])
        assert acc.aggregate()["cpex.control.error_count"] == 1

    def test_timeout_count(self):
        r1 = _make_rec(status="timeout")
        r2 = _make_rec(status="completed")
        acc = self._make_acc_with_records([("pre", r1), ("pre", r2)])
        assert acc.aggregate()["cpex.control.timeout_count"] == 1

    def test_result_allowed_false_when_pre_denied(self):
        acc = ControlTelemetryAccumulator()
        acc.add(_make_result([], continue_processing=False), hook="pre")
        assert acc.aggregate()["cpex.control.result.allowed"] is False

    def test_result_allowed_false_when_post_denied(self):
        acc = ControlTelemetryAccumulator()
        acc.add(_make_result([], continue_processing=False), hook="post")
        assert acc.aggregate()["cpex.control.result.allowed"] is False

    def test_malformed_record_skipped_without_raising(self):
        """A bad record (raises on attribute access) should not abort aggregate()."""
        acc = ControlTelemetryAccumulator()
        bad_rec = MagicMock()
        bad_rec.matched = property(lambda self: (_ for _ in ()).throw(RuntimeError("oops")))
        acc._records.append(("pre", bad_rec))  # pylint: disable=protected-access
        agg = acc.aggregate()
        assert "cpex.control.invocation_count" in agg


# ---------------------------------------------------------------------------
# aggregate() — inner exception path (lines 192-193)
# ---------------------------------------------------------------------------


class TestAggregateExceptionPath:
    def test_record_raising_on_duration_ns_is_skipped(self):
        """Lines 192-193: record raising during aggregation is caught; others still counted."""
        acc = ControlTelemetryAccumulator()
        # Make a record whose duration_ns property raises — status read is first, so it
        # will increment invocation_count before raising.  Verify the exception is caught
        # and the good sibling record still contributes its duration.
        bad = MagicMock()
        bad.matched = True
        bad.applied = False
        bad.status = "completed"
        bad.duration_ns = property(lambda self: (_ for _ in ()).throw(ValueError("bad")))
        good = _make_rec(status="completed", duration_ns=100)
        acc._records.append(("pre", bad))   # pylint: disable=protected-access
        acc._records.append(("pre", good))  # pylint: disable=protected-access
        agg = acc.aggregate()
        # bad record was counted (status read succeeded) but its duration is 0 (exception caught)
        # good record adds its duration
        assert agg["cpex.control.invocation_count"] == 2
        assert agg["cpex.control.duration_ns"] == 100


# ---------------------------------------------------------------------------
# _per_control_attributes
# ---------------------------------------------------------------------------


class TestPerControlAttributes:
    def test_completed_allow(self):
        rec = _make_rec(status="completed", effective_allow=True, duration_ns=500)
        attrs = _per_control_attributes("pre", rec)
        assert attrs["cpex.control.status"] == "completed"
        assert attrs["cpex.control.result.allowed"] is True
        assert attrs["cpex.control.duration_ns"] == 500
        assert attrs["cpex.control.enforcement_point"] == "pre"
        # New fields added in review response
        assert "cpex.control.plugin_id" in attrs
        assert "cpex.control.plugin_kind" in attrs
        assert "cpex.control.matched" in attrs
        assert "cpex.control.applied" in attrs
        assert "cpex.control.payload_modified" in attrs

    def test_completed_deny_with_reason(self):
        rec = _make_rec(effective_allow=False, reason="PII detected")
        # reason is only emitted when CPEX_CONTROL_TELEMETRY_EMIT_REASON=true
        with patch("mcpgateway.plugins.control_telemetry._emit_reason_enabled", return_value=True):
            attrs = _per_control_attributes("pre", rec)
        assert attrs["cpex.control.result.allowed"] is False
        assert attrs["cpex.control.result.reason"] == "PII detected"

    def test_error_status(self):
        rec = _make_rec(status="error", error_code="PLUGIN_ERROR")
        # error_code is only emitted when CPEX_CONTROL_TELEMETRY_EMIT_REASON=true
        with patch("mcpgateway.plugins.control_telemetry._emit_reason_enabled", return_value=True):
            attrs = _per_control_attributes("pre", rec)
        assert attrs["cpex.control.status"] == "error"
        assert attrs["cpex.control.result.error_code"] == "PLUGIN_ERROR"

    def test_timeout_status(self):
        rec = _make_rec(status="timeout")
        attrs = _per_control_attributes("pre", rec)
        assert attrs["cpex.control.status"] == "timeout"

    def test_faf_mode(self):
        rec = _make_rec(mode="fire_and_forget", duration_ns=0)
        attrs = _per_control_attributes("post", rec)
        assert attrs["cpex.control.mode"] == "fire_and_forget"
        assert attrs["cpex.control.duration_ns"] == 0

    def test_missing_optional_fields_omitted(self):
        rec = _make_rec(reason=None, error_code=None, config_keys=[])
        attrs = _per_control_attributes("pre", rec)
        assert "cpex.control.result.reason" not in attrs
        assert "cpex.control.result.error_code" not in attrs
        assert "cpex.control.config.keys" not in attrs

    def test_reason_omitted_when_flag_disabled(self):
        """reason is not emitted when emit_reason=False (default), even when present."""
        rec = _make_rec(reason="sensitive", error_code="E01")
        with patch("mcpgateway.plugins.control_telemetry._emit_reason_enabled", return_value=False):
            attrs = _per_control_attributes("pre", rec)
        assert "cpex.control.result.reason" not in attrs
        assert "cpex.control.result.error_code" not in attrs

    def test_reason_truncated_to_256(self):
        rec = _make_rec(reason="x" * 300)
        with patch("mcpgateway.plugins.control_telemetry._emit_reason_enabled", return_value=True):
            attrs = _per_control_attributes("pre", rec)
        assert len(attrs["cpex.control.result.reason"].encode("utf-8")) <= 256

    def test_config_keys_bounded(self):
        rec = _make_rec(config_keys=[f"key{i}" for i in range(_MAX_CONFIG_KEYS + 10)])
        attrs = _per_control_attributes("pre", rec)
        parts = attrs["cpex.control.config.keys"].split(",")
        assert len(parts) == _MAX_CONFIG_KEYS

    def test_returns_empty_on_attribute_error(self):
        # rec missing plugin_name entirely
        attrs = _per_control_attributes("pre", MagicMock(spec=[]))
        assert attrs == {}


# ---------------------------------------------------------------------------
# _safe_str
# ---------------------------------------------------------------------------


class TestSafeStr:
    def test_within_limit_unchanged(self):
        assert _safe_str("hello", 10) == "hello"

    def test_requested_allow_emitted_when_not_none(self):
        rec = _make_rec()
        rec.requested_allow = True
        attrs = _per_control_attributes("pre", rec)
        assert attrs.get("cpex.control.result.requested_allowed") is True

    def test_requested_allow_omitted_when_none(self):
        rec = _make_rec()
        rec.requested_allow = None
        attrs = _per_control_attributes("pre", rec)
        assert "cpex.control.result.requested_allowed" not in attrs

    def test_truncated_with_ellipsis(self):
        result = _safe_str("a" * 100, 10)
        assert result.endswith("...")
        assert len(result.encode("utf-8")) <= 10

    def test_non_string_coerced(self):
        assert _safe_str(42, 20) == "42"

    def test_exact_limit_boundary(self):
        s = "a" * 10
        assert _safe_str(s, 10) == s


# ---------------------------------------------------------------------------
# _enforcement_point
# ---------------------------------------------------------------------------


class TestEnforcementPoint:
    def _acc(self, pre: bool = False, post: bool = False):
        acc = ControlTelemetryAccumulator()
        if pre:
            acc._records.append(("pre", _make_rec()))    # pylint: disable=protected-access
        if post:
            acc._records.append(("post", _make_rec()))   # pylint: disable=protected-access
        return acc

    def test_pre_only(self):
        assert _enforcement_point(self._acc(pre=True)) == "pre"

    def test_post_only(self):
        assert _enforcement_point(self._acc(post=True)) == "post"

    def test_pre_and_post(self):
        assert _enforcement_point(self._acc(pre=True, post=True)) == "pre+post"

    def test_neither(self):
        assert _enforcement_point(self._acc()) == "none"


# ---------------------------------------------------------------------------
# _get_max_results — exception path (lines 484-485)
# ---------------------------------------------------------------------------


class TestGetMaxResultsExceptionPath:
    def test_returns_default_when_settings_raises(self):
        """Lines 484-485: if settings access raises, _get_max_results returns 32."""
        mock_settings = MagicMock()
        # Make getattr(settings, "cpex_control_telemetry_max_results", 32) return an
        # object that raises when int() is called on it — that hits the except branch.
        mock_settings.cpex_control_telemetry_max_results = "not-an-int-\x00"
        original = cfg_mod.settings
        try:
            cfg_mod.settings = mock_settings
            result = _get_max_results()
        finally:
            cfg_mod.settings = original
        assert result == 32


# ---------------------------------------------------------------------------
# _build_flattened_attributes
# ---------------------------------------------------------------------------


class TestBuildFlattenedAttributes:
    def test_basic_flatten(self):
        acc = ControlTelemetryAccumulator()
        acc.add(_make_result([_make_rec(plugin_name="pii_guard", status="completed", effective_allow=True, duration_ns=1000)]), hook="pre")
        flat = _build_flattened_attributes(acc, 32)
        assert "cpex.control.results.pii_guard.status" in flat
        assert flat["cpex.control.results.pii_guard.status"] == "completed"
        assert flat["cpex.control.results.pii_guard.result.allowed"] is True
        # duration key must use _ns suffix — item 3 fix
        assert "cpex.control.results.pii_guard.duration_ns" in flat
        assert flat["cpex.control.results.pii_guard.duration_ns"] == 1000
        assert "cpex.control.results.pii_guard.duration" not in flat
        assert flat["cpex.control.results.pii_guard.enforcement_point"] == "pre"
        # name field must be present — item 2 fix
        assert flat["cpex.control.results.pii_guard.name"] == "pii_guard"

    def test_invalid_name_skipped(self):
        """plugin_name with spaces/special chars is dropped from flattening."""
        acc = ControlTelemetryAccumulator()
        acc._records.append(("pre", _make_rec(plugin_name="bad name!")))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        assert not any("bad" in k for k in flat)

    def test_collision_drops_both_and_emits_counter(self):
        """Two records with the same plugin_name cause both to be dropped."""
        acc = ControlTelemetryAccumulator()
        acc._records.append(("pre", _make_rec(plugin_name="myctrl")))   # pylint: disable=protected-access
        acc._records.append(("post", _make_rec(plugin_name="myctrl")))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        assert not any("cpex.control.results.myctrl." in k for k in flat)
        assert flat.get("cpex.control.results._collision_count", 0) >= 1

    def test_reason_included_when_present(self):
        acc = ControlTelemetryAccumulator()
        acc._records.append(("pre", _make_rec(plugin_name="pii_guard", reason="PII found")))  # pylint: disable=protected-access
        with patch("mcpgateway.plugins.control_telemetry._emit_reason_enabled", return_value=True):
            flat = _build_flattened_attributes(acc, 32)
        assert flat.get("cpex.control.results.pii_guard.result.reason") == "PII found"

    def test_reason_omitted_when_none(self):
        acc = ControlTelemetryAccumulator()
        acc._records.append(("pre", _make_rec(plugin_name="pii_guard", reason=None)))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        assert "cpex.control.results.pii_guard.result.reason" not in flat

    def test_bounded_by_max_results(self):
        """Only up to max_results records are flattened."""
        acc = ControlTelemetryAccumulator()
        for i in range(10):
            acc._records.append(("pre", _make_rec(plugin_name=f"ctrl{i}")))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 3)
        flattened_names = {k.split(".")[3] for k in flat if k.startswith("cpex.control.results.") and not k.endswith("_collision_count")}
        assert len(flattened_names) == 3

    def test_empty_accumulator_returns_empty(self):
        flat = _build_flattened_attributes(ControlTelemetryAccumulator(), 32)
        assert flat == {}


# ---------------------------------------------------------------------------
# _build_flattened_attributes — error_code branch + per-record except + outer except
# (lines 553-555, 561-563)
# ---------------------------------------------------------------------------


class TestBuildFlattenedAttributesEdgeCases:
    def test_error_code_included_when_present(self):
        """error_code branch emits the attribute when emit_reason=True."""
        acc = ControlTelemetryAccumulator()
        acc._records.append(("pre", _make_rec(plugin_name="guard", error_code="TIMEOUT")))  # pylint: disable=protected-access
        with patch("mcpgateway.plugins.control_telemetry._emit_reason_enabled", return_value=True):
            flat = _build_flattened_attributes(acc, 32)
        assert flat.get("cpex.control.results.guard.result.error_code") == "TIMEOUT"

    def test_per_record_exception_is_caught(self):
        """Lines 554-555: exception inside per-record block is caught; other records continue."""
        acc = ControlTelemetryAccumulator()
        bad = MagicMock()
        bad.plugin_name = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        good_rec = _make_rec(plugin_name="good_ctrl", status="completed")
        acc._records.append(("pre", bad))        # pylint: disable=protected-access
        acc._records.append(("pre", good_rec))   # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        assert "cpex.control.results.good_ctrl.status" in flat

    def test_outer_exception_returns_empty(self):
        """Lines 561-563: if the outer try raises, returns {}."""

        class ExplodingAcc:
            @property
            def records(self):
                raise RuntimeError("outer explode")

        result = _build_flattened_attributes(ExplodingAcc(), 32)  # type: ignore[arg-type]
        assert result == {}


# ---------------------------------------------------------------------------
# Item 2 — artifact fields in _per_control_attributes and flattened projection
# ---------------------------------------------------------------------------


class TestArtifactFieldsInPerControlAttributes:
    """_per_control_attributes emits cpex.control.artifact.* when the record has them."""

    def test_artifact_name_emitted_when_present(self):
        rec = _make_rec()
        rec.artifact_name = "my-artifact"
        rec.artifact_id = None
        attrs = _per_control_attributes("pre", rec)
        assert attrs.get("cpex.control.artifact.name") == "my-artifact"
        assert "cpex.control.artifact.id" not in attrs

    def test_artifact_id_emitted_when_present(self):
        rec = _make_rec()
        rec.artifact_name = None
        rec.artifact_id = "artifact-123"
        attrs = _per_control_attributes("pre", rec)
        assert attrs.get("cpex.control.artifact.id") == "artifact-123"
        assert "cpex.control.artifact.name" not in attrs

    def test_both_artifact_fields_emitted(self):
        rec = _make_rec()
        rec.artifact_name = "svc-a"
        rec.artifact_id = "id-xyz"
        attrs = _per_control_attributes("pre", rec)
        assert attrs["cpex.control.artifact.name"] == "svc-a"
        assert attrs["cpex.control.artifact.id"] == "id-xyz"

    def test_artifact_fields_absent_when_not_on_record(self):
        """Records without artifact fields (older CPEX) must not emit artifact attrs."""
        rec = _make_rec()
        # Simulate a record that has no artifact_name / artifact_id attributes at all
        del rec.artifact_name  # MagicMock deletion makes getattr return default
        del rec.artifact_id
        attrs = _per_control_attributes("pre", rec)
        assert "cpex.control.artifact.name" not in attrs
        assert "cpex.control.artifact.id" not in attrs

    def test_artifact_name_truncated_to_128(self):
        rec = _make_rec()
        rec.artifact_name = "x" * 200
        rec.artifact_id = None
        attrs = _per_control_attributes("pre", rec)
        assert len(attrs["cpex.control.artifact.name"].encode("utf-8")) <= 128


class TestArtifactFieldsInFlattenedAttributes:
    """_build_flattened_attributes emits artifact.name/id + config.keys + name fields."""

    def test_artifact_name_in_flattened(self):
        acc = ControlTelemetryAccumulator()
        rec = _make_rec(plugin_name="guard")
        rec.artifact_name = "my-svc"
        rec.artifact_id = None
        acc._records.append(("pre", rec))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        assert flat.get("cpex.control.results.guard.artifact.name") == "my-svc"
        assert "cpex.control.results.guard.artifact.id" not in flat

    def test_artifact_id_in_flattened(self):
        acc = ControlTelemetryAccumulator()
        rec = _make_rec(plugin_name="guard")
        rec.artifact_name = None
        rec.artifact_id = "id-42"
        acc._records.append(("pre", rec))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        assert flat.get("cpex.control.results.guard.artifact.id") == "id-42"

    def test_config_keys_in_flattened(self):
        acc = ControlTelemetryAccumulator()
        rec = _make_rec(plugin_name="guard", config_keys=["key1", "key2"])
        rec.artifact_name = None
        rec.artifact_id = None
        acc._records.append(("pre", rec))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        assert flat.get("cpex.control.results.guard.config.keys") == "key1,key2"

    def test_name_field_in_flattened(self):
        acc = ControlTelemetryAccumulator()
        rec = _make_rec(plugin_name="rate_limit")
        rec.artifact_name = None
        rec.artifact_id = None
        acc._records.append(("pre", rec))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        assert flat.get("cpex.control.results.rate_limit.name") == "rate_limit"


# ---------------------------------------------------------------------------
# Item 3 — duration_ns key in flattened projection (no bare .duration key)
# ---------------------------------------------------------------------------


class TestFlattenedDurationKey:
    """Flattened projection must use .duration_ns, never .duration."""

    def test_duration_ns_key_present(self):
        acc = ControlTelemetryAccumulator()
        rec = _make_rec(plugin_name="ctrl", duration_ns=9876)
        rec.artifact_name = None
        rec.artifact_id = None
        acc._records.append(("pre", rec))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        assert flat["cpex.control.results.ctrl.duration_ns"] == 9876

    def test_bare_duration_key_absent(self):
        acc = ControlTelemetryAccumulator()
        rec = _make_rec(plugin_name="ctrl")
        rec.artifact_name = None
        rec.artifact_id = None
        acc._records.append(("pre", rec))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        assert "cpex.control.results.ctrl.duration" not in flat


# ---------------------------------------------------------------------------
# Item 4 — mark_denied() and per-hook truncation counter
# ---------------------------------------------------------------------------


class TestMarkDenied:
    """mark_denied() sets the correct denial flag without requiring add() to run."""

    def test_mark_denied_pre_sets_pre_denied(self):
        acc = ControlTelemetryAccumulator()
        acc.mark_denied(hook="pre")
        assert acc.pre_denied is True
        assert acc.post_denied is False

    def test_mark_denied_post_sets_post_denied(self):
        acc = ControlTelemetryAccumulator()
        acc.mark_denied(hook="post")
        assert acc.post_denied is True
        assert acc.pre_denied is False

    def test_effective_allowed_false_after_pre_deny(self):
        acc = ControlTelemetryAccumulator()
        acc.mark_denied(hook="pre")
        assert acc.effective_allowed is False

    def test_effective_allowed_false_after_post_deny(self):
        acc = ControlTelemetryAccumulator()
        acc.mark_denied(hook="post")
        assert acc.effective_allowed is False

    def test_mark_denied_with_no_records_still_triggers_telemetry(self):
        """Accumulator with no records but pre_denied=True is non-empty for telemetry gate."""
        acc = ControlTelemetryAccumulator()
        acc.mark_denied(hook="pre")
        # record_control_telemetry gates on: not records AND not pre_denied AND not post_denied
        assert acc.pre_denied is True  # telemetry will NOT be skipped

    def test_mark_denied_then_add_still_works(self):
        """mark_denied does not break subsequent add() calls for partial records."""
        acc = ControlTelemetryAccumulator()
        acc.mark_denied(hook="pre")
        result = _make_result([_make_rec(status="completed")])
        acc.add(result, hook="pre")
        assert len(acc.records) == 1
        assert acc.pre_denied is True

    def test_aggregate_result_allowed_false_when_mark_denied(self):
        """aggregate() must emit cpex.control.result.allowed=False after mark_denied."""
        acc = ControlTelemetryAccumulator()
        acc.mark_denied(hook="pre")
        agg = acc.aggregate()
        assert agg["cpex.control.result.allowed"] is False


class TestPerHookTruncationCounter:
    """add() must count records dropped at the per-hook cap (_MAX_RECORDS_PER_HOOK=64)."""

    def test_per_hook_overflow_increments_truncated(self):
        """Records beyond _MAX_RECORDS_PER_HOOK are counted in _truncated."""
        acc = ControlTelemetryAccumulator()
        # Build 70 records — 64 allowed per hook, 6 should be truncated
        records = [_make_rec(plugin_name=f"ctrl{i}") for i in range(70)]
        result = _make_result(records)
        acc.add(result, hook="pre")
        assert len(acc.records) == 64
        assert acc.truncated == 6

    def test_per_hook_exactly_at_cap_not_truncated(self):
        """Exactly _MAX_RECORDS_PER_HOOK records — no truncation."""
        acc = ControlTelemetryAccumulator()
        records = [_make_rec(plugin_name=f"ctrl{i}") for i in range(64)]
        acc.add(_make_result(records), hook="pre")
        assert acc.truncated == 0
        assert len(acc.records) == 64

    def test_per_call_overflow_also_counted(self):
        """Records beyond _MAX_RECORDS_PER_CALL are also counted in truncated."""
        acc = ControlTelemetryAccumulator()
        # Fill to cap via two hooks of 64 each = 128 accepted, then add more
        first_batch = [_make_rec(plugin_name=f"pre{i}") for i in range(64)]
        second_batch = [_make_rec(plugin_name=f"post{i}") for i in range(64)]
        extra_batch = [_make_rec(plugin_name=f"extra{i}") for i in range(10)]
        acc.add(_make_result(first_batch), hook="pre")
        acc.add(_make_result(second_batch), hook="post")
        acc.add(_make_result(extra_batch), hook="post")
        assert len(acc.records) == _MAX_RECORDS_PER_CALL
        assert acc.truncated == 10


# ---------------------------------------------------------------------------
# Item 7 — tier-3 export-cap truncation accounting
# ---------------------------------------------------------------------------


class TestExportCapTruncation:
    """mark_export_cap_dropped() and record_control_telemetry() tier-3 drop accounting."""

    def test_mark_export_cap_dropped_adds_to_truncated(self):
        """mark_export_cap_dropped() must add to the truncated total."""
        acc = ControlTelemetryAccumulator()
        acc.mark_export_cap_dropped(5)
        assert acc.truncated == 5

    def test_mark_export_cap_dropped_zero_is_no_op(self):
        """Calling mark_export_cap_dropped(0) must not change truncated."""
        acc = ControlTelemetryAccumulator()
        acc.mark_export_cap_dropped(0)
        assert acc.truncated == 0

    def test_truncated_combines_all_three_tiers(self):
        """truncated = tier-1/2 accumulation drops + tier-3 export-cap drops."""
        acc = ControlTelemetryAccumulator()
        # Simulate tier-1/2 drops by directly incrementing the internal counter
        acc._truncated = 3  # pylint: disable=protected-access
        acc.mark_export_cap_dropped(4)
        assert acc.truncated == 7

    def test_record_control_telemetry_includes_export_cap_in_truncated(self):
        """When records_received > max_results, cpex.control.truncated reflects the tier-3 drop."""
        acc = ControlTelemetryAccumulator()
        # Load 10 records into the accumulator directly (bypass add() to avoid cpex dependency)
        for i in range(10):
            acc._records.append(("pre", _make_rec(plugin_name=f"ctrl{i}")))  # pylint: disable=protected-access

        captured_attributes: dict = {}

        def fake_start_span(**kwargs):
            if kwargs.get("name") == "cpex.control.summary":
                captured_attributes.update(kwargs.get("attributes", {}))
            return "span-id-123"

        mock_service = MagicMock()
        mock_service.start_span.side_effect = fake_start_span
        mock_service.end_span.return_value = None

        mock_settings = MagicMock()
        mock_settings.cpex_control_telemetry_enabled = True
        mock_settings.cpex_control_telemetry_db_enabled = True
        mock_settings.cpex_control_telemetry_flatten_results = False
        mock_settings.cpex_control_telemetry_max_results = 3  # cap at 3 out of 10

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal"),
            patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
            patch("mcpgateway.config.settings", mock_settings),
        ):
            record_control_telemetry("trace-abc", acc, tool_name="my_tool", agent_id="u@e.com", binding_name="gw")

        # 10 accumulated, 3 exported → 7 export-cap drops should be in truncated
        assert captured_attributes.get("cpex.control.truncated") == 7

    def test_no_truncated_attribute_when_no_drops(self):
        """cpex.control.truncated must be absent when records_received <= max_results."""
        acc = ControlTelemetryAccumulator()
        for i in range(2):
            acc._records.append(("pre", _make_rec(plugin_name=f"ctrl{i}")))  # pylint: disable=protected-access

        captured_attributes: dict = {}

        def fake_start_span(**kwargs):
            if kwargs.get("name") == "cpex.control.summary":
                captured_attributes.update(kwargs.get("attributes", {}))
            return "span-id-456"

        mock_service = MagicMock()
        mock_service.start_span.side_effect = fake_start_span
        mock_service.end_span.return_value = None

        mock_settings = MagicMock()
        mock_settings.cpex_control_telemetry_enabled = True
        mock_settings.cpex_control_telemetry_db_enabled = True
        mock_settings.cpex_control_telemetry_flatten_results = False
        mock_settings.cpex_control_telemetry_max_results = 32

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal"),
            patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
            patch("mcpgateway.config.settings", mock_settings),
        ):
            record_control_telemetry("trace-def", acc, tool_name="my_tool", agent_id="u@e.com", binding_name="gw")

        assert "cpex.control.truncated" not in captured_attributes

    def test_mark_export_cap_dropped_is_idempotent(self):
        """Calling mark_export_cap_dropped() more than once must not inflate truncated.

        Regression guard for the idempotency bug where repeated calls on the same
        accumulator (e.g. on a retry path) used += and doubled the count.
        """
        acc = ControlTelemetryAccumulator()
        acc.mark_export_cap_dropped(7)
        acc.mark_export_cap_dropped(7)  # second call must be a no-op
        acc.mark_export_cap_dropped(7)  # third call must also be a no-op
        assert acc.truncated == 7  # still 7, not 21

    def test_mark_export_cap_dropped_zero_then_positive(self):
        """Zero call does not lock the slot; a subsequent positive call must succeed."""
        acc = ControlTelemetryAccumulator()
        acc.mark_export_cap_dropped(0)  # no-op — must not consume the single-write slot
        acc.mark_export_cap_dropped(4)  # first positive call — must succeed
        acc.mark_export_cap_dropped(4)  # second call — must be a no-op
        assert acc.truncated == 4


# ---------------------------------------------------------------------------
# Item 6/7 — records_received counter in aggregate()
# ---------------------------------------------------------------------------


class TestAggregateRecordsReceived:
    """aggregate() must emit cpex.control.records_received — total before export cap."""

    def _make_acc(self, n: int, status: str = "completed") -> ControlTelemetryAccumulator:
        acc = ControlTelemetryAccumulator()
        for i in range(n):
            acc.add(_make_result([_make_rec(plugin_name=f"ctrl{i}", status=status)]), hook="pre")
        return acc

    def test_records_received_equals_accumulated_count(self):
        acc = self._make_acc(5)
        agg = acc.aggregate()
        assert agg["cpex.control.records_received"] == 5

    def test_records_received_zero_when_empty(self):
        acc = ControlTelemetryAccumulator()
        agg = acc.aggregate()
        assert agg["cpex.control.records_received"] == 0

    def test_records_received_includes_skipped_disabled_cancelled(self):
        """records_received counts ALL accumulated records, including non-active statuses."""
        acc = ControlTelemetryAccumulator()
        acc.add(_make_result([
            _make_rec(plugin_name="a", status="completed"),
            _make_rec(plugin_name="b", status="skipped"),
            _make_rec(plugin_name="c", status="disabled"),
            _make_rec(plugin_name="d", status="cancelled"),
        ]), hook="pre")
        agg = acc.aggregate()
        assert agg["cpex.control.records_received"] == 4
        # invocation_count only counts active statuses
        assert agg["cpex.control.invocation_count"] == 1

    def test_results_count_capped_at_max_results(self):
        """results_count = min(records_received, max_results)."""
        import mcpgateway.config as cfg_mod  # noqa: PLC0415
        mock_settings = MagicMock()
        mock_settings.cpex_control_telemetry_max_results = 3
        original = cfg_mod.settings
        try:
            cfg_mod.settings = mock_settings
            acc = self._make_acc(10)
            agg = acc.aggregate()
        finally:
            cfg_mod.settings = original
        assert agg["cpex.control.records_received"] == 10
        assert agg["cpex.control.results_count"] == 3

    def test_records_received_present_in_aggregate_keys(self):
        """records_received is always in the aggregate dict."""
        agg = ControlTelemetryAccumulator().aggregate()
        assert "cpex.control.records_received" in agg


# ---------------------------------------------------------------------------
# Item 9 — CPEX_CONTROL_TELEMETRY_EMIT_REASON gates reason/error_code
# ---------------------------------------------------------------------------


class TestEmitReasonFlag:
    """result.reason and result.error_code are only emitted when emit_reason=True."""

    def _attrs_with_reason_flag(self, flag: bool) -> dict:
        rec = _make_rec(reason="PII found", error_code="DENY_001")
        import mcpgateway.config as cfg_mod  # noqa: PLC0415
        mock_settings = MagicMock()
        mock_settings.cpex_control_telemetry_emit_reason = flag
        original = cfg_mod.settings
        try:
            cfg_mod.settings = mock_settings
            return _per_control_attributes("pre", rec)
        finally:
            cfg_mod.settings = original

    def test_reason_absent_by_default(self):
        """result.reason must not appear when emit_reason=False (default)."""
        attrs = self._attrs_with_reason_flag(False)
        assert "cpex.control.result.reason" not in attrs
        assert "cpex.control.result.error_code" not in attrs

    def test_reason_present_when_flag_enabled(self):
        """result.reason and result.error_code appear when emit_reason=True."""
        attrs = self._attrs_with_reason_flag(True)
        assert attrs.get("cpex.control.result.reason") == "PII found"
        assert attrs.get("cpex.control.result.error_code") == "DENY_001"

    def test_reason_absent_from_flattened_by_default(self):
        """Flattened projection also respects emit_reason=False."""
        acc = ControlTelemetryAccumulator()
        rec = _make_rec(plugin_name="guard", reason="sensitive text", error_code="E001")
        rec.artifact_name = None
        rec.artifact_id = None
        acc._records.append(("pre", rec))  # pylint: disable=protected-access
        import mcpgateway.config as cfg_mod  # noqa: PLC0415
        mock_settings = MagicMock()
        mock_settings.cpex_control_telemetry_emit_reason = False
        original = cfg_mod.settings
        try:
            cfg_mod.settings = mock_settings
            flat = _build_flattened_attributes(acc, 32)
        finally:
            cfg_mod.settings = original
        assert "cpex.control.results.guard.result.reason" not in flat
        assert "cpex.control.results.guard.result.error_code" not in flat

    def test_reason_present_in_flattened_when_flag_enabled(self):
        """Flattened projection emits reason/error_code when emit_reason=True."""
        acc = ControlTelemetryAccumulator()
        rec = _make_rec(plugin_name="guard", reason="deny reason", error_code="E002")
        rec.artifact_name = None
        rec.artifact_id = None
        acc._records.append(("pre", rec))  # pylint: disable=protected-access
        import mcpgateway.config as cfg_mod  # noqa: PLC0415
        mock_settings = MagicMock()
        mock_settings.cpex_control_telemetry_emit_reason = True
        original = cfg_mod.settings
        try:
            cfg_mod.settings = mock_settings
            flat = _build_flattened_attributes(acc, 32)
        finally:
            cfg_mod.settings = original
        assert flat.get("cpex.control.results.guard.result.reason") == "deny reason"
        assert flat.get("cpex.control.results.guard.result.error_code") == "E002"

    def test_emit_reason_enabled_returns_bool(self):
        """_emit_reason_enabled() always returns a plain bool."""
        from mcpgateway.plugins.control_telemetry import _emit_reason_enabled  # noqa: PLC0415
        assert isinstance(_emit_reason_enabled(), bool)

    def test_emit_reason_enabled_default_false(self):
        """Default value is False when setting is absent."""
        from mcpgateway.plugins.control_telemetry import _emit_reason_enabled  # noqa: PLC0415
        import mcpgateway.config as cfg_mod  # noqa: PLC0415
        mock_settings = MagicMock(spec=[])  # no cpex_control_telemetry_emit_reason attr
        original = cfg_mod.settings
        try:
            cfg_mod.settings = mock_settings
            result = _emit_reason_enabled()
        finally:
            cfg_mod.settings = original
        assert result is False


# ---------------------------------------------------------------------------
# Fix 4 — mark_plugin_error() and cpex.control.plugin_error flag
# ---------------------------------------------------------------------------


class TestMarkPluginError:
    """mark_plugin_error() sets the plugin_errored flag and bypasses the empty-accumulator guard."""

    def test_plugin_errored_false_by_default(self):
        acc = ControlTelemetryAccumulator()
        assert acc.plugin_errored is False

    def test_mark_plugin_error_sets_flag(self):
        acc = ControlTelemetryAccumulator()
        acc.mark_plugin_error()
        assert acc.plugin_errored is True

    def test_effective_allowed_unchanged_after_plugin_error(self):
        """PluginError does NOT set effective_allowed=False — it stays True."""
        acc = ControlTelemetryAccumulator()
        acc.mark_plugin_error()
        assert acc.effective_allowed is True

    def test_aggregate_emits_plugin_error_true_when_flagged(self):
        acc = ControlTelemetryAccumulator()
        acc.mark_plugin_error()
        agg = acc.aggregate()
        assert agg.get("cpex.control.plugin_error") is True

    def test_aggregate_omits_plugin_error_when_not_flagged(self):
        acc = ControlTelemetryAccumulator()
        agg = acc.aggregate()
        assert "cpex.control.plugin_error" not in agg

    def test_plugin_error_flag_bypasses_empty_accumulator_guard(self):
        """record_control_telemetry() must emit a summary span even with an empty accumulator
        when plugin_errored=True (first-plugin failure path)."""
        acc = ControlTelemetryAccumulator()
        acc.mark_plugin_error()
        # No records, no denial — only the error flag

        captured_attributes: dict = {}

        def fake_start_span(**kwargs):
            if kwargs.get("name") == "cpex.control.summary":
                captured_attributes.update(kwargs.get("attributes", {}))
            return "span-id-plugin-err"

        mock_service = MagicMock()
        mock_service.start_span.side_effect = fake_start_span
        mock_service.end_span.return_value = None

        mock_settings = MagicMock()
        mock_settings.cpex_control_telemetry_enabled = True
        mock_settings.cpex_control_telemetry_db_enabled = True
        mock_settings.cpex_control_telemetry_flatten_results = False
        mock_settings.cpex_control_telemetry_max_results = 32

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal"),
            patch("mcpgateway.plugins.control_telemetry._emit_otel_spans"),
            patch("mcpgateway.config.settings", mock_settings),
        ):
            record_control_telemetry("trace-plugin-err", acc, tool_name="my_tool", agent_id="u@e.com", binding_name="gw")

        # Summary span must be emitted and carry plugin_error=True
        assert captured_attributes, "Expected a summary span to be emitted for a first-plugin PluginError"
        assert captured_attributes.get("cpex.control.plugin_error") is True
        # result.allowed must be ABSENT — the decision is indeterminate when a PluginError
        # fires with no denial flag set.  Dashboards must treat absence as "unknown".
        assert "cpex.control.result.allowed" not in captured_attributes, (
            "cpex.control.result.allowed must be absent when decision is indeterminate (PluginError, no denial)"
        )


# ---------------------------------------------------------------------------
# Fix 3 — _enforcement_point uses denial flags when records are empty
# ---------------------------------------------------------------------------


class TestEnforcementPointDenialFlags:
    """_enforcement_point() must use pre_denied/post_denied when no records exist."""

    def test_enforcement_point_pre_from_flag_no_records(self):
        """mark_denied(hook='pre') with no records should yield enforcement_point='pre'."""
        from mcpgateway.plugins.control_telemetry import _enforcement_point  # noqa: PLC0415
        acc = ControlTelemetryAccumulator()
        acc.mark_denied(hook="pre")
        assert _enforcement_point(acc) == "pre"

    def test_enforcement_point_post_from_flag_no_records(self):
        from mcpgateway.plugins.control_telemetry import _enforcement_point  # noqa: PLC0415
        acc = ControlTelemetryAccumulator()
        acc.mark_denied(hook="post")
        assert _enforcement_point(acc) == "post"

    def test_enforcement_point_none_no_records_no_flags(self):
        from mcpgateway.plugins.control_telemetry import _enforcement_point  # noqa: PLC0415
        acc = ControlTelemetryAccumulator()
        assert _enforcement_point(acc) == "none"


# ---------------------------------------------------------------------------
# _sanitize_config_key — charset validation and injection guards
# ---------------------------------------------------------------------------


class TestSanitizeConfigKey:
    """_sanitize_config_key() rejects unsafe key names, passes safe ones."""

    def test_valid_simple_key(self):
        assert _sanitize_config_key("my_key") == "my_key"

    def test_valid_key_with_dots_and_hyphens(self):
        assert _sanitize_config_key("some.key-name") == "some.key-name"

    def test_comma_rejected(self):
        """Commas are the CSV delimiter — must be rejected."""
        assert _sanitize_config_key("bad,key") is None

    def test_lf_rejected(self):
        """Newline is a log-injection vector."""
        assert _sanitize_config_key("bad\nkey") is None

    def test_cr_rejected(self):
        assert _sanitize_config_key("bad\rkey") is None

    def test_nul_rejected(self):
        assert _sanitize_config_key("bad\x00key") is None

    def test_tab_rejected(self):
        assert _sanitize_config_key("bad\tkey") is None

    def test_non_ascii_rejected(self):
        """Non-ASCII characters (e.g. CJK) must be rejected."""
        assert _sanitize_config_key("钥匙") is None

    def test_secret_marker_equals_rejected(self):
        """Secret-shaped keys like 'api_key=sk-abc123' contain '=' which is not in charset."""
        assert _sanitize_config_key("api_key=sk-abc123") is None

    def test_empty_string_rejected(self):
        assert _sanitize_config_key("") is None

    def test_oversized_key_rejected(self):
        """Keys longer than 64 chars are rejected by the regex (not just the byte cap)."""
        assert _sanitize_config_key("a" * 65) is None

    def test_max_length_key_accepted(self):
        """A key exactly 64 chars passes (the regex allows 1..64)."""
        assert _sanitize_config_key("a" * 64) is not None

    def test_per_control_attributes_drops_comma_key(self):
        """_per_control_attributes must drop a key with a comma from config.keys."""
        rec = _make_rec(plugin_name="ctrl")
        rec.config_keys = ["good_key", "bad,key", "another_good"]
        attrs = _per_control_attributes("pre", rec)
        val = attrs.get("cpex.control.config.keys", "")
        assert "bad,key" not in val
        assert "good_key" in val
        assert "another_good" in val

    def test_per_control_attributes_drops_crlf_key(self):
        """_per_control_attributes must drop keys with CR/LF."""
        rec = _make_rec(plugin_name="ctrl")
        rec.config_keys = ["safe_key", "inject\nkey"]
        attrs = _per_control_attributes("pre", rec)
        val = attrs.get("cpex.control.config.keys", "")
        assert "inject" not in val
        assert "safe_key" in val

    def test_per_control_attributes_all_keys_unsafe_omits_attribute(self):
        """When every key fails validation, config.keys must be absent."""
        rec = _make_rec(plugin_name="ctrl")
        rec.config_keys = ["bad,one", "bad\ntwo"]
        attrs = _per_control_attributes("pre", rec)
        assert "cpex.control.config.keys" not in attrs


# ---------------------------------------------------------------------------
# PluginError indeterminate decision semantics
# ---------------------------------------------------------------------------


class TestPluginErrorIndeterminate:
    """mark_plugin_error() makes result.allowed indeterminate; aggregate() must omit it."""

    def test_aggregate_omits_result_allowed_on_plugin_error(self):
        """result.allowed must be absent when plugin_errored=True and no denial."""
        acc = ControlTelemetryAccumulator()
        acc.mark_plugin_error(hook="pre")
        agg = acc.aggregate()
        assert "cpex.control.result.allowed" not in agg

    def test_aggregate_emits_result_allowed_false_when_also_denied(self):
        """If a denial flag is also set, denial takes precedence: emit result.allowed=False."""
        acc = ControlTelemetryAccumulator()
        acc.mark_plugin_error(hook="pre")
        acc.mark_denied(hook="pre")  # unusual but possible
        agg = acc.aggregate()
        assert agg.get("cpex.control.result.allowed") is False

    def test_aggregate_emits_result_allowed_true_without_error(self):
        """Normal (no error, no denial) still emits result.allowed=True."""
        acc = ControlTelemetryAccumulator()
        agg = acc.aggregate()
        assert agg.get("cpex.control.result.allowed") is True

    def test_mark_plugin_error_hook_tracked(self):
        """mark_plugin_error(hook=) stores the hook for enforcement_point derivation."""
        acc = ControlTelemetryAccumulator()
        acc.mark_plugin_error(hook="post")
        assert acc.plugin_error_hook == "post"

    def test_mark_plugin_error_unknown_hook_stored_as_empty(self):
        """Invalid hook values are silently ignored; plugin_error_hook stays empty."""
        acc = ControlTelemetryAccumulator()
        acc.mark_plugin_error(hook="unknown")
        assert acc.plugin_error_hook == ""

    def test_enforcement_point_uses_error_hook_pre(self):
        """_enforcement_point falls back to plugin_error_hook when no records/denial."""
        acc = ControlTelemetryAccumulator()
        acc.mark_plugin_error(hook="pre")
        assert _enforcement_point(acc) == "pre"

    def test_enforcement_point_uses_error_hook_post(self):
        acc = ControlTelemetryAccumulator()
        acc.mark_plugin_error(hook="post")
        assert _enforcement_point(acc) == "post"

    def test_enforcement_point_none_when_error_hook_empty(self):
        """When mark_plugin_error() called with no hook, enforcement_point is 'none'."""
        acc = ControlTelemetryAccumulator()
        acc.mark_plugin_error()
        assert _enforcement_point(acc) == "none"
