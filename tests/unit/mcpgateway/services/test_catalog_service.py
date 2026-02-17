# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_catalog_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit Tests for Catalog Service .
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import (
    CatalogBulkRegisterRequest,
    CatalogListRequest,
    CatalogServerRegisterRequest,
)
from mcpgateway.services.catalog_service import CatalogService


@pytest.fixture
def service():
    return CatalogService()


@pytest.mark.asyncio
async def test_load_catalog_cached(service):
    service._catalog_cache = {"cached": True}
    service._cache_timestamp = 1000.0
    with patch("mcpgateway.services.catalog_service.settings", MagicMock(mcpgateway_catalog_cache_ttl=9999)), patch("mcpgateway.services.catalog_service.time.time", return_value=1001.0):
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
async def test_load_catalog_non_dict_payload_normalized(service):
    with patch("mcpgateway.services.catalog_service.settings", MagicMock(mcpgateway_catalog_file="catalog.yml", mcpgateway_catalog_cache_ttl=0, runtime_catalog_remote_urls=[])):
        with patch("mcpgateway.services.catalog_service.Path.exists", return_value=True):
            with patch("mcpgateway.services.catalog_service.asyncio.to_thread", new_callable=AsyncMock, return_value="[]"), patch(
                "mcpgateway.services.catalog_service.yaml.safe_load", return_value=["not-a-dict"]
            ):
                result = await service.load_catalog(force_reload=True)
                assert result == {"catalog_servers": []}


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
        # Return tuples of (url, enabled, auth_type, oauth_config) - enabled=True means active
        db.execute.return_value = [("http://a", True, None, None)]
        req = CatalogListRequest(category="cat", auth_type="Open", provider="prov", search="srv", tags=["t1"], show_registered_only=True, show_available_only=True, offset=0, limit=10)
        result = await service.get_catalog_servers(req, db)
        assert result.total >= 1
        assert all(s.category == "cat" for s in result.servers)


@pytest.mark.asyncio
async def test_get_catalog_servers_runtime_metadata_normalization(service):
    fake_catalog = {
        "catalog_servers": [
            "invalid-entry",
            {
                "id": "compose-entry",
                "name": "Compose",
                "url": "http://compose",
                "category": "cat",
                "auth_type": "Open",
                "provider": "prov",
                "tags": [],
                "description": "compose",
                "source": {"type": "compose", "compose_file": "services: {}", "main_service": "app"},
            },
            {
                "id": "docker-entry",
                "name": "Docker",
                "url": "http://docker",
                "category": "cat",
                "auth_type": "Open",
                "provider": "prov",
                "tags": [],
                "description": "docker",
                "source_type": "docker",
            },
            {
                "id": "github-entry",
                "name": "GitHub",
                "url": "http://github",
                "category": "cat",
                "auth_type": "Open",
                "provider": "prov",
                "tags": [],
                "description": "github",
                "source_type": "github",
            },
        ]
    }
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)), patch.object(service, "_get_registry_cache", return_value=None):
        db = MagicMock()
        db.execute.return_value = []
        req = CatalogListRequest(show_available_only=False, limit=20, offset=0)
        result = await service.get_catalog_servers(req, db)
        assert result.total == 3
        by_id = {server.id: server for server in result.servers}
        assert by_id["compose-entry"].supported_backends == ["docker"]
        assert by_id["docker-entry"].supported_backends == ["docker", "ibm_code_engine"]
        assert by_id["github-entry"].supported_backends == ["docker", "ibm_code_engine"]


@pytest.mark.asyncio
async def test_merge_remote_catalogs_skips_invalid_and_duplicates(service):
    local = {"catalog_servers": [{"id": "existing", "name": "local"}]}
    remote = {"catalog_servers": [{"id": "existing", "name": "dup"}, {"id": "new", "name": "new"}, "bad-row"]}
    with patch.object(service, "_fetch_remote_catalog", AsyncMock(return_value=remote)):
        merged = await service._merge_remote_catalogs(local, ["https://catalog.example.com"])
    ids = [item.get("id") for item in merged["catalog_servers"] if isinstance(item, dict)]
    assert ids.count("existing") == 1
    assert "new" in ids


