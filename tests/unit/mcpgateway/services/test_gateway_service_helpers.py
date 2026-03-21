# -*- coding: utf-8 -*-
"""GatewayService helper tests."""

# Standard
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.schemas import GatewayRead
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayNameConflictError, GatewayService, OAuthToolValidationError
from mcpgateway.utils.services_auth import decode_auth, encode_auth
from mcpgateway.validation.tags import validate_tags_field


def test_gateway_name_conflict_error_messages():
    error = GatewayNameConflictError("gw-name")
    assert "Public Gateway already exists" in str(error)
    assert error.enabled is True

    error_inactive = GatewayNameConflictError("gw-name", enabled=False, gateway_id=123, visibility="team")
    assert "Team-level Gateway already exists" in str(error_inactive)
    assert "currently inactive" in str(error_inactive)
    assert error_inactive.gateway_id == 123


def test_gateway_service_normalize_url():
    service = GatewayService()
    assert service.normalize_url("http://localhost:8080/path") == "http://localhost:8080/path"
    assert service.normalize_url("http://127.0.0.1:8080/path") == "http://localhost:8080/path"


def test_gateway_service_auth_headers():
    """Test that _get_auth_headers returns only Content-Type (no credentials).

    Gateway credentials are intentionally NOT included to prevent
    sending this gateway's credentials to remote servers.
    """
    service = GatewayService()
    headers = service._get_auth_headers()
    assert headers["Content-Type"] == "application/json"
    # Authorization is intentionally NOT included - each gateway should have its own auth_value
    assert "Authorization" not in headers
    assert "X-API-Key" not in headers


def test_gateway_service_validate_tools():
    service = GatewayService()
    valid_tool = {"name": "tool-1", "integration_type": "REST", "request_type": "POST", "url": "http://example.com"}
    invalid_tool = {"name": None}

    valid, errors = service._validate_tools([valid_tool, invalid_tool])
    assert len(valid) == 1
    assert len(errors) == 1

    with pytest.raises(GatewayConnectionError):
        service._validate_tools([invalid_tool], context="default")

    with pytest.raises(OAuthToolValidationError):
        service._validate_tools([invalid_tool], context="oauth")


def test_gateway_service_lock_path_absolute(monkeypatch):
    monkeypatch.setattr(settings, "cache_type", "file")
    monkeypatch.setattr(settings, "filelock_name", "/var/tmp/gw.lock")

    service = GatewayService()

    assert service._lock_path.startswith(tempfile.gettempdir())
    assert service._lock_path.endswith("var/tmp/gw.lock")


def test_gateway_service_convert_gateway_to_read(monkeypatch):
    service = GatewayService()

    gateway = SimpleNamespace(
        auth_value={"token": "secret"},
        tags=["Analytics", "ml"],
        created_by="tester",
        modified_by=None,
        created_at=None,
        updated_at=None,
        version=None,
        team=None,
    )

    # Mock model_validate to return a mock that returns itself when masked() is called
    # and also stores the original dict for assertions
    class MockGatewayRead:
        def __init__(self, data):
            self._data = data
            self._masked_called = False

        def masked(self):
            self._masked_called = True
            return self

        def __getitem__(self, key):
            return self._data[key]

    monkeypatch.setattr(GatewayRead, "model_validate", staticmethod(lambda x: MockGatewayRead(x)))

    result = service.convert_gateway_to_read(gateway)
    assert decode_auth(result["auth_value"]) == {"token": "secret"}
    assert result["tags"] == validate_tags_field(["Analytics", "ml"])
    # SECURITY: Verify .masked() is called to prevent credential leakage
    assert result._masked_called, "convert_gateway_to_read must call .masked() to prevent credential leakage"


def test_gateway_service_validate_tools_valueerror(monkeypatch):
    service = GatewayService()

    monkeypatch.setattr("mcpgateway.services.gateway_service.ToolCreate.model_validate", lambda _data: (_ for _ in ()).throw(ValueError("JSON structure exceeds maximum depth")))

    with pytest.raises(GatewayConnectionError) as excinfo:
        service._validate_tools([{"name": "tool-depth"}])
    assert "schema too deeply nested" in str(excinfo.value)

    monkeypatch.setattr("mcpgateway.services.gateway_service.ToolCreate.model_validate", lambda _data: (_ for _ in ()).throw(ValueError("other")))

    with pytest.raises(GatewayConnectionError) as excinfo:
        service._validate_tools([{"name": "tool-other"}])
    assert "ValueError" in str(excinfo.value)


