# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/test_plugins_utils.py
Copyright contributors to the MCP-CONTEXT-FORGE project
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
      oversized strings rejected outright, not truncated; key count capped and the
      scan itself is bounded (not just the accepted count); dropped values are
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

    def test_noop_when_every_plugin_yields_nothing_sanitized(self):
        """If every plugin namespace's metadata is dropped in full (no surviving keys), the
        overall call is a no-op: ObservabilityService is never even constructed.
        """
        with patch("mcpgateway.services.observability_service.ObservabilityService") as mock_cls:
            record_plugin_metrics("trace-1", {"some_plugin": {"bad key!": "x"}})
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

    def test_per_call_numeric_cap_stops_before_a_later_plugin_is_even_examined(self):
        """Once the per-call numeric-row cap is already reached by earlier plugins, a
        later plugin's fields are never examined at all -- the outer per-plugin loop
        breaks immediately rather than relying solely on the inner per-field cap check.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        # Only total_detections/total_masked are numeric-allowlisted, so a single plugin
        # namespace can contribute at most 2 numeric fields; 8 earlier namespaces (16
        # fields total) exhaust the default cap (16), so plugin_last's field must never
        # be reached.
        metadata = {f"plugin_{i}": {"total_detections": i, "total_masked": i} for i in range(8)}
        metadata["plugin_last"] = {"total_detections": 999}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
        ):
            record_plugin_metrics("trace-1", metadata)

        assert mock_service.record_metric.call_count == 16
        recorded_plugins = {call.kwargs["resource_id"] for call in mock_service.record_metric.call_args_list}
        assert recorded_plugins == {f"plugin_{i}" for i in range(8)}


class TestRecordPluginMetricsS4Validation:
    """S4: untrusted plugin output must be validated/bounded before it reaches observability."""

    def test_non_scalar_values_are_dropped(self, caplog):
        """A dict/None/mixed-type-list value is dropped; scalar siblings still survive."""
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {
            "some_plugin": {
                "stage": "ok",
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
        assert attrs == {"stage": "ok"}

        # S4: dropped-value log lines must name the key but never the value.
        dropped_records = [r.getMessage() for r in caplog.records if "Dropped" in r.getMessage()]
        assert any("bad_dict" in msg for msg in dropped_records)
        assert any("bad_none" in msg for msg in dropped_records)
        assert any("bad_mixed_list" in msg for msg in dropped_records)
        for msg in dropped_records:
            assert "nested" not in msg
            assert "value" not in msg or "nested" not in msg

    def test_oversized_string_is_rejected_not_truncated(self, caplog):
        """An oversized string value is rejected outright, not truncated -- a truncated
        secret/token/hash fragment would still be sensitive, so it must never be exported.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        huge = "x" * 5000
        # Use allowlisted field names so this test isolates the length check from the
        # separate field-name allowlist check (test_string_value_field_name_not_in_allowlist_is_rejected).
        metadata = {"some_plugin": {"stage": huge, "detection_types": "fine"}}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            caplog.at_level(logging.DEBUG),
        ):
            record_plugin_metrics("trace-1", metadata)

        attrs = mock_service.start_span.call_args.kwargs["attributes"]
        assert "stage" not in attrs
        assert attrs["detection_types"] == "fine"
        dropped_records = [r.getMessage() for r in caplog.records if "Dropped" in r.getMessage()]
        assert any("stage" in msg for msg in dropped_records)
        for msg in dropped_records:
            assert huge not in msg

    def test_string_value_with_disallowed_characters_is_rejected(self, caplog):
        """A short string value that simply isn't in the safe low-cardinality charset
        (e.g. contains a space) is rejected on the charset check, independent of length.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        # Allowlisted field names, to isolate the charset check from the field-name allowlist check.
        metadata = {"some_plugin": {"stage": "has a space", "detection_types": "fine"}}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            caplog.at_level(logging.DEBUG),
        ):
            record_plugin_metrics("trace-1", metadata)

        attrs = mock_service.start_span.call_args.kwargs["attributes"]
        assert "stage" not in attrs
        assert attrs["detection_types"] == "fine"
        dropped_records = [r.getMessage() for r in caplog.records if "Dropped" in r.getMessage()]
        assert any("stage" in msg for msg in dropped_records)

    def test_string_value_field_name_not_in_allowlist_is_rejected(self, caplog):
        """A string value that is perfectly valid by charset AND length is still dropped
        if its field name isn't in the explicit low-cardinality allowlist -- the charset
        alone doesn't bound semantic sensitivity, so an SSN- or token-shaped value under
        an arbitrary field name must never reach the DB/OTel sinks just because it
        happens to be short and made of allowed characters.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {
            "some_plugin": {
                "user_ssn": "123-45-6789",  # charset/length-valid, but not an allowlisted field name
                "stage": "fine",
            }
        }

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            caplog.at_level(logging.DEBUG),
        ):
            record_plugin_metrics("trace-1", metadata)

        attrs = mock_service.start_span.call_args.kwargs["attributes"]
        assert "user_ssn" not in attrs
        assert attrs["stage"] == "fine"
        dropped_records = [r.getMessage() for r in caplog.records if "Dropped" in r.getMessage()]
        assert any("user_ssn" in msg and "not in the explicit string allowlist" in msg for msg in dropped_records)
        for msg in dropped_records:
            assert "123-45-6789" not in msg

    def test_non_dict_per_plugin_metadata_is_dropped(self):
        """A plugin namespace whose value isn't itself a dict is dropped; other,
        well-formed plugin namespaces in the same call are unaffected.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {"bad_plugin": "not-a-dict", "good_plugin": {"total_detections": 1}}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
        ):
            record_plugin_metrics("trace-1", metadata)

        span_names = {call.kwargs["name"] for call in mock_service.start_span.call_args_list}
        assert span_names == {"plugin.metrics.good_plugin"}

    def test_invalid_plugin_name_identifier_is_dropped(self, caplog):
        """A plugin namespace key that isn't a valid identifier is dropped before its
        metadata is even sanitized; other plugin namespaces are unaffected.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {"bad plugin name!": {"total_detections": 1}, "good_plugin": {"total_detections": 2}}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            caplog.at_level(logging.DEBUG),
        ):
            record_plugin_metrics("trace-1", metadata)

        span_names = {call.kwargs["name"] for call in mock_service.start_span.call_args_list}
        assert span_names == {"plugin.metrics.good_plugin"}
        dropped_records = [r.getMessage() for r in caplog.records if "Dropped" in r.getMessage()]
        assert any("plugin name is not a valid identifier" in msg for msg in dropped_records)

    def test_joined_list_value_with_disallowed_characters_is_rejected(self, caplog):
        """A list value whose joined string contains a character outside the safe
        low-cardinality charset (e.g. '@') is rejected by the same value contract as
        any other string, even though every individual item was within the size bound.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        # Allowlisted field name, to isolate the charset check from the field-name allowlist check.
        metadata = {"some_plugin": {"detection_types": ["ok", "bad@char"], "stage": "fine"}}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            caplog.at_level(logging.DEBUG),
        ):
            record_plugin_metrics("trace-1", metadata)

        attrs = mock_service.start_span.call_args.kwargs["attributes"]
        assert "detection_types" not in attrs
        assert attrs["stage"] == "fine"
        dropped_records = [r.getMessage() for r in caplog.records if "Dropped" in r.getMessage()]
        assert any("detection_types" in msg and "joined list value" in msg for msg in dropped_records)

    def test_oversized_list_item_is_rejected_before_join(self, caplog):
        """A list item longer than _MAX_STRING_LENGTH is rejected before the list is
        joined, so an oversized item can't force an unbounded join + regex scan.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        # Allowlisted field name, to isolate the size check from the field-name allowlist check.
        metadata = {"some_plugin": {"detection_types": ["ok", "x" * 5000], "stage": "fine"}}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            caplog.at_level(logging.DEBUG),
        ):
            record_plugin_metrics("trace-1", metadata)

        attrs = mock_service.start_span.call_args.kwargs["attributes"]
        assert "detection_types" not in attrs
        assert attrs["stage"] == "fine"
        dropped_records = [r.getMessage() for r in caplog.records if "Dropped" in r.getMessage()]
        assert any("detection_types" in msg for msg in dropped_records)

    def test_list_value_field_name_not_in_allowlist_is_rejected(self, caplog):
        """A list[str] value that is perfectly valid by charset/length is still dropped
        if its field name isn't in the explicit allowlist -- the same deny-by-default
        gate applies to joined list values as to plain string values.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {"some_plugin": {"custom_tags": ["a", "b"], "stage": "fine"}}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            caplog.at_level(logging.DEBUG),
        ):
            record_plugin_metrics("trace-1", metadata)

        attrs = mock_service.start_span.call_args.kwargs["attributes"]
        assert "custom_tags" not in attrs
        assert attrs["stage"] == "fine"
        dropped_records = [r.getMessage() for r in caplog.records if "Dropped" in r.getMessage()]
        assert any("custom_tags" in msg and "not in the explicit string allowlist" in msg for msg in dropped_records)

    def test_bool_value_bypasses_the_string_and_numeric_field_name_allowlists(self, caplog):
        """A bool value is accepted unconditionally, regardless of field name -- unlike
        str/int/float values, bools are never checked against _SAFE_STRING_FIELD_NAMES or
        _SAFE_NUMERIC_FIELD_NAMES. Mirrors the real encoded_exfil_detection.redacted field:
        `redacted` is not a member of either allowlist, yet the value must still survive.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {"encoded_exfil_detection": {"redacted": True}}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            caplog.at_level(logging.DEBUG),
        ):
            record_plugin_metrics("trace-1", metadata)

        attrs = mock_service.start_span.call_args.kwargs["attributes"]
        assert attrs["redacted"] is True
        dropped_records = [r.getMessage() for r in caplog.records if "Dropped" in r.getMessage()]
        assert not any("redacted" in msg for msg in dropped_records)

    def test_key_scan_is_bounded_not_just_accepted_count(self):
        """Invalid keys don't get a free pass: only the first _MAX_PLUGIN_KEYS items of
        the raw dict are ever inspected, so a valid key placed after that window is
        never reached even though fewer than _MAX_PLUGIN_KEYS keys were accepted.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        # First 32 items: one valid (numeric-allowlisted) key, then 31 invalid keys. A 33rd
        # item (also numeric-allowlisted) follows but sits outside the inspected window and
        # must never be reached.
        raw = {"total_detections": 1}
        raw.update({f"bad key {i}": i for i in range(31)})
        raw["total_masked"] = 1
        assert len(raw) == 33
        metadata = {"some_plugin": raw}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
        ):
            record_plugin_metrics("trace-1", metadata)

        attrs = mock_service.start_span.call_args.kwargs["attributes"]
        assert attrs.get("total_detections") == 1
        assert "total_masked" not in attrs

    def test_key_count_is_capped(self):
        """A plugin dict with more than the max allowed keys is truncated to the cap.

        Uses bool values (accepted unconditionally, no field-name allowlist) so the test
        isolates key-count capping from the separate numeric field-name allowlist check.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {"some_plugin": {f"key_{i}": True for i in range(100)}}

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

        metadata = {f"plugin_{i}": {"total_detections": i} for i in range(40)}

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
            "plugin_a": {"total_detections": 1},
            "plugin_b": {"total_detections": 2},
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

    def test_swallows_exception_from_commit_rollback_and_close(self):
        """If db.commit() fails, the resulting rollback() is also best-effort -- and if
        THAT fails too, it's swallowed. Same for the final db.close() in the ``finally``
        block: none of these secondary failures may propagate out of the call.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()
        mock_session.commit.side_effect = RuntimeError("commit failed")
        mock_session.rollback.side_effect = RuntimeError("rollback also failed")
        mock_session.close.side_effect = RuntimeError("close also failed")

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
        ):
            record_plugin_metrics("trace-1", {"pii_filter": {"total_detections": 1}})  # should not raise

        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_called_once()
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


class TestRecordPluginMetricsG2OTelExport:
    """G2: optional OTel-SDK export sink for plugin metrics (gateway is the export authority)."""

    def test_otel_span_created_when_enabled(self):
        """When OTel is enabled, one dedicated span per plugin is opened with sanitized attributes
        as span attributes, using the gateway's configured exporter.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()
        mock_create_span = MagicMock()
        mock_context_manager = MagicMock()
        mock_create_span.return_value = mock_context_manager

        metadata = {
            "pii_filter": {
                "total_detections": 2,
                "stage": "tool_post_invoke",
            },
            "secrets_detection": {
                "total_detections": 1,
            },
        }

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            patch("mcpgateway.observability.otel_tracing_enabled", return_value=True),
            patch("mcpgateway.observability.otel_context_active", return_value=True),
            patch("mcpgateway.observability.create_span", mock_create_span),
        ):
            record_plugin_metrics("trace-1", metadata)

        # Verify create_span was called twice (once per plugin)
        assert mock_create_span.call_count == 2

        # Verify the span names and attributes
        calls = mock_create_span.call_args_list
        span_names = {call[0][0] for call in calls}
        assert span_names == {"plugin.metrics.pii_filter", "plugin.metrics.secrets_detection"}

        # Verify attributes were passed correctly for pii_filter
        pii_call = [c for c in calls if c[0][0] == "plugin.metrics.pii_filter"][0]
        assert pii_call[0][1] == {"total_detections": 2, "stage": "tool_post_invoke"}

        # Verify attributes for secrets_detection
        secrets_call = [c for c in calls if c[0][0] == "plugin.metrics.secrets_detection"][0]
        assert secrets_call[0][1] == {"total_detections": 1}

        # Verify the context manager was used (entered and exited)
        assert mock_context_manager.__enter__.call_count == 2
        assert mock_context_manager.__exit__.call_count == 2

    def test_otel_export_noop_when_disabled(self):
        """When OTel tracing is disabled, create_span is not called and no span is exported."""
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()
        mock_create_span = MagicMock()

        metadata = {"pii_filter": {"total_detections": 2}}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            patch("mcpgateway.observability.otel_tracing_enabled", return_value=False),
            patch("mcpgateway.observability.create_span", mock_create_span),
        ):
            record_plugin_metrics("trace-1", metadata)

        # When OTel is disabled, create_span should not be called
        mock_create_span.assert_not_called()

        # But the DB sink should still work
        mock_service.start_span.assert_called_once()
        mock_service.end_span.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_otel_export_failure_does_not_break_db_sink(self):
        """When create_span raises, the exception is swallowed and the DB sink still completes."""
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()
        mock_create_span = MagicMock(side_effect=RuntimeError("OTel export failed"))

        metadata = {"pii_filter": {"total_detections": 2}}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            patch("mcpgateway.observability.otel_tracing_enabled", return_value=True),
            patch("mcpgateway.observability.otel_context_active", return_value=True),
            patch("mcpgateway.observability.create_span", mock_create_span),
        ):
            record_plugin_metrics("trace-1", metadata)  # should not raise

        # OTel export was attempted but failed
        mock_create_span.assert_called_once()

        # DB sink should still complete successfully
        mock_service.start_span.assert_called_once()
        mock_service.end_span.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    def test_otel_export_sink_failure_outside_the_per_plugin_loop_does_not_break_db_sink(self):
        """If the OTel sink fails before/outside the per-plugin loop (e.g. checking
        whether tracing is enabled raises), that's swallowed by the sink's own outer
        try/except -- distinct from the per-plugin try/except -- and the DB sink,
        which already completed earlier in the call, is unaffected.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {"pii_filter": {"total_detections": 2}}

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            patch("mcpgateway.observability.otel_tracing_enabled", side_effect=RuntimeError("boom")),
        ):
            record_plugin_metrics("trace-1", metadata)  # should not raise

        mock_service.start_span.assert_called_once()
        mock_service.end_span.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_otel_export_failure_for_one_plugin_does_not_affect_others(self):
        """When create_span fails for one plugin, the export for other plugins still runs."""
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()
        mock_create_span = MagicMock(side_effect=[RuntimeError("boom"), None])

        metadata = {
            "plugin_a": {"total_detections": 1},
            "plugin_b": {"total_detections": 2},
        }

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
            patch("mcpgateway.observability.otel_tracing_enabled", return_value=True),
            patch("mcpgateway.observability.otel_context_active", return_value=True),
            patch("mcpgateway.observability.create_span", mock_create_span),
        ):
            record_plugin_metrics("trace-1", metadata)  # should not raise

        # create_span was called twice despite the first failure
        assert mock_create_span.call_count == 2

        # DB sink still works regardless of OTel export issues
        assert mock_service.start_span.call_count == 2
        assert mock_service.end_span.call_count == 2
        mock_session.commit.assert_called_once()


class TestRecordPluginMetricsIssue5554FieldAllowlist:
    """Issue #5554 / cpex-plugins#129: extend the S4 allowlists so the 5 non-pii_filter
    bundled plugins' metrics fields survive sanitization instead of being silently
    dropped as not-yet-allowlisted field names.
    """

    def test_new_plugin_fields_survive_sanitization(self):
        """One representative field per new plugin, all in a single call, all must
        reach start_span's attributes -- proves each name was added to the allowlist,
        not just charset/length-valid by coincidence.
        """
        mock_service = _make_observability_service_mock()
        mock_session = MagicMock()

        metadata = {
            "secrets_detection": {"secret_types": "aws_key", "total_blocked": 1},
            "encoded_exfil_detection": {"encoding_types": "base64"},
            "url_reputation": {"reputation_categories": "malware", "total_checked": 4},
            "rate_limiter": {"backend": "redis", "allowed": 1, "throttled": 0},
            "retry_with_backoff": {"retry_count": 2, "retry_delay_ms": 250},
        }

        with (
            patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service),
            patch("mcpgateway.db.SessionLocal", return_value=mock_session),
        ):
            record_plugin_metrics("trace-1", metadata)

        attrs_by_plugin = {call.kwargs["resource_name"]: call.kwargs["attributes"] for call in mock_service.start_span.call_args_list}

        assert attrs_by_plugin["secrets_detection"] == {"secret_types": "aws_key", "total_blocked": 1}
        assert attrs_by_plugin["encoded_exfil_detection"] == {"encoding_types": "base64"}
        assert attrs_by_plugin["url_reputation"] == {"reputation_categories": "malware", "total_checked": 4}
        assert attrs_by_plugin["rate_limiter"] == {"backend": "redis", "allowed": 1, "throttled": 0}
        assert attrs_by_plugin["retry_with_backoff"] == {"retry_count": 2, "retry_delay_ms": 250}
