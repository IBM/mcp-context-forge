# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_openapi_schema_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for the OpenAPI schema generation router.

Tests cover:
    - POST /v1/tools/generate-schemas-from-openapi: success, validation, error mapping
    - RBAC enforcement (with real permission check)
    - Default value handling
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
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


def _create_body(url, request_type="GET", openapi_url=""):
    """Create GenerateSchemaRequest body object."""
    from mcpgateway.routers.openapi_schema_router import GenerateSchemaRequest

    return GenerateSchemaRequest(url=url, request_type=request_type, openapi_url=openapi_url)


# ---------------------------------------------------------------------------
# Happy Path Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_schema_success_all_fields():
    """Valid request with all fields returns schemas successfully."""
    body = _create_body(
        url="http://api.example.com/calculate",
        request_type="POST",
        openapi_url="http://api.example.com/openapi.json",
    )

    mock_schemas = (
        {"type": "object", "properties": {"a": {"type": "number"}}},
        {"type": "object", "properties": {"result": {"type": "number"}}},
        "http://api.example.com/openapi.json",
    )

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_schemas

        response = await router_mod.generate_schemas_from_openapi(body, _user=_mock_user())

        assert response.status_code == 200
        content = response.body
        assert b'"success":true' in content
        assert b'"message":"Schemas generated successfully from OpenAPI spec"' in content
        assert b'"spec_url":"http://api.example.com/openapi.json"' in content


@pytest.mark.asyncio
async def test_generate_schema_success_minimal_fields():
    """Valid request with minimal fields applies defaults."""
    body = _create_body(url="http://api.example.com/calculate")

    mock_schemas = (
        {"type": "object"},
        {"type": "object"},
        "http://api.example.com/openapi.json",
    )

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_schemas

        response = await router_mod.generate_schemas_from_openapi(body, _user=_mock_user())

        assert response.status_code == 200
        # Verify default request_type="GET" was used
        mock_fetch.assert_called_once()
        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["method"] == "GET"


@pytest.mark.asyncio
async def test_generate_schema_auto_discovery():
    """Empty openapi_url triggers auto-discovery."""
    body = _create_body(url="http://api.example.com/calculate", openapi_url="")

    mock_schemas = (
        {"type": "object"},
        {"type": "object"},
        "http://api.example.com/openapi.json",
    )

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_schemas

        response = await router_mod.generate_schemas_from_openapi(body, _user=_mock_user())

        assert response.status_code == 200
        # Verify empty openapi_url was passed (triggers auto-discovery in service)
        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["openapi_url"] == ""


# ---------------------------------------------------------------------------
# Input Validation Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_schema_invalid_json():
    """Invalid JSON body returns 422 (Pydantic validation error)."""
    # Pydantic validation happens before the function is called
    # This test verifies that invalid input is rejected by FastAPI
    # In practice, FastAPI returns 422 for validation errors
    # We test this by attempting to create an invalid body object
    with pytest.raises(Exception):  # Pydantic will raise validation error
        from mcpgateway.routers.openapi_schema_router import GenerateSchemaRequest

        GenerateSchemaRequest.model_validate_json('{invalid json}')


@pytest.mark.asyncio
async def test_generate_schema_missing_url():
    """Missing url field returns validation error."""
    # Pydantic validation happens before the function is called
    with pytest.raises(Exception):  # Pydantic will raise validation error
        from mcpgateway.routers.openapi_schema_router import GenerateSchemaRequest

        GenerateSchemaRequest(request_type="POST")  # Missing required 'url'


@pytest.mark.asyncio
async def test_generate_schema_empty_url():
    """Empty url field is accepted by Pydantic but rejected by security validation."""
    body = _create_body(url="   ")

    # Empty URL passes Pydantic but fails security validation
    with patch("mcpgateway.routers.openapi_schema_router.SecurityValidator.validate_url") as mock_validate:
        mock_validate.side_effect = ValueError("URL cannot be empty")

        response = await router_mod.generate_schemas_from_openapi(body, _user=_mock_user())

        assert response.status_code == 400
        content = response.body
        assert b'"success":false' in content


@pytest.mark.asyncio
async def test_generate_schema_invalid_url_format():
    """Invalid URL format returns 400 from security validation."""
    body = _create_body(url="not-a-valid-url")

    with patch("mcpgateway.routers.openapi_schema_router.SecurityValidator.validate_url") as mock_validate:
        mock_validate.side_effect = ValueError("Invalid URL format")

        response = await router_mod.generate_schemas_from_openapi(body, _user=_mock_user())

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
    body = _create_body(url="http://api.example.com/calculate")

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = ValueError("Security validation failed: blocked domain")

        response = await router_mod.generate_schemas_from_openapi(body, _user=_mock_user())

        assert response.status_code == 400
        content = response.body
        assert b'"success":false' in content
        assert b"Security validation failed" in content


