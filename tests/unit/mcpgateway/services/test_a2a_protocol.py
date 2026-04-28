# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_protocol.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for mcpgateway.services.a2a_protocol.
"""

# Standard
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services.a2a_protocol import (
    _build_default_message,
    _normalize_message,
    _normalize_part,
    _normalize_role,
    _normalize_task,
    _normalize_task_state,
    _normalize_task_status,
    build_a2a_jsonrpc_request,
    is_jsonrpc_a2a_agent,
    is_v1_a2a_protocol,
    normalize_a2a_method,
    normalize_a2a_params,
    normalize_a2a_version_header,
    prepare_a2a_invocation,
)

# ── is_v1_a2a_protocol ──────────────────────────────────────────────────────


class TestIsV1A2AProtocol:
    def test_none_defaults_to_v1(self):
        assert is_v1_a2a_protocol(None) is True

    def test_empty_string_defaults_to_v1(self):
        assert is_v1_a2a_protocol("") is True

    def test_whitespace_only_defaults_to_v1(self):
        assert is_v1_a2a_protocol("   ") is True

    def test_v1_returns_true(self):
        assert is_v1_a2a_protocol("1.0.0") is True

    def test_v2_returns_true(self):
        assert is_v1_a2a_protocol("2.0") is True

    def test_legacy_returns_false(self):
        assert is_v1_a2a_protocol("0.3.0") is False

    def test_non_numeric_starting_with_1(self):
        assert is_v1_a2a_protocol("1beta") is True

    def test_non_numeric_not_starting_with_1(self):
        assert is_v1_a2a_protocol("beta") is False

    def test_dots_only_defaults_to_v1(self):
        """A version string of only dots produces no parts after split/filter."""
        assert is_v1_a2a_protocol("...") is True

    def test_v_prefixed_v1_returns_true(self):
        """Regression: 'v1' should be recognized as v1 protocol."""
        assert is_v1_a2a_protocol("v1") is True

    def test_v_prefixed_v1_dot_0_returns_true(self):
        assert is_v1_a2a_protocol("v1.0") is True

    def test_v_prefixed_uppercase_V1_returns_true(self):
        assert is_v1_a2a_protocol("V1") is True

    def test_v_prefixed_v0_3_returns_false(self):
        assert is_v1_a2a_protocol("v0.3") is False

    def test_v_prefixed_v0_3_0_returns_false(self):
        assert is_v1_a2a_protocol("v0.3.0") is False


# ── normalize_a2a_version_header ─────────────────────────────────────────────


class TestNormalizeA2AVersionHeader:
    def test_none_returns_v1_default(self):
        assert normalize_a2a_version_header(None) == "1.0"

    def test_empty_returns_v1_default(self):
        assert normalize_a2a_version_header("") == "1.0"

    def test_whitespace_returns_v1_default(self):
        assert normalize_a2a_version_header("   ") == "1.0"

    def test_dots_only_returns_v1_default(self):
        assert normalize_a2a_version_header("...") == "1.0"

    def test_single_digit_gets_dot_zero(self):
        assert normalize_a2a_version_header("1") == "1.0"

    def test_single_non_digit_returns_as_is(self):
        assert normalize_a2a_version_header("beta") == "beta"

    def test_v_prefixed_v1_canonicalizes(self):
        """Regression: 'v1' should canonicalize to '1.0'."""
        assert normalize_a2a_version_header("v1") == "1.0"

    def test_v_prefixed_v1_0_0_canonicalizes(self):
        assert normalize_a2a_version_header("v1.0.0") == "1.0"

    def test_v_prefixed_v0_3_canonicalizes(self):
        assert normalize_a2a_version_header("v0.3") == "0.3"

    def test_two_parts(self):
        assert normalize_a2a_version_header("0.3") == "0.3"

    def test_three_parts_truncates(self):
        assert normalize_a2a_version_header("1.0.0") == "1.0"


# ── is_jsonrpc_a2a_agent ─────────────────────────────────────────────────────


class TestIsJsonrpcA2AAgent:
    def test_generic_type(self):
        assert is_jsonrpc_a2a_agent("generic", "https://x.com") is True

    def test_jsonrpc_type(self):
        assert is_jsonrpc_a2a_agent("jsonrpc", "https://x.com") is True

    def test_trailing_slash_url(self):
        assert is_jsonrpc_a2a_agent("custom", "https://x.com/") is True

    def test_custom_type_no_trailing_slash(self):
        assert is_jsonrpc_a2a_agent("custom", "https://x.com") is False

    def test_none_values(self):
        assert is_jsonrpc_a2a_agent(None, None) is False


# ── normalize_a2a_method ─────────────────────────────────────────────────────


class TestNormalizeA2AMethod:
    def test_none_method_v1(self):
        assert normalize_a2a_method(None, "1.0") == "SendMessage"

    def test_none_method_legacy(self):
        assert normalize_a2a_method(None, "0.3") == "message/send"

    def test_empty_method_v1(self):
        assert normalize_a2a_method("", "1.0") == "SendMessage"

    def test_legacy_to_v1_mapping(self):
        assert normalize_a2a_method("message/send", "1.0") == "SendMessage"
        assert normalize_a2a_method("tasks/get", "1.0") == "GetTask"

    def test_v1_to_legacy_mapping(self):
        assert normalize_a2a_method("SendMessage", "0.3") == "message/send"
        assert normalize_a2a_method("GetTask", "0.3") == "tasks/get"

    def test_unknown_method_passes_through(self):
        assert normalize_a2a_method("CustomMethod", "1.0") == "CustomMethod"
        assert normalize_a2a_method("custom/method", "0.3") == "custom/method"


# ── _normalize_role ──────────────────────────────────────────────────────────


class TestNormalizeRole:
    def test_empty_role_returns_original(self):
        assert _normalize_role("", "1.0") == ""
        assert _normalize_role(None, "1.0") is None

    def test_legacy_to_v1(self):
        assert _normalize_role("user", "1.0") == "ROLE_USER"
        assert _normalize_role("agent", "1.0") == "ROLE_AGENT"

    def test_v1_to_legacy(self):
        assert _normalize_role("ROLE_USER", "0.3") == "user"
        assert _normalize_role("ROLE_AGENT", "0.3") == "agent"

    def test_unknown_role_passes_through(self):
        assert _normalize_role("custom", "1.0") == "custom"


# ── _normalize_part ──────────────────────────────────────────────────────────


class TestNormalizePart:
    def test_non_mapping_returns_as_is(self):
        assert _normalize_part("just text", "1.0") == "just text"
        assert _normalize_part(42, "1.0") == 42

    def test_v1_text_part_strips_kind(self):
        part = {"kind": "text", "text": "hello"}
        result = _normalize_part(part, "1.0")
        assert result == {"text": "hello"}
        assert "kind" not in result

    def test_v1_part_with_type_discriminator(self):
        part = {"type": "text", "text": "hello"}
        result = _normalize_part(part, "1.0")
        assert result == {"text": "hello"}

    def test_v1_non_text_part(self):
        part = {"kind": "data", "data": "abc"}
        result = _normalize_part(part, "1.0")
        assert result == {"data": "abc"}

    def test_legacy_adds_kind_from_discriminator(self):
        part = {"kind": "text", "text": "hello"}
        result = _normalize_part(part, "0.3")
        assert result["kind"] == "text"

    def test_legacy_infers_text_kind(self):
        part = {"text": "hello"}
        result = _normalize_part(part, "0.3")
        assert result["kind"] == "text"

    def test_legacy_infers_data_kind(self):
        part = {"data": "abc"}
        result = _normalize_part(part, "0.3")
        assert result["kind"] == "data"

    def test_legacy_infers_file_kind(self):
        part = {"file": "test.pdf"}
        result = _normalize_part(part, "0.3")
        assert result["kind"] == "file"

    def test_legacy_infers_file_from_uri(self):
        part = {"uri": "s3://bucket/file"}
        result = _normalize_part(part, "0.3")
        assert result["kind"] == "file"

    def test_legacy_no_inference_fallback(self):
        part = {"custom": "value"}
        result = _normalize_part(part, "0.3")
        assert "kind" not in result


# ── _normalize_task_state ────────────────────────────────────────────────────


class TestNormalizeTaskState:
    def test_empty_returns_original(self):
        assert _normalize_task_state("", "1.0") == ""
        assert _normalize_task_state(None, "1.0") is None

    def test_legacy_to_v1(self):
        assert _normalize_task_state("completed", "1.0") == "TASK_STATE_COMPLETED"
        assert _normalize_task_state("working", "1.0") == "TASK_STATE_WORKING"
        assert _normalize_task_state("input-required", "1.0") == "TASK_STATE_INPUT_REQUIRED"
        assert _normalize_task_state("cancelled", "1.0") == "TASK_STATE_CANCELED"

    def test_v1_to_legacy(self):
        assert _normalize_task_state("TASK_STATE_COMPLETED", "0.3") == "completed"
        assert _normalize_task_state("TASK_STATE_WORKING", "0.3") == "working"

    def test_unknown_state_passes_through(self):
        assert _normalize_task_state("custom_state", "1.0") == "custom_state"


# ── _normalize_task_status ───────────────────────────────────────────────────


class TestNormalizeTaskStatus:
    def test_string_status_normalizes_as_state(self):
        assert _normalize_task_status("completed", "1.0") == "TASK_STATE_COMPLETED"

    def test_non_mapping_non_string_returns_as_is(self):
        assert _normalize_task_status(42, "1.0") == 42

    def test_dict_status_normalizes_state_and_message(self):
        status = {
            "state": "completed",
            "message": {"role": "agent", "parts": [{"kind": "text", "text": "done"}]},
        }
        result = _normalize_task_status(status, "1.0")
        assert result["state"] == "TASK_STATE_COMPLETED"
        assert result["message"]["role"] == "ROLE_AGENT"

    def test_dict_status_without_state_or_message(self):
        status = {"other": "data"}
        result = _normalize_task_status(status, "1.0")
        assert result == {"other": "data"}


# ── _normalize_message ───────────────────────────────────────────────────────


class TestNormalizeMessage:
    def test_non_mapping_returns_as_is(self):
        assert _normalize_message("not a dict", "1.0") == "not a dict"

    def test_v1_strips_kind(self):
        msg = {"kind": "message", "role": "user", "parts": [{"kind": "text", "text": "hi"}]}
        result = _normalize_message(msg, "1.0")
        assert "kind" not in result
        assert result["role"] == "ROLE_USER"
        assert result["parts"] == [{"text": "hi"}]

    def test_legacy_adds_kind(self):
        msg = {"role": "ROLE_USER", "parts": [{"text": "hi"}]}
        result = _normalize_message(msg, "0.3")
        assert result["kind"] == "message"
        assert result["role"] == "user"
        assert result["parts"] == [{"kind": "text", "text": "hi"}]


# ── _normalize_task ──────────────────────────────────────────────────────────


class TestNormalizeTask:
    def test_non_mapping_returns_as_is(self):
        assert _normalize_task("not a dict", "1.0") == "not a dict"

    def test_v1_strips_kind_normalizes_status(self):
        task = {
            "kind": "task",
            "id": "t1",
            "status": {"state": "completed"},
        }
        result = _normalize_task(task, "1.0")
        assert "kind" not in result
        assert result["status"]["state"] == "TASK_STATE_COMPLETED"

    def test_legacy_adds_kind(self):
        task = {"id": "t1", "status": {"state": "TASK_STATE_COMPLETED"}}
        result = _normalize_task(task, "0.3")
        assert result["kind"] == "task"
        assert result["status"]["state"] == "completed"

    def test_history_normalized(self):
        task = {
            "id": "t1",
            "history": [
                {"role": "user", "parts": [{"text": "hi"}]},
                "non-mapping-item",
            ],
        }
        result = _normalize_task(task, "1.0")
        assert result["history"][0]["role"] == "ROLE_USER"
        assert result["history"][1] == "non-mapping-item"

    def test_artifacts_normalized_v1(self):
        task = {
            "id": "t1",
            "artifacts": [
                {"kind": "artifact", "parts": [{"kind": "text", "text": "data"}]},
                "non-mapping",
            ],
        }
        result = _normalize_task(task, "1.0")
        assert "kind" not in result["artifacts"][0]
        assert result["artifacts"][0]["parts"] == [{"text": "data"}]
        assert result["artifacts"][1] == "non-mapping"

    def test_artifacts_normalized_legacy(self):
        task = {
            "id": "t1",
            "artifacts": [
                {"parts": [{"text": "data"}]},
            ],
        }
        result = _normalize_task(task, "0.3")
        assert result["artifacts"][0]["kind"] == "artifact"
        assert result["artifacts"][0]["parts"] == [{"kind": "text", "text": "data"}]


# ── normalize_a2a_params ─────────────────────────────────────────────────────


class TestNormalizeA2AParams:
    def test_non_mapping_returns_as_is(self):
        assert normalize_a2a_params("string", "1.0") == "string"
        assert normalize_a2a_params(42, "1.0") == 42

    def test_message_key_normalized(self):
        params = {"message": {"role": "user", "parts": [{"kind": "text", "text": "hi"}]}}
        result = normalize_a2a_params(params, "1.0")
        assert result["message"]["role"] == "ROLE_USER"

    def test_history_key_normalized(self):
        params = {
            "history": [
                {"role": "user", "parts": [{"text": "hi"}]},
                "non-mapping",
            ]
        }
        result = normalize_a2a_params(params, "1.0")
        assert result["history"][0]["role"] == "ROLE_USER"
        assert result["history"][1] == "non-mapping"

    def test_task_key_normalized(self):
        params = {"task": {"id": "t1", "kind": "task", "status": {"state": "completed"}}}
        result = normalize_a2a_params(params, "1.0")
        assert "kind" not in result["task"]
        assert result["task"]["status"]["state"] == "TASK_STATE_COMPLETED"

    def test_status_key_normalized(self):
        params = {"status": "completed"}
        result = normalize_a2a_params(params, "1.0")
        assert result["status"] == "TASK_STATE_COMPLETED"

    def test_other_keys_passed_through(self):
        params = {"foo": "bar", "count": 5}
        result = normalize_a2a_params(params, "1.0")
        assert result == {"foo": "bar", "count": 5}

    def test_messages_key_normalized(self):
        params = {"messages": [{"role": "user", "parts": [{"text": "hi"}]}, "raw"]}
        result = normalize_a2a_params(params, "1.0")
        assert result["messages"][0]["role"] == "ROLE_USER"
        assert result["messages"][1] == "raw"


# ── _build_default_message ───────────────────────────────────────────────────


class TestBuildDefaultMessage:
    def test_v1_message(self):
        msg = _build_default_message("hello", "1.0", message_id="msg-1")
        assert msg["messageId"] == "msg-1"
        assert msg["role"] == "ROLE_USER"
        assert msg["parts"] == [{"text": "hello"}]
        assert "kind" not in msg

    def test_legacy_message(self):
        msg = _build_default_message("hello", "0.3", message_id="msg-1")
        assert msg["kind"] == "message"
        assert msg["role"] == "user"
        assert msg["parts"] == [{"kind": "text", "text": "hello"}]

    def test_auto_generated_message_id(self):
        msg = _build_default_message("hello", "1.0")
        assert msg["messageId"].startswith("contextforge-")


# ── build_a2a_jsonrpc_request ────────────────────────────────────────────────


class TestBuildA2AJsonrpcRequest:
    def test_passthrough_existing_jsonrpc_request(self):
        params = {"jsonrpc": "2.0", "method": "message/send", "params": {"message": {"role": "user"}}, "id": 99}
        result = build_a2a_jsonrpc_request(params, "1.0")
        assert result["method"] == "SendMessage"
        assert result["id"] == 99

    def test_explicit_params_takes_precedence(self):
        result = build_a2a_jsonrpc_request({"params": {"key": "value"}}, "1.0")
        assert result["params"] == {"key": "value"}

    def test_explicit_message_wraps_in_params(self):
        msg = {"role": "user", "parts": [{"text": "hi"}]}
        result = build_a2a_jsonrpc_request({"message": msg}, "1.0")
        assert result["params"]["message"]["role"] == "ROLE_USER"

    def test_text_field_builds_default_message(self):
        result = build_a2a_jsonrpc_request({"text": "hello"}, "1.0")
        assert result["params"]["message"]["role"] == "ROLE_USER"
        assert result["params"]["message"]["parts"] == [{"text": "hello"}]

    def test_no_recognized_field_uses_payload_as_params(self):
        result = build_a2a_jsonrpc_request({"custom": "data"}, "1.0")
        assert result["params"] == {"custom": "data"}

    def test_custom_id_preserved(self):
        result = build_a2a_jsonrpc_request({"id": 42, "query": "hello"}, "1.0")
        assert result["id"] == 42

    def test_text_with_message_id(self):
        result = build_a2a_jsonrpc_request({"text": "hi", "messageId": "m-1"}, "1.0")
        assert result["params"]["message"]["messageId"] == "m-1"


# ── prepare_a2a_invocation ───────────────────────────────────────────────────


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


def test_prepare_a2a_invocation_fails_closed_on_query_param_decrypt_failure(monkeypatch):
    """Decrypt failure for a query_param credential must fail the invocation.

    Silently dropping the credential and sending the request unauthenticated
    can reach the agent as an anonymous call with unpredictable results. The
    header-path equivalent (a2a_service.invoke_agent) already fails closed;
    the query_param path must do the same.
    """
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", lambda _value: (_ for _ in ()).throw(ValueError("bad")))
    apply_query_param_auth = MagicMock()
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.apply_query_param_auth", apply_query_param_auth)

    with pytest.raises(ValueError, match="Failed to decrypt query_param"):
        prepare_a2a_invocation(
            agent_type="generic",
            endpoint_url="https://example.com/",
            protocol_version="1.0.0",
            parameters={"query": "hello"},
            interaction_type="query",
            auth_type="query_param",
            auth_query_params={"api_key": "bad"},  # pragma: allowlist secret
        )

    apply_query_param_auth.assert_not_called()


def test_prepare_a2a_invocation_custom_agent_non_jsonrpc():
    """Custom agent type without trailing slash uses non-JSONRPC format."""
    prepared = prepare_a2a_invocation(
        agent_type="custom",
        endpoint_url="https://example.com/agent",
        protocol_version="1.0.0",
        parameters={"key": "value"},
        interaction_type="query",
    )

    assert prepared.uses_jsonrpc is False
    assert prepared.request_data["interaction_type"] == "query"
    assert prepared.request_data["parameters"] == {"key": "value"}
    assert prepared.request_data["protocol_version"] == "1.0.0"


def test_prepare_a2a_invocation_applies_basic_auth_from_string(monkeypatch):
    """Basic auth with a string auth_value is decoded and applied as headers."""
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", lambda _val: {"Authorization": "Basic dGVzdDp0ZXN0"})

    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hi"},
        interaction_type="query",
        auth_type="basic",
        auth_value="encoded-value",
    )

    assert prepared.headers["Authorization"] == "Basic dGVzdDp0ZXN0"


def test_prepare_a2a_invocation_applies_auth_from_mapping():
    """Auth value as a mapping is applied directly as headers."""
    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hi"},
        interaction_type="query",
        auth_type="bearer",
        auth_value={"Authorization": "Bearer tok-123"},
    )

    assert prepared.headers["Authorization"] == "Bearer tok-123"


def test_prepare_a2a_invocation_api_key_auth():
    """api_key auth type sets Authorization header with Bearer prefix."""
    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hi"},
        interaction_type="query",
        auth_type="api_key",
        auth_value="my-api-key",
    )

    assert prepared.headers["Authorization"] == "Bearer my-api-key"


def test_prepare_a2a_invocation_api_key_auth_falls_back_to_raw_value_on_decode_error(monkeypatch):
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", MagicMock(side_effect=ValueError("boom")))

    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hi"},
        interaction_type="query",
        auth_type="api_key",
        auth_value="raw-api-key",  # pragma: allowlist secret
    )

    assert prepared.headers["Authorization"] == "Bearer raw-api-key"  # pragma: allowlist secret


def test_prepare_a2a_invocation_api_key_auth_uses_decoded_scalar(monkeypatch):
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", lambda _val: "decoded-key")

    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hi"},
        interaction_type="query",
        auth_type="api_key",
        auth_value="encrypted-api-key",  # pragma: allowlist secret
    )

    assert prepared.headers["Authorization"] == "Bearer decoded-key"  # pragma: allowlist secret


def test_prepare_a2a_invocation_api_key_auth_from_mapping_uses_first_value():
    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hi"},
        interaction_type="query",
        auth_type="api_key",
        auth_value={"x-api-key": "mapped-key"},  # pragma: allowlist secret
    )

    assert prepared.headers["Authorization"] == "Bearer mapped-key"  # pragma: allowlist secret


def test_prepare_a2a_invocation_rejects_non_mapping_decoded_auth(monkeypatch):
    """A decoded auth value that is not a mapping should raise ValueError."""
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", lambda _val: "not-a-mapping")

    with pytest.raises(ValueError, match="must be a mapping"):
        prepare_a2a_invocation(
            agent_type="generic",
            endpoint_url="https://example.com/",
            protocol_version="1.0.0",
            parameters={"query": "hi"},
            interaction_type="query",
            auth_type="basic",
            auth_value="encoded-value",
        )


def test_prepare_a2a_invocation_query_param_auth_applies(monkeypatch):
    """Successful query param auth decryption applies params to URL."""
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", lambda _val: {"api_key": "real-key"})  # pragma: allowlist secret
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.apply_query_param_auth", lambda url, params: url + "?api_key=real-key")  # pragma: allowlist secret

    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hi"},
        interaction_type="query",
        auth_type="query_param",
        auth_query_params={"api_key": "encrypted"},  # pragma: allowlist secret
    )

    assert "api_key=real-key" in prepared.endpoint_url
    assert "api_key" not in prepared.sanitized_endpoint_url or "real-key" not in prepared.sanitized_endpoint_url


def test_prepare_a2a_invocation_skips_empty_query_param_values(monkeypatch):
    """Empty encrypted values in auth_query_params are skipped."""
    decode_mock = MagicMock()
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", decode_mock)

    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hi"},
        interaction_type="query",
        auth_type="query_param",
        auth_query_params={"api_key": ""},
    )

    decode_mock.assert_not_called()
    assert prepared.endpoint_url == "https://example.com/"


def test_prepare_a2a_invocation_no_correlation_id():
    """When no correlation_id is provided, X-Correlation-ID header is not set."""
    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hi"},
        interaction_type="query",
    )

    assert "X-Correlation-ID" not in prepared.headers


def test_prepare_a2a_invocation_preserves_base_headers():
    """Base headers are included in the prepared invocation."""
    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hi"},
        interaction_type="query",
        base_headers={"X-Custom": "value"},
    )

    assert prepared.headers["X-Custom"] == "value"


def test_prepare_a2a_invocation_none_parameters():
    """None parameters default to empty dict."""
    prepared = prepare_a2a_invocation(
        agent_type="custom",
        endpoint_url="https://example.com/agent",
        protocol_version="1.0.0",
        parameters=None,
        interaction_type="query",
    )

    assert prepared.request_data["parameters"] == {}


def test_prepare_a2a_invocation_legacy_custom_agent_uses_legacy_version():
    """Custom agent with legacy protocol uses the legacy default version."""
    prepared = prepare_a2a_invocation(
        agent_type="custom",
        endpoint_url="https://example.com/agent",
        protocol_version="0.3",
        parameters=None,
        interaction_type="query",
    )

    assert prepared.request_data["protocol_version"] == "0.3"


def test_prepare_a2a_invocation_exposes_sensitive_query_param_names(monkeypatch):
    """Regression: sensitive_query_param_names must be set so callers can redact error messages."""
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", lambda _val: {"custom_key": "secret-val"})
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.apply_query_param_auth", lambda url, params: url + "?custom_key=secret-val")

    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hi"},
        interaction_type="query",
        auth_type="query_param",
        auth_query_params={"custom_key": "encrypted"},
    )

    assert prepared.sensitive_query_param_names is not None
    assert "custom_key" in prepared.sensitive_query_param_names


def test_prepare_a2a_invocation_sensitive_query_param_names_none_when_no_auth():
    """Without query_param auth, sensitive_query_param_names should be None."""
    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hi"},
        interaction_type="query",
    )

    assert prepared.sensitive_query_param_names is None


def test_prepare_a2a_invocation_v_prefixed_protocol_uses_v1_format():
    """Regression: 'v1' protocol should produce v1 wire format."""
    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="v1",
        parameters={"query": "hello"},
        interaction_type="query",
    )

    assert prepared.headers["A2A-Version"] == "1.0"
    assert prepared.request_data["method"] == "SendMessage"
    assert prepared.request_data["params"]["message"]["role"] == "ROLE_USER"


def test_prepare_a2a_invocation_preserves_encrypted_auth_fields(monkeypatch):
    """Query-param auth preserves encrypted blobs and sets base_endpoint_url."""
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", lambda _val: {"api_key": "decrypted-key"})  # pragma: allowlist secret
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.apply_query_param_auth", lambda url, params: url + "?api_key=decrypted-key")  # pragma: allowlist secret

    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hello"},
        interaction_type="query",
        auth_type="query_param",
        auth_query_params={"api_key": "encrypted_blob"},  # pragma: allowlist secret
    )

    assert prepared.auth_query_params_encrypted == {"api_key": "encrypted_blob"}  # pragma: allowlist secret
    assert prepared.base_endpoint_url == "https://example.com/"


def test_prepare_a2a_invocation_preserves_encrypted_auth_value(monkeypatch):
    """Bearer auth preserves the encrypted auth_value blob for Rust-side decryption."""
    monkeypatch.setattr("mcpgateway.services.a2a_protocol.decode_auth", lambda _val: {"Authorization": "Bearer decrypted"})

    prepared = prepare_a2a_invocation(
        agent_type="generic",
        endpoint_url="https://example.com/",
        protocol_version="1.0.0",
        parameters={"query": "hello"},
        interaction_type="query",
        auth_type="bearer",
        auth_value="encrypted_blob",
    )

    assert prepared.auth_value_encrypted == "encrypted_blob"
