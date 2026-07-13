# -*- coding: utf-8 -*-
"""Location: ./tests/integration/plugins/test_plugin_metrics_consumer_integration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for mcpgateway.plugins.utils.record_plugin_metrics() (Task B2 / G1)
against a real ObservabilityService backed by a real (test) database.

Mirrors tests/integration/plugins/test_span_attribute_customizer_integration.py's style
(real ObservabilityService, real DB session, no mocking of the observability layer, no
live HTTP/plugin execution) plus the SessionLocal-patching pattern from
tests/integration/test_audit_trail_transaction_isolation.py -- needed here because
``record_plugin_metrics()`` opens its own independent DB session (issue #3883 pattern,
via a deferred ``from mcpgateway.db import SessionLocal``) rather than accepting one as
an argument, and ``ObservabilityService`` binds ``SessionLocal`` at module-import time.

A fake ``result.metadata`` dict (the shape ``PluginResult.metadata`` takes after a real
``invoke_hook()`` call, e.g. ``{"pii_filter": {...}}``) is constructed directly and passed
straight into ``record_plugin_metrics()`` -- no plugin manager, no HTTP. Assertions read
back real rows from the observability tables.
"""

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, ObservabilityMetric, ObservabilitySpan
from mcpgateway.plugins.utils import record_plugin_metrics
from mcpgateway.services.observability_service import ObservabilityService