@pytest.mark.asyncio
async def test_generate_schema_path_not_found():
    """KeyError (path/method not found) returns 404."""
    body = _create_body(url="http://api.example.com/nonexistent")

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = KeyError("Path /nonexistent not found in OpenAPI spec")

        response = await router_mod.generate_schemas_from_openapi(body, _user=_mock_user())

        assert response.status_code == 404
        content = response.body
        assert b'"success":false' in content


@pytest.mark.asyncio
async def test_generate_schema_http_status_error():
    """httpx.HTTPStatusError returns 502."""
    body = _create_body(url="http://api.example.com/calculate")

    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)

        response = await router_mod.generate_schemas_from_openapi(body, _user=_mock_user())

        assert response.status_code == 502
        content = response.body
        assert b'"success":false' in content
        assert b"OpenAPI spec server returned HTTP 404" in content


@pytest.mark.asyncio
async def test_generate_schema_http_error():
    """httpx.HTTPError returns 502."""
    body = _create_body(url="http://api.example.com/calculate")

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = httpx.HTTPError("Connection failed")

        response = await router_mod.generate_schemas_from_openapi(body, _user=_mock_user())

        assert response.status_code == 502
        content = response.body
        assert b'"success":false' in content
        assert b"Failed to fetch OpenAPI spec" in content


@pytest.mark.asyncio
async def test_generate_schema_generic_exception():
    """Generic Exception returns 500."""
    body = _create_body(url="http://api.example.com/calculate")

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = Exception("Unexpected error")

        response = await router_mod.generate_schemas_from_openapi(body, _user=_mock_user())

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
    body = _create_body(url="http://api.example.com/calculate")

    mock_schemas = ({"type": "object"}, {"type": "object"}, "http://api.example.com/openapi.json")

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_schemas

        await router_mod.generate_schemas_from_openapi(body, _user=_mock_user())

        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["method"] == "GET"


@pytest.mark.asyncio
async def test_generate_schema_openapi_url_can_be_empty():
    """openapi_url can be empty (triggers auto-discovery)."""
    body = _create_body(url="http://api.example.com/calculate", openapi_url="")

    mock_schemas = ({"type": "object"}, {"type": "object"}, "http://api.example.com/openapi.json")

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_schemas

        await router_mod.generate_schemas_from_openapi(body, _user=_mock_user())

        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["openapi_url"] == ""


# ---------------------------------------------------------------------------
# URL Parsing Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_schema_url_parsing():
    """URL is correctly parsed into base_url and path."""
    body = _create_body(url="https://api.example.com:8080/v1/calculate")

    mock_schemas = ({"type": "object"}, {"type": "object"}, "https://api.example.com:8080/openapi.json")

    with patch("mcpgateway.routers.openapi_schema_router.fetch_and_extract_schemas", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_schemas

        await router_mod.generate_schemas_from_openapi(body, _user=_mock_user())

        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["base_url"] == "https://api.example.com:8080"
        assert call_kwargs["path"] == "/v1/calculate"


# ---------------------------------------------------------------------------
# RBAC Tests (Real Permission Check)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_schemas_403_when_permission_denied(monkeypatch: pytest.MonkeyPatch):
    """Endpoint returns 403 when user lacks tools.create permission.

    This test temporarily restores the real RBAC decorators to verify
    the endpoint correctly enforces the tools.create permission.
    """
    # Restore real decorators for this test
    from tests.utils.rbac_mocks import restore_rbac_decorators
    restore_rbac_decorators(_originals)

    # Patch PermissionService to deny all permissions
    class DenyAll:
        def __init__(self, _db):
            pass

        async def check_permission(self, **_kwargs):
            return False

    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", DenyAll)

    # Re-import the router module to pick up the restored decorators
    import importlib
    importlib.reload(router_mod)

    # Create test data
    body = router_mod.GenerateSchemaRequest(url="http://api.example.com/calculate")
    non_admin_user = {"email": "user@example.com", "is_admin": False, "ip_address": "127.0.0.1", "user_agent": "tests"}

    # The @require_permission decorator should raise HTTPException with 403
    # when PermissionService.check_permission returns False
    with pytest.raises(HTTPException) as exc:
        await router_mod.generate_schemas_from_openapi(body, _user=non_admin_user)

    assert exc.value.status_code == 403
    assert "access denied" in str(exc.value.detail).lower()

    # Re-patch decorators for remaining tests
    from tests.utils.rbac_mocks import patch_rbac_decorators
    patch_rbac_decorators()
    importlib.reload(router_mod)
