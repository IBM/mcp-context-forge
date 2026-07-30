# -*- coding: utf-8 -*-
"""Unit tests for mcpgateway/plugins/control_telemetry.py.

Location: ./tests/unit/mcpgateway/plugins/test_control_telemetry.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Covers:
  - ControlTelemetryAccumulator: empty init, add pre/post, caps, truncated, denied flags,
    effective_allowed, aggregate() semantics.
  - _per_control_attributes: completed allow/deny, error/timeout/faf, optional field omission,
    reason truncation, config_keys bounded.
  - _safe_str: within-limit unchanged, truncated with ellipsis.
  - _enforcement_point: pre/post/pre+post/none.
"""

# Standard
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
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
    duration_ns: int = 1000,
    reason: object = None,
    error_code: object = None,
    config_keys: list = None,
) -> MagicMock:
    """Create a minimal ControlExecutionRecord mock."""
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
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        assert acc.records == []
        assert acc.truncated == 0
        assert acc.pre_denied is False
        assert acc.post_denied is False
        assert acc.effective_allowed is True

    def test_aggregate_all_zeros_when_empty(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        agg = acc.aggregate()
        assert agg["cpex.control.invocation_count"] == 0
        assert agg["cpex.control.matched_count"] == 0
        assert agg["cpex.control.applied_count"] == 0
        assert agg["cpex.control.duration"] == 0
        assert agg["cpex.control.result.allowed"] is True
        assert agg["cpex.control.error_count"] == 0
        assert agg["cpex.control.timeout_count"] == 0


class TestAccumulatorAdd:
    def test_add_pre_only(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        result = _make_result([_make_rec()])
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            acc.add(result, hook="pre")
        assert len(acc.records) == 1
        assert acc.records[0][0] == "pre"

    def test_add_post_only(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        result = _make_result([_make_rec()])
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            acc.add(result, hook="post")
        assert len(acc.records) == 1
        assert acc.records[0][0] == "post"

    def test_add_pre_and_post(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            acc.add(_make_result([_make_rec()]), hook="pre")
            acc.add(_make_result([_make_rec()]), hook="post")
        assert len(acc.records) == 2

    def test_noop_when_records_unsupported(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=False):
            acc.add(_make_result([_make_rec()]), hook="pre")
        assert acc.records == []

    def test_noop_on_none_result(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            acc.add(None, hook="pre")
        assert acc.records == []


class TestAccumulatorCap:
    def test_cap_enforced_at_max_records_per_call(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator, _MAX_RECORDS_PER_CALL

        acc = ControlTelemetryAccumulator()
        # Fill up to the cap with individual adds
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            for _ in range(_MAX_RECORDS_PER_CALL + 5):
                acc.add(_make_result([_make_rec()]), hook="pre")
        assert len(acc.records) == _MAX_RECORDS_PER_CALL
        assert acc.truncated == 5

    def test_truncated_counter(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator, _MAX_RECORDS_PER_CALL

        acc = ControlTelemetryAccumulator()
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            for _ in range(_MAX_RECORDS_PER_CALL + 3):
                acc.add(_make_result([_make_rec()]), hook="pre")
        assert acc.truncated == 3


class TestAccumulatorDenied:
    def test_pre_denied_flag(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        result = _make_result([], continue_processing=False)
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            acc.add(result, hook="pre")
        assert acc.pre_denied is True
        assert acc.post_denied is False

    def test_post_denied_flag(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        result = _make_result([], continue_processing=False)
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            acc.add(result, hook="post")
        assert acc.post_denied is True
        assert acc.pre_denied is False

    def test_effective_allowed_when_neither_denied(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        assert acc.effective_allowed is True

    def test_effective_allowed_false_when_pre_denied(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        result = _make_result([], continue_processing=False)
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            acc.add(result, hook="pre")
        assert acc.effective_allowed is False

    def test_effective_allowed_false_when_post_denied(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        result = _make_result([], continue_processing=False)
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            acc.add(result, hook="post")
        assert acc.effective_allowed is False


# ---------------------------------------------------------------------------
# ControlTelemetryAccumulator.aggregate()
# ---------------------------------------------------------------------------


class TestAggregate:
    def _make_acc_with_records(self, recs):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            for hook, rec in recs:
                acc.add(_make_result([rec]), hook=hook)
        return acc

    def test_invocation_count(self):
        acc = self._make_acc_with_records([("pre", _make_rec()), ("pre", _make_rec())])
        assert acc.aggregate()["cpex.control.invocation_count"] == 2

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
        assert acc.aggregate()["cpex.control.duration"] == 3000

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
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            acc.add(_make_result([], continue_processing=False), hook="pre")
        assert acc.aggregate()["cpex.control.result.allowed"] is False

    def test_result_allowed_false_when_post_denied(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            acc.add(_make_result([], continue_processing=False), hook="post")
        assert acc.aggregate()["cpex.control.result.allowed"] is False

    def test_malformed_record_skipped_without_raising(self):
        """A bad record (raises on attribute access) should not abort aggregate()."""
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        bad_rec = MagicMock()
        bad_rec.matched = property(lambda self: (_ for _ in ()).throw(RuntimeError("oops")))
        # Manually inject so we bypass get_executions
        acc._records.append(("pre", bad_rec))  # pylint: disable=protected-access
        # Should not raise
        agg = acc.aggregate()
        assert "cpex.control.invocation_count" in agg


# ---------------------------------------------------------------------------
# _per_control_attributes
# ---------------------------------------------------------------------------


class TestPerControlAttributes:
    def test_completed_allow(self):
        from mcpgateway.plugins.control_telemetry import _per_control_attributes

        rec = _make_rec(status="completed", effective_allow=True, duration_ns=500)
        attrs = _per_control_attributes("pre", rec)
        assert attrs["cpex.control.status"] == "completed"
        assert attrs["cpex.control.result.allowed"] is True
        assert attrs["cpex.control.duration"] == 500
        assert attrs["cpex.control.enforcement_point"] == "pre"

    def test_completed_deny_with_reason(self):
        from mcpgateway.plugins.control_telemetry import _per_control_attributes

        rec = _make_rec(effective_allow=False, reason="PII detected")
        attrs = _per_control_attributes("pre", rec)
        assert attrs["cpex.control.result.allowed"] is False
        assert attrs["cpex.control.result.reason"] == "PII detected"

    def test_error_status(self):
        from mcpgateway.plugins.control_telemetry import _per_control_attributes

        rec = _make_rec(status="error", error_code="PLUGIN_ERROR")
        attrs = _per_control_attributes("pre", rec)
        assert attrs["cpex.control.status"] == "error"
        assert attrs["cpex.control.result.error_code"] == "PLUGIN_ERROR"

    def test_timeout_status(self):
        from mcpgateway.plugins.control_telemetry import _per_control_attributes

        rec = _make_rec(status="timeout")
        attrs = _per_control_attributes("pre", rec)
        assert attrs["cpex.control.status"] == "timeout"

    def test_faf_mode(self):
        from mcpgateway.plugins.control_telemetry import _per_control_attributes

        rec = _make_rec(mode="fire_and_forget", duration_ns=0)
        attrs = _per_control_attributes("post", rec)
        assert attrs["cpex.control.mode"] == "fire_and_forget"
        assert attrs["cpex.control.duration"] == 0

    def test_missing_optional_fields_omitted(self):
        from mcpgateway.plugins.control_telemetry import _per_control_attributes

        rec = _make_rec(reason=None, error_code=None, config_keys=[])
        attrs = _per_control_attributes("pre", rec)
        assert "cpex.control.result.reason" not in attrs
        assert "cpex.control.result.error_code" not in attrs
        assert "cpex.control.config.keys" not in attrs

    def test_reason_truncated_to_256(self):
        from mcpgateway.plugins.control_telemetry import _per_control_attributes

        rec = _make_rec(reason="x" * 300)
        attrs = _per_control_attributes("pre", rec)
        assert len(attrs["cpex.control.result.reason"].encode("utf-8")) <= 256

    def test_config_keys_bounded(self):
        from mcpgateway.plugins.control_telemetry import _per_control_attributes, _MAX_CONFIG_KEYS

        rec = _make_rec(config_keys=[f"key{i}" for i in range(_MAX_CONFIG_KEYS + 10)])
        attrs = _per_control_attributes("pre", rec)
        # Joined keys — count commas+1
        parts = attrs["cpex.control.config.keys"].split(",")
        assert len(parts) == _MAX_CONFIG_KEYS

    def test_returns_empty_on_attribute_error(self):
        from mcpgateway.plugins.control_telemetry import _per_control_attributes

        # rec missing plugin_name entirely
        attrs = _per_control_attributes("pre", MagicMock(spec=[]))
        assert attrs == {}


# ---------------------------------------------------------------------------
# _safe_str
# ---------------------------------------------------------------------------


class TestSafeStr:
    def test_within_limit_unchanged(self):
        from mcpgateway.plugins.control_telemetry import _safe_str

        assert _safe_str("hello", 10) == "hello"

    def test_truncated_with_ellipsis(self):
        from mcpgateway.plugins.control_telemetry import _safe_str

        result = _safe_str("a" * 100, 10)
        assert result.endswith("...")
        assert len(result.encode("utf-8")) <= 10

    def test_non_string_coerced(self):
        from mcpgateway.plugins.control_telemetry import _safe_str

        assert _safe_str(42, 20) == "42"

    def test_exact_limit_boundary(self):
        from mcpgateway.plugins.control_telemetry import _safe_str

        s = "a" * 10
        assert _safe_str(s, 10) == s


# ---------------------------------------------------------------------------
# _enforcement_point
# ---------------------------------------------------------------------------


class TestEnforcementPoint:
    def _acc(self, pre: bool = False, post: bool = False):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator

        acc = ControlTelemetryAccumulator()
        if pre:
            acc._records.append(("pre", _make_rec()))  # pylint: disable=protected-access
        if post:
            acc._records.append(("post", _make_rec()))  # pylint: disable=protected-access
        return acc

    def test_pre_only(self):
        from mcpgateway.plugins.control_telemetry import _enforcement_point

        assert _enforcement_point(self._acc(pre=True)) == "pre"

    def test_post_only(self):
        from mcpgateway.plugins.control_telemetry import _enforcement_point

        assert _enforcement_point(self._acc(post=True)) == "post"

    def test_pre_and_post(self):
        from mcpgateway.plugins.control_telemetry import _enforcement_point

        assert _enforcement_point(self._acc(pre=True, post=True)) == "pre+post"

    def test_neither(self):
        from mcpgateway.plugins.control_telemetry import _enforcement_point

        assert _enforcement_point(self._acc()) == "none"


# ---------------------------------------------------------------------------
# _build_flattened_attributes
# ---------------------------------------------------------------------------


class TestBuildFlattenedAttributes:
    def test_basic_flatten(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator, _build_flattened_attributes

        acc = ControlTelemetryAccumulator()
        with patch("mcpgateway.plugins.control_telemetry.execution_records_supported", return_value=True):
            acc.add(_make_result([_make_rec(plugin_name="pii_guard", status="completed", effective_allow=True, duration_ns=1000)]), hook="pre")

        flat = _build_flattened_attributes(acc, 32)
        assert "cpex.control.results.pii_guard.status" in flat
        assert flat["cpex.control.results.pii_guard.status"] == "completed"
        assert flat["cpex.control.results.pii_guard.result.allowed"] is True
        assert flat["cpex.control.results.pii_guard.duration"] == 1000
        assert flat["cpex.control.results.pii_guard.enforcement_point"] == "pre"

    def test_invalid_name_skipped(self):
        """plugin_name with spaces/special chars is dropped from flattening."""
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator, _build_flattened_attributes

        acc = ControlTelemetryAccumulator()
        acc._records.append(("pre", _make_rec(plugin_name="bad name!")))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        # no key should mention the bad name
        assert not any("bad" in k for k in flat)

    def test_collision_drops_both_and_emits_counter(self):
        """Two records with the same plugin_name cause both to be dropped."""
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator, _build_flattened_attributes

        acc = ControlTelemetryAccumulator()
        acc._records.append(("pre", _make_rec(plugin_name="myctrl")))   # pylint: disable=protected-access
        acc._records.append(("post", _make_rec(plugin_name="myctrl")))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        # no flattened key for myctrl
        assert not any("cpex.control.results.myctrl." in k for k in flat)
        # collision counter emitted
        assert flat.get("cpex.control.results._collision_count", 0) >= 1

    def test_reason_included_when_present(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator, _build_flattened_attributes

        acc = ControlTelemetryAccumulator()
        acc._records.append(("pre", _make_rec(plugin_name="pii_guard", reason="PII found")))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        assert flat.get("cpex.control.results.pii_guard.result.reason") == "PII found"

    def test_reason_omitted_when_none(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator, _build_flattened_attributes

        acc = ControlTelemetryAccumulator()
        acc._records.append(("pre", _make_rec(plugin_name="pii_guard", reason=None)))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 32)
        assert "cpex.control.results.pii_guard.result.reason" not in flat

    def test_bounded_by_max_results(self):
        """Only up to max_results records are flattened."""
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator, _build_flattened_attributes

        acc = ControlTelemetryAccumulator()
        for i in range(10):
            acc._records.append(("pre", _make_rec(plugin_name=f"ctrl{i}")))  # pylint: disable=protected-access
        flat = _build_flattened_attributes(acc, 3)
        # Only ctrl0, ctrl1, ctrl2 flattened
        flattened_names = {k.split(".")[3] for k in flat if k.startswith("cpex.control.results.") and not k.endswith("_collision_count")}
        assert len(flattened_names) == 3

    def test_empty_accumulator_returns_empty(self):
        from mcpgateway.plugins.control_telemetry import ControlTelemetryAccumulator, _build_flattened_attributes

        flat = _build_flattened_attributes(ControlTelemetryAccumulator(), 32)
        assert flat == {}