@pytest.mark.asyncio
async def test_fetch_remote_catalog_json_list_payload(service):
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.text = '[{"id":"srv"}]'
    mock_response.json.return_value = [{"id": "srv"}]
    mock_response.raise_for_status.return_value = None

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("mcpgateway.services.catalog_service.settings", MagicMock(runtime_catalog_remote_timeout_seconds=9)), patch(
        "mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client
    ):
        result = await service._fetch_remote_catalog("https://catalog.example.com")

    assert result == {"catalog_servers": [{"id": "srv"}]}
    mock_client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_remote_catalog_yaml_servers_key(service):
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "text/yaml"}
    mock_response.text = "servers: []"
    mock_response.raise_for_status.return_value = None

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("mcpgateway.services.catalog_service.settings", MagicMock(runtime_catalog_remote_timeout_seconds=15)), patch(
        "mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client
    ), patch("mcpgateway.services.catalog_service.yaml.safe_load", return_value={"servers": [{"id": "srv2"}]}):
        result = await service._fetch_remote_catalog("https://catalog.example.com/yaml")

    assert result == {"catalog_servers": [{"id": "srv2"}]}


@pytest.mark.asyncio
async def test_fetch_remote_catalog_dict_catalog_servers_key(service):
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.text = '{"catalog_servers":[{"id":"srv3"}]}'
    mock_response.json.return_value = {"catalog_servers": [{"id": "srv3"}]}
    mock_response.raise_for_status.return_value = None

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("mcpgateway.services.catalog_service.settings", MagicMock(runtime_catalog_remote_timeout_seconds=15)), patch(
        "mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client
    ):
        result = await service._fetch_remote_catalog("https://catalog.example.com/json-dict")

    assert result == {"catalog_servers": [{"id": "srv3"}]}


@pytest.mark.asyncio
async def test_fetch_remote_catalog_unsupported_payload_raises(service):
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.text = '{"unexpected":"shape"}'
    mock_response.json.return_value = {"unexpected": "shape"}
    mock_response.raise_for_status.return_value = None

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("mcpgateway.services.catalog_service.settings", MagicMock(runtime_catalog_remote_timeout_seconds=15)), patch(
        "mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client
    ):
        with pytest.raises(ValueError, match="Unsupported remote catalog payload"):
            await service._fetch_remote_catalog("https://catalog.example.com/unsupported")


@pytest.mark.asyncio
async def test_get_catalog_servers_requires_oauth_config_unconfigured(service):
    """Test that disabled OAuth server with no oauth_config is marked as requires_oauth_config."""
    fake_catalog = {
        "catalog_servers": [
            {"id": "1", "name": "oauth-srv", "url": "http://oauth.example.com", "category": "cat", "auth_type": "OAuth2.1", "provider": "prov", "tags": [], "description": "OAuth server"},
        ]
    }
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)), \
         patch.object(service, "_get_registry_cache", return_value=None):
        db = MagicMock()
        # Disabled OAuth server with no oauth_config - needs configuration
        db.execute.return_value = [("http://oauth.example.com", False, "oauth", None)]
        req = CatalogListRequest(offset=0, limit=10)
        result = await service.get_catalog_servers(req, db)
        assert result.total == 1
        server = result.servers[0]
        assert server.is_registered is True
        assert server.requires_oauth_config is True


@pytest.mark.asyncio
async def test_get_catalog_servers_requires_oauth_config_configured(service):
    """Test that disabled OAuth server with oauth_config is NOT marked as requires_oauth_config."""
    fake_catalog = {
        "catalog_servers": [
            {"id": "2", "name": "oauth-configured", "url": "http://oauth-configured.example.com", "category": "cat", "auth_type": "OAuth2.1", "provider": "prov", "tags": [], "description": "Configured OAuth server"},
        ]
    }
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)), \
         patch.object(service, "_get_registry_cache", return_value=None):
        db = MagicMock()
        # Disabled OAuth server WITH oauth_config - manually disabled, not needing setup
        db.execute.return_value = [("http://oauth-configured.example.com", False, "oauth", {"client_id": "abc", "client_secret": "xyz"})]
        req = CatalogListRequest(offset=0, limit=10)
        result = await service.get_catalog_servers(req, db)
        assert result.total == 1
        server = result.servers[0]
        assert server.is_registered is True
        assert server.requires_oauth_config is False


