# -*- coding: utf-8 -*-
"""Schema auth validation tests to improve coverage."""

# Third-Party
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.schemas import A2AAgentCreate, A2AAgentUpdate, EmailRegistrationRequest, GatewayCreate, GatewayUpdate
from mcpgateway.utils.services_auth import decode_auth


def test_gateway_create_authheaders_multi_duplicate(caplog):
    caplog.set_level("WARNING")
    gateway = GatewayCreate(
        name="gw",
        url="https://example.com",
        auth_type="authheaders",
        auth_headers=[{"key": "X-Token", "value": "a"}, {"key": "X-Token", "value": "b"}],
    )
    decoded = decode_auth(gateway.auth_value)
    assert decoded["X-Token"] == "b"
    assert any("Duplicate header keys detected" in rec.message for rec in caplog.records)


def test_gateway_create_authheaders_invalid_key():
    with pytest.raises(ValueError):
        GatewayCreate(
            name="gw",
            url="https://example.com",
            auth_type="authheaders",
            auth_headers=[{"key": "X:Bad", "value": "v"}],
        )


def test_gateway_create_authheaders_missing_key():
    with pytest.raises(ValueError):
        GatewayCreate(
            name="gw",
            url="https://example.com",
            auth_type="authheaders",
            auth_headers=[{"value": "v"}],
        )


def test_gateway_create_legacy_header():
    gateway = GatewayCreate(
        name="gw",
        url="https://example.com",
        auth_type="authheaders",
        auth_header_key="X-Api-Key",
        auth_header_value="secret",
    )
    decoded = decode_auth(gateway.auth_value)
    assert decoded["X-Api-Key"] == "secret"


def test_gateway_create_query_param_disabled(monkeypatch):
    monkeypatch.setattr(settings, "insecure_allow_queryparam_auth", False)
    with pytest.raises(ValueError):
        GatewayCreate(
            name="gw",
            url="https://example.com",
            auth_type="query_param",
            auth_query_param_key="api_key",
            auth_query_param_value=SecretStr("secret"),
        )


def test_gateway_create_query_param_host_not_allowed(monkeypatch):
    monkeypatch.setattr(settings, "insecure_allow_queryparam_auth", True)
    monkeypatch.setattr(settings, "insecure_queryparam_auth_allowed_hosts", ["allowed.com"])
    with pytest.raises(ValueError):
        GatewayCreate(
            name="gw",
            url="https://bad.com/path",
            auth_type="query_param",
            auth_query_param_key="api_key",
            auth_query_param_value=SecretStr("secret"),
        )


def test_gateway_create_query_param_valid(monkeypatch):
    monkeypatch.setattr(settings, "insecure_allow_queryparam_auth", True)
    monkeypatch.setattr(settings, "insecure_queryparam_auth_allowed_hosts", [])
    gateway = GatewayCreate(
        name="gw",
        url="https://good.com/path",
        auth_type="query_param",
        auth_query_param_key="api_key",
        auth_query_param_value=SecretStr("secret"),
    )
    assert gateway.auth_query_param_key == "api_key"


def test_gateway_update_query_param_missing_value():
    with pytest.raises(ValueError):
        GatewayUpdate(auth_type="query_param", auth_query_param_key="api_key")


def test_a2a_agent_create_auth_basic():
    agent = A2AAgentCreate(
        name="agent",
        endpoint_url="https://example.com",
        auth_type="basic",
        auth_username="user",
        auth_password="pass",
    )
    decoded = decode_auth(agent.auth_value)
    assert decoded["Authorization"].startswith("Basic ")


def test_a2a_agent_create_bearer_missing_token():
    with pytest.raises(ValueError):
        A2AAgentCreate(
            name="agent",
            endpoint_url="https://example.com",
            auth_type="bearer",
        )


def test_a2a_agent_create_authheaders_invalid_key():
    with pytest.raises(ValueError):
        A2AAgentCreate(
            name="agent",
            endpoint_url="https://example.com",
            auth_type="authheaders",
            auth_headers=[{"key": "Bad:Key", "value": "v"}],
        )


def test_a2a_agent_create_query_param_disabled(monkeypatch):
    monkeypatch.setattr(settings, "insecure_allow_queryparam_auth", False)
    with pytest.raises(ValueError):
        A2AAgentCreate(
            name="agent",
            endpoint_url="https://example.com",
            auth_type="query_param",
            auth_query_param_key="api_key",
            auth_query_param_value=SecretStr("secret"),
        )


