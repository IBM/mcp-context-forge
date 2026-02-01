# -*- coding: utf-8 -*-
"""Schema auth validation tests to improve coverage."""

# Third-Party
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.schemas import A2AAgentCreate, A2AAgentUpdate, GatewayCreate, GatewayUpdate
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
