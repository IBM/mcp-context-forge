# -*- coding: utf-8 -*-
"""Tests for policy_audit ORM model serialization."""

# Standard
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.common.policy_audit import PolicyDecision


def _make_decision(**kwargs):
    """Create a PolicyDecision with default test values."""
    defaults = {
        "id": "test-uuid",
        "timestamp": datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        "request_id": "req-123",
        "gateway_node": "gw-1",
        "subject_type": "user",
        "subject_id": "user-1",
        "subject_email": "user@example.com",
        "subject_roles": ["developer"],
        "subject_teams": ["engineering"],
        "subject_clearance_level": 2,
        "subject_data": None,
        "action": "tools.invoke",
        "resource_type": "tool",
        "resource_id": "db-query",
        "resource_server": "prod-db",
        "resource_classification": 4,
        "resource_data": None,
        "decision": "deny",
        "reason": "Insufficient clearance",
        "matching_policies": [{"id": "p1", "result": "deny"}],
        "policy_engines_used": ["mac"],
        "ip_address": "10.0.0.50",
        "user_agent": "claude-desktop/1.0",
        "mfa_verified": True,
        "geo_location": None,
        "context_data": {"source": "api"},
        "duration_ms": 5.0,
        "severity": "warning",
        "risk_score": 75,
        "anomaly_detected": False,
        "compliance_frameworks": ["SOC2"],
        "extra_metadata": {"custom": "value"},
    }
    defaults.update(kwargs)
    d = PolicyDecision()
    for k, v in defaults.items():
        setattr(d, k, v)
    return d


def test_to_dict_full():
    """to_dict returns full schema with all fields populated."""
    d = _make_decision()
    result = d.to_dict()
    assert result["id"] == "test-uuid"
    assert result["decision"] == "deny"
    assert result["subject"]["email"] == "user@example.com"
    assert result["resource"]["type"] == "tool"
    assert result["matching_policies"] == [{"id": "p1", "result": "deny"}]
    assert result["metadata"]["severity"] == "warning"
    assert result["metadata"]["custom"] == "value"


def test_to_dict_no_subject():
    """to_dict returns None subject when subject_id is None."""
    d = _make_decision(subject_id=None)
    result = d.to_dict()
    assert result["subject"] is None


def test_to_dict_no_resource():
    """to_dict returns None resource when resource_id is None."""
    d = _make_decision(resource_id=None)
    result = d.to_dict()
    assert result["resource"] is None


def test_to_splunk_hec():
    """to_splunk_hec returns proper Splunk HEC format."""
    d = _make_decision()
    result = d.to_splunk_hec()
    assert result["source"] == "mcp-policy-engine"
    assert result["sourcetype"] == "policy_decision"
    assert result["host"] == "gw-1"
    assert isinstance(result["time"], int)
    assert result["event"]["id"] == "test-uuid"


def test_to_elasticsearch():
    """to_elasticsearch returns doc with @timestamp."""
    d = _make_decision()
    result = d.to_elasticsearch()
    assert "@timestamp" in result
    assert result["event_type"] == "policy_decision"
    assert result["id"] == "test-uuid"


def test_to_webhook():
    """to_webhook returns proper webhook format."""
    d = _make_decision()
    result = d.to_webhook()
    assert result["event_type"] == "policy.decision"
    assert "timestamp" in result
    assert result["data"]["id"] == "test-uuid"
