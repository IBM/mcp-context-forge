# -*- coding: utf-8 -*-
"""Tests for token scoping utilities."""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.utils import token_scoping


@pytest.mark.asyncio
async def test_extract_token_scopes_no_auth_header():
    request = MagicMock()
    request.headers = {}

    assert await token_scoping.extract_token_scopes_from_request(request) is None


@pytest.mark.asyncio
async def test_extract_token_scopes_invalid_header():
    request = MagicMock()
    request.headers = {"Authorization": "Invalid"}

    assert await token_scoping.extract_token_scopes_from_request(request) is None


@pytest.mark.asyncio
async def test_extract_token_scopes_success():
    request = MagicMock()
    request.headers = {"Authorization": "Bearer token123"}

    with patch("mcpgateway.utils.token_scoping.verify_jwt_token_cached", new=AsyncMock(return_value={"scopes": {"server_id": "srv"}})):
        scopes = await token_scoping.extract_token_scopes_from_request(request)

    assert scopes == {"server_id": "srv"}


@pytest.mark.asyncio
async def test_extract_token_scopes_http_exception():
    request = MagicMock()
    request.headers = {"Authorization": "Bearer token123"}

    with patch("mcpgateway.utils.token_scoping.verify_jwt_token_cached", new=AsyncMock(side_effect=HTTPException(status_code=401))):
        assert await token_scoping.extract_token_scopes_from_request(request) is None


def test_is_token_server_scoped_and_get_server_id():
    assert token_scoping.is_token_server_scoped(None) is False
    assert token_scoping.is_token_server_scoped({"server_id": None}) is False
    assert token_scoping.is_token_server_scoped({"server_id": "abc"}) is True

    assert token_scoping.get_token_server_id(None) is None
    assert token_scoping.get_token_server_id({"server_id": None}) is None
    assert token_scoping.get_token_server_id({"server_id": "abc"}) == "abc"


def test_validate_server_access():
    assert token_scoping.validate_server_access(None, "any") is True
    assert token_scoping.validate_server_access({"server_id": None}, "any") is True
    assert token_scoping.validate_server_access({"server_id": "srv-1"}, "srv-1") is True
    assert token_scoping.validate_server_access({"server_id": "srv-1"}, "srv-2") is False
