# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_well_known.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for well_known and server_well_known routers.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException

# First-Party
from mcpgateway.routers.well_known import (
    get_base_url_with_protocol,
    get_well_known_file_content,
    validate_security_txt,
)
from tests.helpers.router_helpers import collect_routes

# ---------- get_base_url_with_protocol ----------


def test_get_base_url_with_forwarded_proto():
    request = MagicMock()
    request.headers = {"x-forwarded-proto": "https"}
    request.url.scheme = "http"
    request.base_url = "http://example.com/"
    result = get_base_url_with_protocol(request)
    assert result.startswith("https://")
    assert not result.endswith("/")


def test_get_base_url_without_forwarded_proto():
    request = MagicMock()
    request.headers = {}
    request.url.scheme = "http"
    request.base_url = "http://example.com/"
    result = get_base_url_with_protocol(request)
    assert result.startswith("http://")
    assert not result.endswith("/")


def test_get_base_url_with_multiple_forwarded_protos():
    request = MagicMock()
    request.headers = {"x-forwarded-proto": "https, http"}
    request.url.scheme = "http"
    request.base_url = "http://example.com/"
    result = get_base_url_with_protocol(request)
    assert result.startswith("https://")


# ---------- validate_security_txt ----------


def test_validate_security_txt_empty():
    assert validate_security_txt("") is None
    assert validate_security_txt(None) is None


def test_validate_security_txt_with_expires():
    content = "Contact: security@example.com\nExpires: 2026-12-31T00:00:00Z"
    result = validate_security_txt(content)
    assert "Expires:" in result
    assert "Contact:" in result


def test_validate_security_txt_without_expires():
    content = "Contact: security@example.com"
    result = validate_security_txt(content)
    assert "Expires:" in result


def test_validate_security_txt_without_header_comment():
    content = "Contact: security@example.com"
    result = validate_security_txt(content)
    assert result.startswith("# Security contact information")


def test_validate_security_txt_with_header_comment():
    content = "# My security file\nContact: security@example.com"
    result = validate_security_txt(content)
    assert result.startswith("# My security file")


# ---------- get_well_known_file_content ----------


def test_get_well_known_robots_txt():
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        mock_settings.well_known_robots_txt = "User-agent: *\nDisallow: /"
        mock_settings.well_known_cache_max_age = 3600
        response = get_well_known_file_content("robots.txt")
    assert response.status_code == 200
    assert "Disallow" in response.body.decode()


def test_get_well_known_security_txt():
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        mock_settings.well_known_security_txt_enabled = True
        mock_settings.well_known_security_txt = "Contact: sec@example.com\nExpires: 2026-12-31T00:00:00Z"
        mock_settings.well_known_cache_max_age = 3600
        response = get_well_known_file_content("security.txt")
    assert response.status_code == 200


def test_get_well_known_security_txt_disabled():
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        mock_settings.well_known_security_txt_enabled = False
        mock_settings.well_known_cache_max_age = 3600
        with pytest.raises(HTTPException) as exc_info:
            get_well_known_file_content("security.txt")
    assert exc_info.value.status_code == 404


def test_get_well_known_security_txt_empty_content():
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        mock_settings.well_known_security_txt_enabled = True
        mock_settings.well_known_security_txt = ""
        mock_settings.well_known_cache_max_age = 3600
        with pytest.raises(HTTPException) as exc_info:
            get_well_known_file_content("security.txt")
    assert exc_info.value.status_code == 404


def test_get_well_known_custom_file():
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        mock_settings.well_known_cache_max_age = 3600
        mock_settings.custom_well_known_files = {"ai.txt": "AI policy content"}
        response = get_well_known_file_content("ai.txt")
    assert response.status_code == 200
    assert "AI policy" in response.body.decode()


def test_get_well_known_custom_file_not_in_registry():
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        mock_settings.well_known_cache_max_age = 3600
        mock_settings.custom_well_known_files = {"custom.txt": "custom content"}
        mock_settings.well_known_security_txt_enabled = False
        response = get_well_known_file_content("custom.txt")
    assert response.status_code == 200


def test_get_well_known_unknown_registered_file():
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        mock_settings.well_known_cache_max_age = 3600
        mock_settings.custom_well_known_files = {}
        mock_settings.well_known_security_txt_enabled = False
        with pytest.raises(HTTPException) as exc_info:
            get_well_known_file_content("dnt-policy.txt")
    assert exc_info.value.status_code == 404
    assert "not configured" in exc_info.value.detail


def test_get_well_known_completely_unknown_file():
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        mock_settings.well_known_cache_max_age = 3600
        mock_settings.custom_well_known_files = {}
        mock_settings.well_known_security_txt_enabled = False
        with pytest.raises(HTTPException) as exc_info:
            get_well_known_file_content("nonexistent.txt")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Not found"


def test_get_well_known_disabled():
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = False
        with pytest.raises(HTTPException) as exc_info:
            get_well_known_file_content("robots.txt")
    assert exc_info.value.status_code == 404


def test_get_well_known_strips_leading_slashes():
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        mock_settings.well_known_robots_txt = "User-agent: *"
        mock_settings.well_known_cache_max_age = 3600
        response = get_well_known_file_content("/robots.txt")
    assert response.status_code == 200


# ---------- server_well_known router ----------


