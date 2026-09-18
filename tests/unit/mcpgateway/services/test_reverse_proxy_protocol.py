# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_reverse_proxy_protocol.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the reverse-proxy wire protocol boundary.
"""

from datetime import datetime, timezone

from pydantic import ValidationError
import pytest

from mcpgateway.services.reverse_proxy_protocol import (
    DownstreamAuth,
    HeartbeatMessage,
    JsonRpcErrorResponse,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcSuccessResponse,
    NotificationMessage,
    RegisterMessage,
    RegisterCompleteMessage,
    RegistrationStatus,
    ResponseMessage,
    UnregisterMessage,
    error,
    heartbeat,
    parse_client_message,
    register_ack,
    register_complete,
    request,
)


@pytest.mark.parametrize(
    ("frame", "expected_type"),
    [
        ('{"type":"register","server":{"name":"local","description":"MCP","protocol":"mcp"}}', RegisterMessage),
        ('{"type":"unregister","sessionId":"client-value"}', UnregisterMessage),
        ('{"type":"heartbeat","sessionId":"client-value"}', HeartbeatMessage),
        ('{"type":"response","payload":{"jsonrpc":"2.0","id":0,"result":{}}}', ResponseMessage),
        ('{"type":"notification","payload":{"jsonrpc":"2.0","method":"notifications/test"}}', NotificationMessage),
    ],
)
def test_parse_client_message_returns_exhaustive_typed_variants(frame: str, expected_type: type) -> None:
    message = parse_client_message(frame)

    assert isinstance(message, expected_type)


def test_parse_client_message_preserves_numeric_zero_request_id() -> None:
    message = parse_client_message('{"type":"response","payload":{"jsonrpc":"2.0","id":0,"result":"ok"}}')

    assert isinstance(message, ResponseMessage)
    assert message.payload.id == 0


@pytest.mark.parametrize(
    "frame",
    [
        "[]",
        '"register"',
        '{"type":"unknown"}',
        '{"type":"register","server":{}}',
        '{"type":"register","server":{"name":""}}',
        '{"type":"register","server":{"name":"x","description":"' + ("d" * 1025) + '"}}',
        '{"type":"register","server":{"name":"' + ("n" * 129) + '"}}',
        '{"type":"response"}',
        '{"type":"response","payload":{"id":1,"result":{}}}',
        '{"type":"response","payload":{"jsonrpc":"2.0","id":1}}',
        '{"type":"response","payload":{"jsonrpc":"2.0","id":1,"result":{},"error":{"code":-1,"message":"failed"}}}',
        '{"type":"response","payload":{"jsonrpc":"2.0","id":1,"result":{},"method":"tools/list"}}',
        '{"type":"response","payload":{"id":true}}',
        '{"type":"response","payload":{"id":1.5}}',
        '{"type":"notification","payload":{"jsonrpc":"2.0","id":1,"method":"notifications/test"}}',
        '{"type":"notification","payload":{"jsonrpc":"2.0"}}',
        '{"type":"notification","payload":{"jsonrpc":"2.0","method":"notifications/test","params":"scalar"}}',
    ],
)
def test_parse_client_message_rejects_invalid_boundary_values(frame: str) -> None:
    with pytest.raises(ValidationError):
        parse_client_message(frame)


def test_register_ignores_client_authority_fields() -> None:
    message = parse_client_message(
        '{"type":"register","sessionId":"chosen","owner_email":"attacker@example.com",'
        '"team_id":"foreign","visibility":"private","id":"chosen-id",'
        '"server":{"name":"local","owner_email":"attacker@example.com","team_id":"foreign",'
        '"visibility":"private","id":"chosen-server"}}'
    )

    assert isinstance(message, RegisterMessage)
    assert message.model_dump() == {"type": "register", "server": {"name": "local", "description": None, "protocol": None}}


def test_parsed_models_are_frozen() -> None:
    message = parse_client_message('{"type":"register","server":{"name":"local"}}')
    assert isinstance(message, RegisterMessage)

    with pytest.raises(ValidationError):
        setattr(message.server, "name", "changed")


def test_json_rpc_request_requires_version_method_and_structured_params() -> None:
    for payload in (
        {"id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 1},
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": 1},
    ):
        with pytest.raises(ValidationError):
            JsonRpcRequest.model_validate(payload)


def test_json_rpc_response_preserves_null_result_and_error_data() -> None:
    success = parse_client_message('{"type":"response","payload":{"jsonrpc":"2.0","id":1,"result":null}}')
    failure = parse_client_message('{"type":"response","payload":{"jsonrpc":"2.0","id":2,"error":{"code":-32603,"message":"failed","data":null}}}')

    assert isinstance(success, ResponseMessage)
    assert isinstance(success.payload, JsonRpcSuccessResponse)
    assert success.payload.result is None
    assert isinstance(failure, ResponseMessage)
    assert isinstance(failure.payload, JsonRpcErrorResponse)
    assert failure.payload.error.data is None


def test_register_complete_rejects_processing_status() -> None:
    with pytest.raises(ValidationError):
        RegisterCompleteMessage.model_validate({"sessionId": "connection-1", "status": "processing"})


def test_outgoing_registration_and_heartbeat_constructors_match_contract() -> None:
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)

    assert register_ack("connection-1").model_dump(by_alias=True, mode="json", exclude_none=True) == {
        "type": "register_ack",
        "sessionId": "connection-1",
        "status": "processing",
    }
    assert register_complete("connection-1", RegistrationStatus.SUCCESS).model_dump(by_alias=True, mode="json", exclude_none=True) == {
        "type": "register_complete",
        "sessionId": "connection-1",
        "status": "success",
    }
    assert heartbeat("connection-1", now).model_dump(by_alias=True, mode="json", exclude_none=True) == {
        "type": "heartbeat",
        "sessionId": "connection-1",
        "timestamp": "2026-08-11T00:00:00Z",
    }


def test_outgoing_request_omits_downstream_auth_when_absent() -> None:
    payload = JsonRpcRequest.model_validate({"jsonrpc": "2.0", "id": 0, "method": "tools/list"})

    message = request("connection-1", payload)

    assert message.model_dump(by_alias=True, mode="json", exclude_none=True) == {
        "type": "request",
        "sessionId": "connection-1",
        "payload": {"jsonrpc": "2.0", "id": 0, "method": "tools/list"},
    }


def test_outgoing_request_includes_typed_downstream_auth_when_present() -> None:
    payload = JsonRpcRequest.model_validate({"jsonrpc": "2.0", "id": "request-1", "method": "tools/list"})
    auth = DownstreamAuth(headers={"Authorization": "Bearer downstream"}, auth_type="bearer")

    message = request("connection-1", payload, auth)

    assert message.model_dump(by_alias=True, mode="json", exclude_none=True) == {
        "type": "request",
        "sessionId": "connection-1",
        "payload": {"jsonrpc": "2.0", "id": "request-1", "method": "tools/list"},
        "authentication": {"Authorization": "Bearer downstream"},
        "authType": "bearer",
    }


def test_outgoing_request_envelope_accepts_notification_payload() -> None:
    payload = JsonRpcNotification.model_validate({"jsonrpc": "2.0", "method": "notifications/initialized"})

    message = request("connection-1", payload)

    assert message.model_dump(by_alias=True, mode="json", exclude_none=True) == {
        "type": "request",
        "sessionId": "connection-1",
        "payload": {"jsonrpc": "2.0", "method": "notifications/initialized"},
    }


def test_outgoing_error_constructor_matches_contract() -> None:
    message = error("connection-1", "invalid frame")

    assert message.model_dump(by_alias=True, mode="json", exclude_none=True) == {
        "type": "error",
        "sessionId": "connection-1",
        "message": "invalid frame",
    }