@pytest.mark.asyncio
async def test_get_catalog_servers_requires_oauth_config_enabled(service):
    """Test that enabled OAuth server is NOT marked as requires_oauth_config."""
    fake_catalog = {
        "catalog_servers": [
            {"id": "3", "name": "oauth-enabled", "url": "http://oauth-enabled.example.com", "category": "cat", "auth_type": "OAuth2.1", "provider": "prov", "tags": [], "description": "Enabled OAuth server"},
        ]
    }
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)), \
         patch.object(service, "_get_registry_cache", return_value=None):
        db = MagicMock()
        # Enabled OAuth server - fully configured and active
        db.execute.return_value = [("http://oauth-enabled.example.com", True, "oauth", {"client_id": "abc"})]
        req = CatalogListRequest(offset=0, limit=10)
        result = await service.get_catalog_servers(req, db)
        assert result.total == 1
        server = result.servers[0]
        assert server.is_registered is True
        assert server.requires_oauth_config is False


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
        with patch("mcpgateway.services.catalog_service.select"), patch.object(service._gateway_service, "register_gateway", AsyncMock(side_effect=Exception("Connection refused"))):
            result = await service.register_catalog_server("1", None, db)
            assert "offline" in result.message


@pytest.mark.asyncio
async def test_check_server_availability_success(service):
    fake_catalog = {"catalog_servers": [{"id": "1", "url": "http://a"}]}
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        with patch("mcpgateway.services.http_client_service.get_http_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value.status_code = 200
            mock_get_client.return_value = mock_instance
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
        with patch("mcpgateway.services.http_client_service.get_http_client", side_effect=Exception("fail")):
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


@pytest.mark.asyncio
async def test_register_catalog_server_with_tags(service, test_db):
    """Test that catalog server registration properly handles tags.

    This test verifies the fix for the tag validation error where:
    - Catalog YAML provides tags as List[str]: ["development", "git", "version-control"]
    - GatewayCreate validator converts to List[Dict[str, str]]: [{"id": "development", "label": "development"}, ...]
    - Database stores as List[str]: ["development", "git", "version-control"]
    - GatewayRead returns as List[Dict[str, str]] for API responses
    """
    # Simulate a catalog server with tags (as they appear in mcp-catalog.yml)
    fake_catalog = {
        "catalog_servers": [
            {
                "id": "github",
                "name": "GitHub",
                "url": "https://api.githubcopilot.com/mcp",
                "description": "Version control and collaborative software development",
                "auth_type": "OAuth2.1",
                "tags": ["development", "git", "version-control", "collaboration"],  # List[str] from YAML
            }
        ]
    }

    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        # Use real database session instead of MagicMock
        # No existing gateway
        with patch("mcpgateway.services.catalog_service.select"):
            result = await service.register_catalog_server("github", None, test_db)

            # Verify registration succeeded
            assert result.success, f"Registration failed: {result.error}"
            assert "Successfully registered" in result.message

            # Verify the gateway was created with proper tags
            assert result.server_id, "Server ID should be set"

            # Query the database to verify tags were stored correctly
            # First-Party
            from mcpgateway.db import Gateway

            gateway = test_db.query(Gateway).filter_by(slug="github").first()
            assert gateway is not None, "Gateway should exist in database"

            # Verify tags are stored as List[str] in database
            assert gateway.tags == ["development", "git", "version-control", "collaboration"], "Tags should be stored as List[str]"
            assert isinstance(gateway.tags, list), "Tags should be a list"
            assert len(gateway.tags) == 4, f"Expected 4 tags, got {len(gateway.tags)}"

            # Verify all expected tags are present
            expected_tags = {"development", "git", "version-control", "collaboration"}
            assert set(gateway.tags) == expected_tags, f"Tag mismatch: expected {expected_tags}, got {set(gateway.tags)}"


@pytest.mark.asyncio
async def test_register_catalog_server_tags_validation_error_handling(service):
    """Test that invalid tags are handled gracefully during catalog registration.

    This ensures the tag validator properly filters out invalid tags while
    keeping valid ones, preventing validation errors.
    """
    fake_catalog = {
        "catalog_servers": [
            {
                "id": "test-server",
                "name": "Test Server",
                "url": "https://test.example.com/mcp",
                "description": "Test server with mixed valid/invalid tags",
                "auth_type": "Open",
                "tags": ["valid-tag", "a", "", "another-valid", "x"],  # Mix of valid and invalid
            }
        ]
    }

    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None

        captured_tags = None

        async def mock_register_gateway(db, gateway, **kwargs):
            nonlocal captured_tags
            captured_tags = gateway.tags
            return MagicMock(id="test-id", name="Test Server", tags=[])

        with patch("mcpgateway.services.catalog_service.select"), patch.object(service._gateway_service, "register_gateway", mock_register_gateway):

            result = await service.register_catalog_server("test-server", None, db)

            # Registration should succeed even with some invalid tags
            assert result.success, f"Registration failed: {result.error}"

            # Verify that only valid tags were kept (tags < 2 chars are filtered out)
            if captured_tags:
                valid_tag_ids = []
                for tag in captured_tags:
                    if isinstance(tag, dict):
                        valid_tag_ids.append(tag["id"])
                    else:
                        valid_tag_ids.append(tag)

                # Only "valid-tag" and "another-valid" should remain (min length is 2)
                assert "valid-tag" in valid_tag_ids or "another-valid" in valid_tag_ids, "At least one valid tag should be present"
                assert "a" not in valid_tag_ids, "Single-char tag 'a' should be filtered out"
                assert "x" not in valid_tag_ids, "Single-char tag 'x' should be filtered out"
                assert "" not in valid_tag_ids, "Empty tag should be filtered out"


@pytest.mark.asyncio
async def test_register_catalog_server_oauth_without_credentials(service):
    """Test that OAuth servers without credentials are registered as disabled."""
    fake_catalog = {
        "catalog_servers": [{"id": "oauth-server", "name": "OAuth Server", "url": "https://oauth.example.com/mcp", "description": "OAuth server", "auth_type": "OAuth2.1", "tags": ["oauth"]}]
    }

    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        db.commit = MagicMock()
        db.add = MagicMock()

        # Create a proper datetime for mocking
        now = datetime.now(timezone.utc)

        # Mock db.refresh to set the id and timestamps on the object
        def mock_refresh(obj):
            obj.id = "test-id"
            obj.created_at = now
            obj.updated_at = now
            obj.reachable = False

        db.refresh = MagicMock(side_effect=mock_refresh)

        with (
            patch("mcpgateway.services.catalog_service.select"),
            patch("mcpgateway.services.catalog_service.slugify", return_value="oauth-server"),
            patch("mcpgateway.services.catalog_service.validate_tags_field", return_value=[{"id": "oauth", "label": "oauth"}]),
        ):

            result = await service.register_catalog_server("oauth-server", None, db)

            # Verify OAuth server was registered successfully but requires configuration
            assert result.success, f"Registration failed: {result.error}"
            assert "OAuth configuration required" in result.message
            assert result.server_id == "test-id"
            assert result.oauth_required is True

            # Verify database operations were called
            db.add.assert_called_once()
            db.commit.assert_called_once()
            db.refresh.assert_called_once()


# ---------- Exception mapping in register_catalog_server ----------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_msg,expected_keyword",
    [
        ("SSL: CERTIFICATE_VERIFY_FAILED", "SSL certificate"),
        ("Read timed out waiting", "took too long"),
        ("401 Unauthorized access", "Authentication failed"),
        ("403 Forbidden resource", "Access forbidden"),
        ("404 Not Found endpoint", "endpoint not found"),
        ("500 Internal Server Error", "server error"),
        ("IPv6 address not supported", "IPv6"),
    ],
)
async def test_register_exception_mapping_parametrized(service, error_msg, expected_keyword):
    fake_catalog = {"catalog_servers": [{"id": "1", "name": "srv", "url": "http://a", "description": "desc"}]}
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with patch("mcpgateway.services.catalog_service.select"), patch.object(service._gateway_service, "register_gateway", AsyncMock(side_effect=Exception(error_msg))):
            result = await service.register_catalog_server("1", None, db)
            assert not result.success
            assert expected_keyword in result.message


