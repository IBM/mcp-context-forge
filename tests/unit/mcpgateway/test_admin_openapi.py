# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_openapi.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the generate_schemas_from_openapi admin endpoint.

These tests verify the endpoint's own logic: input validation, URL parsing,
and exception-to-HTTP-status mapping.  The underlying service layer
(fetch_and_extract_schemas) is mocked — its logic is tested separately in
test_openapi_service.py.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import Request
import httpx
import orjson
import pytest

# First-Party
from mcpgateway.admin import generate_schemas_from_openapi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_request(body) -> MagicMock:
    """Return a mock FastAPI Request compatible with ``_read_request_json``."""
    raw = orjson.dumps(body) if isinstance(body, dict) else body
    req = MagicMock(spec=Request)
    req.body = AsyncMock(return_value=raw)
    # _read_request_json falls back to request.json() for empty bodies
    req.json = AsyncMock(return_value=body if isinstance(body, dict) else {})
    return req


_USER = {"email": "test@example.com"}


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestGenerateSchemasFromOpenAPI:
    """Tests for generate_schemas_from_openapi endpoint."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Successful schema generation returns 200 with both schemas."""
        input_schema = {"type": "object", "properties": {"x": {"type": "number"}}}
        output_schema = {"type": "object", "properties": {"result": {"type": "number"}}}

        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.return_value = (input_schema, output_schema, "http://example.com/openapi.json")

            response = await generate_schemas_from_openapi(
                request=_mock_request({"url": "http://example.com/calculate", "request_type": "POST"}),
                _user=_USER,
            )

        assert response.status_code == 200
        content = orjson.loads(response.body)
        assert content["success"] is True
        assert content["input_schema"] == input_schema
        assert content["output_schema"] == output_schema
        assert content["spec_url"] == "http://example.com/openapi.json"

    @pytest.mark.asyncio
    async def test_with_openapi_url(self):
        """Custom openapi_url is forwarded to the service."""
        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.return_value = (None, {"type": "object"}, "http://example.com/custom-spec.json")

            response = await generate_schemas_from_openapi(
                request=_mock_request({"url": "http://example.com/api", "openapi_url": "http://example.com/custom-spec.json", "request_type": "GET"}),
                _user=_USER,
            )

        assert response.status_code == 200
        assert mock_fetch.call_args[1]["openapi_url"] == "http://example.com/custom-spec.json"

    @pytest.mark.asyncio
    async def test_default_request_type_is_get(self):
        """request_type defaults to GET when omitted."""
        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.return_value = (None, {"type": "object"}, "http://example.com/openapi.json")

            response = await generate_schemas_from_openapi(
                request=_mock_request({"url": "http://example.com/status"}),
                _user=_USER,
            )

        assert response.status_code == 200
        assert mock_fetch.call_args[1]["method"] == "GET"

    @pytest.mark.asyncio
    async def test_url_parsing(self):
        """URL is correctly split into base_url and path for the service call."""
        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.return_value = ({"type": "object"}, {"type": "object"}, "https://api.example.com:8443/openapi.json")

            response = await generate_schemas_from_openapi(
                request=_mock_request({"url": "https://api.example.com:8443/v1/calculate", "request_type": "POST"}),
                _user=_USER,
            )

        assert response.status_code == 200
        call_args = mock_fetch.call_args[1]
        assert call_args["base_url"] == "https://api.example.com:8443"
        assert call_args["path"] == "/v1/calculate"
        assert call_args["method"] == "POST"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestGenerateSchemasInputValidation:
    """Tests for request-level validation in the endpoint."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"request_type": "POST"}, id="missing-url"),
            pytest.param({"url": "", "openapi_url": "http://x.com/spec.json", "request_type": "POST"}, id="empty-url"),
            pytest.param({"openapi_url": "http://x.com/spec.json", "request_type": "GET"}, id="openapi-url-without-url"),
        ],
    )
    async def test_missing_or_empty_url_returns_400(self, body):
        """url is required; its absence yields 400."""
        response = await generate_schemas_from_openapi(request=_mock_request(body), _user=_USER)

        assert response.status_code == 400
        content = orjson.loads(response.body)
        assert content["success"] is False
        assert "'url' is required" in content["message"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(b"[1, 2, 3]", id="json-array"),
            pytest.param(b"42", id="json-scalar"),
            pytest.param(b'"hello"', id="json-string"),
        ],
    )
    async def test_non_object_json_returns_400(self, body):
        """JSON body that is not an object yields 400."""
        response = await generate_schemas_from_openapi(request=_mock_request(body), _user=_USER)

        assert response.status_code == 400
        content = orjson.loads(response.body)
        assert content["success"] is False
        assert "JSON object" in content["message"]

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self):
        """Malformed JSON body yields 400."""
        response = await generate_schemas_from_openapi(request=_mock_request(b"invalid json {"), _user=_USER)

        assert response.status_code == 400
        content = orjson.loads(response.body)
        assert "Invalid JSON" in content["message"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"url": 123, "request_type": "POST"}, id="url-is-int"),
            pytest.param({"url": "http://example.com/api", "request_type": ["POST"]}, id="request_type-is-list"),
            pytest.param({"url": "http://example.com/api", "openapi_url": 42}, id="openapi_url-is-int"),
        ],
    )
    async def test_non_string_fields_return_400(self, body):
        """Non-string values for url/request_type/openapi_url yield 400."""
        response = await generate_schemas_from_openapi(request=_mock_request(body), _user=_USER)

        assert response.status_code == 400
        content = orjson.loads(response.body)
        assert content["success"] is False
        assert "must be strings" in content["message"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            pytest.param("just-a-path", id="no-scheme-no-host"),
            pytest.param("/calculate", id="path-only"),
            pytest.param("ftp://example.com/api", id="unsupported-scheme"),
        ],
    )
    async def test_invalid_url_returns_400(self, url):
        """URLs that fail SecurityValidator.validate_url yield 400."""
        response = await generate_schemas_from_openapi(request=_mock_request({"url": url, "request_type": "GET"}), _user=_USER)

        assert response.status_code == 400
        content = orjson.loads(response.body)
        assert content["success"] is False


# ---------------------------------------------------------------------------
# Exception → HTTP status mapping
# ---------------------------------------------------------------------------


class TestGenerateSchemasErrorMapping:
    """Each service-layer exception type maps to the correct HTTP status."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exception,expected_status,expected_fragment",
        [
            pytest.param(ValueError("SSRF blocked"), 400, "Security validation failed", id="ValueError-400"),
            pytest.param(KeyError("Path '/x' not found"), 404, "Path '/x' not found", id="KeyError-404"),
            pytest.param(
                httpx.HTTPStatusError("error", request=MagicMock(), response=MagicMock(status_code=403)),
                502,
                "OpenAPI spec server returned HTTP 403",
                id="HTTPStatusError-502",
            ),
            pytest.param(httpx.ConnectError("refused"), 502, "Failed to fetch OpenAPI spec from the provided URL", id="ConnectError-502"),
            pytest.param(httpx.TimeoutException("timeout"), 502, "Failed to fetch OpenAPI spec from the provided URL", id="Timeout-502"),
            pytest.param(Exception("unexpected"), 500, "An unexpected error occurred", id="Exception-500"),
        ],
    )
    async def test_exception_to_status(self, exception, expected_status, expected_fragment):
        """Service exceptions are converted to the correct HTTP status and message."""
        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.side_effect = exception

            response = await generate_schemas_from_openapi(
                request=_mock_request({"url": "http://example.com/api", "request_type": "POST"}),
                _user=_USER,
            )

        assert response.status_code == expected_status
        content = orjson.loads(response.body)
        assert content["success"] is False
        assert expected_fragment in content["message"]

    @pytest.mark.asyncio
    async def test_request_body_failure_returns_400(self):
        """If _read_request_json fails, the endpoint returns 400."""
        req = MagicMock(spec=Request)
        req.body = AsyncMock(side_effect=Exception("boom"))

        response = await generate_schemas_from_openapi(request=req, _user=_USER)

        assert response.status_code == 400
        content = orjson.loads(response.body)
        assert "Invalid JSON" in content["message"]


# ---------------------------------------------------------------------------
# Deny-path regression tests
# ---------------------------------------------------------------------------


class TestGenerateSchemasPermissionDenial:
    """Verify the endpoint rejects callers without tools.create permission."""

    @pytest.mark.asyncio
    async def test_denies_without_tools_create_permission(self, monkeypatch):
        """Users with only tools.read (not tools.create) are rejected with 403."""
        # Third-Party
        from fastapi import HTTPException

        deny_service = MagicMock()
        deny_service.check_permission = AsyncMock(return_value=False)
        monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda db: deny_service)
        monkeypatch.setattr("mcpgateway.admin.PermissionService", lambda db: deny_service)

        with pytest.raises(HTTPException) as exc_info:
            await generate_schemas_from_openapi(
                request=_mock_request({"url": "http://example.com/api", "request_type": "GET"}),
                _user={"email": "viewer@example.com"},
            )

        assert exc_info.value.status_code == 403
