# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_resource_service_reverse_proxy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for PROXIED gateway dispatch in ResourceService.invoke_resource() (reverse-proxy Phase 4).

A PROXIED gateway persists no reachable URL: resource reads resolve the
process-local reverse-proxy WebSocket connection for the persisted stable gateway
ID and send a ``resources/read`` JSON-RPC request carrying the persisted upstream
URI (or the substituted request URI for template-derived reads) — never a
namespaced public catalog name. Stored gateway auth material, when present, is
attached to the outbound frame as ``DownstreamAuth``; when absent, the
authentication fields are omitted. All failure modes fail closed through the
existing MCP-path error taxonomy.
"""

# Standard
import logging
from unittest.mock import AsyncMock, MagicMock, Mock, patch, PropertyMock

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.common.models import BlobResourceContents, ResourceContent, TextResourceContents
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Resource as DbResource
from mcpgateway.services.resource_service import ResourceError, ResourceNotFoundError, ResourceService
from mcpgateway.services.reverse_proxy_protocol import JsonRpcErrorResponse, JsonRpcSuccessResponse, ResponseMessage
from mcpgateway.services.reverse_proxy_relay import RelayUnavailableError
from mcpgateway.services.reverse_proxy_sessions import ConnectionClosedError, ConnectionId, ConnectionNotFoundError

PROXIED_RESOURCE_URI = "file:///upstream/docs/readme.md"  # persisted upstream URI, sent verbatim (D1)
PROXIED_TEMPLATE_URI = "file:///upstream/docs/{name}"
PROXIED_SUBSTITUTED_URI = "file:///upstream/docs/readme"  # template read: substituted request URI (D1)
PROXIED_TEXT_RESULT = {"contents": [{"uri": PROXIED_RESOURCE_URI, "mimeType": "text/markdown", "text": "proxied ok"}]}
PROXIED_BLOB_RESULT = {"contents": [{"uri": PROXIED_RESOURCE_URI, "mimeType": "application/octet-stream", "blob": "aGVsbG8="}]}


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    with patch("mcpgateway.services.resource_service.audit_trail") as mock_audit, patch("mcpgateway.services.resource_service.structured_logger") as mock_logger:
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture
def resource_service():
    """Create a plain resource service instance (no SSRF/httpx surface on the PROXIED path)."""
    return ResourceService()


@pytest.fixture
def proxied_gateway():
    """Create a PROXIED gateway model: no auth material, transport is the dispatch authority."""
    gateway = MagicMock(spec=DbGateway)
    gateway.id = "proxied-gw-1"
    gateway.name = "proxied_gateway"
    gateway.url = "reverse-proxy://local"
    gateway.transport = "PROXIED"
    gateway.created_via = "reverse_proxy"
    gateway.auth_type = None
    gateway.auth_value = None
    gateway.auth_query_params = None
    gateway.oauth_config = None
    gateway.ca_certificate = None
    gateway.ca_certificate_sig = None
    gateway.client_cert = None
    gateway.client_key = None
    return gateway


@pytest.fixture
def proxied_resource(proxied_gateway):
    """Create a resource synced from a PROXIED gateway; the upstream URI is the dispatch key (D1)."""
    resource = MagicMock(spec=DbResource)
    resource.id = "res-1"
    resource.name = "proxied_resource"
    resource.uri = PROXIED_RESOURCE_URI
    resource.mime_type = "text/markdown"
    resource.gateway_id = proxied_gateway.id
    resource.gateway = proxied_gateway
    return resource


def _success_response(request_id: str, result: dict) -> ResponseMessage:
    """Build a JSON-RPC success response frame carrying a ReadResourceResult payload."""
    return ResponseMessage(type="response", payload=JsonRpcSuccessResponse.model_validate({"jsonrpc": "2.0", "id": request_id, "result": result}))


def _error_response(request_id: str, code: int, message: str) -> ResponseMessage:
    """Build a JSON-RPC error response frame."""
    return ResponseMessage(type="response", payload=JsonRpcErrorResponse.model_validate({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}))


def _manager_mock(connection_id=ConnectionId("conn-1"), send_return=None, send_side_effect=None):
    """Build a reverse-proxy session manager mock with a fixed stable-ID resolution."""
    manager = MagicMock()
    manager.resolve_connection_id = Mock(return_value=connection_id)
    if send_side_effect is not None:
        manager.send_request = AsyncMock(side_effect=send_side_effect)
    else:
        manager.send_request = AsyncMock(return_value=send_return)
    return manager


def _structured_log_events(mock_logger):
    """Index structured-log metadata by event name for assertion."""
    return {logged_call.kwargs["metadata"].get("event"): logged_call.kwargs["metadata"] for logged_call in mock_logger.log.call_args_list if isinstance(logged_call.kwargs.get("metadata"), dict)}


def _structured_log_call_kwargs(mock_logger, event_name):
    """Return kwargs for the first matching structured-log event, or None."""
    for logged_call in mock_logger.log.call_args_list:
        metadata = logged_call.kwargs.get("metadata")
        if isinstance(metadata, dict) and metadata.get("event") == event_name:
            return logged_call.kwargs
    return None


class TestReadResourceReverseProxied:
    """PROXIED gateway resource reads dispatch through the reverse-proxy session manager."""

    @pytest.mark.asyncio
    async def test_read_resource_without_cached_content_dispatches_to_proxied_gateway(self, resource_service, proxied_gateway, mock_logging_services):
        """A discovered PROXIED resource has metadata only; its body comes from resources/read."""
        resource = MagicMock(spec=DbResource)
        resource.id = "res-1"
        resource.uri = PROXIED_RESOURCE_URI
        resource.mime_type = "text/markdown"
        resource.enabled = True
        resource.gateway = proxied_gateway
        resource.gateway_id = proxied_gateway.id
        resource.extension_metadata = None
        type(resource).content = PropertyMock(side_effect=ValueError("Resource has no content"))
        db = MagicMock()
        db.get.return_value = resource

        with (
            patch.object(resource_service, "_check_resource_access", AsyncMock(return_value=True)),
            patch.object(resource_service, "_get_plugin_manager", AsyncMock(return_value=None)),
            patch.object(resource_service, "invoke_resource", AsyncMock(return_value="live downstream text")) as invoke,
        ):
            result = await resource_service.read_resource(db, resource_id=resource.id)

        assert result.text == "live downstream text"
        invoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_distributed_dispatch_uses_relay_stable_id_api(self, resource_service, monkeypatch):
        relay = MagicMock(send_request_by_stable_id=AsyncMock(return_value=_success_response("relay", {"contents": [{"uri": "file:///upstream", "text": "relay resource"}]})))
        monkeypatch.setattr(settings, "mcpgateway_reverse_proxy_distributed_enabled", True)

        with patch("mcpgateway.services.reverse_proxy_relay_runtime.get_reverse_proxy_relay", AsyncMock(return_value=relay)):
            result = await resource_service._read_reverse_proxied_resource("proxied-gw-1", "file:///upstream", 1.0)

        stable_id, request = relay.send_request_by_stable_id.await_args.args
        assert stable_id == "proxied-gw-1"
        assert request.method == "resources/read"
        assert request.params == {"uri": "file:///upstream"}
        assert isinstance(result, TextResourceContents)
        assert result.text == "relay resource"

    @pytest.mark.asyncio
    async def test_distributed_redis_failure_maps_to_code_only_resource_error(self, resource_service, monkeypatch):
        relay = MagicMock(send_request_by_stable_id=AsyncMock(side_effect=RelayUnavailableError()))
        monkeypatch.setattr(settings, "mcpgateway_reverse_proxy_distributed_enabled", True)

        with patch("mcpgateway.services.reverse_proxy_relay_runtime.get_reverse_proxy_relay", AsyncMock(return_value=relay)):
            with pytest.raises(ResourceError) as caught:
                await resource_service._read_reverse_proxied_resource("proxied-gw-1", "file:///upstream", 1.0)

        assert str(caught.value) == "Reverse-proxy relay unavailable for gateway 'proxied-gw-1'"

    @pytest.mark.asyncio
    async def test_dispatch_sends_resources_read_with_persisted_uri(self, resource_service, proxied_resource, mock_logging_services):
        """resources/read must carry the persisted upstream URI verbatim and normalize via the shared path."""
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_TEXT_RESULT))

        with patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            result = await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=proxied_resource.gateway)

        manager.resolve_connection_id.assert_called_once_with("proxied-gw-1")
        manager.send_request.assert_awaited_once()
        sent_connection_id, sent_request = manager.send_request.await_args.args
        assert sent_connection_id == "conn-1"
        assert sent_request.method == "resources/read"
        assert sent_request.params == {"uri": PROXIED_RESOURCE_URI}
        assert manager.send_request.await_args.kwargs["timeout_seconds"] == settings.health_check_timeout

        assert isinstance(result, TextResourceContents)
        assert result.text == "proxied ok"
        assert result.mime_type == "text/markdown"

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert events["mcp_call_started"]["transport"] == "proxied"
        assert events["mcp_call_started"]["resource_uri"] == PROXIED_RESOURCE_URI
        assert events["mcp_call_completed"]["transport"] == "proxied"
        assert events["mcp_call_completed"]["success"] is True
        assert "mcp_call_failed" not in events

    @pytest.mark.asyncio
    async def test_template_read_sends_substituted_uri(self, resource_service, proxied_resource):
        """Template-derived reads dispatch the substituted request URI, never the raw template (D1)."""
        assert PROXIED_SUBSTITUTED_URI != PROXIED_TEMPLATE_URI  # precedence is only exercised when they differ
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_TEXT_RESULT))

        with patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            result = await resource_service.invoke_resource(
                MagicMock(),
                "res-1",
                PROXIED_TEMPLATE_URI,
                resource_template_uri=PROXIED_SUBSTITUTED_URI,
                resource_obj=proxied_resource,
                gateway_obj=proxied_resource.gateway,
            )

        sent_request = manager.send_request.await_args.args[1]
        assert sent_request.method == "resources/read"
        assert sent_request.params == {"uri": PROXIED_SUBSTITUTED_URI}
        assert isinstance(result, TextResourceContents)
        assert result.text == "proxied ok"

    @pytest.mark.asyncio
    async def test_absent_stable_id_mapping_fails_closed(self, resource_service, proxied_resource):
        """No live connection for the stable gateway ID: fail closed, never send, name the gateway."""
        manager = _manager_mock(connection_id=None)

        with patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            with pytest.raises(ResourceError, match=r"No active reverse-proxy connection for gateway 'proxied-gw-1'"):
                await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=proxied_resource.gateway)

        manager.send_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_session_timeout_maps_to_resource_error(self, resource_service, proxied_resource, mock_logging_services):
        """A session-level timeout surfaces as ResourceError with a proxied resource_timeout log event."""
        manager = _manager_mock(send_side_effect=TimeoutError("slow downstream"))

        with (
            patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ResourceError, match="Resource read timed out after"),
        ):
            await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=proxied_resource.gateway)

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert events["resource_timeout"]["transport"] == "proxied"
        assert events["resource_timeout"]["resource_uri"] == PROXIED_RESOURCE_URI
        assert "mcp_call_failed" not in events

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "connection_error, expected_error_type",
        [
            (ConnectionClosedError(connection_id=ConnectionId("conn-1")), "ConnectionClosedError"),
            (ConnectionNotFoundError(connection_id=ConnectionId("conn-1")), "ConnectionNotFoundError"),
        ],
        ids=["connection_closed", "connection_not_found"],
    )
    async def test_connection_failure_maps_to_resource_error(self, resource_service, proxied_resource, mock_logging_services, connection_error, expected_error_type):
        """Dropped or stale connections surface as ResourceError, never raw session errors."""
        manager = _manager_mock(send_side_effect=connection_error)

        with (
            patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ResourceError, match=r"Reverse-proxy connection for gateway 'proxied-gw-1'"),
        ):
            await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=proxied_resource.gateway)

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert events["mcp_call_failed"]["transport"] == "proxied"
        failed_call = _structured_log_call_kwargs(mock_logging_services["structured_logger"], "mcp_call_failed")
        assert failed_call is not None
        assert failed_call["level"] == "ERROR"
        assert failed_call["error_details"]["error_type"] == expected_error_type

    @pytest.mark.asyncio
    async def test_mcp_error_response_raises_code_only(self, resource_service, proxied_resource, mock_logging_services):
        """A JSON-RPC error response surfaces the MCP error code only; peer free text never escapes."""
        manager = _manager_mock(send_return=_error_response("req-1", code=-32001, message="upstream exploded"))

        with patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            with pytest.raises(ResourceError) as direct_exc:
                await resource_service._read_reverse_proxied_resource("proxied-gw-1", PROXIED_RESOURCE_URI, 30.0)
        assert str(direct_exc.value) == "MCP error -32001"

        with (
            patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ResourceError, match=r"MCP error -32001"),
        ):
            await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=proxied_resource.gateway)

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert "mcp_call_failed" in events
        failed_call = _structured_log_call_kwargs(mock_logging_services["structured_logger"], "mcp_call_failed")
        assert failed_call is not None
        assert failed_call["level"] == "ERROR"
        assert failed_call["error_details"]["error_type"] == "JsonRpcErrorResponse"
        assert failed_call["error_details"]["error_message"] == "MCP error -32001"

        # Peer-controlled free text must reach no telemetry sink: scan every
        # structured-logger call at any level for the peer message.
        all_logged_calls = " ".join(repr(logged_call) for logged_call in mock_logging_services["structured_logger"].mock_calls)
        assert "upstream exploded" not in all_logged_calls

    @pytest.mark.asyncio
    async def test_read_resource_full_path_normalizes_text_and_preserves_mime_type(self, resource_service, proxied_gateway):
        """read_resource()'s shared normalization runs unchanged: text resolved, persisted mimeType kept."""
        content_obj = ResourceContent(type="resource", id="res-1", uri=PROXIED_RESOURCE_URI, mime_type="text/markdown", text=PROXIED_RESOURCE_URI)
        resource_db = MagicMock(spec=DbResource)
        resource_db.id = "res-1"
        resource_db.uri = PROXIED_RESOURCE_URI
        resource_db.mime_type = "text/markdown"
        resource_db.enabled = True
        resource_db.visibility = "public"
        resource_db.team_id = None
        resource_db.owner_email = "admin@example.com"
        resource_db.content = content_obj
        resource_db.gateway = proxied_gateway

        db = MagicMock()
        db.get.return_value = resource_db

        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_TEXT_RESULT))

        with patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            result = await resource_service.read_resource(db, resource_id="res-1")

        manager.send_request.assert_awaited_once()
        assert manager.send_request.await_args.args[1].params == {"uri": PROXIED_RESOURCE_URI}
        assert result.text == "proxied ok"
        assert result.mime_type == "text/markdown"

    @pytest.mark.asyncio
    async def test_blob_contents_return_blob_payload(self, resource_service, proxied_resource):
        """BlobResourceContents remain typed with their runtime MIME metadata."""
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_BLOB_RESULT))

        with patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            result = await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=proxied_resource.gateway)

        assert isinstance(result, BlobResourceContents)
        assert result.blob == "aGVsbG8="
        assert result.mime_type == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_read_resource_preserves_blob_type_and_runtime_mime_type(self, resource_service, proxied_gateway):
        """The public read path returns the upstream blob model without scalar conversion."""
        resource_db = MagicMock(spec=DbResource)
        resource_db.id = "res-1"
        resource_db.uri = PROXIED_RESOURCE_URI
        resource_db.mime_type = "text/plain"
        resource_db.enabled = True
        resource_db.visibility = "public"
        resource_db.team_id = None
        resource_db.owner_email = "admin@example.com"
        resource_db.gateway = proxied_gateway
        db = MagicMock()
        db.get.return_value = resource_db
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_BLOB_RESULT))

        with patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            result = await resource_service.read_resource(db, resource_id="res-1")

        assert isinstance(result, BlobResourceContents)
        assert result.blob == "aGVsbG8="
        assert result.mime_type == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_read_resource_preserves_runtime_text_mime_type(self, resource_service, proxied_gateway):
        """Runtime resources/read MIME metadata overrides stale persisted discovery metadata."""
        resource_db = MagicMock(spec=DbResource)
        resource_db.id = "res-1"
        resource_db.uri = PROXIED_RESOURCE_URI
        resource_db.mime_type = "text/plain"
        resource_db.enabled = True
        resource_db.visibility = "public"
        resource_db.team_id = None
        resource_db.owner_email = "admin@example.com"
        resource_db.gateway = proxied_gateway
        db = MagicMock()
        db.get.return_value = resource_db
        runtime_result = {"contents": [{"uri": PROXIED_RESOURCE_URI, "mimeType": "application/json", "text": '{"ok":true}'}]}
        manager = _manager_mock(send_return=_success_response("req-1", runtime_result))

        with patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            result = await resource_service.read_resource(db, resource_id="res-1")

        assert isinstance(result, TextResourceContents)
        assert result.text == '{"ok":true}'
        assert result.mime_type == "application/json"

    @pytest.mark.asyncio
    async def test_malformed_upstream_result_raises_validation_error(self, resource_service, mock_logging_services):
        """A malformed upstream ReadResourceResult logs mcp_call_failed with ValidationError, no completed event."""
        manager = _manager_mock(send_return=_success_response("req-1", {}))  # missing required contents

        with (
            patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ValidationError),
        ):
            await resource_service._read_reverse_proxied_resource("proxied-gw-1", PROXIED_RESOURCE_URI, 30.0)

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert events["mcp_call_started"]["transport"] == "proxied"
        assert "mcp_call_completed" not in events
        failed_call = _structured_log_call_kwargs(mock_logging_services["structured_logger"], "mcp_call_failed")
        assert failed_call is not None
        assert failed_call["level"] == "ERROR"
        assert failed_call["error_details"]["error_type"] == "ValidationError"
        assert failed_call["error_details"]["error_message"] == "malformed upstream resources/read result"

    @pytest.mark.asyncio
    async def test_empty_contents_fail_closed(self, resource_service, mock_logging_services):
        """A well-formed result with zero contents entries fails closed instead of indexing blindly."""
        manager = _manager_mock(send_return=_success_response("req-1", {"contents": []}))

        with (
            patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ResourceError, match=r"returned no contents"),
        ):
            await resource_service._read_reverse_proxied_resource("proxied-gw-1", PROXIED_RESOURCE_URI, 30.0)

        events = _structured_log_events(mock_logging_services["structured_logger"])
        assert "mcp_call_completed" not in events
        assert "mcp_call_failed" in events

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "transport, client_patch, stream_size",
        [("sse", "sse_client", 2), ("streamablehttp", "streamablehttp_client", 3)],
        ids=["sse_gateway", "streamablehttp_gateway"],
    )
    async def test_non_proxied_gateways_never_touch_session_manager(self, resource_service, proxied_resource, monkeypatch, transport, client_patch, stream_size):
        """Regression: SSE/streamablehttp gateways keep their existing dispatch, no proxy lookup."""
        gateway = proxied_resource.gateway
        gateway.transport = transport
        gateway.url = "http://fake-mcp:8080/mcp"

        monkeypatch.setattr(
            "mcpgateway.services.resource_service.settings",
            MagicMock(
                enable_ed25519_signing=False,
                platform_admin_email="admin@test.com",
                httpx_max_connections=10,
                httpx_max_keepalive_connections=5,
                httpx_keepalive_expiry=30,
                mcp_session_pool_enabled=False,
            ),
        )
        monkeypatch.setattr(
            "mcpgateway.services.resource_service.create_span", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False)))
        )

        mock_cs_instance = AsyncMock()
        mock_cs_instance.initialize = AsyncMock()
        mock_cs_instance.read_resource.return_value = MagicMock(contents=[MagicMock(text=f"{transport} ok", blob=None)])

        with (
            patch(f"mcpgateway.services.resource_service.{client_patch}") as mock_client,
            patch("mcpgateway.services.resource_service.ClientSession") as mock_client_session,
            patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager") as manager_factory,
        ):
            mock_client_session.return_value.__aenter__ = AsyncMock(return_value=mock_cs_instance)
            mock_client_session.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=tuple([AsyncMock(), AsyncMock(), None][:stream_size]))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=gateway)

        mock_cs_instance.read_resource.assert_awaited_once()
        manager_factory.assert_not_called()
        assert result == f"{transport} ok"

    @pytest.mark.asyncio
    async def test_team_scoped_proxied_resource_denied_to_other_team(self, resource_service, proxied_gateway):
        """Layer-1 regression: a team-scoped proxied resource is invisible to another team's caller."""
        content_obj = ResourceContent(type="resource", id="res-1", uri=PROXIED_RESOURCE_URI, mime_type="text/markdown", text=PROXIED_RESOURCE_URI)
        resource_db = MagicMock(spec=DbResource)
        resource_db.id = "res-1"
        resource_db.uri = PROXIED_RESOURCE_URI
        resource_db.mime_type = "text/markdown"
        resource_db.enabled = True
        resource_db.visibility = "team"
        resource_db.team_id = "team-a"
        resource_db.owner_email = "admin@example.com"
        resource_db.content = content_obj
        resource_db.gateway = proxied_gateway

        db = MagicMock()
        db.get.return_value = resource_db

        with (
            patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager") as manager_factory,
            pytest.raises(ResourceNotFoundError, match="Resource not found"),
        ):
            await resource_service.read_resource(db, resource_id="res-1", user="outsider@example.com", token_teams=["team-b"])

        manager_factory.assert_not_called()