@pytest.fixture
def test_db_engine():
    """Create a real, thread-safe, in-memory SQLite engine with the full schema applied."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(test_db_engine):
    """Create a test database session bound to the real in-memory schema."""
    TestSessionLocal = sessionmaker(bind=test_db_engine)
    session = TestSessionLocal()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def patch_session_local(test_db_engine, monkeypatch):
    """Patch SessionLocal so both ObservabilityService and record_plugin_metrics() write
    to the same real in-memory database as the assertions read from.

    Patches:
      - ``mcpgateway.db.SessionLocal`` -- picked up by ``record_plugin_metrics()``'s
        deferred ``from mcpgateway.db import SessionLocal`` (the primary span-batching
        session it opens itself).
      - ``mcpgateway.services.observability_service.SessionLocal`` -- the module-level
        binding ``ObservabilityService`` uses for its own independent-session writes
        (``start_trace``/``end_trace``, and ``record_metric``'s secondary-path writes).
    """
    TestSessionLocal = sessionmaker(bind=test_db_engine)
    monkeypatch.setattr("mcpgateway.db.SessionLocal", TestSessionLocal)
    monkeypatch.setattr("mcpgateway.services.observability_service.SessionLocal", TestSessionLocal)


@pytest.fixture
def observability_service():
    """Create a real ObservabilityService instance."""
    return ObservabilityService()


class TestRecordPluginMetricsIntegration:
    """Integration tests for record_plugin_metrics() against a real DB."""

    def test_single_plugin_creates_span_with_attributes(self, db_session, observability_service: ObservabilityService):
        """A single plugin's fake result.metadata produces one dedicated span row with
        the validated attributes attached, correlated to the given trace_id.
        """
        trace_id = observability_service.start_trace(name="test_trace_g1_single")

        # Fake PluginResult.metadata as invoke_hook() would return it after a real
        # pii_filter plugin ran -- constructed directly, no plugin/HTTP execution.
        result_metadata = {
            "pii_filter": {
                "total_detections": 3,
                "total_masked": 3,
                "detection_types": ["email", "ssn"],
                "stage": "tool_post_invoke",
            }
        }

        record_plugin_metrics(trace_id, result_metadata)

        spans = db_session.query(ObservabilitySpan).filter_by(trace_id=trace_id, name="plugin.metrics.pii_filter").all()
        assert len(spans) == 1
        span = spans[0]
        assert span.resource_type == "plugin"
        assert span.resource_name == "pii_filter"
        assert span.status == "ok"
        assert span.attributes["total_detections"] == 3
        assert span.attributes["total_masked"] == 3
        assert span.attributes["detection_types"] == "email,ssn"
        assert span.attributes["stage"] == "tool_post_invoke"

        observability_service.end_trace(trace_id)

    def test_numeric_fields_also_recorded_as_metrics(self, db_session, observability_service: ObservabilityService):
        """Numeric (int/float, non-bool) validated fields are additionally persisted as
        ObservabilityMetric rows, queryable independently of the span attributes.
        """
        trace_id = observability_service.start_trace(name="test_trace_g1_metrics")

        result_metadata = {
            "pii_filter": {
                "total_detections": 5,
                "total_masked": 4.5,
                "blocked": True,  # bool -- must NOT produce a metric row
                "stage": "tool_pre_invoke",  # str -- must NOT produce a metric row
            }
        }

        record_plugin_metrics(trace_id, result_metadata)

        metrics = db_session.query(ObservabilityMetric).filter_by(trace_id=trace_id).all()
        metrics_by_name = {m.name: m for m in metrics}

        assert set(metrics_by_name) == {"plugin.pii_filter.total_detections", "plugin.pii_filter.total_masked"}
        assert metrics_by_name["plugin.pii_filter.total_detections"].value == 5.0
        assert metrics_by_name["plugin.pii_filter.total_masked"].value == 4.5
        for metric in metrics_by_name.values():
            assert metric.resource_type == "plugin"
            assert metric.resource_id == "pii_filter"

        observability_service.end_trace(trace_id)

    def test_multiple_plugins_each_get_their_own_span(self, db_session, observability_service: ObservabilityService):
        """Multiple plugin namespaces in one result.metadata dict each get their own
        dedicated span, all correlated to the same trace (P-3 batching under the hood).
        """
        trace_id = observability_service.start_trace(name="test_trace_g1_multi")

        result_metadata = {
            "pii_filter": {"total_detections": 1},
            "secrets_detection": {"total_detections": 7, "severity": "high"},
        }

        record_plugin_metrics(trace_id, result_metadata)

        spans = db_session.query(ObservabilitySpan).filter_by(trace_id=trace_id).all()
        span_names = {s.name for s in spans}
        assert span_names == {"plugin.metrics.pii_filter", "plugin.metrics.secrets_detection"}

        secrets_span = next(s for s in spans if s.name == "plugin.metrics.secrets_detection")
        assert secrets_span.attributes["total_detections"] == 7
        # "severity" is not in the string field allowlist (_SAFE_STRING_FIELD_NAMES),
        # so it is dropped rather than persisted -- deny-by-default.
        assert "severity" not in secrets_span.attributes

        observability_service.end_trace(trace_id)

    def test_s4_untrusted_metadata_is_sanitized_before_persisting(self, db_session, observability_service: ObservabilityService):
        """Untrusted/malformed plugin metadata (non-allowlisted field, oversized string,
        nested dict, non-scalar list) is bounded/dropped by the S4 validator before
        anything reaches the DB -- the persisted span only contains the sanitized,
        allowlisted attributes. Non-allowlisted string fields are dropped outright
        (deny-by-default), and overlong values are rejected rather than truncated.
        """
        trace_id = observability_service.start_trace(name="test_trace_g1_s4")

        huge_value = "y" * 5000
        result_metadata = {
            "custom_plugin": {
                "stage": "tool_post_invoke",
                "good_field": "keep-me",
                "huge_field": huge_value,
                "nested_dict": {"should": "be-dropped"},
                "mixed_list": ["a", 1, None],
            }
        }

        record_plugin_metrics(trace_id, result_metadata)

        span = db_session.query(ObservabilitySpan).filter_by(trace_id=trace_id, name="plugin.metrics.custom_plugin").one()
        assert span.attributes["stage"] == "tool_post_invoke"
        assert "good_field" not in span.attributes  # not in the string field allowlist
        assert "huge_field" not in span.attributes  # overlong values are rejected, not truncated
        assert "nested_dict" not in span.attributes
        assert "mixed_list" not in span.attributes

        observability_service.end_trace(trace_id)

    def test_noop_does_not_touch_db_when_trace_id_missing(self, db_session):
        """No-op guard: with no trace_id, nothing is written to the real DB at all."""
        before_spans = db_session.query(ObservabilitySpan).count()
        before_metrics = db_session.query(ObservabilityMetric).count()

        record_plugin_metrics(None, {"pii_filter": {"total_detections": 1}})

        assert db_session.query(ObservabilitySpan).count() == before_spans
        assert db_session.query(ObservabilityMetric).count() == before_metrics

    def test_noop_does_not_touch_db_when_metadata_missing(self, db_session, observability_service: ObservabilityService):
        """No-op guard: with no result_metadata, nothing new is written for this trace."""
        trace_id = observability_service.start_trace(name="test_trace_g1_noop_metadata")

        before_spans = db_session.query(ObservabilitySpan).filter_by(trace_id=trace_id).count()

        record_plugin_metrics(trace_id, None)
        record_plugin_metrics(trace_id, {})

        assert db_session.query(ObservabilitySpan).filter_by(trace_id=trace_id).count() == before_spans

        observability_service.end_trace(trace_id)
