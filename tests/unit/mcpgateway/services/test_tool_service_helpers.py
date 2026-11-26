# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_service_helpers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Helper tests for tool_service schema and response filter utilities.
"""

# Standard
import logging
from types import SimpleNamespace

# Third-Party
import jsonschema
import pytest

# First-Party
from mcpgateway.services import tool_service


def test_validate_with_cached_schema_success_and_error():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    tool_service._validate_with_cached_schema({"a": "ok"}, schema)

    with pytest.raises(jsonschema.exceptions.ValidationError):
        tool_service._validate_with_cached_schema({"a": 1}, schema)


def test_get_validator_fallback_draft4():
    schema = {
        "$schema": "http://json-schema.org/draft-04/schema#",
        "type": "number",
        "minimum": 0,
        "exclusiveMinimum": True,
    }
    schema_json = tool_service._canonicalize_schema(schema)
    validator_cls, parsed = tool_service._get_validator_class_and_check(schema_json)
    assert parsed["type"] == "number"
    assert validator_cls is not None


def test_apply_response_filter_edge_cases():
    """Input that cannot be filtered raises, never comes back as plain output."""
    assert tool_service.apply_response_filter({"a": 1}, "") == {"a": 1}
    with pytest.raises(tool_service.ResponseFilterError, match="Invalid JSON string provided."):
        tool_service.apply_response_filter("not json", "response.a")
    with pytest.raises(tool_service.ResponseFilterError, match="Input data must be a JSON string, dictionary, or list."):
        tool_service.apply_response_filter(123, "response.a")


def test_apply_response_filter_rejects_a_filter_that_is_not_cel():
    """A stored jq-era filter is reported at invoke time, not executed."""
    with pytest.raises(tool_service.ResponseFilterError, match="jsonpath filter is not a valid CEL expression"):
        tool_service.apply_response_filter({"a": 1}, "$ENV")


def test_apply_response_filter_does_not_echo_engine_errors(monkeypatch):
    """Filter engine detail goes to the log, never to the caller."""
    # First-Party
    from mcpgateway.utils.cel_runner import CelEvaluationError

    monkeypatch.setattr(tool_service, "evaluate_value", lambda *_args: (_ for _ in ()).throw(CelEvaluationError("secret path /etc/app/x")))
    with pytest.raises(tool_service.ResponseFilterError) as excinfo:
        tool_service.apply_response_filter({"a": 1}, "response.a")
    assert str(excinfo.value) == "Error applying jsonpath filter"
    assert excinfo.value.detail == "secret path /etc/app/x"
    assert excinfo.value.warning is False


def test_apply_response_filter_reports_timeout_distinctly(monkeypatch):
    """A timed-out filter is distinguishable from a malformed one, and is only a warning."""
    # First-Party
    from mcpgateway.utils.cel_runner import CelTimeout

    monkeypatch.setattr(tool_service, "evaluate_value", lambda *_args: (_ for _ in ()).throw(CelTimeout("too slow")))
    with pytest.raises(tool_service.ResponseFilterError, match="jsonpath filter exceeded the execution time limit") as excinfo:
        tool_service.apply_response_filter({"a": 1}, "response.a")
    assert excinfo.value.warning is True


def test_apply_response_filter_reports_busy_distinctly_from_timeout(monkeypatch):
    """A full pool with no free worker is distinguishable from a genuine timeout."""
    # First-Party
    from mcpgateway.utils.cel_runner import CelBusy

    monkeypatch.setattr(tool_service, "evaluate_value", lambda *_args: (_ for _ in ()).throw(CelBusy("no free worker")))
    with pytest.raises(tool_service.ResponseFilterError, match="jsonpath filter sandbox is busy, try again") as excinfo:
        tool_service.apply_response_filter({"a": 1}, "response.a")
    assert excinfo.value.warning is True


def test_filter_error_content_logs_the_tool_and_sanitizes_the_detail(caplog):
    """The log line names the tool, keeps engine detail out of the response, and strips newlines."""
    # First-Party
    from mcpgateway.common.models import TextContent

    exc = tool_service.ResponseFilterError("Error applying jsonpath filter", detail="line one\nline two")
    with caplog.at_level(logging.ERROR, logger="mcpgateway.services.tool_service"):
        content = tool_service._filter_error_content(exc, "my\ntool")
    assert content == [TextContent(type="text", text="Error applying jsonpath filter")]
    assert "my tool" in caplog.text and "line one line two" in caplog.text
    assert "\n" not in caplog.records[-1].getMessage()
    assert caplog.records[-1].levelno == logging.ERROR


def test_filter_error_content_logs_transient_failures_as_warnings(caplog):
    """A timeout or busy sandbox is a warning, not an error."""
    exc = tool_service.ResponseFilterError("jsonpath filter sandbox is busy, try again", warning=True)
    with caplog.at_level(logging.WARNING, logger="mcpgateway.services.tool_service"):
        tool_service._filter_error_content(exc, "t")
    assert caplog.records[-1].levelno == logging.WARNING


def test_as_content_blocks_keeps_a_block_list_as_blocks():
    """A filter that selected whole content blocks delivers them as blocks."""
    # First-Party
    from mcpgateway.common.models import ImageContent, TextContent

    blocks = [{"type": "text", "text": "a"}, {"type": "image", "data": "x", "mimeType": "image/png"}]
    assert tool_service._as_content_blocks(blocks) == [TextContent(type="text", text="a"), ImageContent(type="image", data="x", mime_type="image/png")]


@pytest.mark.parametrize(
    "value",
    [
        [{"type": "text"}],
        [{"type": "foo"}],
        [{"type": 5}],
        [{"type": "text", "text": "a"}, 1],
    ],
)
def test_as_content_blocks_wraps_a_malformed_block_list_as_text(value):
    """A list that only looks like content blocks becomes one text block instead of a validation crash."""
    # First-Party
    from mcpgateway.common.models import TextContent

    # Third-Party
    import orjson

    assert tool_service._as_content_blocks(value) == [TextContent(type="text", text=orjson.dumps(value).decode())]


@pytest.mark.parametrize("value,expected", [("a", '"a"'), (1, "1"), ({"a": 1}, '{"a":1}'), (["a", "b"], '["a","b"]'), ([], "[]"), (None, "null"), ([{"a": 1}], '[{"a":1}]')])
def test_as_content_blocks_wraps_anything_else_as_text(value, expected):
    """A value picked out of a block becomes one text block carrying its JSON."""
    # First-Party
    from mcpgateway.common.models import TextContent

    assert tool_service._as_content_blocks(value) == [TextContent(type="text", text=expected)]


def test_response_status_content_keeps_a_safe_challenge():
    """An upstream 401 keeps its status and a printable WWW-Authenticate value."""
    response = SimpleNamespace(status_code=401, headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="expired"'})

    assert tool_service._response_status_content(response) == {
        "status_code": 401,
        "www_authenticate": 'Bearer error="invalid_token", error_description="expired"',
    }


def test_response_status_content_drops_unsafe_challenges():
    """Control characters, over-long values, and non-strings are not stored."""
    injected = SimpleNamespace(status_code=401, headers={"www-authenticate": "Bearer\r\nX-Injected: yes"})
    too_long = SimpleNamespace(status_code=403, headers={"www-authenticate": "Bearer " + ("a" * 600)})
    missing = SimpleNamespace(status_code=500, headers={})

    assert tool_service._response_status_content(injected) == {"status_code": 401}
    assert tool_service._response_status_content(too_long) == {"status_code": 403}
    assert tool_service._response_status_content(missing) == {"status_code": 500}
    assert tool_service._response_status_content(SimpleNamespace(status_code=True, headers={})) is None


def test_http_error_structured_content_reads_httpx_and_httpx2():
    """Both HTTP client libraries expose the upstream status to the tool result."""
    # Third-Party
    import httpx
    import httpx2

    def status_error(module, status_code):
        request = module.Request("POST", "https://upstream.example/mcp")
        response = module.Response(status_code, headers={"www-authenticate": 'Bearer error="invalid_token"'}, request=request)
        return module.HTTPStatusError("unauthorized", request=request, response=response)

    for module in (httpx, httpx2):
        content = tool_service._http_error_structured_content(status_error(module, 401))
        assert content["status_code"] == 401
        assert content["www_authenticate"] == 'Bearer error="invalid_token"'

    assert tool_service._http_error_structured_content(RuntimeError("no status")) is None


def test_tool_invocation_error_keeps_only_auth_statuses():
    """Only upstream 401 and 403 stay on the invocation error."""
    denied = tool_service.ToolInvocationError("denied", upstream_status_code=403, upstream_www_authenticate='Bearer error="insufficient_scope"')
    other = tool_service.ToolInvocationError("missing", upstream_status_code=404, upstream_www_authenticate="Bearer")

    assert denied.upstream_status_code == 403
    assert denied.upstream_www_authenticate == 'Bearer error="insufficient_scope"'
    assert other.upstream_status_code is None
    assert other.upstream_www_authenticate is None