# ---------- Transport auto-detection ----------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,expected_result",
    [
        # WebSocket URLs currently fail validation because WEBSOCKET is not a valid transport type in the schema
        # The schema only supports: SSE, HTTP, STDIO, STREAMABLEHTTP
        ("ws://localhost:9000", False),  # Fails with validation error
        ("wss://secure.example.com/mcp", False),  # Fails with validation error
        ("http://example.com/sse", "SSE"),
        ("http://example.com/path/sse/endpoint", "SSE"),
        ("http://example.com/mcp", "STREAMABLEHTTP"),
        ("http://example.com/api/", "STREAMABLEHTTP"),
        ("http://example.com/other", "SSE"),
    ],
)
async def test_transport_auto_detection(service, url, expected_result):
    fake_catalog = {"catalog_servers": [{"id": "1", "name": "srv", "url": url, "description": "desc"}]}
    captured_data = {}

    async def mock_register(db, gateway, **kwargs):
        captured_data["transport"] = gateway.transport
        return MagicMock(id=1, name="srv")

    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with patch("mcpgateway.services.catalog_service.select"), patch.object(service._gateway_service, "register_gateway", mock_register):
            result = await service.register_catalog_server("1", None, db)
            if expected_result is False:
                # WebSocket URLs should fail validation
                assert not result.success, f"Expected registration to fail for {url}"
                assert "Invalid transport type: WEBSOCKET" in result.error or "WEBSOCKET" in result.error
            else:
                # HTTP URLs should succeed
                assert result.success, f"Registration failed: {result.error}"
                assert captured_data["transport"] == expected_result, f"Expected {expected_result}, got {captured_data['transport']}"


