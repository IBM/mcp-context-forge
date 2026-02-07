# -*- coding: utf-8 -*-
"""Schema auth validation tests to improve coverage."""

# Third-Party
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.schemas import A2AAgentCreate, A2AAgentUpdate, AdminCreateUserRequest, EmailRegistrationRequest, GatewayCreate, GatewayUpdate, PublicRegistrationRequest
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
# PublicRegistrationRequest Schema Tests
# =========================================================================


def test_public_registration_request_valid():
    """Test PublicRegistrationRequest with valid data."""
    request = PublicRegistrationRequest(
        email="test@example.com",
        password="SecurePass123!",
        full_name="Test User",
    )
    assert request.email == "test@example.com"
    assert request.password == "SecurePass123!"
    assert request.full_name == "Test User"


def test_public_registration_request_password_required():
    """Test PublicRegistrationRequest requires password (not optional)."""
    with pytest.raises(ValueError):
        PublicRegistrationRequest(
            email="test@example.com",
            full_name="Test User",
        )


def test_public_registration_request_password_too_short():
    """Test PublicRegistrationRequest rejects short password."""
    with pytest.raises(ValueError, match="at least 8 characters"):
        PublicRegistrationRequest(
            email="test@example.com",
            password="Short1!",
            full_name="Test User",
        )


def test_public_registration_request_invalid_email():
    """Test PublicRegistrationRequest rejects invalid email."""
    with pytest.raises(ValueError):
        PublicRegistrationRequest(
            email="not-an-email",
            password="SecurePass123!",
            full_name="Test User",
        )


def test_public_registration_request_rejects_admin_fields():
    """Test PublicRegistrationRequest rejects is_admin/is_active/password_change_required (extra=forbid)."""
    with pytest.raises(ValueError):
        PublicRegistrationRequest(
            email="test@example.com",
            password="SecurePass123!",
            full_name="Test User",
            is_admin=True,
        )
    with pytest.raises(ValueError):
        PublicRegistrationRequest(
            email="test@example.com",
            password="SecurePass123!",
            full_name="Test User",
            is_active=False,
        )
    with pytest.raises(ValueError):
        PublicRegistrationRequest(
            email="test@example.com",
            password="SecurePass123!",
            full_name="Test User",
            password_change_required=True,
        )


# =========================================================================
# AdminCreateUserRequest Schema Tests
# =========================================================================


def test_admin_create_user_request_valid():
    """Test AdminCreateUserRequest with password provided."""
    request = AdminCreateUserRequest(
        email="test@example.com",
        password="SecurePass123!",
        full_name="Test User",
    )
    assert request.email == "test@example.com"
    assert request.password == "SecurePass123!"
    assert request.full_name == "Test User"
    assert request.is_admin is False
    assert request.is_active is True
    assert request.password_change_required is False


def test_admin_create_user_request_password_required():
    """Test AdminCreateUserRequest requires password (not optional)."""
    with pytest.raises(ValueError):
        AdminCreateUserRequest(
            email="test@example.com",
            full_name="Test User",
        )


def test_admin_create_user_request_with_all_fields():
    """Test AdminCreateUserRequest with all fields set."""
    request = AdminCreateUserRequest(
        email="complete@example.com",
        password="CompletePass123!",
        full_name="Complete User",
        is_admin=True,
        is_active=False,
        password_change_required=True,
    )
    assert request.email == "complete@example.com"
    assert request.password == "CompletePass123!"
    assert request.full_name == "Complete User"
    assert request.is_admin is True
    assert request.is_active is False
    assert request.password_change_required is True


def test_admin_create_user_request_password_too_short():
    """Test AdminCreateUserRequest rejects short password."""
    with pytest.raises(ValueError, match="at least 8 characters"):
        AdminCreateUserRequest(
            email="test@example.com",
            password="Short1!",
            full_name="Test User",
        )


def test_admin_create_user_request_invalid_email():
    """Test AdminCreateUserRequest rejects invalid email."""
    with pytest.raises(ValueError):
        AdminCreateUserRequest(
            email="not-an-email",
            password="SecurePass123!",
            full_name="Test User",
        )


def test_admin_create_user_request_with_is_active_false():
    """Test AdminCreateUserRequest with is_active=False."""
    request = AdminCreateUserRequest(
        email="inactive@example.com",
        password="SecurePass123!",
        full_name="Inactive User",
        is_active=False,
    )
    assert request.is_active is False


def test_admin_create_user_request_with_pcr_true():
    """Test AdminCreateUserRequest with password_change_required=True."""
    request = AdminCreateUserRequest(
        email="pwchange@example.com",
        password="TempPass123!",
        full_name="PCR User",
        password_change_required=True,
    )
    assert request.password_change_required is True


def test_email_registration_request_deprecated_alias():
    """Test EmailRegistrationRequest is a deprecated alias for AdminCreateUserRequest."""
    assert EmailRegistrationRequest is AdminCreateUserRequest
