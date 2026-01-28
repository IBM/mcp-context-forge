"""GatewayService helper tests."""

# Third-Party
import pytest

# First-Party
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayNameConflictError, GatewayService, OAuthToolValidationError


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
    service = GatewayService()
    headers = service._get_auth_headers()
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"].startswith("Basic ")
    assert "X-API-Key" in headers


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
