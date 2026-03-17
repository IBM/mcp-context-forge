# -*- coding: utf-8 -*-
"""Tests for mcpgateway.services.a2a_protocol."""

# Standard
from unittest.mock import MagicMock

# First-Party
from mcpgateway.services.a2a_protocol import prepare_a2a_invocation


def test_prepare_a2a_invocation_builds_v1_send_message_for_query():
    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hello"},
        interaction_type="query",
        correlation_id="corr-123",
    )

    assert prepared.uses_jsonrpc is True
    assert prepared.headers["A2A-Version"] == "1.0"
    assert prepared.headers["X-Correlation-ID"] == "corr-123"
    assert prepared.request_data["method"] == "SendMessage"
    assert prepared.request_data["params"]["message"]["role"] == "ROLE_USER"
    assert prepared.request_data["params"]["message"]["parts"] == [{"text": "hello"}]
    assert "kind" not in prepared.request_data["params"]["message"]


def test_prepare_a2a_invocation_builds_legacy_send_message_for_legacy_protocol():
    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="0.3.0",
        parameters={"query": "hello"},
        interaction_type="query",
    )

    assert prepared.headers["A2A-Version"] == "0.3"
    assert prepared.request_data["method"] == "message/send"
    assert prepared.request_data["params"]["message"]["kind"] == "message"
    assert prepared.request_data["params"]["message"]["parts"] == [{"kind": "text", "text": "hello"}]


def test_prepare_a2a_invocation_maps_v1_method_to_legacy_protocol():
    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="0.3.0",
        parameters={"method": "GetTask", "params": {"id": "task-1"}},
        interaction_type="query",
    )

    assert prepared.request_data["method"] == "tasks/get"
    assert prepared.request_data["params"] == {"id": "task-1"}


def test_prepare_a2a_invocation_normalizes_task_states_between_protocol_versions():
    v1_prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"method": "ListTasks", "params": {"status": "completed"}},
        interaction_type="query",
    )
    legacy_prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="0.3.0",
        parameters={"method": "tasks/list", "params": {"status": "TASK_STATE_WORKING"}},
        interaction_type="query",
    )

    assert v1_prepared.request_data["params"]["status"] == "TASK_STATE_COMPLETED"
    assert legacy_prepared.request_data["params"]["status"] == "working"


def test_prepare_a2a_invocation_skips_query_param_decrypt_failures(monkeypatch):
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", lambda _value: (_ for _ in ()).throw(ValueError("bad")))
    apply_query_param_auth = MagicMock()
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.apply_query_param_auth", apply_query_param_auth)

    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hello"},
        interaction_type="query",
        auth_type="query_param",
        auth_query_params={"api_key": "bad"},
    )

    assert prepared.endpoint_url == "https://example.com/"
    apply_query_param_auth.assert_not_called()
