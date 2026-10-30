# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_rest_url_template_encoding.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests that REST tool URL template values are percent-encoded before substitution in
``ToolService.invoke_tool``.

DNS and the HTTP client are mocked and the real
``SecurityValidator.validate_url_for_connection_pinning`` runs. Each value must stay one
path segment or one query value, and values that could change the path are rejected before
any outbound request.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, quote, urlparse

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.schemas import ToolCreate
from mcpgateway.services.tool_service import _validate_tool_input_arguments, ToolInvocationError, ToolService

# Reuse the REST-path fixtures and DB mock helper of the main tool service tests.
from tests.unit.mcpgateway.services.test_tool_service import (  # noqa: F401  pylint: disable=unused-import
    mock_fresh_db_session,
    mock_gateway,
    mock_global_config_obj,
    mock_logging_services,
    mock_tool,
    reset_tool_lookup_cache,
    setup_db_execute_mock,
)

TEMPLATE = "https://api.example.com/v1/users/{id}/public"
FAKE_AUTH = {"Authorization": "Bearer FAKE-BACKEND-TOKEN"}  # pragma: allowlist secret
PAYLOADS = ["42", "../../admin/keys", "42#", "42?role=admin", "../../admin/keys#"]
ATTACKS = PAYLOADS[1:]
PERMISSIVE_SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}
STRICT_SCHEMA = {"type": "object", "properties": {"id": {"type": "string", "pattern": "^[0-9]+$"}}, "required": ["id"]}


@pytest.fixture
def test_db():
    """Mocked DB session."""
    return Mock()


