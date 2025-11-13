# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_catalog_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit Tests for Catalog Service .
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from mcpgateway.services.catalog_service import CatalogService
from mcpgateway.schemas import (
    CatalogListRequest,
    CatalogBulkRegisterRequest,
    CatalogServerRegisterRequest,
)

@pytest.fixture
def service():
    return CatalogService()

@pytest.mark.asyncio
async def test_load_catalog_cached(service):
    service._catalog_cache = {"cached": True}
    service._cache_timestamp = 1000.0
    with patch("mcpgateway.services.catalog_service.settings", MagicMock(mcpgateway_catalog_cache_ttl=9999)), \
         patch("mcpgateway.services.catalog_service.time.time", return_value=1001.0):
        result = await service.load_catalog()
        assert result == {"cached": True}

@pytest.mark.asyncio
async def test_load_catalog_missing_file(service):
    with patch("mcpgateway.services.catalog_service.settings", MagicMock(mcpgateway_catalog_file="missing.yml", mcpgateway_catalog_cache_ttl=0)):
        with patch("mcpgateway.services.catalog_service.Path.exists", return_value=False):
            result = await service.load_catalog(force_reload=True)
            assert "catalog_servers" in result

@pytest.mark.asyncio
async def test_load_catalog_valid_yaml(service):
    fake_yaml = {"catalog_servers": [{"id": "1", "name": "srv"}]}
    with patch("mcpgateway.services.catalog_service.settings", MagicMock(mcpgateway_catalog_file="catalog.yml", mcpgateway_catalog_cache_ttl=0)):
        with patch("mcpgateway.services.catalog_service.Path.exists", return_value=True):
            with patch("builtins.open", new_callable=MagicMock) as mock_open, patch("mcpgateway.services.catalog_service.yaml.safe_load", return_value=fake_yaml):
                mock_open.return_value.__enter__.return_value.read.return_value = "data"
                result = await service.load_catalog(force_reload=True)
                assert "catalog_servers" in result

@pytest.mark.asyncio
async def test_load_catalog_exception(service):
    with patch("mcpgateway.services.catalog_service.settings", MagicMock(mcpgateway_catalog_file="catalog.yml", mcpgateway_catalog_cache_ttl=0)):
        with patch("mcpgateway.services.catalog_service.open", side_effect=Exception("fail")):
            result = await service.load_catalog(force_reload=True)
            assert result["catalog_servers"] == []

@pytest.mark.asyncio
async def test_get_catalog_servers_filters(service):
    fake_catalog = {
        "catalog_servers": [
            {"id": "1", "name": "srv1", "url": "http://a", "category": "cat", "auth_type": "Open", "provider": "prov", "tags": ["t1"], "description": "desc"},
            {"id": "2", "name": "srv2", "url": "http://b", "category": "other", "auth_type": "API", "provider": "prov2", "tags": ["t2"], "description": "desc2"},
        ]
    }
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value = [("http://a",)]
        req = CatalogListRequest(category="cat", auth_type="Open", provider="prov", search="srv", tags=["t1"], show_registered_only=True, show_available_only=True, offset=0, limit=10)
        result = await service.get_catalog_servers(req, db)
        assert result.total >= 1
        assert all(s.category == "cat" for s in result.servers)

@pytest.mark.asyncio
async def test_register_catalog_server_not_found(service):
    with patch.object(service, "load_catalog", AsyncMock(return_value={"catalog_servers": []})):
        db = MagicMock()
        result = await service.register_catalog_server("missing", None, db)
        assert not result.success
        assert "not found" in result.message

@pytest.mark.asyncio
async def test_register_catalog_server_already_registered(service):
    fake_catalog = {"catalog_servers": [{"id": "1", "name": "srv", "url": "http://a", "description": "desc"}]}
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = MagicMock(id=123)
        with patch("mcpgateway.services.catalog_service.select"):
            result = await service.register_catalog_server("1", None, db)
            assert not result.success
            assert "already registered" in result.message

