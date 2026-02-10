# -*- coding: utf-8 -*-
"""GatewayService helper tests."""

# Standard
import tempfile
from types import SimpleNamespace

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.schemas import GatewayRead
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayNameConflictError, GatewayService, OAuthToolValidationError
from mcpgateway.utils.services_auth import decode_auth
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


def test_gateway_service_prepare_gateway_for_read():
    service = GatewayService()
    gateway = SimpleNamespace(auth_value={"token": "secret"}, tags=["Analytics", "ml"])

    updated = service._prepare_gateway_for_read(gateway)
    assert decode_auth(updated.auth_value) == {"token": "secret"}
    assert updated.tags == validate_tags_field(["Analytics", "ml"])


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
