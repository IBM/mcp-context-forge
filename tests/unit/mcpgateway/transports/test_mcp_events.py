#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Native MCP Events dispatch and authorization boundaries.

Location: ./tests/unit/mcpgateway/transports/test_mcp_events.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

# Third-Party
from mcp import Client
from mcp.shared.exceptions import MCPError
import mcp_types as types
from pydantic import RootModel
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.request_logging_middleware import _mask_json_payload_for_logging
from mcpgateway.services.mcp_events import event_provider, EventRequestContext, EventRequestParams, get_event_provider
from mcpgateway.transports import streamablehttp_transport as transport


class EventResult(RootModel[dict[str, Any]]):
    """Preserve the raw extension result through the SDK's typed boundary."""


class FixtureProvider:
    """Synthetic application owner with observable authorization and calls."""

    def __init__(self) -> None:
        """Initialize synthetic request observations."""
        self.calls: list[tuple[EventRequestContext, str, dict[str, Any]]] = []
        self.denied = False
        self.fail: str | bool = False
        self.revoke_during_request = False

    async def authorize(self, context: EventRequestContext, method: str) -> bool:
        """Authorize the original synthetic account."""
        return not self.denied and context.user["email"] == "owner@example.test"

    async def request(self, context: EventRequestContext, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Return a synthetic application-owned result."""
        self.calls.append((context, method, params))
        if self.fail == "callback-error":
            raise MCPError(-32015, params["delivery"]["secret"], {"reason": [params["delivery"]["secret"]]})
        if self.fail == "bad-result":
            return {"secret": params["delivery"]["secret"]}
        if self.fail:
            raise RuntimeError(params["delivery"]["secret"])
        if self.revoke_during_request:
            self.denied = True
        if method == "events/list":
            return {"events": [{"name": "example.changed", "delivery": ["webhook"], "inputSchema": {"type": "object"}, "payloadSchema": {"type": "object"}}]}
        if method == "events/subscribe":
            return {"id": "sub_synthetic", "refreshBefore": "2026-11-16T00:00:00Z", "cursor": None, "truncated": False}
        return {}


@pytest.fixture
def event_scope(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], AsyncMock, AsyncMock]:
    """Supply explicit current authority around the real SDK dispatcher."""
    user = {"email": "owner@example.test", "user_id": "original-owner", "teams": ["team-a"], "is_authenticated": True, "scoped_permissions": ["events.read", "events.subscribe", "events.unsubscribe"]}
    monkeypatch.setattr(settings, "mcpgateway_mcp_events_enabled", True)
    monkeypatch.setattr(transport, "_resolve_request_context", AsyncMock(return_value=("server-a", {"Authorization": "Bearer synthetic-original"}, user)))
    permission = AsyncMock(return_value=True)
    monkeypatch.setattr(transport, "_check_streamable_permission", permission)
    visibility = AsyncMock(return_value=SimpleNamespace(enabled=True))
    monkeypatch.setattr("mcpgateway.services.server_service.server_service.get_server", visibility)
    monkeypatch.setattr(transport, "_catalog_ttl_ms", AsyncMock(return_value=1000))
    monkeypatch.setattr(transport, "_instructions_for_server", AsyncMock(return_value=None))
    return user, permission, visibility


async def send(client: Client, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Send an actual SDK request with provider-owned parameters."""
    result = await client.session.send_request(types.Request[EventRequestParams, str](method=method, params=params), EventResult)
    return result.root


async def test_events_use_native_dispatch_and_preserve_original_context(event_scope: tuple[dict[str, Any], AsyncMock, AsyncMock]) -> None:
    """Discovery and lifecycle use real methods and retain explicit nulls."""
    provider = FixtureProvider()
    with event_provider("server-a", provider):
        with pytest.raises(ValueError):
            with event_provider("server-a", FixtureProvider()):
                pass
        async with Client(transport.mcp_app, mode="2026-07-28", cache=None) as client:
            discovered = await client.session.send_discover("2026-07-28")
            assert discovered["capabilities"]["events"] == {}
            assert "example.changed" == (await send(client, "events/list", {}))["events"][0]["name"]
            params: dict[str, Any] = {
                "name": "example.changed",
                "arguments": {"projectId": "project-a"},
                "delivery": {"mode": "webhook", "url": "https://callback.example.test/events", "secret": "whsec_synthetic-only"},  # pragma: allowlist secret
                "cursor": None,
                "ttlMs": None,
            }
            assert (await send(client, "events/subscribe", params))["id"] == "sub_synthetic"
            context, method, forwarded = provider.calls[-1]
            assert method == "events/subscribe"
            assert {key: value for key, value in forwarded.items() if key != "_meta"} == {key: value for key, value in params.items() if value is not None}
            assert context.server_id == "server-a"
            assert context.user["user_id"] == "original-owner"
            assert context.headers["Authorization"] == "Bearer synthetic-original"
            assert "synthetic-original" not in repr(context)
            unsubscribed = await send(client, "events/unsubscribe", {"name": params["name"], "arguments": params["arguments"], "delivery": {"mode": "webhook", "url": params["delivery"]["url"]}})
            assert set(unsubscribed) <= {"resultType", "_meta"}
        await transport._adapt_event_request(SimpleNamespace(method="events/subscribe"), EventRequestParams.model_validate({"name": "example.changed", "cursor": None, "ttlMs": None}))
        assert provider.calls[-1][2] == {"name": "example.changed", "cursor": None, "ttlMs": None}
    assert get_event_provider("server-a") is None
    event_scope[2].assert_awaited()


@pytest.mark.parametrize("denial", ["disabled", "anonymous", "malformed-auth", "scope", "rbac", "foreign-server", "provider"])
async def test_events_deny_without_invoking_owner(event_scope: tuple[dict[str, Any], AsyncMock, AsyncMock], monkeypatch: pytest.MonkeyPatch, denial: str) -> None:
    """Feature, caller, scope, RBAC, visibility, and owner each fail closed."""
    user, permission, visibility = event_scope
    provider = FixtureProvider()
    if denial == "disabled":
        monkeypatch.setattr(settings, "mcpgateway_mcp_events_enabled", False)
    elif denial == "anonymous":
        user["is_authenticated"] = False
    elif denial == "malformed-auth":
        user["is_authenticated"] = "false"
    elif denial == "scope":
        user["scoped_permissions"] = ["tools.read"]
    elif denial == "rbac":
        permission.return_value = False
    elif denial == "foreign-server":
        visibility.side_effect = PermissionError("private server")
    else:
        provider.denied = True
    with event_provider("server-a", provider):
        async with Client(transport.mcp_app, mode="2026-07-28", cache=None) as client:
            assert "events" not in (await client.session.send_discover("2026-07-28"))["capabilities"]
            with pytest.raises(MCPError) as error:
                await send(client, "events/subscribe", {"name": "example.changed"})
            assert error.value.code in {-32601, -32001, -32603}
    assert provider.calls == []


@pytest.mark.parametrize("failure", ["provider-error", "callback-error", "bad-result", "revoked-during-call"])
async def test_events_hide_secret_errors_and_recheck_after_io(event_scope: tuple[dict[str, Any], AsyncMock, AsyncMock], failure: str, caplog: pytest.LogCaptureFixture) -> None:
    """Provider errors and revoked rights never return subscription secrets."""
    provider = FixtureProvider()
    provider.fail = failure if failure != "revoked-during-call" else False
    provider.revoke_during_request = failure == "revoked-during-call"
    secret = "whsec_only-a-public-synthetic-sentinel"  # pragma: allowlist secret
    with event_provider("server-a", provider):
        async with Client(transport.mcp_app, mode="2026-07-28", cache=None) as client:
            with pytest.raises(MCPError) as error:
                await send(client, "events/subscribe", {"name": "example.changed", "delivery": {"secret": secret}})
            assert secret not in str(error.value)
            assert secret not in caplog.text


def test_event_logging_omits_secret_callback_and_arguments() -> None:
    """Detailed request logging omits the entire Events parameter object."""
    payload = (
        b'{"method":"events/subscribe","params":{"delivery":{"secret":"whsec_sentinel","url":"https://private-callback.example.test"},"arguments":{"private":"evidence"}}}'  # pragma: allowlist secret
    )
    logged = _mask_json_payload_for_logging(payload)
    assert "events/subscribe" in logged
    assert "whsec_sentinel" not in logged and "private-callback" not in logged and "evidence" not in logged
    assert "private-callback" not in _mask_json_payload_for_logging(b"[" + payload + b"]")
    assert "whsec_sentinel" not in _mask_json_payload_for_logging(b'{"method":{},"secret":"whsec_sentinel"}')  # pragma: allowlist secret
    assert EventRequestParams.model_validate({"cursor": None, "ttlMs": None}).model_dump(exclude_unset=True) == {"cursor": None, "ttlMs": None}
