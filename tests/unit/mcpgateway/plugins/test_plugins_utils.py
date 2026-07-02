# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/test_plugins_utils.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for mcpgateway.plugins.utils.build_request_extensions() (Task B1 / G0)
and mcpgateway.plugins.utils.record_plugin_metrics() (Task B2 / G1).

Covers build_request_extensions() in isolation (no HTTP request or PluginManager involved):
    - Returns a populated Extensions(request=RequestExtension(...)) when a trace_id
      is active in the observability ContextVars.
    - Returns None when no trace_id is active (the common case: observability
      disabled, or code running outside of a traced request).
    - Returns None (never raises) when span_id is unset but trace_id is present.
    - Is best-effort: any unexpected exception while reading the ContextVars or
      constructing the CPEX Extensions object is swallowed and None is returned,
      so this helper can never break the request path it's called from.

Covers record_plugin_metrics() in isolation (ObservabilityService/SessionLocal mocked):
    - No-op (no DB/service touched) when trace_id or result_metadata is falsy.
    - S4: only scalar values + list[str] (joined) survive; other types are dropped;
      oversized strings truncated, not dropped; key count capped; dropped values are
      never present in log output (only the key name/reason).
    - Primary path: start_span()/end_span() called once per plugin namespace with the
      validated attributes, sharing a single DB session (obs_db) across all plugins.
    - Secondary path: record_metric() called once per validated *numeric* field.
    - L4: swallows exceptions raised by ObservabilityService (session creation, start_span,
      end_span, record_metric) without propagating into the caller.
"""

# Standard
import logging
from unittest.mock import MagicMock, patch

# First-Party
from mcpgateway.plugins.utils import build_request_extensions, record_plugin_metrics
from mcpgateway.services.observability_service import current_span_id, current_trace_id


class TestBuildRequestExtensions:
    """Tests for build_request_extensions()."""

    def test_returns_none_when_no_trace_active(self):
        """With no trace_id set in the ContextVar, the helper returns None."""
        token = current_trace_id.set(None)
        try:
            assert build_request_extensions() is None
        finally:
            current_trace_id.reset(token)

    def test_returns_extensions_with_trace_and_span_id(self):
        """When both trace_id and span_id are active, both are carried through."""
        trace_token = current_trace_id.set("trace-abc")
        span_token = current_span_id.set("span-xyz")
        try:
            extensions = build_request_extensions()
        finally:
            current_trace_id.reset(trace_token)
            current_span_id.reset(span_token)

        assert extensions is not None
        assert extensions.request.trace_id == "trace-abc"
        assert extensions.request.span_id == "span-xyz"

    def test_returns_extensions_with_trace_id_only_when_span_id_unset(self):
        """A trace_id without a span_id still produces Extensions (span_id=None)."""
        trace_token = current_trace_id.set("trace-only")
        try:
            extensions = build_request_extensions()
        finally:
            current_trace_id.reset(trace_token)

        assert extensions is not None
        assert extensions.request.trace_id == "trace-only"
        assert extensions.request.span_id is None

    def test_never_raises_when_contextvar_read_fails(self):
        """If reading the ContextVar unexpectedly raises, the helper swallows it and
        returns None rather than propagating into the request path.
        """
        with patch("mcpgateway.services.observability_service.current_trace_id") as mock_trace_id:
            mock_trace_id.get.side_effect = RuntimeError("boom")
            assert build_request_extensions() is None

    def test_never_raises_when_extensions_construction_fails(self):
        """If building the CPEX Extensions/RequestExtension object unexpectedly raises,
        the helper swallows it and returns None rather than propagating.
        """
        trace_token = current_trace_id.set("trace-abc")
        try:
            with patch("mcpgateway.plugins.utils.RequestExtension", side_effect=RuntimeError("boom")):
                assert build_request_extensions() is None
        finally:
            current_trace_id.reset(trace_token)


def _make_observability_service_mock():
    """Build a MagicMock standing in for ObservabilityService with sane defaults."""
    service = MagicMock()
    service.start_span.return_value = "span-1"
    service.end_span.return_value = None
    service.record_metric.return_value = 1
    return service


class TestRecordPluginMetricsNoOp:
    """No-op guard clauses: nothing is touched when there's nothing to record."""

    def test_noop_when_trace_id_falsy(self):
        """No DB/service touched when trace_id is None."""
        with patch("mcpgateway.services.observability_service.ObservabilityService") as mock_cls:
            record_plugin_metrics(None, {"pii_filter": {"total_detections": 2}})
        mock_cls.assert_not_called()

    def test_noop_when_result_metadata_falsy(self):
        """No DB/service touched when result_metadata is empty/None."""
        with patch("mcpgateway.services.observability_service.ObservabilityService") as mock_cls:
            record_plugin_metrics("trace-1", None)
            record_plugin_metrics("trace-1", {})
        mock_cls.assert_not_called()

    def test_noop_when_result_metadata_not_a_dict(self):
        """Malformed (non-dict) result_metadata is a no-op, never raises."""
        with patch("mcpgateway.services.observability_service.ObservabilityService") as mock_cls:
            record_plugin_metrics("trace-1", "not-a-dict")  # type: ignore[arg-type]
        mock_cls.assert_not_called()


