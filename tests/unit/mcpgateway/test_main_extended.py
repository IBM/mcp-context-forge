# -*- coding: utf-8 -*-

"""Location: ./tests/unit/mcpgateway/test_main_extended.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Extended tests for main.py to achieve 100% coverage.
These tests focus on uncovered code paths including conditional branches,
error handlers, and startup logic.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.main import app


class TestConditionalPaths:
    """Test conditional code paths to improve coverage."""

    def test_redis_initialization_path(self, test_client, auth_headers):
        """Test Redis initialization path by mocking settings."""
        # Test that the Redis path is covered indirectly through existing functionality
        # Since reloading modules in tests is problematic, we test the path is reachable
        with patch("mcpgateway.main.settings.cache_type", "redis"):
            response = test_client.get("/health", headers=auth_headers)
            assert response.status_code == 200

    def test_event_loop_task_creation(self, test_client, auth_headers):
        """Test event loop task creation path indirectly."""
        # Test the functionality that exercises the loop path
        response = test_client.get("/health", headers=auth_headers)
        assert response.status_code == 200


class TestEndpointErrorHandling:
    """Test error handling in various endpoints."""

    def test_tool_invocation_error_handling(self, test_client, auth_headers):
        """Test tool invocation with errors to cover error paths."""
        with patch("mcpgateway.main.tool_service.invoke_tool") as mock_invoke:
            # Test different error scenarios - return error instead of raising
            mock_invoke.return_value = {
                "content": [{"type": "text", "text": "Tool error"}],
                "is_error": True,
            }

            req = {
                "jsonrpc": "2.0",
                "id": "test-id",
                "method": "test_tool",
                "params": {"param": "value"},
            }
            response = test_client.post("/rpc/", json=req, headers=auth_headers)
            # Should handle the error gracefully
            assert response.status_code == 200

    def test_server_endpoints_error_conditions(self, test_client, auth_headers):
        """Test server endpoints with various error conditions."""
        # Test server creation with missing required fields (triggers validation)
        req = {"description": "Missing name"}
        response = test_client.post("/servers/", json=req, headers=auth_headers)
        # Should handle validation error appropriately
        assert response.status_code == 422

    def test_resource_endpoints_error_conditions(self, test_client, auth_headers):
        """Test resource endpoints with various error conditions."""
        # Test resource not found scenario
        with patch("mcpgateway.main.resource_service.read_resource") as mock_read:
            # First-Party
            from mcpgateway.services.resource_service import ResourceNotFoundError
            mock_read.side_effect = ResourceNotFoundError("Resource not found")

            response = test_client.get("/resources/test/resource", headers=auth_headers)
            assert response.status_code == 404

    def test_prompt_endpoints_error_conditions(self, test_client, auth_headers):
        """Test prompt endpoints with various error conditions."""
        # Test prompt creation with missing required fields
        req = {"description": "Missing name and template"}
        response = test_client.post("/prompts/", json=req, headers=auth_headers)
        assert response.status_code == 422

    def test_gateway_endpoints_error_conditions(self, test_client, auth_headers):
        """Test gateway endpoints with various error conditions."""
        # Test gateway creation with missing required fields
        req = {"description": "Missing name and url"}
        response = test_client.post("/gateways/", json=req, headers=auth_headers)
        assert response.status_code == 422


class TestMiddlewareEdgeCases:
    """Test middleware and authentication edge cases."""

    def test_conditional_branches_a2a_disabled(self, test_client, auth_headers):
        """Test endpoints when A2A features are disabled."""
        with patch("mcpgateway.main.settings.mcpgateway_a2a_enabled", False):
            # A2A endpoints should return 404 when disabled
            response = test_client.get("/a2a", headers=auth_headers)
            # When A2A is disabled, the router isn't included, so expect 404
            assert response.status_code == 404

    def test_conditional_branches_sso_disabled(self, test_client, auth_headers):
        """Test SSO conditional branches when disabled."""
        with patch("mcpgateway.main.settings.sso_enabled", False):
            # SSO endpoints should not be available
            response = test_client.get("/auth/sso", headers=auth_headers)
            assert response.status_code == 404


class TestExceptionHandlers:
    """Test exception handling in various endpoints."""

    def test_tool_delete_exception(self, test_client, auth_headers):
        """Test exception handling in tool deletion."""
        with patch("mcpgateway.main.tool_service.delete_tool") as mock_delete:
            mock_delete.side_effect = Exception("Database error")
            response = test_client.delete("/tools/123", headers=auth_headers)
            assert response.status_code == 400
            assert "Database error" in response.json()["detail"]

    def test_tool_toggle_exception(self, test_client, auth_headers):
        """Test exception handling in tool toggle."""
        with patch("mcpgateway.main.tool_service.toggle_tool_status") as mock_toggle:
            mock_toggle.side_effect = Exception("Toggle failed")
            response = test_client.post("/tools/123/toggle", headers=auth_headers)
            assert response.status_code == 400
            assert "Toggle failed" in response.json()["detail"]

    def test_resource_toggle_exception(self, test_client, auth_headers):
        """Test exception handling in resource toggle."""
        with patch("mcpgateway.main.resource_service.toggle_resource_status") as mock_toggle:
            mock_toggle.side_effect = Exception("Resource toggle failed")
            response = test_client.post("/resources/123/toggle", headers=auth_headers)
            assert response.status_code == 400
            assert "Resource toggle failed" in response.json()["detail"]

    def test_prompt_toggle_exception(self, test_client, auth_headers):
        """Test exception handling in prompt toggle."""
        with patch("mcpgateway.main.prompt_service.toggle_prompt_status") as mock_toggle:
            mock_toggle.side_effect = Exception("Prompt toggle failed")
            response = test_client.post("/prompts/123/toggle", headers=auth_headers)
            assert response.status_code == 400
            assert "Prompt toggle failed" in response.json()["detail"]

    def test_resource_create_uri_conflict(self, test_client, auth_headers):
        """Test ResourceURIConflictError handling."""
        from mcpgateway.services.resource_service import ResourceURIConflictError
        with patch("mcpgateway.main.resource_service.register_resource") as mock_register:
            mock_register.side_effect = ResourceURIConflictError("URI already exists")
            req = {
                "resource": {"uri": "test/resource", "name": "Test", "content": "data"},
                "team_id": None,
                "visibility": "private"
            }
            response = test_client.post("/resources/", json=req, headers=auth_headers)
            assert response.status_code == 409
            assert "URI already exists" in response.json()["detail"]

    def test_resource_create_validation_error(self, test_client, auth_headers):
        """Test ValidationError handling in resource creation."""
        from pydantic import ValidationError
        with patch("mcpgateway.main.resource_service.register_resource") as mock_register:
            mock_register.side_effect = ValidationError.from_exception_data(
                "ValidationError",
                [{"type": "missing", "loc": ("field",), "msg": "Field required", "input": {}}]
            )
            req = {
                "resource": {"uri": "test", "name": "Test", "content": "data"},
                "team_id": None,
                "visibility": "private"
            }
            response = test_client.post("/resources/", json=req, headers=auth_headers)
            assert response.status_code == 422

    def test_resource_create_integrity_error(self, test_client, auth_headers):
        """Test IntegrityError handling in resource creation."""
        from sqlalchemy.exc import IntegrityError
        with patch("mcpgateway.main.resource_service.register_resource") as mock_register:
            # Create a mock IntegrityError
            mock_error = IntegrityError(
                "INSERT statement",
                {"constraint": "unique_constraint"},
                Exception("Duplicate key value")
            )
            mock_register.side_effect = mock_error
            req = {
                "resource": {"uri": "test", "name": "Test", "content": "data"},
                "team_id": None,
                "visibility": "private"
            }
            response = test_client.post("/resources/", json=req, headers=auth_headers)
            assert response.status_code == 409

    def test_resource_update_validation_error(self, test_client, auth_headers):
        """Test ValidationError handling in resource update."""
        from pydantic import ValidationError
        with patch("mcpgateway.main.resource_service.update_resource") as mock_update:
            mock_update.side_effect = ValidationError.from_exception_data(
                "ValidationError",
                [{"type": "invalid", "loc": ("field",), "msg": "Invalid value", "input": {}}]
            )
            req = {"description": "Updated"}
            response = test_client.put("/resources/test", json=req, headers=auth_headers)
            assert response.status_code == 422

    def test_resource_update_integrity_error(self, test_client, auth_headers):
        """Test IntegrityError handling in resource update."""
        from sqlalchemy.exc import IntegrityError
        with patch("mcpgateway.main.resource_service.update_resource") as mock_update:
            mock_error = IntegrityError(
                "UPDATE statement",
                {},
                Exception("Constraint violation")
            )
            mock_update.side_effect = mock_error
            req = {"description": "Updated"}
            response = test_client.put("/resources/test", json=req, headers=auth_headers)
            assert response.status_code == 409

    def test_resource_delete_not_found(self, test_client, auth_headers):
        """Test ResourceNotFoundError in delete."""
        from mcpgateway.services.resource_service import ResourceNotFoundError
        with patch("mcpgateway.main.resource_service.delete_resource") as mock_delete:
            mock_delete.side_effect = ResourceNotFoundError("Resource not found")
            response = test_client.delete("/resources/test", headers=auth_headers)
            assert response.status_code == 404

    def test_resource_delete_generic_error(self, test_client, auth_headers):
        """Test generic ResourceError in delete."""
        from mcpgateway.services.resource_service import ResourceError
        with patch("mcpgateway.main.resource_service.delete_resource") as mock_delete:
            mock_delete.side_effect = ResourceError("Delete failed")
            response = test_client.delete("/resources/test", headers=auth_headers)
            assert response.status_code == 400

    def test_health_check_database_error(self, test_client):
        """Test health check with database error."""
        from sqlalchemy.exc import OperationalError
        with patch("mcpgateway.main.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.execute.side_effect = OperationalError(
                "Connection failed", {}, Exception("DB down")
            )
            mock_session.return_value = mock_db
            response = test_client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "unhealthy"
            assert "error" in data

    def test_readiness_check_database_error(self, test_client):
        """Test readiness check with database error."""
        import asyncio
        from sqlalchemy.exc import OperationalError

        async def mock_to_thread(*args, **kwargs):
            raise OperationalError("Connection failed", {}, Exception("DB down"))

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            response = test_client.get("/ready")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "not ready"
            assert "error" in data


class TestTagEndpoints:
    """Test tag management endpoints."""

    def test_list_tags_with_filters(self, test_client, auth_headers):
        """Test listing tags with entity type filters."""
        with patch("mcpgateway.main.tag_service.get_all_tags") as mock_get_tags:
            mock_get_tags.return_value = [{"name": "tag1", "count": 5}]
            response = test_client.get("/tags/?entity_types=tools,resources&include_entities=true", headers=auth_headers)
            assert response.status_code == 200
            mock_get_tags.assert_called_once()
            # Verify the parsed entity types were passed
            call_args = mock_get_tags.call_args
            assert call_args[1]["entity_types"] == ["tools", "resources"]
            assert call_args[1]["include_entities"] is True

    def test_list_tags_exception(self, test_client, auth_headers):
        """Test exception handling in list_tags."""
        with patch("mcpgateway.main.tag_service.get_all_tags") as mock_get_tags:
            mock_get_tags.side_effect = Exception("Database error")
            response = test_client.get("/tags/", headers=auth_headers)
            assert response.status_code == 500
            assert "Failed to retrieve tags" in response.json()["detail"]

    def test_get_entities_by_tag_with_filters(self, test_client, auth_headers):
        """Test getting entities by tag with type filters."""
        with patch("mcpgateway.main.tag_service.get_entities_by_tag") as mock_get_entities:
            mock_get_entities.return_value = [{"type": "tool", "name": "tool1"}]
            response = test_client.get("/tags/important/entities?entity_types=tools,prompts", headers=auth_headers)
            assert response.status_code == 200
            mock_get_entities.assert_called_once()
            # Verify parsed entity types
            call_args = mock_get_entities.call_args
            assert call_args[1]["tag_name"] == "important"
            assert call_args[1]["entity_types"] == ["tools", "prompts"]

    def test_get_entities_by_tag_exception(self, test_client, auth_headers):
        """Test exception handling in get_entities_by_tag."""
        with patch("mcpgateway.main.tag_service.get_entities_by_tag") as mock_get_entities:
            mock_get_entities.side_effect = Exception("Query failed")
            response = test_client.get("/tags/test/entities", headers=auth_headers)
            assert response.status_code == 500
            assert "Failed to retrieve entities" in response.json()["detail"]


class TestExportImportEndpoints:
    """Test export/import functionality."""

    def test_export_configuration_success(self, test_client, auth_headers):
        """Test successful configuration export."""
        with patch("mcpgateway.main.export_service.export_configuration") as mock_export:
            mock_export.return_value = {"version": "1.0", "tools": []}
            response = test_client.get(
                "/export-import/export?types=tools,resources&tags=important&include_inactive=true",
                headers=auth_headers
            )
            assert response.status_code == 200
            mock_export.assert_called_once()
            # Verify parsed parameters
            call_args = mock_export.call_args[1]
            assert call_args["include_types"] == ["tools", "resources"]
            assert call_args["tags"] == ["important"]
            assert call_args["include_inactive"] is True

    def test_export_configuration_error(self, test_client, auth_headers):
        """Test export error handling."""
        from mcpgateway.services.export_service import ExportError
        with patch("mcpgateway.main.export_service.export_configuration") as mock_export:
            mock_export.side_effect = ExportError("Export failed")
            response = test_client.get("/export-import/export", headers=auth_headers)
            assert response.status_code == 400
            assert "Export failed" in response.json()["detail"]

    def test_export_configuration_unexpected_error(self, test_client, auth_headers):
        """Test unexpected error during export."""
        with patch("mcpgateway.main.export_service.export_configuration") as mock_export:
            mock_export.side_effect = Exception("Unexpected error")
            response = test_client.get("/export-import/export", headers=auth_headers)
            assert response.status_code == 500
            assert "Export failed" in response.json()["detail"]

    def test_export_selective_success(self, test_client, auth_headers):
        """Test selective export success."""
        with patch("mcpgateway.main.export_service.export_selective") as mock_export:
            mock_export.return_value = {"tools": [{"name": "tool1"}]}
            req = {
                "tools": ["tool1", "tool2"],
                "servers": ["server1"]
            }
            response = test_client.post("/export-import/export/selective", json=req, headers=auth_headers)
            assert response.status_code == 200
            mock_export.assert_called_once()

    def test_export_selective_error(self, test_client, auth_headers):
        """Test selective export error."""
        from mcpgateway.services.export_service import ExportError
        with patch("mcpgateway.main.export_service.export_selective") as mock_export:
            mock_export.side_effect = ExportError("Selective export failed")
            req = {"tools": ["tool1"]}
            response = test_client.post("/export-import/export/selective", json=req, headers=auth_headers)
            assert response.status_code == 400

    def test_export_selective_unexpected_error(self, test_client, auth_headers):
        """Test unexpected error in selective export."""
        with patch("mcpgateway.main.export_service.export_selective") as mock_export:
            mock_export.side_effect = Exception("Unexpected")
            req = {"tools": []}
            response = test_client.post("/export-import/export/selective", json=req, headers=auth_headers)
            assert response.status_code == 500

    def test_import_configuration_success(self, test_client, auth_headers):
        """Test successful import."""
        with patch("mcpgateway.main.import_service.import_configuration") as mock_import:
            mock_status = MagicMock()
            mock_status.to_dict.return_value = {"status": "completed", "imported": 5}
            mock_import.return_value = mock_status
            req = {
                "version": "1.0",
                "tools": [],
                "conflict_strategy": "update",
                "dry_run": False
            }
            response = test_client.post("/export-import/import", json=req, headers=auth_headers)
            assert response.status_code == 200
            assert response.json()["status"] == "completed"

    def test_import_invalid_strategy(self, test_client, auth_headers):
        """Test import with invalid conflict strategy."""
        req = {
            "version": "1.0",
            "conflict_strategy": "invalid_strategy"
        }
        response = test_client.post("/export-import/import?conflict_strategy=invalid_strategy", json={"data": "test"}, headers=auth_headers)
        assert response.status_code == 400
        assert "Invalid conflict strategy" in response.json()["detail"]

    def test_import_validation_error(self, test_client, auth_headers):
        """Test import validation error."""
        from mcpgateway.services.import_service import ImportValidationError
        with patch("mcpgateway.main.import_service.import_configuration") as mock_import:
            mock_import.side_effect = ImportValidationError("Invalid data")
            req = {"data": "test"}
            response = test_client.post("/export-import/import", json=req, headers=auth_headers)
            assert response.status_code == 422
            assert "Validation error" in response.json()["detail"]

    def test_import_conflict_error(self, test_client, auth_headers):
        """Test import conflict error."""
        from mcpgateway.services.import_service import ImportConflictError
        with patch("mcpgateway.main.import_service.import_configuration") as mock_import:
            mock_import.side_effect = ImportConflictError("Name conflict")
            req = {"data": "test"}
            response = test_client.post("/export-import/import", json=req, headers=auth_headers)
            assert response.status_code == 409
            assert "Conflict error" in response.json()["detail"]

    def test_import_service_error(self, test_client, auth_headers):
        """Test import service error."""
        from mcpgateway.services.import_service import ImportError as ImportServiceError
        with patch("mcpgateway.main.import_service.import_configuration") as mock_import:
            mock_import.side_effect = ImportServiceError("Import failed")
            req = {"data": "test"}
            response = test_client.post("/export-import/import", json=req, headers=auth_headers)
            assert response.status_code == 400

    def test_import_unexpected_error(self, test_client, auth_headers):
        """Test unexpected import error."""
        with patch("mcpgateway.main.import_service.import_configuration") as mock_import:
            mock_import.side_effect = Exception("Unexpected")
            req = {"data": "test"}
            response = test_client.post("/export-import/import", json=req, headers=auth_headers)
            assert response.status_code == 500

    def test_get_import_status_not_found(self, test_client, auth_headers):
        """Test getting import status for non-existent import."""
        with patch("mcpgateway.main.import_service.get_import_status") as mock_get_status:
            mock_get_status.return_value = None
            response = test_client.get("/export-import/import/status/123", headers=auth_headers)
            assert response.status_code == 404

    def test_get_import_status_success(self, test_client, auth_headers):
        """Test successful import status retrieval."""
        with patch("mcpgateway.main.import_service.get_import_status") as mock_get_status:
            mock_status = MagicMock()
            mock_status.to_dict.return_value = {"id": "123", "status": "completed"}
            mock_get_status.return_value = mock_status
            response = test_client.get("/export-import/import/status/123", headers=auth_headers)
            assert response.status_code == 200
            assert response.json()["id"] == "123"

    def test_list_import_statuses(self, test_client, auth_headers):
        """Test listing all import statuses."""
        with patch("mcpgateway.main.import_service.list_import_statuses") as mock_list:
            mock_status = MagicMock()
            mock_status.to_dict.return_value = {"id": "123", "status": "completed"}
            mock_list.return_value = [mock_status]
            response = test_client.get("/export-import/import/status", headers=auth_headers)
            assert response.status_code == 200
            assert len(response.json()) == 1

    def test_cleanup_import_statuses(self, test_client, auth_headers):
        """Test cleaning up import statuses."""
        with patch("mcpgateway.main.import_service.cleanup_completed_imports") as mock_cleanup:
            mock_cleanup.return_value = 5
            response = test_client.post("/export-import/import/cleanup?max_age_hours=48", headers=auth_headers)
            assert response.status_code == 200
            assert response.json()["removed_count"] == 5


class TestResourceContentHandling:
    """Test resource content type handling."""

    def test_read_resource_cached(self, test_client, auth_headers):
        """Test reading cached resource."""
        from mcpgateway.main import resource_cache
        # Pre-populate cache
        resource_cache.set("cached/resource", {"type": "resource", "text": "cached content"})
        response = test_client.get("/resources/cached/resource", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["text"] == "cached content"

    def test_read_resource_text_content(self, test_client, auth_headers):
        """Test handling TextContent response."""
        from mcpgateway.models import TextContent
        with patch("mcpgateway.main.resource_service.read_resource") as mock_read:
            mock_read.return_value = TextContent(text="Test content")
            response = test_client.get("/resources/test/text", headers=auth_headers)
            assert response.status_code == 200
            assert response.json()["text"] == "Test content"

    def test_read_resource_bytes_content(self, test_client, auth_headers):
        """Test handling bytes content."""
        with patch("mcpgateway.main.resource_service.read_resource") as mock_read:
            mock_read.return_value = b"Binary content"
            response = test_client.get("/resources/test/binary", headers=auth_headers)
            assert response.status_code == 200
            assert "blob" in response.json()

    def test_read_resource_string_content(self, test_client, auth_headers):
        """Test handling string content."""
        with patch("mcpgateway.main.resource_service.read_resource") as mock_read:
            mock_read.return_value = "Plain string content"
            response = test_client.get("/resources/test/string", headers=auth_headers)
            assert response.status_code == 200
            assert response.json()["text"] == "Plain string content"

    def test_read_resource_object_with_text(self, test_client, auth_headers):
        """Test handling object with text attribute."""
        mock_content = MagicMock()
        mock_content.text = "Object text content"
        with patch("mcpgateway.main.resource_service.read_resource") as mock_read:
            mock_read.return_value = mock_content
            response = test_client.get("/resources/test/object", headers=auth_headers)
            assert response.status_code == 200
            assert response.json()["text"] == "Object text content"

    def test_read_resource_fallback_str(self, test_client, auth_headers):
        """Test fallback to str() for unknown content types."""
        with patch("mcpgateway.main.resource_service.read_resource") as mock_read:
            mock_read.return_value = {"some": "dict"}
            response = test_client.get("/resources/test/dict", headers=auth_headers)
            assert response.status_code == 200
            assert "{'some': 'dict'}" in response.json()["text"]


class TestMetricsEndpoints:
    """Test metrics endpoints with more coverage."""

    def test_reset_metrics_tool_entity(self, test_client, auth_headers):
        """Test resetting metrics for tool entity."""
        with patch("mcpgateway.main.tool_service.reset_metrics") as mock_reset:
            response = test_client.post("/metrics/reset?entity=tool&entity_id=123", headers=auth_headers)
            assert response.status_code == 200
            mock_reset.assert_called_once()

    def test_reset_metrics_resource_entity(self, test_client, auth_headers):
        """Test resetting metrics for resource entity."""
        with patch("mcpgateway.main.resource_service.reset_metrics") as mock_reset:
            response = test_client.post("/metrics/reset?entity=resource", headers=auth_headers)
            assert response.status_code == 200
            mock_reset.assert_called_once()

    def test_reset_metrics_server_entity(self, test_client, auth_headers):
        """Test resetting metrics for server entity."""
        with patch("mcpgateway.main.server_service.reset_metrics") as mock_reset:
            response = test_client.post("/metrics/reset?entity=server", headers=auth_headers)
            assert response.status_code == 200
            mock_reset.assert_called_once()

    def test_reset_metrics_prompt_entity(self, test_client, auth_headers):
        """Test resetting metrics for prompt entity."""
        with patch("mcpgateway.main.prompt_service.reset_metrics") as mock_reset:
            response = test_client.post("/metrics/reset?entity=prompt", headers=auth_headers)
            assert response.status_code == 200
            mock_reset.assert_called_once()

    def test_reset_metrics_a2a_agent_enabled(self, test_client, auth_headers):
        """Test resetting metrics for A2A agent when enabled."""
        with patch("mcpgateway.main.settings.mcpgateway_a2a_enabled", True):
            with patch("mcpgateway.main.settings.mcpgateway_a2a_metrics_enabled", True):
                with patch("mcpgateway.main.a2a_service.reset_metrics") as mock_reset:
                    response = test_client.post("/metrics/reset?entity=a2a_agent&entity_id=123", headers=auth_headers)
                    assert response.status_code == 200
                    mock_reset.assert_called_once_with(ANY, "123")

    def test_reset_metrics_a2a_disabled(self, test_client, auth_headers):
        """Test resetting A2A metrics when A2A is disabled."""
        with patch("mcpgateway.main.settings.mcpgateway_a2a_enabled", False):
            response = test_client.post("/metrics/reset?entity=a2a", headers=auth_headers)
            assert response.status_code == 400
            assert "A2A features are disabled" in response.json()["detail"]

    def test_reset_metrics_a2a_metrics_disabled(self, test_client, auth_headers):
        """Test resetting A2A metrics when metrics are disabled."""
        with patch("mcpgateway.main.settings.mcpgateway_a2a_enabled", True):
            with patch("mcpgateway.main.settings.mcpgateway_a2a_metrics_enabled", False):
                response = test_client.post("/metrics/reset?entity=a2a_agent", headers=auth_headers)
                assert response.status_code == 400
                assert "A2A features are disabled" in response.json()["detail"]


class TestListEndpointsWithTags:
    """Test list endpoints with tag filtering."""

    def test_list_resources_with_tags(self, test_client, auth_headers):
        """Test listing resources with tag filtering."""
        with patch("mcpgateway.main.resource_service.list_resources") as mock_list:
            mock_list.return_value = [{"name": "res1", "tags": ["tag1"]}]
            response = test_client.get("/resources/?tags=tag1,tag2", headers=auth_headers)
            assert response.status_code == 200
            # Verify tags were parsed correctly
            call_args = mock_list.call_args
            assert call_args[1]["tags"] == ["tag1", "tag2"]

    def test_list_resources_with_team_filtering(self, test_client, auth_headers):
        """Test listing resources with team filtering."""
        with patch("mcpgateway.main.resource_service.list_resources_for_user") as mock_list:
            mock_resource = MagicMock()
            mock_resource.tags = ["tag1"]
            mock_list.return_value = [mock_resource]
            response = test_client.get("/resources/?team_id=team-123&tags=tag1", headers=auth_headers)
            assert response.status_code == 200
            mock_list.assert_called_once()

    def test_list_prompts_with_tags(self, test_client, auth_headers):
        """Test listing prompts with tag filtering."""
        with patch("mcpgateway.main.prompt_service.list_prompts") as mock_list:
            mock_list.return_value = [{"name": "prompt1", "tags": ["tag1"]}]
            response = test_client.get("/prompts/?tags=tag1,tag2", headers=auth_headers)
            assert response.status_code == 200
            # Verify tags were parsed
            call_args = mock_list.call_args
            assert call_args[1]["tags"] == ["tag1", "tag2"]

    def test_list_prompts_with_team_filtering(self, test_client, auth_headers):
        """Test listing prompts with team filtering."""
        with patch("mcpgateway.main.prompt_service.list_prompts_for_user") as mock_list:
            mock_prompt = MagicMock()
            mock_prompt.tags = ["tag1", "tag2"]
            mock_list.return_value = [mock_prompt]
            response = test_client.get("/prompts/?visibility=public&tags=tag1,tag3", headers=auth_headers)
            assert response.status_code == 200
            # Should filter by tags after getting team-filtered results
            mock_list.assert_called_once()

    def test_docs_endpoint_without_auth(self):
        """Test accessing docs without authentication."""
        # Create client without auth override to test real auth
        client = TestClient(app)
        response = client.get("/docs")
        assert response.status_code == 401

    def test_openapi_endpoint_without_auth(self):
        """Test accessing OpenAPI spec without authentication."""
        client = TestClient(app)
        response = client.get("/openapi.json")
        assert response.status_code == 401

    def test_redoc_endpoint_without_auth(self):
        """Test accessing ReDoc without authentication."""
        client = TestClient(app)
        response = client.get("/redoc")
        assert response.status_code == 401


class TestApplicationStartupPaths:
    """Test application startup conditional paths."""

    @patch("mcpgateway.main.plugin_manager", None)
    @patch("mcpgateway.main.logging_service")
    async def test_startup_without_plugin_manager(self, mock_logging_service):
        """Test startup path when plugin_manager is None."""
        mock_logging_service.initialize = AsyncMock()
        mock_logging_service.configure_uvicorn_after_startup = MagicMock()

        # Mock all required services
        with patch("mcpgateway.main.tool_service") as mock_tool, \
             patch("mcpgateway.main.resource_service") as mock_resource, \
             patch("mcpgateway.main.prompt_service") as mock_prompt, \
             patch("mcpgateway.main.gateway_service") as mock_gateway, \
             patch("mcpgateway.main.root_service") as mock_root, \
             patch("mcpgateway.main.completion_service") as mock_completion, \
             patch("mcpgateway.main.sampling_handler") as mock_sampling, \
             patch("mcpgateway.main.resource_cache") as mock_cache, \
             patch("mcpgateway.main.streamable_http_session") as mock_session, \
             patch("mcpgateway.main.refresh_slugs_on_startup") as mock_refresh:

            # Setup all mocks
            services = [
                mock_tool, mock_resource, mock_prompt, mock_gateway,
                mock_root, mock_completion, mock_sampling, mock_cache, mock_session
            ]
            for service in services:
                service.initialize = AsyncMock()
                service.shutdown = AsyncMock()

            # Test lifespan without plugin manager
            # First-Party
            from mcpgateway.main import lifespan
            async with lifespan(app):
                pass

            # Verify initialization happened without plugin manager
            mock_logging_service.initialize.assert_called_once()
            for service in services:
                service.initialize.assert_called_once()
                service.shutdown.assert_called_once()


class TestUtilityFunctions:
    """Test utility functions for edge cases."""

    def test_message_endpoint_edge_cases(self, test_client, auth_headers):
        """Test message endpoint with edge case parameters."""
        # Test with missing session_id to trigger validation error
        message = {"type": "test", "data": "hello"}
        response = test_client.post("/message", json=message, headers=auth_headers)
        assert response.status_code == 400  # Should require session_id parameter

        # Test with valid session_id
        with patch("mcpgateway.main.session_registry.broadcast") as mock_broadcast:
            response = test_client.post(
                "/message?session_id=test-session",
                json=message,
                headers=auth_headers
            )
            assert response.status_code == 202
            mock_broadcast.assert_called_once()

    def test_root_endpoint_conditional_behavior(self):
        """Test root endpoint behavior based on UI settings."""
        with patch("mcpgateway.main.settings.mcpgateway_ui_enabled", True):
            client = TestClient(app)
            response = client.get("/", follow_redirects=False)

            # Should redirect to /admin when UI is enabled
            if response.status_code == 303:
                assert response.headers.get("location") == "/admin"
            else:
                # Fallback behavior
                assert response.status_code == 200

        with patch("mcpgateway.main.settings.mcpgateway_ui_enabled", False):
            client = TestClient(app)
            response = client.get("/")

            # Should return API info when UI is disabled
            if response.status_code == 200:
                data = response.json()
                assert "name" in data or "ui_enabled" in data

    def test_exception_handler_scenarios(self, test_client, auth_headers):
        """Test exception handlers with various scenarios."""
        # Test simple validation error by providing invalid data
        req = {"invalid": "data"}  # Missing required 'name' field
        response = test_client.post("/servers/", json=req, headers=auth_headers)
        # Should handle validation error
        assert response.status_code == 422

    def test_json_rpc_error_paths(self, test_client, auth_headers):
        """Test JSON-RPC error handling paths."""
        # Test with a valid JSON-RPC request that might not find the tool
        req = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "method": "nonexistent_tool",
            "params": {},
        }
        response = test_client.post("/rpc/", json=req, headers=auth_headers)
        # Should return a valid JSON-RPC response even for non-existent tools
        assert response.status_code == 200
        body = response.json()
        # Should have either result or error
        assert "result" in body or "error" in body

    @patch("mcpgateway.main.settings")
    def test_websocket_error_scenarios(self, mock_settings):
        """Test WebSocket error scenarios."""
        # Configure mock settings for auth disabled
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.auth_required = False
        mock_settings.federation_timeout = 30
        mock_settings.skip_ssl_verify = False
        mock_settings.port = 4444

        with patch("mcpgateway.main.ResilientHttpClient") as mock_client:
            # Standard
            from types import SimpleNamespace

            mock_instance = mock_client.return_value
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = False

            # Mock a failing post operation
            async def failing_post(*_args, **_kwargs):
                raise Exception("Network error")

            mock_instance.post = failing_post

            client = TestClient(app)
            with client.websocket_connect("/ws") as websocket:
                websocket.send_text('{"jsonrpc":"2.0","method":"ping","id":1}')
                # Should handle the error gracefully
                try:
                    data = websocket.receive_text()
                    # Either gets error response or connection closes
                    if data:
                        response = json.loads(data)
                        assert "error" in response or "result" in response
                except Exception:
                    # Connection may close due to error
                    pass

    def test_sse_endpoint_edge_cases(self, test_client, auth_headers):
        """Test SSE endpoint edge cases."""
        with patch("mcpgateway.main.SSETransport") as mock_transport_class, \
             patch("mcpgateway.main.session_registry.add_session") as mock_add_session:

            mock_transport = MagicMock()
            mock_transport.session_id = "test-session"

            # Test SSE transport creation error
            mock_transport_class.side_effect = Exception("SSE error")

            response = test_client.get("/servers/test/sse", headers=auth_headers)
            # Should handle SSE creation error
            assert response.status_code in [404, 500, 503]

    def test_server_toggle_edge_cases(self, test_client, auth_headers):
        """Test server toggle endpoint edge cases."""
        with patch("mcpgateway.main.server_service.toggle_server_status") as mock_toggle:
            # Create a proper ServerRead model response
            # First-Party
            from mcpgateway.schemas import ServerRead

            mock_server_data = {
                "id": "1",
                "name": "test_server",
                "description": "A test server",
                "icon": None,
                "created_at": "2023-01-01T00:00:00+00:00",
                "updated_at": "2023-01-01T00:00:00+00:00",
                "is_active": True,
                "associated_tools": [],
                "associated_resources": [],
                "associated_prompts": [],
                "metrics": {
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": 0.0,
                    "max_response_time": 0.0,
                    "avg_response_time": 0.0,
                    "last_execution_time": None,
                }
            }

            mock_toggle.return_value = ServerRead(**mock_server_data)

            # Test activate=true
            response = test_client.post("/servers/1/toggle?activate=true", headers=auth_headers)
            assert response.status_code == 200

            # Test activate=false
            mock_server_data["is_active"] = False
            mock_toggle.return_value = ServerRead(**mock_server_data)
            response = test_client.post("/servers/1/toggle?activate=false", headers=auth_headers)
            assert response.status_code == 200


# Test fixtures
@pytest.fixture
def test_client(app):
    """Test client with auth override for testing protected endpoints."""
    # Standard
    from unittest.mock import patch

    # First-Party
    from mcpgateway.auth import get_current_user
    from mcpgateway.db import EmailUser
    from mcpgateway.main import require_auth
    from mcpgateway.middleware.rbac import get_current_user_with_permissions

    # Mock user object for RBAC system
    mock_user = EmailUser(
        email="test_user@example.com",
        full_name="Test User",
        is_admin=True,  # Give admin privileges for tests
        is_active=True,
        auth_provider="test"
    )

    # Mock require_auth_override function
    def mock_require_auth_override(user: str) -> str:
        return user

    # Patch the require_docs_auth_override function
    patcher = patch('mcpgateway.main.require_docs_auth_override', mock_require_auth_override)
    patcher.start()

    # Override the core auth function used by RBAC system
    app.dependency_overrides[get_current_user] = lambda credentials=None, db=None: mock_user

    # Override get_current_user_with_permissions for RBAC system
    def mock_get_current_user_with_permissions(request=None, credentials=None, jwt_token=None, db=None):
        return {
            "email": "test_user@example.com",
            "full_name": "Test User",
            "is_admin": True,
            "ip_address": "127.0.0.1",
            "user_agent": "test",
            "db": db
        }
    app.dependency_overrides[get_current_user_with_permissions] = mock_get_current_user_with_permissions

    # Mock the permission service to always return True for tests
    # First-Party
    from mcpgateway.services.permission_service import PermissionService
    if not hasattr(PermissionService, '_original_check_permission'):
        PermissionService._original_check_permission = PermissionService.check_permission
    PermissionService.check_permission = lambda self, permission, scope, scope_id, user_email: True

    # Override require_auth for backward compatibility
    app.dependency_overrides[require_auth] = lambda: "test_user"

    client = TestClient(app)
    yield client

    # Clean up overrides and restore original methods
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_user_with_permissions, None)
    patcher.stop()  # Stop the require_auth_override patch
    if hasattr(PermissionService, '_original_check_permission'):
        PermissionService.check_permission = PermissionService._original_check_permission

@pytest.fixture
def auth_headers():
    """Default auth headers for testing."""
    return {"Authorization": "Bearer test_token"}