class TestReadResourceReverseProxiedAuth:
    """Downstream auth forwarding on the PROXIED resources/read path (reverse-proxy Phase 4)."""

    @pytest.mark.asyncio
    async def test_dispatch_attaches_stored_gateway_auth(self, resource_service, proxied_resource):
        """Stored gateway auth material reaches send_request as DownstreamAuth with the exact header dict."""
        proxied_gateway = proxied_resource.gateway
        proxied_gateway.auth_type = "bearer"
        proxied_gateway.auth_value = {"Authorization": "Bearer proxied-resource-secret"}
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_TEXT_RESULT))

        with patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            result = await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=proxied_gateway)

        assert isinstance(result, TextResourceContents)
        assert result.text == "proxied ok"
        manager.send_request.assert_awaited_once()
        attached_auth = manager.send_request.await_args.kwargs["auth"]
        assert attached_auth is not None
        assert attached_auth.headers == {"Authorization": "Bearer proxied-resource-secret"}
        assert attached_auth.auth_type == "bearer"

    @pytest.mark.asyncio
    async def test_dispatch_without_stored_auth_omits_auth_attachment(self, resource_service, proxied_resource):
        """No stored gateway auth material: send_request receives auth=None so the envelope omits the fields."""
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_TEXT_RESULT))

        with patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            result = await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=proxied_resource.gateway)

        assert isinstance(result, TextResourceContents)
        assert result.text == "proxied ok"
        manager.send_request.assert_awaited_once()
        assert manager.send_request.await_args.kwargs["auth"] is None

    @pytest.mark.asyncio
    async def test_authed_downstream_mcp_error_is_code_only_and_never_logged(self, resource_service, proxied_resource, mock_logging_services, caplog):
        """A 401-equivalent downstream error raises code-only; peer text and the secret reach no telemetry sink."""
        caplog.set_level(logging.DEBUG)
        proxied_gateway = proxied_resource.gateway
        proxied_gateway.auth_type = "bearer"
        proxied_gateway.auth_value = {"Authorization": "Bearer proxied-resource-secret"}
        manager = _manager_mock(send_return=_error_response("req-1", code=-32001, message="unauthorized downstream"))

        with (
            patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ResourceError, match=r"MCP error -32001") as exc_info,
        ):
            await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=proxied_gateway)

        assert "unauthorized downstream" not in str(exc_info.value)
        assert "proxied-resource-secret" not in str(exc_info.value)
        all_logged_calls = " ".join(repr(logged_call) for logged_call in mock_logging_services["structured_logger"].mock_calls)
        assert "unauthorized downstream" not in all_logged_calls
        assert "proxied-resource-secret" not in all_logged_calls
        # The canary proves caplog capture is live, so the denials below are non-vacuous.
        logging.getLogger("mcpgateway.services.resource_service").info("caplog-canary")
        assert "caplog-canary" in caplog.text
        assert "unauthorized downstream" not in caplog.text
        assert "proxied-resource-secret" not in caplog.text

    @pytest.mark.asyncio
    async def test_dispatch_forwards_basic_auth(self, resource_service, proxied_resource):
        """Stored basic credentials reach the envelope as the verbatim Authorization header."""
        proxied_gateway = proxied_resource.gateway
        proxied_gateway.auth_type = "basic"
        proxied_gateway.auth_value = {"Authorization": "Basic dXNlcjpwYXNz"}
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_TEXT_RESULT))

        with patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            result = await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=proxied_gateway)

        assert isinstance(result, TextResourceContents)
        assert result.text == "proxied ok"
        attached_auth = manager.send_request.await_args.kwargs["auth"]
        assert attached_auth is not None
        assert attached_auth.headers == {"Authorization": "Basic dXNlcjpwYXNz"}
        assert attached_auth.auth_type == "basic"

    @pytest.mark.asyncio
    async def test_dispatch_forwards_authheaders_custom_mapping(self, resource_service, proxied_resource):
        """Custom authheaders material forwards the full stored header mapping (Oracle authheaders gap)."""
        proxied_gateway = proxied_resource.gateway
        proxied_gateway.auth_type = "authheaders"
        proxied_gateway.auth_value = {"X-Api-Key": "proxied-resource-key", "X-Tenant": "acme"}  # pragma: allowlist secret
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_TEXT_RESULT))

        with patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)):
            result = await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=proxied_gateway)

        assert isinstance(result, TextResourceContents)
        assert result.text == "proxied ok"
        attached_auth = manager.send_request.await_args.kwargs["auth"]
        assert attached_auth is not None
        assert attached_auth.headers == {"X-Api-Key": "proxied-resource-key", "X-Tenant": "acme"}  # pragma: allowlist secret
        assert attached_auth.auth_type == "authheaders"

    @pytest.mark.asyncio
    async def test_dispatch_rejects_unsupported_auth_mode_code_only(self, resource_service, proxied_resource, mock_logging_services):
        """query_param-mode stored material is rejected with a typed, code-only error — never silently omitted."""
        proxied_gateway = proxied_resource.gateway
        proxied_gateway.auth_type = "query_param"
        proxied_gateway.auth_value = {"api_key": "proxied-resource-secret"}  # pragma: allowlist secret
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_TEXT_RESULT))

        with (
            patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ResourceError) as exc_info,
        ):
            await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=proxied_gateway)

        assert "query_param" in str(exc_info.value)
        assert "proxied-resource-secret" not in str(exc_info.value)
        manager.send_request.assert_not_called()
        all_logged_calls = " ".join(repr(logged_call) for logged_call in mock_logging_services["structured_logger"].mock_calls)
        assert "proxied-resource-secret" not in all_logged_calls

    @pytest.mark.asyncio
    async def test_dispatch_rejects_malformed_auth_map_without_echo(self, resource_service, proxied_resource, mock_logging_services):
        """Non-string header values are rejected at the boundary; the value never reaches error text or telemetry."""
        proxied_gateway = proxied_resource.gateway
        proxied_gateway.auth_type = "authheaders"
        proxied_gateway.auth_value = {"X-Api-Key": 12345}
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_TEXT_RESULT))

        with (
            patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            pytest.raises(ResourceError) as exc_info,
        ):
            await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, resource_obj=proxied_resource, gateway_obj=proxied_gateway)

        assert "12345" not in str(exc_info.value)
        manager.send_request.assert_not_called()
        all_logged_calls = " ".join(repr(logged_call) for logged_call in mock_logging_services["structured_logger"].mock_calls)
        assert "12345" not in all_logged_calls

    @pytest.mark.asyncio
    async def test_inbound_identity_headers_never_enter_envelope(self, resource_service, proxied_resource):
        """Identity-propagation headers built from the inbound user never ride the proxy envelope."""
        # First-Party
        from mcpgateway.transports.context import UserContext

        proxied_gateway = proxied_resource.gateway
        proxied_gateway.auth_type = "bearer"
        proxied_gateway.auth_value = {"Authorization": "Bearer proxied-resource-secret"}
        manager = _manager_mock(send_return=_success_response("req-1", PROXIED_TEXT_RESULT))
        identity = UserContext(user_id="inbound@example.com", email="inbound@example.com", is_admin=False, teams=[], auth_method="bearer")

        with (
            patch("mcpgateway.services.resource_service.get_reverse_proxy_session_manager", AsyncMock(return_value=manager)),
            patch("mcpgateway.services.resource_service.build_identity_headers", return_value={"Authorization": "Bearer INBOUND-HOSTILE", "X-User-Id": "inbound"}),
        ):
            result = await resource_service.invoke_resource(MagicMock(), "res-1", PROXIED_RESOURCE_URI, user_identity=identity, resource_obj=proxied_resource, gateway_obj=proxied_gateway)

        assert isinstance(result, TextResourceContents)
        assert result.text == "proxied ok"
        attached_auth = manager.send_request.await_args.kwargs["auth"]
        assert attached_auth is not None
        assert attached_auth.headers == {"Authorization": "Bearer proxied-resource-secret"}
        assert attached_auth.auth_type == "bearer"