class TestRecordPluginMetricsPrimarySpanPath:
    """Primary path: validated metrics attached as attributes on a dedicated span per plugin."""

    def test_start_and_end_span_called_with_expected_attributes(self):
        """Given fake pii_filter metadata, start_span/end_span are called with the plugin's
        namespaced span name and the validated (scalar + joined list) attributes.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {
            "pii_filter": {
                "total_detections": 2,
                "total_masked": 2,
                "detection_types": ["email", "ssn"],
                "stage": "tool_post_invoke",
            }
        }

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
        ):
            record_plugin_metrics("trace-1", metadata)

        mock_service.start_span.assert_called_once()
        _, kwargs = mock_service.start_span.call_args
        assert kwargs["trace_id"] == "trace-1"
        assert kwargs["name"] == "plugin.metrics.pii_filter"
        assert kwargs["resource_type"] == "plugin"
        assert kwargs["resource_name"] == "pii_filter"
        assert kwargs["obs_db"] is mock_session
        attrs = kwargs["attributes"]
        assert attrs["total_detections"] == 2
        assert attrs["total_masked"] == 2
        assert attrs["detection_types"] == "email,ssn"
        assert attrs["stage"] == "tool_post_invoke"

        mock_service.end_span.assert_called_once_with("span-1", status="ok", commit=False, obs_db=mock_session)
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    def test_multiple_plugins_share_a_single_db_session(self):
        """P-3: spans for multiple plugin namespaces in one call batch into one session."""
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {
            "pii_filter": {"total_detections": 1},
            "secrets_detection": {"total_detections": 5},
        }

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session) as mock_session_factory,
        ):
            record_plugin_metrics("trace-1", metadata)

        # Exactly one session created for the whole call, regardless of plugin count.
        mock_session_factory.assert_called_once()
        assert mock_service.start_span.call_count == 2
        assert mock_service.end_span.call_count == 2
        mock_session.commit.assert_called_once()


class TestRecordPluginMetricsSecondaryMetricPath:
    """Secondary (optional) path: numeric fields also recorded via record_metric()."""

    def test_record_metric_called_for_numeric_fields_only(self):
        """Only int/float (non-bool) validated fields are passed to record_metric();
        strings/lists/bools are skipped for this secondary path.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {
            "pii_filter": {
                "total_detections": 2,
                "total_masked": 2.5,
                "detection_types": ["email", "ssn"],
                "stage": "tool_post_invoke",
                "blocked": True,
            }
        }

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
        ):
            record_plugin_metrics("trace-1", metadata)

        recorded_names = {call.kwargs["name"] for call in mock_service.record_metric.call_args_list}
        assert recorded_names == {"plugin.pii_filter.total_detections", "plugin.pii_filter.total_masked"}
        for call in mock_service.record_metric.call_args_list:
            assert call.kwargs["trace_id"] == "trace-1"
            assert isinstance(call.kwargs["value"], float)


