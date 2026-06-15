# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_openapi_schema_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for the OpenAPI schema generation router.

Tests cover:
    - POST /v1/tools/generate-schema-from-openapi: success, validation, error mapping
    - RBAC enforcement
    - Default value handling
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import status
import httpx
import pytest

# Local
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators

_originals = patch_rbac_decorators()
# First-Party
from mcpgateway.routers import openapi_schema_router as router_mod  # noqa: E402  # pylint: disable=wrong-import-position

restore_rbac_decorators(_originals)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_user():
    """Return mock user context dict."""
    return {"email": "test@example.com", "is_admin": False}


def _mock_request(body):
    """Create mock FastAPI Request with JSON body."""
    request = MagicMock()
    request.body = AsyncMock(return_value=body)
    return request


# ---------------------------------------------------------------------------
# Happy Path Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_schema_success_all_fields():
    """Valid request with all fields returns schemas successfully."""
    request = _mock_request(b'{"url": "http://api.example.com/calculate", "request_type": "POST", "openapi_url": "http://api.example.com/openapi.json"}')

    mock_schemas = (
        {"type": "object", "properties": {"a": {"type": "number"}}},
        {"type": "object", "properties": {"result": {"type": "number"}}},
        "http://api.example.com/openapi.json",
    )

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_schemas

        response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

        assert response.status_code == 200
        content = response.body
        assert b'"success":true' in content
        assert b'"message":"Schemas generated successfully from OpenAPI spec"' in content
        assert b'"spec_url":"http://api.example.com/openapi.json"' in content


@pytest.mark.asyncio
async def test_generate_schema_success_minimal_fields():
    """Valid request with minimal fields applies defaults."""
    request = _mock_request(b'{"url": "http://api.example.com/calculate"}')

    mock_schemas = (
        {"type": "object"},
        {"type": "object"},
        "http://api.example.com/openapi.json",
    )

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_schemas

        response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

        assert response.status_code == 200
        # Verify default request_type="GET" was used
        mock_fetch.assert_called_once()
        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["method"] == "GET"


@pytest.mark.asyncio
async def test_generate_schema_auto_discovery():
    """Empty openapi_url triggers auto-discovery."""
    request = _mock_request(b'{"url": "http://api.example.com/calculate", "openapi_url": ""}')

    mock_schemas = (
        {"type": "object"},
        {"type": "object"},
        "http://api.example.com/openapi.json",
    )

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_schemas

        response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

        assert response.status_code == 200
        # Verify empty openapi_url was passed (triggers auto-discovery in service)
        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["openapi_url"] == ""


# ---------------------------------------------------------------------------
# Input Validation Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_schema_invalid_json():
    """Invalid JSON body returns 400."""
    request = _mock_request(b'{invalid json}')

    response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

    assert response.status_code == 400
    content = response.body
    assert b'"success":false' in content
    assert b'"message":"Invalid JSON in request body"' in content


@pytest.mark.asyncio
async def test_generate_schema_non_dict_body():
    """Non-dict JSON body returns 400."""
    request = _mock_request(b'["array", "not", "dict"]')

    response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

    assert response.status_code == 400
    content = response.body
    assert b'"success":false' in content
    assert b'"message":"Request body must be a JSON object"' in content


@pytest.mark.asyncio
async def test_generate_schema_missing_url():
    """Missing url field returns 400."""
    request = _mock_request(b'{"request_type": "POST"}')

    response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

    assert response.status_code == 400
    content = response.body
    assert b'"success":false' in content
    assert b"'url' is required" in content


@pytest.mark.asyncio
async def test_generate_schema_empty_url():
    """Empty url field returns 400."""
    request = _mock_request(b'{"url": "   "}')

    response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

    assert response.status_code == 400
    content = response.body
    assert b'"success":false' in content
    assert b"'url' is required" in content


