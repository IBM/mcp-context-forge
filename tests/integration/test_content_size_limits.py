# -*- coding: utf-8 -*-
"""Integration tests for content size limits

This module tests the acceptance criteria:
- Resource content exceeding 100KB limit returns 413
- Prompt template exceeding 10KB limit returns 413
- Content within limits succeeds
- Error responses include size limit information
- Size validation applies to both create and update operations
"""
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from _pytest.monkeypatch import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from mcpgateway.auth import get_current_user
from mcpgateway.utils.verify_credentials import require_auth
from mcpgateway.db import Base
from mcpgateway.main import app
from mcpgateway.middleware.rbac import (
    get_current_user_with_permissions,
    get_db as rbac_get_db,
    get_permission_service,
)


class MockPermissionService:
    """Mock permission service that always grants access."""

    def __init__(self, always_grant=True):
        self.always_grant = always_grant

    async def check_permission(self, *args, **kwargs):
        return self.always_grant


@pytest.fixture
def test_app():
    """Create test app with proper database setup."""
    mp = MonkeyPatch()

    # Create temp SQLite file
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # Patch settings
    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", url, raising=False)

    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestingSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestingSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    # Create schema
    Base.metadata.create_all(bind=engine)

    # Create mock user for basic auth
    mock_email_user = MagicMock()
    mock_email_user.email = "test_user@example.com"
    mock_email_user.full_name = "Test User"
    mock_email_user.is_admin = True
    mock_email_user.is_active = True

    async def mock_user_with_permissions():
        """Mock user context for RBAC."""
        db_session = TestingSessionLocal()
        try:
            yield {
                "email": "test_user@example.com",
                "full_name": "Test User",
                "is_admin": True,
                "ip_address": "127.0.0.1",
                "user_agent": "test-client",
                "db": db_session,
            }
        finally:
            db_session.close()

    def mock_get_permission_service(*args, **kwargs):
        """Return a mock permission service that always grants access."""
        return MockPermissionService(always_grant=True)

    def override_get_db():
        """Override database dependency to return our test database."""
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Patch the PermissionService class to always return our mock
    with patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService):
        app.dependency_overrides[require_auth] = lambda: "test_user"
        app.dependency_overrides[get_current_user] = lambda: mock_email_user
        app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
        app.dependency_overrides[get_permission_service] = mock_get_permission_service
        app.dependency_overrides[rbac_get_db] = override_get_db

        yield app

        # Cleanup
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_user_with_permissions, None)
        app.dependency_overrides.pop(get_permission_service, None)
        app.dependency_overrides.pop(rbac_get_db, None)

    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Dummy Bearer token accepted by the overridden dependency."""
    return {"Authorization": "Bearer test.token.size_limits"}


from fastapi import status


class TestResourceSizeLimits:
    """Test resource content size limits."""

    def test_create_resource_within_limit(self, client, auth_headers):
        """Test creating resource with content within size limit (50KB)."""
        content = "x" * 50000  # 50KB - well under 100KB limit
        response = client.post("/api/resources", json={"uri": "test://resource-small", "name": "Small Resource", "content": content}, headers=auth_headers)
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["uri"] == "test://resource-small"

    def test_create_resource_at_limit(self, client, auth_headers):
        """Test creating resource with content at exact size limit (100KB)."""
        content = "x" * 102400  # Exactly 100KB
        response = client.post("/api/resources", json={"uri": "test://resource-at-limit", "name": "At Limit Resource", "content": content}, headers=auth_headers)
        # Should succeed at exact limit
        assert response.status_code == status.HTTP_201_CREATED

    def test_create_resource_exceeds_limit(self, client, auth_headers):
        """Test creating resource with oversized content returns 413."""
        content = "x" * 200000  # 200KB - over 100KB limit
        response = client.post("/api/resources", json={"uri": "test://resource-large", "name": "Large Resource", "content": content}, headers=auth_headers)

        # Should return 413 Payload Too Large
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

        # Verify error response structure
        data = response.json()
        assert "detail" in data
        detail = data["detail"]

        # Verify error includes size information
        assert "actual_size" in detail
        assert "max_size" in detail
        assert "error" in detail
        assert "message" in detail

        # Verify size values
        assert detail["actual_size"] == 200000
        assert detail["max_size"] == 102400
        assert detail["actual_size"] > detail["max_size"]

        # Verify error message is clear
        assert "size limit exceeded" in detail["error"].lower()

    def test_create_resource_one_byte_over(self, client, auth_headers):
        """Test creating resource one byte over limit returns 413."""
        content = "x" * 102401  # 100KB + 1 byte
        response = client.post("/api/resources", json={"uri": "test://resource-one-over", "name": "One Over Resource", "content": content}, headers=auth_headers)
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

    def test_create_resource_unicode_content(self, client, auth_headers):
        """Test size validation handles Unicode content correctly."""
        # Unicode emoji characters are 4 bytes each in UTF-8
        content = "🎉" * 30000  # 30000 * 4 = 120KB
        response = client.post("/api/resources", json={"uri": "test://resource-unicode", "name": "Unicode Resource", "content": content}, headers=auth_headers)
        # Should be rejected as it exceeds 100KB
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


class TestPromptSizeLimits:
    """Test prompt template size limits."""

    def test_create_prompt_within_limit(self, client, auth_headers):
        """Test creating prompt with template within size limit (5KB)."""
        template = "x" * 5000  # 5KB - well under 10KB limit
        response = client.post("/api/prompts", json={"name": "small_prompt", "template": template, "description": "Small test prompt"}, headers=auth_headers)
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "small_prompt"

    def test_create_prompt_at_limit(self, client, auth_headers):
        """Test creating prompt with template at exact size limit (10KB)."""
        template = "x" * 10240  # Exactly 10KB
        response = client.post("/api/prompts", json={"name": "at_limit_prompt", "template": template, "description": "At limit test prompt"}, headers=auth_headers)
        # Should succeed at exact limit
        assert response.status_code == status.HTTP_201_CREATED

    def test_create_prompt_exceeds_limit(self, client, auth_headers):
        """Test creating prompt with oversized template returns 413."""
        template = "x" * 20000  # 20KB - over 10KB limit
        response = client.post("/api/prompts", json={"name": "large_prompt", "template": template, "description": "Large test prompt"}, headers=auth_headers)

        # Should return 413 Payload Too Large
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

        # Verify error response structure
        data = response.json()
        assert "detail" in data
        detail = data["detail"]

        # Verify error includes size information
        assert "actual_size" in detail
        assert "max_size" in detail
        assert "error" in detail
        assert "message" in detail

        # Verify size values
        assert detail["actual_size"] == 20000
        assert detail["max_size"] == 10240
        assert detail["actual_size"] > detail["max_size"]

        # Verify error message is clear
        assert "size limit exceeded" in detail["error"].lower()

    def test_create_prompt_one_byte_over(self, client, auth_headers):
        """Test creating prompt one byte over limit returns 413."""
        template = "x" * 10241  # 10KB + 1 byte
        response = client.post("/api/prompts", json={"name": "one_over_prompt", "template": template, "description": "One over test prompt"}, headers=auth_headers)
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

    def test_create_prompt_unicode_template(self, client, auth_headers):
        """Test size validation handles Unicode templates correctly."""
        # Unicode emoji characters are 4 bytes each in UTF-8
        template = "🎉" * 3000  # 3000 * 4 = 12KB
        response = client.post("/api/prompts", json={"name": "unicode_prompt", "template": template, "description": "Unicode test prompt"}, headers=auth_headers)
        # Should be rejected as it exceeds 10KB
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


class TestSizeValidationConsistency:
    """Test that size validation applies consistently across operations."""

    def test_resource_validation_on_create_and_update(self, client, auth_headers):
        """Test size validation applies to both create and update operations."""
        # First, create a small resource
        small_content = "x" * 1000  # 1KB
        create_response = client.post("/api/resources", json={"uri": "test://update-test", "name": "Update Test Resource", "content": small_content}, headers=auth_headers)
        assert create_response.status_code == status.HTTP_201_CREATED
        resource_id = create_response.json()["id"]

        # Try to update with oversized content
        large_content = "x" * 200000  # 200KB
        update_response = client.put(f"/api/resources/{resource_id}", json={"content": large_content}, headers=auth_headers)

        # Update should also be rejected with 413
        assert update_response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

        # Verify error structure
        data = update_response.json()
        assert "detail" in data
        assert "actual_size" in data["detail"]
        assert "max_size" in data["detail"]

    def test_prompt_validation_on_create_and_update(self, client, auth_headers):
        """Test size validation applies to both create and update operations."""
        # First, create a small prompt
        small_template = "x" * 1000  # 1KB
        create_response = client.post("/api/prompts", json={"name": "update_test_prompt", "template": small_template, "description": "Update test"}, headers=auth_headers)
        assert create_response.status_code == status.HTTP_201_CREATED
        prompt_id = create_response.json()["id"]

        # Try to update with oversized template
        large_template = "x" * 20000  # 20KB
        update_response = client.put(f"/api/prompts/{prompt_id}", json={"template": large_template}, headers=auth_headers)

        # Update should also be rejected with 413
        assert update_response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

        # Verify error structure
        data = update_response.json()
        assert "detail" in data
        assert "actual_size" in data["detail"]
        assert "max_size" in data["detail"]


class TestErrorMessageClarity:
    """Test that error messages are clear and helpful."""

    def test_resource_error_message_clarity(self, client, auth_headers):
        """Test resource error message provides clear guidance."""
        content = "x" * 200000  # 200KB
        response = client.post("/api/resources", json={"uri": "test://error-message-test", "name": "Error Message Test", "content": content}, headers=auth_headers)

        data = response.json()
        detail = data["detail"]

        # Error message should be human-readable
        assert "message" in detail
        message = detail["message"]
        assert "Resource content" in message
        assert "exceeds" in message.lower()
        # Verify raw size values are available in the detail response
        assert detail["actual_size"] == 200000
        assert detail["max_size"] == 102400

    def test_prompt_error_message_clarity(self, client, auth_headers):
        """Test prompt error message provides clear guidance."""
        template = "x" * 20000  # 20KB
        response = client.post("/api/prompts", json={"name": "error_message_test", "template": template, "description": "Error message test"}, headers=auth_headers)

        data = response.json()
        detail = data["detail"]

        # Error message should be human-readable
        assert "message" in detail
        message = detail["message"]
        assert "Prompt template" in message
        assert "exceeds" in message.lower()
        # Verify raw size values are available in the detail response
        assert detail["actual_size"] == 20000
        assert detail["max_size"] == 10240


def test_bulk_resource_registration_with_oversized_content(test_app, client, auth_headers):
    """Test that bulk resource registration validates content size for each resource.

    This test verifies that when registering multiple resources in bulk,
    oversized resources are rejected and reported in the error statistics.
    """
    from mcpgateway.schemas import ResourceCreate
    from mcpgateway.services.resource_service import ResourceService
    from mcpgateway.db import get_db

    # Create a mix of valid and oversized resources
    resources = [
        ResourceCreate(uri="resource://test/small1", name="Small Resource 1", content="x" * 1000, description="Small resource"),  # 1KB - OK
        ResourceCreate(uri="resource://test/large1", name="Large Resource 1", content="x" * 200000, description="Oversized resource"),  # 200KB - Too large
        ResourceCreate(uri="resource://test/small2", name="Small Resource 2", content="y" * 2000, description="Another small resource"),  # 2KB - OK
        ResourceCreate(uri="resource://test/large2", name="Large Resource 2", content="z" * 150000, description="Another oversized resource"),  # 150KB - Too large
    ]

    # Get database session
    db = next(get_db())

    # Call bulk registration
    service = ResourceService()
    import asyncio

    result = asyncio.run(service.register_resources_bulk(db=db, resources=resources, created_by="test@example.com", created_from_ip="127.0.0.1", conflict_strategy="skip"))

    # Verify results
    assert result["created"] == 2, "Should create 2 valid resources"
    assert result["failed"] == 2, "Should fail 2 oversized resources"
    assert len(result["errors"]) == 2, "Should have 2 error messages"

    # Check error messages contain size and URI information
    errors_text = " ".join(result["errors"])
    assert "exceeds" in errors_text.lower(), "Errors should mention size exceeds limit"
    assert "resource://test/large1" in errors_text or "resource://test/large2" in errors_text, "Errors should identify the problematic resources"


def test_prompt_update_with_oversized_template(test_app, client, auth_headers):
    """Test that updating a prompt with an oversized template returns 413.

    This test verifies that the update_prompt method validates template size
    and rejects oversized templates with appropriate error response.
    """
    # First create a prompt with valid template
    response = client.post("/api/prompts", json={"name": "test-prompt-for-update", "template": "Small template", "description": "Test prompt"}, headers=auth_headers)
    assert response.status_code == 201
    prompt_data = response.json()
    prompt_id = prompt_data["id"]

    # Try to update with oversized template (20KB)
    oversized_template = "x" * 20000
    response = client.put(f"/api/prompts/{prompt_id}", json={"template": oversized_template}, headers=auth_headers)

    # Should return 413 Payload Too Large
    assert response.status_code == 413

    data = response.json()
    detail = data["detail"]

    # Verify error details
    assert "message" in detail
    assert "actual_size" in detail
    assert "max_size" in detail
    assert detail["actual_size"] == 20000
    assert detail["max_size"] == 10240
    assert "Prompt template" in detail["message"]
    assert "exceeds" in detail["message"].lower()

    # Verify the prompt was not updated
    response = client.get(f"/api/prompts/{prompt_id}", headers=auth_headers)
    assert response.status_code == 200
    prompt_data = response.json()
    assert prompt_data["template"] == "Small template"  # Original template unchanged


def test_prompt_update_with_valid_template(test_app, client, auth_headers):
    """Test that updating a prompt with a valid-sized template succeeds.

    This test verifies that templates within the size limit can be updated successfully.
    """
    # First create a prompt
    response = client.post("/api/prompts", json={"name": "test-prompt-for-valid-update", "template": "Original template", "description": "Test prompt"}, headers=auth_headers)
    assert response.status_code == 201
    prompt_data = response.json()
    prompt_id = prompt_data["id"]

    # Update with valid-sized template (5KB)
    new_template = "y" * 5000
    response = client.put(f"/api/prompts/{prompt_id}", json={"template": new_template}, headers=auth_headers)

    # Should succeed
    assert response.status_code == 200

    # Verify the prompt was updated
    response = client.get(f"/api/prompts/{prompt_id}", headers=auth_headers)
    assert response.status_code == 200
    prompt_data = response.json()
    assert prompt_data["template"] == new_template


def test_resource_update_with_oversized_content(test_app, client, auth_headers):
    """Test that updating a resource with oversized content returns 413.

    This test verifies that the update_resource method validates content size
    and rejects oversized content with appropriate error response.
    """
    # First create a resource with valid content
    response = client.post(
        "/api/resources", json={"uri": "resource://test/update-test", "name": "Test Resource for Update", "content": "Small content", "description": "Test resource"}, headers=auth_headers
    )
    assert response.status_code == 201
    resource_data = response.json()
    resource_id = resource_data["id"]

    # Try to update with oversized content (200KB)
    oversized_content = "x" * 200000
    response = client.put(f"/api/resources/{resource_id}", json={"content": oversized_content}, headers=auth_headers)

    # Should return 413 Payload Too Large
    assert response.status_code == 413

    data = response.json()
    detail = data["detail"]

    # Verify error details
    assert "message" in detail
    assert "actual_size" in detail
    assert "max_size" in detail
    assert detail["actual_size"] == 200000
    assert detail["max_size"] == 102400
    assert "Resource content" in detail["message"]
    assert "exceeds" in detail["message"].lower()

    # Verify the resource was not updated
    response = client.get(f"/api/resources/{resource_id}", headers=auth_headers)
    assert response.status_code == 200
    resource_data = response.json()
    assert resource_data["content"] == "Small content"  # Original content unchanged


def test_resource_update_with_valid_content(test_app, client, auth_headers):
    """Test that updating a resource with valid-sized content succeeds.

    This test verifies that content within the size limit can be updated successfully.
    """
    # First create a resource
    response = client.post(
        "/api/resources", json={"uri": "resource://test/valid-update", "name": "Test Resource for Valid Update", "content": "Original content", "description": "Test resource"}, headers=auth_headers
    )
    assert response.status_code == 201
    resource_data = response.json()
    resource_id = resource_data["id"]

    # Update with valid-sized content (50KB)
    new_content = "y" * 50000
    response = client.put(f"/api/resources/{resource_id}", json={"content": new_content}, headers=auth_headers)

    # Should succeed
    assert response.status_code == 200

    # Verify the resource was updated
    response = client.get(f"/api/resources/{resource_id}", headers=auth_headers)
    assert response.status_code == 200
    resource_data = response.json()
    assert resource_data["content"] == new_content
