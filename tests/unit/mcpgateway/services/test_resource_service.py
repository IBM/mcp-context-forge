# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

"""
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from mcpgateway.schemas import ResourceCreate, ResourceRead
from mcpgateway.services.resource_service import (
    ResourceError,
    ResourceNotFoundError,
    ResourceService,
    ResourceURIConflictError,
)


@pytest.fixture
def resource_service():
    """Create a ResourceService instance."""
    return ResourceService()


@pytest.fixture
def mock_resource():
    """Create a mock resource model."""
    resource = Mock()
    resource.id = 1
    resource.uri = "test/resource"
    resource.name = "Test Resource"
    resource.description = "A test resource"
    resource.mime_type = "text/plain"
    resource.size = 12
    resource.is_active = True
    resource.created_at = "2023-01-01T00:00:00"
    resource.updated_at = "2023-01-01T00:00:00"
    resource.text_content = "Test content"
    resource.binary_content = None
    resource.metrics = []
    resource.__dict__ = {
        "id": 1,
        "uri": "test/resource",
        "name": "Test Resource",
        "description": "A test resource",
        "mime_type": "text/plain",
        "size": 12,
        "is_active": True,
        "created_at": "2023-01-01T00:00:00",
        "updated_at": "2023-01-01T00:00:00",
        "text_content": "Test content",
        "binary_content": None,
    }

    # Create a mock for the content property
    content_mock = Mock()
    content_mock.type = "resource"
    content_mock.uri = "test/resource"
    content_mock.mime_type = "text/plain"
    content_mock.text = "Test content"
    content_mock.blob = None

    # Set up the content property as a property that returns the mock
    type(resource).content = content_mock

    return resource


class TestResourceService:
    """Tests for the ResourceService class."""

    @pytest.mark.asyncio
    async def test_register_resource(self, resource_service, mock_resource, test_db):
        """Test successful resource registration."""
        # Create a resource request
        create_resource = ResourceCreate(
            uri="test/resource",
            name="Test Resource",
            description="A test resource",
            mime_type="text/plain",
            content="Test content",
        )

        # Set up mocks for database session
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none = Mock(return_value=None)

        test_db.execute = Mock(return_value=mock_scalar)
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Set up mock for resource_service methods
        resource_service._is_valid_uri = Mock(return_value=True)
        resource_service._detect_mime_type = Mock(return_value="text/plain")
        resource_service._notify_resource_added = AsyncMock()
        resource_service._convert_resource_to_read = Mock(
            return_value=ResourceRead(
                id=1,
                uri="test/resource",
                name="Test Resource",
                description="A test resource",
                mime_type="text/plain",
                size=12,
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                is_active=True,
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        )

        # Call the method under test
        result = await resource_service.register_resource(test_db, create_resource)

        # Verify result
        assert result.uri == "test/resource"
        assert result.name == "Test Resource"
        assert result.description == "A test resource"
        assert result.mime_type == "text/plain"
        assert result.is_active is True

        # Verify method calls
        test_db.add.assert_called_once()
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()
        resource_service._notify_resource_added.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_resource_conflict(self, resource_service, mock_resource, test_db):
        """Test resource registration with URI conflict."""
        create_resource = ResourceCreate(
            uri="existing/resource",
            name="Existing Resource",
            description="An existing resource",
            mime_type="text/plain",
            content="Existing content",
        )

        # Mock that a resource with same URI exists
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none = Mock(return_value=mock_resource)
        test_db.execute = Mock(return_value=mock_scalar)

        with pytest.raises(ResourceURIConflictError) as exc_info:
            await resource_service.register_resource(test_db, create_resource)

        assert "Resource already exists with URI" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_read_resource(self, resource_service, mock_resource, test_db):
        """Test reading a resource."""
        uri = "test/resource"

        # Mock that the resource exists
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none = Mock(return_value=mock_resource)
        test_db.execute = Mock(return_value=mock_scalar)

        # Make a mock for the content property
        content_mock = MagicMock()
        type(mock_resource).content = property(lambda self: content_mock)

        result = await resource_service.read_resource(test_db, uri)

        # Verify result
        assert result == content_mock

    @pytest.mark.asyncio
    async def test_read_resource_not_found(self, resource_service, test_db):
        """Test reading a non-existent resource."""
        uri = "nonexistent/resource"

        # Mock that the resource doesn't exist
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none = Mock(return_value=None)
        test_db.execute = Mock(return_value=mock_scalar)

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await resource_service.read_resource(test_db, uri)

        assert "Resource not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_resource(self, resource_service, mock_resource, test_db):
        """Test deleting a resource."""
        uri = "test/resource"

        # Mock that the resource exists
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none = Mock(return_value=mock_resource)
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock db operations
        test_db.delete = Mock()
        test_db.commit = Mock()

        # Mock notification
        resource_service._notify_resource_deleted = AsyncMock()

        # Call the method under test
        await resource_service.delete_resource(test_db, uri)

        # Verify DB operations
        test_db.delete.assert_called_once_with(mock_resource)
        test_db.commit.assert_called_once()

        # Verify notification
        resource_service._notify_resource_deleted.assert_called_once()

    @pytest.mark.parametrize(
        "uri, expected_result",
        [
            ("http://example.com/test", True),
            ("https://example.com/test", True),
            ("file:///path/to/resource", True),
            ("invalid-uri", False),
        ],
    )
    def test_is_valid_uri(self, resource_service, uri, expected_result):
        """Test URI validation."""
        # Use the actual method rather than mocking
        result = resource_service._is_valid_uri(uri)
        assert result == expected_result