@pytest.mark.asyncio
async def test_register_catalog_server_success(service):
    fake_catalog = {"catalog_servers": [{"id": "1", "name": "srv", "url": "http://a", "description": "desc"}]}
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with patch("mcpgateway.services.catalog_service.select"), patch.object(service._gateway_service, "register_gateway", AsyncMock(return_value=MagicMock(id=1, name="srv"))):
            result = await service.register_catalog_server("1", None, db)
            assert result.success
            assert "Successfully" in result.message

@pytest.mark.asyncio
async def test_register_catalog_server_ipv6(service):
    fake_catalog = {"catalog_servers": [{"id": "1", "name": "srv", "url": "[::1]", "description": "desc"}]}
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with patch("mcpgateway.services.catalog_service.select"):
            result = await service.register_catalog_server("1", None, db)
            assert not result.success
            assert "IPv6" in result.error

@pytest.mark.asyncio
async def test_register_catalog_server_exception_mapping(service):
    fake_catalog = {"catalog_servers": [{"id": "1", "name": "srv", "url": "http://a", "description": "desc"}]}
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with patch("mcpgateway.services.catalog_service.select"), \
             patch.object(service._gateway_service, "register_gateway", AsyncMock(side_effect=Exception("Connection refused"))):
            result = await service.register_catalog_server("1", None, db)
            assert "offline" in result.message

@pytest.mark.asyncio
async def test_check_server_availability_success(service):
    fake_catalog = {"catalog_servers": [{"id": "1", "url": "http://a"}]}
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        with patch("mcpgateway.services.catalog_service.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value.status_code = 200
            mock_client.return_value.__aenter__.return_value = mock_instance
            result = await service.check_server_availability("1")
            assert result.is_available

@pytest.mark.asyncio
async def test_check_server_availability_not_found(service):
    with patch.object(service, "load_catalog", AsyncMock(return_value={"catalog_servers": []})):
        result = await service.check_server_availability("missing")
        assert not result.is_available
        assert "not found" in result.error

@pytest.mark.asyncio
async def test_check_server_availability_exception(service):
    fake_catalog = {"catalog_servers": [{"id": "1", "url": "http://a"}]}
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        with patch("mcpgateway.services.catalog_service.httpx.AsyncClient", side_effect=Exception("fail")):
            result = await service.check_server_availability("1")
            assert not result.is_available

@pytest.mark.asyncio
async def test_bulk_register_servers_success_and_failure(service):
    fake_request = CatalogBulkRegisterRequest(server_ids=["1", "2"], skip_errors=False)
    with patch.object(service, "register_catalog_server", AsyncMock(side_effect=[MagicMock(success=True), MagicMock(success=False, error="fail")])):
        db = MagicMock()
        result = await service.bulk_register_servers(fake_request, db)
        assert result.total_attempted == 2
        assert len(result.failed) == 1


@pytest.mark.asyncio
async def test_auth_type_api_key_and_oauth(service):
    fake_catalog = {"catalog_servers": [{"id": "1", "name": "srv", "url": "http://a", "description": "desc", "auth_type": "API Key"}]}
    req = CatalogServerRegisterRequest(server_id="1", name="srv", api_key="secret", oauth_credentials=None)
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with patch("mcpgateway.services.catalog_service.select"), patch.object(service._gateway_service, "register_gateway", AsyncMock(return_value=MagicMock(id=1, name="srv"))):
            result = await service.register_catalog_server("1", req, db)
            assert result.success

    fake_catalog["catalog_servers"][0]["auth_type"] = "OAuth2.1 & API Key"
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with patch("mcpgateway.services.catalog_service.select"), patch.object(service._gateway_service, "register_gateway", AsyncMock(return_value=MagicMock(id=1, name="srv"))):
            result = await service.register_catalog_server("1", req, db)
            assert result.success


@pytest.mark.asyncio
async def test_bulk_register_servers_skip_errors(service):
    fake_request = CatalogBulkRegisterRequest(server_ids=["1", "2"], skip_errors=True)
    with patch.object(service, "register_catalog_server", AsyncMock(side_effect=[MagicMock(success=False, error="fail"), MagicMock(success=True)])):
        db = MagicMock()
        result = await service.bulk_register_servers(fake_request, db)
        assert result.total_attempted == 2
        assert len(result.failed) == 1
