# -*- coding: utf-8 -*-
"""Unit tests for well_known and server_well_known routers."""

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
async def test_server_oauth_protected_resource_disabled():
    from mcpgateway.routers.server_well_known import server_oauth_protected_resource

    request = MagicMock()
    with patch("mcpgateway.routers.server_well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = False
        with pytest.raises(HTTPException) as exc_info:
            await server_oauth_protected_resource(request, "server-1")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_server_oauth_protected_resource_not_found():
    from mcpgateway.routers.server_well_known import server_oauth_protected_resource

    request = MagicMock()
    request.headers = {}
    request.url.scheme = "https"
    request.base_url = "https://example.com/"
    mock_db = MagicMock()

    from mcpgateway.services.server_service import ServerNotFoundError

    with (
        patch("mcpgateway.routers.server_well_known.settings") as mock_settings,
        patch("mcpgateway.routers.server_well_known.server_service") as mock_svc,
    ):
        mock_settings.well_known_enabled = True
        mock_settings.well_known_cache_max_age = 3600
        mock_svc.get_oauth_protected_resource_metadata.side_effect = ServerNotFoundError("not found")
        with pytest.raises(HTTPException) as exc_info:
            await server_oauth_protected_resource(request, "server-1", db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_server_oauth_protected_resource_server_error():
    from mcpgateway.routers.server_well_known import server_oauth_protected_resource
    from mcpgateway.services.server_service import ServerError

    request = MagicMock()
    request.headers = {}
    request.url.scheme = "https"
    request.base_url = "https://example.com/"
    mock_db = MagicMock()

    with (
        patch("mcpgateway.routers.server_well_known.settings") as mock_settings,
        patch("mcpgateway.routers.server_well_known.server_service") as mock_svc,
    ):
        mock_settings.well_known_enabled = True
        mock_settings.well_known_cache_max_age = 3600
        mock_svc.get_oauth_protected_resource_metadata.side_effect = ServerError("server error")
        with pytest.raises(HTTPException) as exc_info:
            await server_oauth_protected_resource(request, "server-1", db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_server_oauth_protected_resource_success():
    from mcpgateway.routers.server_well_known import server_oauth_protected_resource

    request = MagicMock()
    request.headers = {}
    request.url.scheme = "https"
    request.base_url = "https://example.com/"
    mock_db = MagicMock()

    with (
        patch("mcpgateway.routers.server_well_known.settings") as mock_settings,
        patch("mcpgateway.routers.server_well_known.server_service") as mock_svc,
    ):
        mock_settings.well_known_enabled = True
        mock_settings.well_known_cache_max_age = 3600
        mock_svc.get_oauth_protected_resource_metadata.return_value = {"resource": "https://example.com/servers/s1"}
        response = await server_oauth_protected_resource(request, "s1", db=mock_db)
    assert response.status_code == 200


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


# ---------- Root well-known OAuth endpoint ----------


@pytest.mark.asyncio
async def test_root_oauth_protected_resource_disabled():
    from mcpgateway.routers.well_known import get_oauth_protected_resource

    request = MagicMock()
    mock_db = MagicMock()
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = False
        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_protected_resource(request, db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_root_oauth_protected_resource_no_server_id():
    from mcpgateway.routers.well_known import get_oauth_protected_resource

    request = MagicMock()
    mock_db = MagicMock()
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_protected_resource(request, server_id=None, db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_root_oauth_protected_resource_server_not_found():
    from mcpgateway.routers.well_known import get_oauth_protected_resource

    request = MagicMock()
    mock_db = MagicMock()
    mock_db.get.return_value = None
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_protected_resource(request, server_id="s1", db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_root_oauth_protected_resource_server_disabled():
    from mcpgateway.routers.well_known import get_oauth_protected_resource

    request = MagicMock()
    mock_server = MagicMock()
    mock_server.enabled = False
    mock_db = MagicMock()
    mock_db.get.return_value = mock_server
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_protected_resource(request, server_id="s1", db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_root_oauth_protected_resource_not_public():
    from mcpgateway.routers.well_known import get_oauth_protected_resource

    request = MagicMock()
    mock_server = MagicMock()
    mock_server.enabled = True
    mock_server.visibility = "private"
    mock_db = MagicMock()
    mock_db.get.return_value = mock_server
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_protected_resource(request, server_id="s1", db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_root_oauth_protected_resource_oauth_disabled():
    from mcpgateway.routers.well_known import get_oauth_protected_resource

    request = MagicMock()
    mock_server = MagicMock()
    mock_server.enabled = True
    mock_server.visibility = "public"
    mock_server.oauth_enabled = False
    mock_db = MagicMock()
    mock_db.get.return_value = mock_server
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_protected_resource(request, server_id="s1", db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_root_oauth_protected_resource_no_config():
    from mcpgateway.routers.well_known import get_oauth_protected_resource

    request = MagicMock()
    mock_server = MagicMock()
    mock_server.enabled = True
    mock_server.visibility = "public"
    mock_server.oauth_enabled = True
    mock_server.oauth_config = None
    mock_db = MagicMock()
    mock_db.get.return_value = mock_server
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_protected_resource(request, server_id="s1", db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_root_oauth_protected_resource_no_auth_servers():
    from mcpgateway.routers.well_known import get_oauth_protected_resource

    request = MagicMock()
    mock_server = MagicMock()
    mock_server.enabled = True
    mock_server.visibility = "public"
    mock_server.oauth_enabled = True
    mock_server.oauth_config = {}
    mock_db = MagicMock()
    mock_db.get.return_value = mock_server
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_protected_resource(request, server_id="s1", db=mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_root_oauth_protected_resource_success():
    from mcpgateway.routers.well_known import get_oauth_protected_resource

    request = MagicMock()
    request.headers = {}
    request.url.scheme = "https"
    request.base_url = "https://example.com/"
    mock_server = MagicMock()
    mock_server.enabled = True
    mock_server.visibility = "public"
    mock_server.oauth_enabled = True
    mock_server.oauth_config = {"authorization_servers": ["https://idp.example.com"], "scopes_supported": ["openid"]}
    mock_db = MagicMock()
    mock_db.get.return_value = mock_server
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        mock_settings.well_known_cache_max_age = 3600
        response = await get_oauth_protected_resource(request, server_id="s1", db=mock_db)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_root_oauth_protected_resource_single_auth_server():
    from mcpgateway.routers.well_known import get_oauth_protected_resource

    request = MagicMock()
    request.headers = {}
    request.url.scheme = "https"
    request.base_url = "https://example.com/"
    mock_server = MagicMock()
    mock_server.enabled = True
    mock_server.visibility = "public"
    mock_server.oauth_enabled = True
    mock_server.oauth_config = {"authorization_server": "https://idp.example.com"}
    mock_db = MagicMock()
    mock_db.get.return_value = mock_server
    with patch("mcpgateway.routers.well_known.settings") as mock_settings:
        mock_settings.well_known_enabled = True
        mock_settings.well_known_cache_max_age = 3600
        response = await get_oauth_protected_resource(request, server_id="s1", db=mock_db)
    assert response.status_code == 200