def test_a2a_agent_create_query_param_host_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "insecure_allow_queryparam_auth", True)
    monkeypatch.setattr(settings, "insecure_queryparam_auth_allowed_hosts", ["allowed.com"])
    with pytest.raises(ValueError):
        A2AAgentCreate(
            name="agent",
            endpoint_url="https://bad.com",
            auth_type="query_param",
            auth_query_param_key="api_key",
            auth_query_param_value=SecretStr("secret"),
        )


def test_a2a_agent_update_query_param_missing_value():
    with pytest.raises(ValueError):
        A2AAgentUpdate(auth_type="query_param", auth_query_param_key="api_key")


# =========================================================================
# EmailRegistrationRequest Schema Tests
# =========================================================================


def test_email_registration_request_with_password():
    """Test EmailRegistrationRequest with password provided."""
    request = EmailRegistrationRequest(
        email="test@example.com",
        password="SecurePass123!",
        full_name="Test User"
    )
    assert request.email == "test@example.com"
    assert request.password == "SecurePass123!"
    assert request.full_name == "Test User"
    assert request.is_admin is False  # Default
    assert request.is_active is True  # Default
    assert request.password_change_required is False  # Default


def test_email_registration_request_without_password():
    """Test EmailRegistrationRequest without password (for updates)."""
    request = EmailRegistrationRequest(
        email="test@example.com",
        full_name="Test User"
    )
    assert request.email == "test@example.com"
    assert request.password is None
    assert request.full_name == "Test User"


def test_email_registration_request_with_is_active_true():
    """Test EmailRegistrationRequest with is_active=True."""
    request = EmailRegistrationRequest(
        email="active@example.com",
        password="SecurePass123!",
        full_name="Active User",
        is_active=True
    )
    assert request.is_active is True


def test_email_registration_request_with_is_active_false():
    """Test EmailRegistrationRequest with is_active=False."""
    request = EmailRegistrationRequest(
        email="inactive@example.com",
        password="SecurePass123!",
        full_name="Inactive User",
        is_active=False
    )
    assert request.is_active is False


def test_email_registration_request_with_password_change_required_true():
    """Test EmailRegistrationRequest with password_change_required=True."""
    request = EmailRegistrationRequest(
        email="pwchange@example.com",
        password="TempPass123!",
        full_name="Password Change User",
        password_change_required=True
    )
    assert request.password_change_required is True


def test_email_registration_request_with_password_change_required_false():
    """Test EmailRegistrationRequest with password_change_required=False."""
    request = EmailRegistrationRequest(
        email="nopwchange@example.com",
        password="SecurePass123!",
        full_name="No Password Change User",
        password_change_required=False
    )
    assert request.password_change_required is False


def test_email_registration_request_with_all_fields():
    """Test EmailRegistrationRequest with all fields set."""
    request = EmailRegistrationRequest(
        email="complete@example.com",
        password="CompletePass123!",
        full_name="Complete User",
        is_admin=True,
        is_active=False,
        password_change_required=True
    )
    assert request.email == "complete@example.com"
    assert request.password == "CompletePass123!"
    assert request.full_name == "Complete User"
    assert request.is_admin is True
    assert request.is_active is False
    assert request.password_change_required is True


def test_email_registration_request_password_too_short():
    """Test EmailRegistrationRequest with password shorter than 8 characters."""
    with pytest.raises(ValueError, match="at least 8 characters"):
        EmailRegistrationRequest(
            email="test@example.com",
            password="Short1!",  # Only 7 characters
            full_name="Test User"
        )


def test_email_registration_request_invalid_email():
    """Test EmailRegistrationRequest with invalid email format."""
    with pytest.raises(ValueError):
        EmailRegistrationRequest(
            email="not-an-email",
            password="SecurePass123!",
            full_name="Test User"
        )


def test_email_registration_request_partial_update_scenario():
    """Test EmailRegistrationRequest for partial update (no password, only other fields)."""
    request = EmailRegistrationRequest(
        email="update@example.com",
        full_name="Updated Name",
        is_admin=True
    )
    assert request.email == "update@example.com"
    assert request.password is None
    assert request.full_name == "Updated Name"
    assert request.is_admin is True
    assert request.is_active is True  # Default preserved
    assert request.password_change_required is False  # Default preserved