# ---------- get_catalog_servers edge cases ----------


@pytest.mark.asyncio
async def test_get_catalog_servers_db_exception(service):
    """Test that DB exception is handled gracefully in get_catalog_servers."""
    fake_catalog = {
        "catalog_servers": [
            {"id": "1", "name": "srv1", "url": "http://a", "category": "cat", "auth_type": "Open", "provider": "prov", "tags": ["t1"], "description": "desc"},
        ]
    }
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)), patch.object(service, "_get_registry_cache", return_value=None):
        db = MagicMock()
        db.execute.side_effect = Exception("DB connection failed")
        req = CatalogListRequest(offset=0, limit=10)
        result = await service.get_catalog_servers(req, db)
        assert result.total == 1
        assert result.servers[0].is_registered is False


@pytest.mark.asyncio
async def test_get_catalog_servers_cache_hit(service):
    """Test cache hit path."""
    mock_cache = AsyncMock()
    cached_response = {
        "servers": [],
        "total": 0,
        "categories": [],
        "auth_types": [],
        "providers": [],
        "all_tags": [],
    }
    mock_cache.get = AsyncMock(return_value=cached_response)
    mock_cache.hash_filters = MagicMock(return_value="hash123")
    with patch.object(service, "_get_registry_cache", return_value=mock_cache):
        req = CatalogListRequest(offset=0, limit=10)
        result = await service.get_catalog_servers(req, MagicMock())
        assert result.total == 0
        mock_cache.get.assert_called_once()


@pytest.mark.asyncio
async def test_get_catalog_servers_cache_store_exception(service):
    """Test that cache store exception is handled gracefully."""
    fake_catalog = {
        "catalog_servers": [
            {"id": "1", "name": "srv1", "url": "http://a", "category": "cat", "auth_type": "Open", "provider": "prov", "tags": ["t1"], "description": "desc"},
        ]
    }
    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.hash_filters = MagicMock(return_value="hash123")
    mock_cache.set = AsyncMock(side_effect=Exception("Redis error"))
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)), patch.object(service, "_get_registry_cache", return_value=mock_cache):
        db = MagicMock()
        db.execute.return_value = [("http://a", True, None, None)]
        req = CatalogListRequest(offset=0, limit=10)
        result = await service.get_catalog_servers(req, db)
        assert result.total == 1


