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


# ---------------------------------------------------------------------------
# tojson_attr filter tests
# ---------------------------------------------------------------------------
class TestTojsonAttrFilter:
    """Tests for the tojson_attr Jinja2 filter in main.py."""

    def test_returns_plain_str_not_markup(self):
        """tojson_attr must return plain str so autoescape HTML-encodes it."""
        from markupsafe import Markup

        result = main.tojson_attr("hello")
        assert isinstance(result, str)
        assert not isinstance(result, Markup)

    def test_string_produces_json_with_quotes(self):
        """String value produces JSON-encoded output with surrounding quotes."""
        result = main.tojson_attr("hello")
        assert result == '"hello"'

    def test_escapes_angle_brackets(self):
        """< and > are escaped to unicode to prevent HTML injection."""
        result = main.tojson_attr("<script>alert(1)</script>")
        assert "<" not in result
        assert ">" not in result
        assert "\\u003c" in result
        assert "\\u003e" in result

    def test_escapes_ampersand(self):
        """& is escaped to unicode to prevent entity injection."""
        result = main.tojson_attr("a&b")
        assert "&" not in result.replace("\\u0026", "")
        assert "\\u0026" in result

    def test_escapes_single_quote(self):
        """Single quotes are escaped to unicode for safety in HTML contexts."""
        result = main.tojson_attr("it's")
        assert "'" not in result
        assert "\\u0027" in result

    def test_double_quotes_left_for_autoescape(self):
        """Double quotes remain literal so Jinja2 autoescape encodes them to &quot;."""
        result = main.tojson_attr('say "hi"')
        # json.dumps produces: "say \"hi\""  — the backslash-quote is JSON escaping
        assert '\\"' in result

    def test_none_value(self):
        """None produces JSON null."""
        assert main.tojson_attr(None) == "null"

    def test_integer_value(self):
        """Integer passes through as JSON number."""
        assert main.tojson_attr(42) == "42"

    def test_xss_payload_is_neutralized(self):
        """A realistic XSS payload is fully escaped."""
        result = main.tojson_attr("'); alert(document.cookie);//")
        assert "\\u0027" in result  # single quote escaped
        assert "alert" in result  # content preserved but escaped
        assert result.startswith('"') and result.endswith('"')  # valid JSON string
