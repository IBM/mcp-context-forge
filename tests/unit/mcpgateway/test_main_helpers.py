# -*- coding: utf-8 -*-
"""Unit tests for mcpgateway.main helper functions."""

# Standard
import asyncio
from types import SimpleNamespace

# Third-Party
from fastapi import HTTPException, Request
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway import main


def _make_request_with_body(body: bytes) -> Request:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {"type": "http", "method": "POST", "path": "/", "headers": []}
    return Request(scope, receive)


def _make_request_with_scope(*, scheme: str = "http", host: str = "example.com", port: int = 80, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    scope = {
        "type": "http",
        "scheme": scheme,
        "server": (host, port),
        "path": "/",
        "headers": headers or [],
    }
    return Request(scope)


def test_get_user_email_variants():
    assert main.get_user_email({"email": "alice@example.com"}) == "alice@example.com"
    assert main.get_user_email({"sub": "bob@example.com"}) == "bob@example.com"
    assert main.get_user_email({"email": "alice@example.com", "sub": "bob@example.com"}) == "alice@example.com"
    assert main.get_user_email({}) == "unknown"
    assert main.get_user_email("charlie@example.com") == "charlie@example.com"
    assert main.get_user_email("") == "unknown"
    assert main.get_user_email(None) == "unknown"
    assert main.get_user_email(True) == "True"
    assert main.get_user_email(False) == "unknown"


def test_normalize_token_teams():
    assert main._normalize_token_teams(None) == []
    assert main._normalize_token_teams([]) == []
    assert main._normalize_token_teams(["t1", "t2"]) == ["t1", "t2"]
    assert main._normalize_token_teams([{"id": "t1", "name": "Team1"}]) == ["t1"]
    assert main._normalize_token_teams([{"id": "t1"}, "t2", {"name": "no_id"}]) == ["t1", "t2"]


def test_get_token_teams_from_request():
    # Teams with mixed formats (string and dict) → normalized to string IDs
    req = SimpleNamespace(state=SimpleNamespace(_jwt_verified_payload=("token", {"teams": ["t1", {"id": "t2"}]})))
    assert main._get_token_teams_from_request(req) == ["t1", "t2"]

    # Empty teams → public-only
    req.state._jwt_verified_payload = ("token", {"teams": []})
    assert main._get_token_teams_from_request(req) == []

    # SECURITY: Null teams + non-admin → public-only (secure default)
    req.state._jwt_verified_payload = ("token", {"teams": None})
    assert main._get_token_teams_from_request(req) == []

    # SECURITY: Null teams + admin → admin bypass (None)
    req.state._jwt_verified_payload = ("token", {"teams": None, "is_admin": True})
    assert main._get_token_teams_from_request(req) is None

    # SECURITY: Missing teams key → public-only (secure default)
    req.state._jwt_verified_payload = ("token", {"sub": "user@example.com"})
    assert main._get_token_teams_from_request(req) == []

    # SECURITY: No JWT → public-only (secure default)
    req.state._jwt_verified_payload = None
    assert main._get_token_teams_from_request(req) == []


def test_get_rpc_filter_context_admin_scoping():
    req = SimpleNamespace(state=SimpleNamespace(_jwt_verified_payload=("token", {"teams": [], "is_admin": True})))
    user = {"email": "user@example.com", "is_admin": True}
    email, teams, is_admin = main._get_rpc_filter_context(req, user)
    assert email == "user@example.com"
    assert teams == []
    assert is_admin is False

    req.state._jwt_verified_payload = ("token", {"teams": ["t1"], "user": {"is_admin": True}})
    email, teams, is_admin = main._get_rpc_filter_context(req, SimpleNamespace(email="obj@example.com"))
    assert email == "obj@example.com"
    assert teams == ["t1"]
    assert is_admin is True


def test_jsonpath_modifier_and_transform_mappings():
    data = [{"user": {"name": "Alice", "roles": ["a", "b"]}}, {"user": {"name": "Bob", "roles": ["c"]}}]
    result = main.jsonpath_modifier(data, "$[*].user", {"name": "$.name", "roles": "$.roles[*]"})
    assert result == [{"name": "Alice", "roles": ["a", "b"]}, {"name": "Bob", "roles": "c"}]

    single = main.jsonpath_modifier({"user": {"name": "Solo"}}, "$.user")
    assert single == {"name": "Solo"}


def test_jsonpath_modifier_invalid_expression(monkeypatch):
    def _raise(_expr):  # noqa: ANN001
        raise ValueError("bad jsonpath")

    monkeypatch.setattr(main, "_parse_jsonpath", _raise)
    with pytest.raises(HTTPException, match="Invalid main JSONPath expression"):
        main.jsonpath_modifier({"a": 1}, "$.a")


def test_transform_data_with_mappings_invalid_mapping(monkeypatch):
    def _raise(_expr):  # noqa: ANN001
        raise ValueError("bad mapping")

    monkeypatch.setattr(main, "_parse_jsonpath", _raise)
    with pytest.raises(HTTPException, match="Invalid mapping JSONPath"):
        main.transform_data_with_mappings([{"a": 1}], {"x": "$.a"})


def test_transform_data_with_mappings_execution_error(monkeypatch):
    class _BadExpr:
        def find(self, _item):  # noqa: ANN001
            raise RuntimeError("boom")

    monkeypatch.setattr(main, "_parse_jsonpath", lambda _expr: _BadExpr())
    with pytest.raises(HTTPException, match="Error executing mapping JSONPath"):
        main.transform_data_with_mappings([{"a": 1}], {"x": "$.a"})


@pytest.mark.asyncio
async def test_read_request_json():
    request = _make_request_with_body(b'{"a": 1}')
    payload = await main._read_request_json(request)
    assert payload == {"a": 1}

    with pytest.raises(HTTPException):
        await main._read_request_json(_make_request_with_body(b""))

    with pytest.raises(HTTPException):
        await main._read_request_json(_make_request_with_body(b"{bad json}"))


def test_require_api_key(monkeypatch):
    monkeypatch.setattr(main.settings, "auth_required", True)
    monkeypatch.setattr(main.settings, "basic_auth_user", "admin")
    monkeypatch.setattr(main.settings, "basic_auth_password", SecretStr("secret"))

    main.require_api_key("admin:secret")
    with pytest.raises(HTTPException):
        main.require_api_key("wrong:key")

    monkeypatch.setattr(main.settings, "auth_required", False)
    main.require_api_key("anything")


def test_get_protocol_from_request_and_update_url_protocol():
    req = _make_request_with_scope(headers=[(b"x-forwarded-proto", b"https,http")])
    assert main.get_protocol_from_request(req) == "https"

    req_direct = _make_request_with_scope(scheme="https", headers=[])
    assert main.get_protocol_from_request(req_direct) == "https"

    url = main.update_url_protocol(_make_request_with_scope(scheme="http", host="localhost", port=8000))
    assert url.startswith("http://localhost:8000")
    assert not url.endswith("/")


@pytest.mark.asyncio
async def test_invalidate_resource_cache_clears_entries():
    main.resource_cache.set("/test/resource", {"value": 1})
    assert main.resource_cache.get("/test/resource") is not None

    await main.invalidate_resource_cache("/test/resource")
    assert main.resource_cache.get("/test/resource") is None

    main.resource_cache.set("/resource1", {"value": 1})
    main.resource_cache.set("/resource2", {"value": 2})
    await main.invalidate_resource_cache()
    assert main.resource_cache.get("/resource1") is None
    assert main.resource_cache.get("/resource2") is None


def test_validate_http_headers_valid():
    """Test _validate_http_headers with valid headers."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer token123",
        "X-Custom-Header": "value with spaces",
    }
    result = main._validate_http_headers(headers)
    assert result == headers


def test_validate_http_headers_invalid_name():
    """Test _validate_http_headers rejects invalid header names (line 1435-1436)."""
    # Invalid header name with space
    headers = {"Invalid Name": "value"}
    result = main._validate_http_headers(headers)
    assert result is None

    # Invalid header name with special characters not in RFC 9110 token
    headers = {"Invalid@Header": "value"}
    result = main._validate_http_headers(headers)
    assert result is None

    # Mix of valid and invalid headers
    headers = {
        "Valid-Header": "value1",
        "Invalid Name": "value2",
        "Another-Valid": "value3",
    }
    result = main._validate_http_headers(headers)
    assert result == {"Valid-Header": "value1", "Another-Valid": "value3"}


def test_validate_http_headers_crlf_in_value():
    """Test _validate_http_headers rejects CRLF in header values (line 1439-1440)."""
    # Header value with carriage return
    headers = {"Content-Type": "application/json\rinjection"}
    result = main._validate_http_headers(headers)
    assert result is None

    # Header value with newline
    headers = {"Authorization": "Bearer token\ninjection"}
    result = main._validate_http_headers(headers)
    assert result is None

    # Header value with both CRLF
    headers = {"X-Custom": "value\r\ninjection"}
    result = main._validate_http_headers(headers)
    assert result is None

    # Mix of valid and invalid headers
    headers = {
        "Valid-Header": "clean value",
        "Invalid-Header": "value\r\ninjection",
        "Another-Valid": "another clean value",
    }
    result = main._validate_http_headers(headers)
    assert result == {"Valid-Header": "clean value", "Another-Valid": "another clean value"}


def test_validate_http_headers_ctl_characters():
    """Test _validate_http_headers rejects CTL characters in values (line 1447-1448, 1450)."""
    # Header value with null byte (0x00)
    headers = {"Content-Type": "application/json\x00"}
    result = main._validate_http_headers(headers)
    assert result is None

    # Header value with control character (0x01)
    headers = {"Authorization": "Bearer\x01token"}
    result = main._validate_http_headers(headers)
    assert result is None

    # Header value with DEL character (0x7F)
    headers = {"X-Custom": "value\x7f"}
    result = main._validate_http_headers(headers)
    assert result is None

    # Header value with various CTL characters (0x00-0x1F except tab and space)
    for code in range(0, 32):
        if code in (9, 32):  # Skip tab and space (allowed)
            continue
        headers = {"Test-Header": f"value{chr(code)}end"}
        result = main._validate_http_headers(headers)
        assert result is None, f"Should reject CTL character 0x{code:02x}"

    # Header value with tab (0x09) - should be allowed
    headers = {"Content-Type": "application/json\tcharset=utf-8"}
    result = main._validate_http_headers(headers)
    assert result == headers

    # Header value with space (0x20) - should be allowed
    headers = {"Authorization": "Bearer token with spaces"}
    result = main._validate_http_headers(headers)
    assert result == headers

    # Mix of valid and invalid headers
    headers = {
        "Valid-Header": "clean value",
        "Invalid-Header": "value\x01injection",
        "Another-Valid": "another clean value",
    }
    result = main._validate_http_headers(headers)
    assert result == {"Valid-Header": "clean value", "Another-Valid": "another clean value"}


def test_validate_http_headers_empty_dict():
    """Test _validate_http_headers with empty dictionary."""
    result = main._validate_http_headers({})
    assert result is None


def test_validate_http_headers_all_invalid():
    """Test _validate_http_headers when all headers are invalid."""
    headers = {
        "Invalid Name": "value1",
        "Valid-But-Bad-Value": "value\r\ninjection",
        "Another-Invalid": "value\x00",
    }
    result = main._validate_http_headers(headers)
    assert result is None