# ---------- Register with different auth types ----------


@pytest.mark.asyncio
async def test_register_with_custom_auth_type(service):
    """Test registration with unrecognized auth type falls back to authheaders."""
    fake_catalog = {"catalog_servers": [{"id": "1", "name": "srv", "url": "http://a", "description": "desc", "auth_type": "Custom"}]}
    req = CatalogServerRegisterRequest(server_id="1", name="srv", api_key="mykey", oauth_credentials=None)
    captured_data = {}

    async def mock_register(db, gateway, **kwargs):
        captured_data["auth_type"] = gateway.auth_type
        return MagicMock(id=1, name="srv")

    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with patch("mcpgateway.services.catalog_service.select"), patch.object(service._gateway_service, "register_gateway", mock_register):
            result = await service.register_catalog_server("1", req, db)
            assert result.success
            assert captured_data["auth_type"] == "authheaders"


@pytest.mark.asyncio
async def test_register_with_explicit_transport(service):
    """Test that explicit transport in catalog data takes priority."""
    fake_catalog = {"catalog_servers": [{"id": "1", "name": "srv", "url": "http://a/sse", "description": "desc", "transport": "STREAMABLEHTTP"}]}
    captured_data = {}

    async def mock_register(db, gateway, **kwargs):
        captured_data["transport"] = gateway.transport
        return MagicMock(id=1, name="srv")

    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with patch("mcpgateway.services.catalog_service.select"), patch.object(service._gateway_service, "register_gateway", mock_register):
            result = await service.register_catalog_server("1", None, db)
            assert result.success
            assert captured_data["transport"] == "STREAMABLEHTTP"


@pytest.mark.asyncio
async def test_register_with_tool_count(service):
    """Test message includes discovered tools count."""
    fake_catalog = {"catalog_servers": [{"id": "1", "name": "srv", "url": "http://a", "description": "desc"}]}
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        mock_tools = [MagicMock(), MagicMock(), MagicMock()]
        db.execute.return_value.scalars.return_value.all.return_value = mock_tools
        with patch("mcpgateway.services.catalog_service.select"), patch.object(service._gateway_service, "register_gateway", AsyncMock(return_value=MagicMock(id=1, name="srv"))):
            result = await service.register_catalog_server("1", None, db)
            assert result.success
            assert "3 tools" in result.message


@pytest.mark.asyncio
async def test_register_check_existing_exception(service):
    """Test graceful handling when checking existing registration fails."""
    fake_catalog = {"catalog_servers": [{"id": "1", "name": "srv", "url": "http://a", "description": "desc"}]}
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.side_effect = Exception("DB error")
        with patch("mcpgateway.services.catalog_service.select"), patch.object(service._gateway_service, "register_gateway", AsyncMock(return_value=MagicMock(id=1, name="srv"))):
            result = await service.register_catalog_server("1", None, db)
            assert result.success


@pytest.mark.asyncio
async def test_bulk_register_exception_per_server(service):
    """Test bulk register when individual server raises exception."""
    fake_request = CatalogBulkRegisterRequest(server_ids=["1", "2"], skip_errors=True)
    with patch.object(service, "register_catalog_server", AsyncMock(side_effect=[Exception("boom"), MagicMock(success=True)])):
        db = MagicMock()
        result = await service.bulk_register_servers(fake_request, db)
        assert result.total_attempted == 2
        assert len(result.failed) == 1
        assert result.total_successful == 1


@pytest.mark.asyncio
async def test_load_catalog_relative_path_falls_back_to_repo_root(service, tmp_path, monkeypatch):
    """Relative catalog file missing in cwd should fall back to repo root (branches 67-85)."""
    monkeypatch.chdir(tmp_path)
    with patch("mcpgateway.services.catalog_service.settings", MagicMock(mcpgateway_catalog_file="mcp-catalog.yml", mcpgateway_catalog_cache_ttl=0)):
        result = await service.load_catalog(force_reload=True)
    assert "catalog_servers" in result
    assert service._catalog_cache is result