@pytest.mark.asyncio
async def test_server_oauth_protected_resource_redirects_to_rfc9728():
    """Test that deprecated server-scoped endpoint returns 301 redirect to RFC 9728 compliant path."""
    from mcpgateway.routers.server_well_known import server_oauth_protected_resource

    request = MagicMock()
    request.headers = {}
    request.url.scheme = "https"
    request.base_url = "https://example.com/"

    with patch("mcpgateway.routers.server_well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        with pytest.raises(HTTPException) as exc_info:
            await server_oauth_protected_resource(request, "server-1")

    assert exc_info.value.status_code == 301
    assert "Location" in exc_info.value.headers
    redirect_url = exc_info.value.headers["Location"]
    assert "/.well-known/oauth-protected-resource/servers/server-1/mcp" in redirect_url


# ---------- admin_router shape (RFC 8615 regression) ----------


def test_admin_router_exists_and_has_single_route():
    """admin_router must export exactly one route at /admin/well-known."""
    from mcpgateway.routers.well_known import admin_router

    paths = [route.path for route in admin_router.routes]
    assert paths == ["/admin/well-known"], f"Unexpected paths in admin_router: {paths}"


def test_admin_router_has_no_well_known_paths():
    """No route in admin_router should start with /.well-known — that would violate RFC 8615 when prefixed with /v1."""
    from mcpgateway.routers.well_known import admin_router

    violations = [route.path for route in admin_router.routes if route.path.startswith("/.well-known")]
    assert violations == [], f"RFC 8615 violation: admin_router contains /.well-known paths: {violations}"


def test_full_router_has_well_known_paths():
    """The full `router` must retain all /.well-known/* routes for the app-level mount."""
    from mcpgateway.routers.well_known import router

    well_known_paths = [route.path for route in router.routes if route.path.startswith("/.well-known")]
    assert len(well_known_paths) >= 1, "Full router missing /.well-known routes — app-level mount would be broken"


def test_v1_prefix_does_not_produce_rfc_violation():
    """Including admin_router in a /v1-prefixed router must not create any /.well-known paths."""
    from fastapi import APIRouter

    from mcpgateway.routers.well_known import admin_router

    v1_router = APIRouter(prefix="/v1")
    v1_router.include_router(admin_router)

    final_paths = [p for p, *_ in collect_routes(v1_router)]
    rfc_violations = [p for p in final_paths if "/.well-known" in p]
    assert rfc_violations == [], f"Including admin_router in /v1 creates RFC 8615 violating paths: {rfc_violations}"


@pytest.mark.asyncio
async def test_server_well_known_file_disabled():
    from mcpgateway.routers.server_well_known import server_well_known_file

    mock_db = MagicMock()
    with patch("mcpgateway.routers.server_well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = False
        with pytest.raises(HTTPException) as exc_info:
            await server_well_known_file("s1", "robots.txt", db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_server_well_known_file_server_not_found():
    from mcpgateway.routers.server_well_known import server_well_known_file

    mock_db = MagicMock()
    mock_db.get.return_value = None
    with patch("mcpgateway.routers.server_well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        with pytest.raises(HTTPException) as exc_info:
            await server_well_known_file("s1", "robots.txt", db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_server_well_known_file_server_disabled():
    from mcpgateway.routers.server_well_known import server_well_known_file

    mock_server = MagicMock()
    mock_server.enabled = False
    mock_db = MagicMock()
    mock_db.get.return_value = mock_server
    with patch("mcpgateway.routers.server_well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        with pytest.raises(HTTPException) as exc_info:
            await server_well_known_file("s1", "robots.txt", db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_server_well_known_file_non_public():
    from mcpgateway.routers.server_well_known import server_well_known_file

    mock_server = MagicMock()
    mock_server.enabled = True
    mock_server.visibility = "private"
    mock_db = MagicMock()
    mock_db.get.return_value = mock_server
    with patch("mcpgateway.routers.server_well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        with pytest.raises(HTTPException) as exc_info:
            await server_well_known_file("s1", "robots.txt", db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_server_well_known_file_success():
    from mcpgateway.routers.server_well_known import server_well_known_file

    mock_server = MagicMock()
    mock_server.enabled = True
    mock_server.visibility = "public"
    mock_db = MagicMock()
    mock_db.get.return_value = mock_server
    with (
        patch("mcpgateway.routers.server_well_known.settings") as mock_settings,
        patch("mcpgateway.routers.well_known.settings") as mock_wk_settings,
    ):
        mock_settings.well_known_enabled = True
        mock_wk_settings.well_known_enabled = True
        mock_wk_settings.well_known_robots_txt = "User-agent: *"
        mock_wk_settings.well_known_cache_max_age = 3600
        response = await server_well_known_file("s1", "robots.txt", db=mock_db)
    assert response.status_code == 200


# ---------- Deprecated OAuth endpoint tests ----------


@pytest.mark.asyncio
async def test_root_oauth_protected_resource_deprecated():
    """Test that deprecated query-parameter endpoint returns 404 with deprecation message."""
    from mcpgateway.routers.well_known import get_oauth_protected_resource

    request = MagicMock()
    request.headers = {}
    request.url.scheme = "https"
    request.base_url = "https://example.com/"

    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        # Deprecated endpoint now returns 404 regardless of server state
        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_protected_resource(request, server_id="s1")

    assert exc_info.value.status_code == 404
    assert "deprecated" in exc_info.value.detail.lower()
    assert "RFC 9728" in exc_info.value.detail