@pytest.mark.asyncio
async def test_generate_schema_non_string_fields():
    """Non-string field types return 400."""
    request = _mock_request(b'{"url": 123, "request_type": true, "openapi_url": null}')

    response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

    assert response.status_code == 400
    content = response.body
    assert b'"success":false' in content
    assert b"must be strings" in content


@pytest.mark.asyncio
async def test_generate_schema_invalid_url_format():
    """Invalid URL format returns 400 from security validation."""
    request = _mock_request(b'{"url": "not-a-valid-url"}')

    with patch("mcpgateway.routers.openapi_schema_router.SecurityValidator.validate_url") as mock_validate:
        mock_validate.side_effect = ValueError("Invalid URL format")

        response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

        assert response.status_code == 400
        content = response.body
        assert b'"success":false' in content
        assert b"Invalid URL format" in content


# ---------------------------------------------------------------------------
# Service Error Mapping Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_schema_security_validation_error():
    """ValueError from security validation returns 400."""
    request = _mock_request(b'{"url": "http://api.example.com/calculate"}')

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = ValueError("Security validation failed: blocked domain")

        response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

        assert response.status_code == 400
        content = response.body
        assert b'"success":false' in content
        assert b"Security validation failed" in content


@pytest.mark.asyncio
async def test_generate_schema_path_not_found():
    """KeyError (path/method not found) returns 404."""
    request = _mock_request(b'{"url": "http://api.example.com/nonexistent"}')

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = KeyError("Path /nonexistent not found in OpenAPI spec")

        response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

        assert response.status_code == 404
        content = response.body
        assert b'"success":false' in content


@pytest.mark.asyncio
async def test_generate_schema_http_status_error():
    """httpx.HTTPStatusError returns 502."""
    request = _mock_request(b'{"url": "http://api.example.com/calculate"}')

    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)

        response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

        assert response.status_code == 502
        content = response.body
        assert b'"success":false' in content
        assert b"OpenAPI spec server returned HTTP 404" in content


@pytest.mark.asyncio
async def test_generate_schema_http_error():
    """httpx.HTTPError returns 502."""
    request = _mock_request(b'{"url": "http://api.example.com/calculate"}')

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = httpx.HTTPError("Connection failed")

        response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

        assert response.status_code == 502
        content = response.body
        assert b'"success":false' in content
        assert b"Failed to fetch OpenAPI spec" in content


@pytest.mark.asyncio
async def test_generate_schema_generic_exception():
    """Generic Exception returns 500."""
    request = _mock_request(b'{"url": "http://api.example.com/calculate"}')

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = Exception("Unexpected error")

        response = await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

        assert response.status_code == 500
        content = response.body
        assert b'"success":false' in content
        assert b"An unexpected error occurred" in content


# ---------------------------------------------------------------------------
# Default Value Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_schema_request_type_defaults_to_get():
    """request_type defaults to GET when omitted."""
    request = _mock_request(b'{"url": "http://api.example.com/calculate"}')

    mock_schemas = ({"type": "object"}, {"type": "object"}, "http://api.example.com/openapi.json")

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_schemas

        await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["method"] == "GET"


@pytest.mark.asyncio
async def test_generate_schema_openapi_url_can_be_empty():
    """openapi_url can be empty (triggers auto-discovery)."""
    request = _mock_request(b'{"url": "http://api.example.com/calculate", "openapi_url": ""}')

    mock_schemas = ({"type": "object"}, {"type": "object"}, "http://api.example.com/openapi.json")

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_schemas

        await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["openapi_url"] == ""


# ---------------------------------------------------------------------------
# URL Parsing Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_schema_url_parsing():
    """URL is correctly parsed into base_url and path."""
    request = _mock_request(b'{"url": "https://api.example.com:8080/v1/calculate"}')

    mock_schemas = ({"type": "object"}, {"type": "object"}, "https://api.example.com:8080/openapi.json")

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_schemas

        await router_mod.generate_schema_from_openapi(request, _user=_mock_user())

        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["base_url"] == "https://api.example.com:8080"
        assert call_kwargs["path"] == "/v1/calculate"

# Made with Bob