@pytest.fixture
def service(monkeypatch):
    """ToolService with the real URL validator; only DNS is faked (to a public IP)."""
    monkeypatch.setattr("mcpgateway.services.tool_service.settings.ssrf_protection_enabled", True)
    monkeypatch.setattr("mcpgateway.common.validators.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    svc = ToolService()
    svc._http_client = AsyncMock()
    svc.get_plugin_manager = AsyncMock()
    return svc


@pytest.fixture
def pinned():
    """Patch the pinned REST client builder; yield the builder mock and the client it returns."""
    response = AsyncMock()
    response.raise_for_status = Mock()
    response.status_code = 200
    response.json = Mock(return_value={"ok": True})
    client = SimpleNamespace(request=AsyncMock(return_value=response), get=AsyncMock(return_value=response), aclose=AsyncMock())
    with (
        patch("mcpgateway.services.tool_service.metrics_buffer", Mock(record_tool_metric=Mock())),
        patch("mcpgateway.services.tool_service.decode_auth", return_value=dict(FAKE_AUTH)),
        patch("mcpgateway.services.tool_service._build_pinned_rest_http_client", return_value=client) as builder,
    ):
        yield SimpleNamespace(builder=builder, client=client)


def assert_no_outbound_call(pinned):
    """Assert that no pinned client was built and no request was sent."""
    pinned.builder.assert_not_called()
    pinned.client.get.assert_not_called()
    pinned.client.request.assert_not_called()


@pytest.fixture
def invoke(service, mock_tool, test_db, mock_global_config_obj, pinned):  # noqa: F811
    """Return a coroutine function that invokes a REST tool through the real ``invoke_tool`` path."""

    async def _invoke(schema, value, *, method="GET", headers=None, template=TEMPLATE, param="id", query_mapping=None):
        """Invoke a REST tool and return (url handed to client, params, headers, wire URL)."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = method
        mock_tool.url = template
        mock_tool.headers = headers or {"Content-Type": "application/json"}
        mock_tool.jsonpath_filter = ""
        mock_tool.input_schema = schema
        mock_tool.auth_type = "bearer"
        mock_tool.auth_value = "opaque-encrypted-blob"
        mock_tool.query_mapping = query_mapping
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        await service.invoke_tool(test_db, "test_tool", {param: value}, request_headers=None)

        if method == "GET":
            call = pinned.client.get.call_args
            url, params = call.args[0], call.kwargs.get("params")
        else:
            call = pinned.client.request.call_args
            url, params = call.args[1], call.kwargs.get("params")
        wire = httpx.Request(method, url, params=params).url  # what httpx puts on the wire
        return url, params, call.kwargs["headers"], wire

    return _invoke


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["42", "42#", "42?role=admin"])
async def test_permissive_schema_template_value_is_encoded(invoke, pinned, value):
    """The value stays one encoded path segment between /v1/users/ and /public."""
    url, params, headers, wire = await invoke(PERMISSIVE_SCHEMA, value)

    path = wire.raw_path.decode().split("?")[0]
    assert path.startswith("/v1/users/") and path.endswith("/public"), f"path escaped template: {path}"
    assert path.count("/") == 4, f"value added path segments: {path}"
    assert wire.query == b"", f"injected query: {wire.query!r}"
    assert not params, f"injected params: {params}"
    assert quote(value, safe="") in url, f"value not percent-encoded in {url}"
    assert headers["Authorization"] == FAKE_AUTH["Authorization"]


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [".", "..", "../../admin/keys", "../../admin/keys#", "a/./b", "..\\x"])
async def test_dot_segment_value_is_rejected(invoke, pinned, value):
    """A value with a dot segment is rejected before any outbound request."""
    with pytest.raises(ToolInvocationError, match="must not contain dot segments"):
        await invoke(PERMISSIVE_SCHEMA, value)
    assert_no_outbound_call(pinned)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["42%2F43", "%41", "..%2Fx"])
async def test_percent_encoded_value_is_rejected(invoke, pinned, value):
    """A value that already holds a percent-encoded sequence is rejected before any outbound request."""
    with pytest.raises(ToolInvocationError, match="must not contain percent-encoded sequences"):
        await invoke(PERMISSIVE_SCHEMA, value)
    assert_no_outbound_call(pinned)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["42#", "42?role=admin"])
async def test_post_json_template_value_is_encoded(invoke, pinned, value):
    """A JSON POST keeps the encoded value inside one path segment."""
    _, _, _, wire = await invoke(PERMISSIVE_SCHEMA, value, method="POST")
    assert wire.raw_path.decode() == f"/v1/users/{quote(value, safe='')}/public"


@pytest.mark.asyncio
async def test_form_post_query_placeholder_stays_one_param(invoke, pinned):
    """A form POST re-parses the query string; an encoded value stays one parameter."""
    _, params, _, _ = await invoke(
        {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
        "a&role=admin",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        template="https://api.example.com/s?q={q}",
        param="q",
    )
    assert params == {"q": "a&role=admin"}


@pytest.mark.asyncio
async def test_get_query_placeholder_with_query_mapping_stays_one_param(invoke, pinned):
    """A GET query placeholder with query_mapping keeps an encoded value as one parameter."""
    _, params, _, _ = await invoke(
        {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
        "a&role=admin",
        template="https://api.example.com/s?q={q}",
        param="q",
        query_mapping={"other": "other"},
    )
    assert params == {"q": "a&role=admin"}
    assert "role" not in params


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ATTACKS)
async def test_strict_pattern_schema_blocks_payload(invoke, pinned, value):
    """A tool with pattern ^[0-9]+$ rejects the payload before any outbound request."""
    with pytest.raises(ToolInvocationError, match="Invalid arguments"):
        await invoke(STRICT_SCHEMA, value)
    assert_no_outbound_call(pinned)


@pytest.mark.asyncio
async def test_strict_pattern_schema_allows_numeric_id(invoke, pinned):
    """Control: the strict schema still accepts a numeric id."""
    _, _, _, wire = await invoke(STRICT_SCHEMA, "42")
    assert wire.raw_path.decode() == "/v1/users/42/public"


@pytest.mark.parametrize("value", PAYLOADS)
def test_default_and_plain_string_schemas_accept_payloads(value):
    """Default REST schema (no input_schema given) and a plain string property both accept every payload."""
    tool = ToolCreate(name="rest-no-schema", integration_type="REST", request_type="GET", url=TEMPLATE)
    assert _validate_tool_input_arguments({"id": value}, tool.input_schema) is None
    assert _validate_tool_input_arguments({"id": value}, PERMISSIVE_SCHEMA) is None


@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        ("folder/file.txt", "folder%2Ffile.txt"),
        ("50%", "50%25"),
        (42, "42"),
        ("é", "%C3%A9"),
    ],
)
def test_substitute_url_template_encodes_value(value, encoded):
    """Each value is percent-encoded and popped from the payload."""
    from mcpgateway.services.tool_service import _substitute_url_template

    payload = {"id": value, "keep": 1}
    assert _substitute_url_template(TEMPLATE, payload) == f"https://api.example.com/v1/users/{encoded}/public"
    assert payload == {"keep": 1}


def test_substitute_url_template_repeated_placeholder():
    """A placeholder used twice is replaced in both positions."""
    from mcpgateway.services.tool_service import _substitute_url_template

    assert _substitute_url_template("https://h/{id}/x/{id}", {"id": "7"}) == "https://h/7/x/7"


def test_substitute_url_template_query_value_stays_one_param():
    """A query value with reserved characters stays one query parameter."""
    from mcpgateway.services.tool_service import _substitute_url_template

    url = _substitute_url_template("https://api.example.com/s?q={q}&v=2", {"q": "a b&role=admin"})
    assert parse_qs(urlparse(url).query) == {"q": ["a b&role=admin"], "v": ["2"]}


def test_substitute_url_template_missing_param_message_unchanged():
    """A missing parameter keeps the original error text."""
    from mcpgateway.services.tool_service import _substitute_url_template

    with pytest.raises(ToolInvocationError, match=r"Required URL parameter 'id' not found in arguments"):
        _substitute_url_template(TEMPLATE, {})