class TestRecordPluginMetricsS4Validation:
    """S4: untrusted plugin output must be validated/bounded before it reaches observability."""

    def test_non_scalar_values_are_dropped(self, caplog):
        """A dict/None/mixed-type-list value is dropped; scalar siblings still survive."""
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {
            "some_plugin": {
                "good_str": "ok",
                "bad_dict": {"nested": "value"},
                "bad_none": None,
                "bad_mixed_list": ["a", 1, None],
            }
        }

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            caplog.at_level(logging.DEBUG, logger="mcpgateway.plugins.utils"),
        ):
            record_plugin_metrics("trace-1", metadata)

        attrs = mock_service.start_span.call_args.kwargs["attributes"]
        assert attrs == {"good_str": "ok"}

        # S4: dropped-value log lines must name the key but never the value.
        dropped_records = [r.getMessage() for r in caplog.records if "Dropped" in r.getMessage()]
        assert any("bad_dict" in msg for msg in dropped_records)
        assert any("bad_none" in msg for msg in dropped_records)
        assert any("bad_mixed_list" in msg for msg in dropped_records)
        for msg in dropped_records:
            assert "nested" not in msg
            assert "value" not in msg or "nested" not in msg

    def test_oversized_string_is_truncated_not_dropped(self):
        """An oversized string value is truncated to the bound, not dropped entirely."""
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        huge = "x" * 5000
        metadata = {"some_plugin": {"huge_field": huge}}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
        ):
            record_plugin_metrics("trace-1", metadata)

        attrs = mock_service.start_span.call_args.kwargs["attributes"]
        assert "huge_field" in attrs
        assert len(attrs["huge_field"]) == 256
        assert attrs["huge_field"] == "x" * 256

    def test_key_count_is_capped(self):
        """A plugin dict with more than the max allowed keys is truncated to the cap."""
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {"some_plugin": {f"key_{i}": i for i in range(100)}}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
        ):
            record_plugin_metrics("trace-1", metadata)

        attrs = mock_service.start_span.call_args.kwargs["attributes"]
        assert len(attrs) <= 32

    def test_extra_plugin_namespaces_beyond_cap_are_dropped(self):
        """More than the max allowed plugin namespaces per call are dropped, not processed."""
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {f"plugin_{i}": {"count": i} for i in range(40)}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
        ):
            record_plugin_metrics("trace-1", metadata)

        assert mock_service.start_span.call_count <= 16


class TestRecordPluginMetricsL4Swallow:
    """L4: record_plugin_metrics must never raise into the request path."""

    def test_swallows_exception_from_observability_service_constructor(self):
        """If constructing ObservabilityService itself raises, nothing propagates."""
        with patch("mcpgateway.services.observability_service.ObservabilityService", side_effect=RuntimeError("boom")):
            record_plugin_metrics("trace-1", {"pii_filter": {"total_detections": 1}})  # should not raise

    def test_swallows_exception_from_session_local(self):
        """If SessionLocal() itself raises, the primary path fails silently and the
        secondary (record_metric) path is still attempted best-effort.
        """
        mock_service = _make_observability_service_mock()

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", side_effect=RuntimeError("db down")),
        ):
            record_plugin_metrics("trace-1", {"pii_filter": {"total_detections": 1}})  # should not raise

        mock_service.start_span.assert_not_called()
        # Secondary path is independent of the primary session and still attempted.
        mock_service.record_metric.assert_called_once()

    def test_swallows_exception_from_start_span(self):
        """If start_span() raises for one plugin, other plugins are still processed and
        the exception never propagates.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()
        mock_service.start_span.side_effect = [RuntimeError("boom"), "span-2"]

        metadata = {
            "plugin_a": {"count": 1},
            "plugin_b": {"count": 2},
        }

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
        ):
            record_plugin_metrics("trace-1", metadata)  # should not raise

        assert mock_service.start_span.call_count == 2
        # end_span only called for the plugin whose start_span succeeded.
        mock_service.end_span.assert_called_once_with("span-2", status="ok", commit=False, obs_db=mock_session)
        mock_session.commit.assert_called_once()

    def test_swallows_exception_from_end_span(self):
        """If end_span() raises, the exception never propagates and the session is still closed."""
        mock_service = _make_observability_service_mock()
        mock_service.end_span.side_effect = RuntimeError("boom")
        mock_session = MagicMock()

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
        ):
            record_plugin_metrics("trace-1", {"pii_filter": {"total_detections": 1}})  # should not raise

        mock_session.close.assert_called_once()

    def test_swallows_exception_from_record_metric(self):
        """If record_metric() raises for one field, other fields/plugins still get processed
        and the exception never propagates.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()
        mock_service.record_metric.side_effect = RuntimeError("boom")

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
        ):
            record_plugin_metrics("trace-1", {"pii_filter": {"total_detections": 1, "total_masked": 2}})  # should not raise

        assert mock_service.record_metric.call_count == 2