def test_get_registry_cache_importerror_returns_none(service):
    """ImportError in registry cache path returns None (lines 102-103)."""
    with patch("mcpgateway.cache.registry_cache.get_registry_cache", side_effect=ImportError):
        assert service._get_registry_cache() is None


@pytest.mark.asyncio
async def test_get_catalog_servers_empty_servers_no_available_filter(service):
    """Cover branches for empty catalog and show_available_only=False (lines 138, 199)."""
    with patch.object(service, "load_catalog", AsyncMock(return_value={"catalog_servers": []})), patch.object(service, "_get_registry_cache", return_value=None):
        req = CatalogListRequest(offset=0, limit=10, show_available_only=False)
        result = await service.get_catalog_servers(req, MagicMock())
    assert result.total == 0


@pytest.mark.asyncio
async def test_register_catalog_server_match_not_first_skips_tool_query_and_cache(service):
    """Server found after first loop iteration; gateway_read.id can be falsy (branches 245, 426, 438)."""
    fake_catalog = {
        "catalog_servers": [
            {"id": "other", "name": "other", "url": "http://other", "description": "desc"},
            {"id": "target", "name": "srv", "url": "http://a", "description": "desc"},
        ]
    }
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)), patch.object(service, "_get_registry_cache", return_value=None):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with patch("mcpgateway.services.catalog_service.select"), patch.object(service._gateway_service, "register_gateway", AsyncMock(return_value=MagicMock(id=None, name="srv"))):
            result = await service.register_catalog_server("target", None, db)
    assert result.success


@pytest.mark.asyncio
async def test_register_catalog_server_oauth_without_credentials_tags_dict_format(service):
    """OAuth no-credentials path should pass through dict tags (line 368)."""
    fake_catalog = {
        "catalog_servers": [
            {
                "id": "oauth-server",
                "name": "OAuth Server",
                "url": "https://oauth.example.com/mcp",
                "description": "OAuth server",
                "auth_type": "OAuth2.1",
                "tags": [{"id": "oauth", "label": "oauth"}],
            }
        ]
    }

    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)), patch.object(service, "_get_registry_cache", return_value=None):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        db.commit = MagicMock()
        db.add = MagicMock()

        now = datetime.now(timezone.utc)

        def mock_refresh(obj):
            obj.id = "test-id"
            obj.created_at = now
            obj.updated_at = now
            obj.reachable = False

        db.refresh = MagicMock(side_effect=mock_refresh)

        with patch("mcpgateway.services.catalog_service.select"), patch("mcpgateway.services.catalog_service.slugify", return_value="oauth-server"):
            result = await service.register_catalog_server("oauth-server", None, db)

    assert result.success
    assert result.oauth_required is True


@pytest.mark.asyncio
async def test_register_catalog_server_oauth_without_credentials_tags_empty(service):
    """OAuth no-credentials path with empty tags should produce [] (line 370)."""
    fake_catalog = {
        "catalog_servers": [
            {
                "id": "oauth-server",
                "name": "OAuth Server",
                "url": "https://oauth.example.com/mcp",
                "description": "OAuth server",
                "auth_type": "OAuth2.1",
                "tags": [],
            }
        ]
    }

    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)), patch.object(service, "_get_registry_cache", return_value=None):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        db.commit = MagicMock()
        db.add = MagicMock()

        now = datetime.now(timezone.utc)

        def mock_refresh(obj):
            obj.id = "test-id"
            obj.created_at = now
            obj.updated_at = now
            obj.reachable = False

        db.refresh = MagicMock(side_effect=mock_refresh)

        with patch("mcpgateway.services.catalog_service.select"), patch("mcpgateway.services.catalog_service.slugify", return_value="oauth-server"):
            result = await service.register_catalog_server("oauth-server", None, db)

    assert result.success
    assert result.oauth_required is True