@pytest.mark.asyncio
async def test_authheaders_auth_value_stored_as_dict(monkeypatch):
    """Verify that registering a gateway with authheaders stores auth_value as a plain dict.

    auth_value DB column is Mapped[Optional[Dict[str, str]]] (JSON). Storing a string
    in that column causes the driver to write JSON null, which breaks health checks
    and the auto-refresh loop. The creation path must store the plain dict, consistent
    with the update path and the column type annotation.
    """
    # Verify the type contract: encode_auth() returns str, NOT a dict.
    # This is why storing its result in a Dict-typed JSON column produces null.
    encoded = encode_auth({"X-Key": "value"})
    assert isinstance(encoded, str), "encode_auth must return str — storing it in a dict JSON column yields null"

    # Build a minimal gateway with authheaders
    # Standard
    from types import SimpleNamespace as NS

    gateway = NS(
        name="test-gw",
        url="http://localhost:8000/mcp",
        description=None,
        transport="sse",
        tags=[],
        passthrough_headers=None,
        auth_type="authheaders",
        auth_value=None,
        auth_headers=[
            {"key": "X-Custom-Auth-Header", "value": "my-token"},
            {"key": "X-Custom-User-ID", "value": "user-123"},
        ],
        auth_query_param_key=None,
        auth_query_param_value=None,
        auth_query_params=None,
        oauth_config=None,
        one_time_auth=False,
        ca_certificate=None,
        ca_certificate_sig=None,
        signing_algorithm=None,
        visibility="public",
        enabled=True,
        team_id=None,
        owner_email=None,
        gateway_mode="cache",
    )

    # First-Party
    from mcpgateway.schemas import ToolCreate

    fake_tool = ToolCreate(name="echo", integration_type="REST", request_type="POST", url="http://localhost:8000/mcp")

    service = GatewayService()
    service._check_gateway_uniqueness = MagicMock(return_value=None)
    service._initialize_gateway = AsyncMock(return_value=({"tools": {}}, [fake_tool], [], []))
    service._notify_gateway_added = AsyncMock()

    monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        "mcpgateway.services.gateway_service.GatewayRead.model_validate",
        lambda x: MagicMock(masked=lambda: x),
    )

    db = MagicMock()
    db.flush = Mock()
    db.refresh = Mock()

    # Snapshot at db.add() time — tools flow through the gateway relationship (gateway.tools=tools),
    # not separate db.add() calls.
    # First-Party
    from mcpgateway.db import Gateway as DbGateway

    captured_gw: dict = {}
    captured_tool_auth_values: list = []

    def _capture_add(obj):
        if isinstance(obj, DbGateway):
            captured_gw["auth_value"] = obj.auth_value  # snapshot before any mutation
            for t in obj.tools or []:
                captured_tool_auth_values.append(t.auth_value)

    db.add = Mock(side_effect=_capture_add)

    await service.register_gateway(db, gateway)

    # --- DbGateway assertion ---
    # auth_value must be a plain dict — NOT a string.
    # A string stored in a Mapped[Optional[Dict[str, str]]] JSON column is written as JSON null.
    assert "auth_value" in captured_gw, "db.add was never called with a DbGateway object"
    assert isinstance(captured_gw["auth_value"], dict), f"DbGateway.auth_value must be dict for authheaders auth type, got {type(captured_gw['auth_value'])}: {captured_gw['auth_value']!r}"
    assert captured_gw["auth_value"] == {"X-Custom-Auth-Header": "my-token", "X-Custom-User-ID": "user-123"}

    # --- DbTool assertion ---
    # DbTool.auth_value is Mapped[Optional[str]] (Text), so it must be an encoded string,
    # not a raw dict. tool_service.py calls decode_auth() on it at read-time.
    assert len(captured_tool_auth_values) == 1, "expected exactly one DbTool to be added"
    assert isinstance(captured_tool_auth_values[0], str), f"DbTool.auth_value must be an encoded string for Text column, got {type(captured_tool_auth_values[0])}: {captured_tool_auth_values[0]!r}"
    # Decoding must recover the original headers dict
    assert decode_auth(captured_tool_auth_values[0]) == {"X-Custom-Auth-Header": "my-token", "X-Custom-User-ID": "user-123"}


def test_update_or_create_tools_authheaders_no_spurious_update():
    """Verify _update_or_create_tools does NOT trigger a spurious update when the
    gateway's auth_value dict matches the existing tool's encoded auth_value.

    encode_auth() uses os.urandom(12) for the AES-GCM nonce, so comparing
    ciphertext would always differ even when the plaintext is identical. The
    comparison must use decoded/plaintext values to avoid write amplification
    on every health-check refresh cycle.
    """
    # Standard
    from types import SimpleNamespace as NS

    service = GatewayService()

    auth_dict = {"X-My-Header": "secret-val"}
    encoded = encode_auth(auth_dict)
    original_encoded = encoded  # save for byte-for-byte comparison

    # Existing tool already has the correctly encoded auth_value stored
    existing = MagicMock()
    existing.original_name = "my-tool"
    existing.url = "http://gw.example.com/mcp"
    existing.description = "desc"
    existing.original_description = "desc"
    existing.integration_type = "MCP"
    existing.request_type = "POST"
    existing.headers = {}
    existing.input_schema = {}
    existing.output_schema = None
    existing.jsonpath_filter = None
    existing.auth_type = "authheaders"
    existing.auth_value = encoded  # Text column — already encoded
    existing.visibility = "public"

    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [existing]

    tool = NS(
        name="my-tool",
        description="desc",
        input_schema={},
        output_schema=None,
        request_type="POST",
        headers={},
        annotations=None,
        jsonpath_filter=None,
    )

    gateway = MagicMock()
    gateway.id = "gw-1"
    gateway.url = "http://gw.example.com/mcp"
    gateway.auth_type = "authheaders"
    gateway.auth_value = auth_dict  # JSON column — plain dict
    gateway.visibility = "public"

    result = service._update_or_create_tools(db, [tool], gateway, "update")

    # No new tools returned
    assert result == []
    # auth_value must be the EXACT same string — no spurious re-encryption
    assert existing.auth_value is original_encoded, f"auth_value was spuriously rewritten: {existing.auth_value!r} != {original_encoded!r}"
    assert decode_auth(existing.auth_value) == auth_dict