@pytest.mark.asyncio
async def test_check_server_availability_match_not_first(service):
    """Server id match later in list should still succeed (branch 488->487)."""
    fake_catalog = {"catalog_servers": [{"id": "other", "url": "http://other"}, {"id": "1", "url": "http://a"}]}
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)):
        with patch("mcpgateway.services.http_client_service.get_http_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value.status_code = 200
            mock_get_client.return_value = mock_instance
            result = await service.check_server_availability("1")
    assert result.is_available


@pytest.mark.asyncio
async def test_check_server_availability_outer_exception(service):
    """Exceptions outside the inner HTTP check fall into the outer handler (lines 521-523)."""
    with patch.object(service, "load_catalog", AsyncMock(side_effect=RuntimeError("catalog fail"))):
        result = await service.check_server_availability("1")
    assert result.is_available is False
    assert "catalog fail" in (result.error or "")


@pytest.mark.asyncio
async def test_bulk_register_breaks_on_exception_when_not_skipping_errors(service):
    """When a per-server call raises and skip_errors=False, loop breaks (line 554)."""
    fake_request = CatalogBulkRegisterRequest(server_ids=["1", "2"], skip_errors=False)
    with patch.object(service, "register_catalog_server", AsyncMock(side_effect=Exception("boom"))):
        db = MagicMock()
        result = await service.bulk_register_servers(fake_request, db)
    assert result.failed and result.failed[0]["error"] == "boom"


@pytest.mark.asyncio
async def test_get_catalog_servers_filter_by_source_and_backend(service):
    """Catalog listing supports source_type and supported_backends filtering."""
    fake_catalog = {
        "catalog_servers": [
            {
                "id": "docker-entry",
                "name": "Docker Entry",
                "url": "http://docker.local/mcp",
                "category": "cat",
                "auth_type": "Open",
                "provider": "prov",
                "tags": ["runtime"],
                "description": "docker runtime",
                "source_type": "docker",
                "supported_backends": ["docker", "ibm_code_engine"],
            },
            {
                "id": "compose-entry",
                "name": "Compose Entry",
                "url": "http://compose.local/mcp",
                "category": "cat",
                "auth_type": "Open",
                "provider": "prov",
                "tags": ["runtime"],
                "description": "compose runtime",
                "source_type": "compose",
                "supported_backends": ["docker"],
            },
        ]
    }
    with patch.object(service, "load_catalog", AsyncMock(return_value=fake_catalog)), patch.object(service, "_get_registry_cache", return_value=None):
        db = MagicMock()
        db.execute.return_value = []
        req = CatalogListRequest(source_type="compose", supported_backends=["docker"], show_available_only=False, offset=0, limit=10)
        result = await service.get_catalog_servers(req, db)
        assert result.total == 1
        assert result.servers[0].id == "compose-entry"
        assert "docker" in result.supported_backends
        assert "compose" in result.source_types


@pytest.mark.asyncio
async def test_load_catalog_merges_remote_catalog(service):
    """Remote catalog URLs should be merged with local catalog entries."""
    local_catalog = {
        "catalog_servers": [
            {"id": "local", "name": "Local", "url": "http://local", "category": "cat", "auth_type": "Open", "provider": "prov", "description": "local"},
        ]
    }
    remote_catalog = {
        "catalog_servers": [
            {"id": "remote", "name": "Remote", "url": "http://remote", "category": "cat", "auth_type": "Open", "provider": "prov", "description": "remote"},
        ]
    }
    with patch("mcpgateway.services.catalog_service.settings", MagicMock(mcpgateway_catalog_file="catalog.yml", mcpgateway_catalog_cache_ttl=0, runtime_catalog_remote_urls=["https://example.com/catalog.yaml"])):
        with patch("mcpgateway.services.catalog_service.Path.exists", return_value=True), patch(
            "mcpgateway.services.catalog_service.asyncio.to_thread", AsyncMock(return_value="catalog")
        ), patch("mcpgateway.services.catalog_service.yaml.safe_load", return_value=local_catalog), patch.object(service, "_fetch_remote_catalog", AsyncMock(return_value=remote_catalog)):
            result = await service.load_catalog(force_reload=True)
            ids = {s["id"] for s in result["catalog_servers"]}
            assert ids == {"local", "remote"}
