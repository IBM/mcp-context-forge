# -*- coding: utf-8 -*-
"""Integration tests for malicious pattern detection

This module tests the acceptance criteria:
- XSS patterns in resources/prompts are blocked
- Template injection patterns are blocked
- Command injection patterns are blocked
- SQL injection patterns are blocked
- Pattern validation applies to create, update, and bulk operations
- Error responses include violation details
- Validation modes (strict, moderate, lenient) work correctly
- Pattern caching improves performance
"""

# Standard
import os
import tempfile
from unittest.mock import MagicMock, patch

# Third-Party
from _pytest.monkeypatch import MonkeyPatch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.db import Base

# Don't import app at module level - import in fixture after patching
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.middleware.rbac import get_db as rbac_get_db
from mcpgateway.middleware.rbac import get_permission_service
from mcpgateway.utils.verify_credentials import require_auth


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
    # First-Party
    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", url, raising=False)

    # Enable pattern detection for tests (use correct config keys with raising=True)
    mp.setattr(settings, "content_pattern_detection_enabled", True, raising=True)
    mp.setattr(settings, "content_pattern_validation_mode", "strict", raising=True)
    mp.setattr(settings, "content_pattern_cache_enabled", True, raising=True)

    # Enable admin API for tests - patch both settings and the constant in main.py
    mp.setattr(settings, "mcpgateway_admin_api_enabled", True, raising=True)

    # First-Party
    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    # Patch the ADMIN_API_ENABLED constant that was read at import time
    mp.setattr(main_mod, "ADMIN_API_ENABLED", True, raising=True)

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestingSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestingSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    # Create schema
    Base.metadata.create_all(bind=engine)

    # Import app AFTER patching settings
    # First-Party
    from mcpgateway.main import app

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
    return {"Authorization": "Bearer test.token.pattern_detection"}


class TestXSSPatternDetection:
    """Test XSS attack pattern detection in resources and prompts."""

    def test_resource_blocks_script_tag(self, client, auth_headers):
        """Test that resources with <script> tags are blocked."""
        malicious_content = "Hello <script>alert('XSS')</script> World"
        response = client.post("/api/resources", json={"uri": "test://xss-script", "name": "XSS Script Test", "content": malicious_content}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        detail = data["detail"]
        assert "violation_type" in detail
        assert detail["violation_type"] == "xss"
        assert "content_type" in detail
        assert "message" in detail

    def test_resource_blocks_event_handler(self, client, auth_headers):
        """Test that resources with event handlers are blocked."""
        malicious_content = '<img src="x" onerror="alert(1)">'
        response = client.post("/api/resources", json={"uri": "test://xss-event", "name": "XSS Event Test", "content": malicious_content}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["violation_type"] == "xss"

    def test_resource_blocks_javascript_protocol(self, client, auth_headers):
        """Test that resources with javascript: protocol are blocked."""
        malicious_content = '<a href="javascript:alert(1)">Click me</a>'
        response = client.post("/api/resources", json={"uri": "test://xss-js-protocol", "name": "XSS JS Protocol Test", "content": malicious_content}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["violation_type"] == "xss"

    def test_prompt_blocks_script_tag(self, client, auth_headers):
        """Test that prompts with <script> tags are blocked."""
        malicious_template = "Generate code: <script>alert('XSS')</script>"
        response = client.post("/api/prompts", json={"name": "xss_script_prompt", "template": malicious_template, "description": "XSS test"}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["violation_type"] == "xss"


class TestTemplateInjectionDetection:
    """Test template injection pattern detection."""

    def test_resource_blocks_jinja2_template(self, client, auth_headers):
        """Test that resources with Jinja2 template syntax are blocked."""
        malicious_content = "User input: {{ config.items() }}"
        response = client.post("/api/resources", json={"uri": "test://template-jinja", "name": "Template Injection Test", "content": malicious_content}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["violation_type"] == "template_injection"

    def test_resource_blocks_expression_evaluation(self, client, auth_headers):
        """Test that resources with ${} expressions are blocked."""
        malicious_content = "Value: ${7*7}"
        response = client.post("/api/resources", json={"uri": "test://template-expr", "name": "Expression Test", "content": malicious_content}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["violation_type"] == "template_injection"

    def test_prompt_blocks_template_syntax(self, client, auth_headers):
        """Test that prompts with template injection are blocked."""
        malicious_template = "Process: {% for item in config %} {{ item }} {% endfor %}"
        response = client.post("/api/prompts", json={"name": "template_injection_prompt", "template": malicious_template, "description": "Template injection test"}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["violation_type"] == "template_injection"


class TestCommandInjectionDetection:
    """Test command injection pattern detection."""

    def test_resource_blocks_shell_metacharacters(self, client, auth_headers):
        """Test that resources with shell metacharacters are blocked."""
        malicious_content = "Run: ls -la; rm -rf /"
        response = client.post("/api/resources", json={"uri": "test://cmd-shell", "name": "Command Injection Test", "content": malicious_content}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["violation_type"] == "command_injection"

    def test_resource_blocks_command_chaining(self, client, auth_headers):
        """Test that resources with command chaining are blocked."""
        malicious_content = "echo hello && cat /etc/passwd"
        response = client.post("/api/resources", json={"uri": "test://cmd-chain", "name": "Command Chain Test", "content": malicious_content}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["violation_type"] == "command_injection"

    def test_resource_blocks_backtick_execution(self, client, auth_headers):
        """Test that resources with backtick command execution are blocked."""
        malicious_content = "Output: `whoami`"
        response = client.post("/api/resources", json={"uri": "test://cmd-backtick", "name": "Backtick Test", "content": malicious_content}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["violation_type"] == "command_injection"


class TestSQLInjectionDetection:
    """Test SQL injection pattern detection."""

    def test_resource_blocks_sql_keywords(self, client, auth_headers):
        """Test that resources with SQL keywords are blocked."""
        malicious_content = "Query: SELECT * FROM users WHERE id=1"
        response = client.post("/api/resources", json={"uri": "test://sql-keywords", "name": "SQL Keywords Test", "content": malicious_content}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["violation_type"] == "sql_injection"

    def test_resource_blocks_sql_comments(self, client, auth_headers):
        """Test that resources with SQL comment injection are blocked."""
        malicious_content = "Input: admin'-- "
        response = client.post("/api/resources", json={"uri": "test://sql-comment", "name": "SQL Comment Test", "content": malicious_content}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["violation_type"] == "sql_injection"

    def test_resource_blocks_sql_string_concat(self, client, auth_headers):
        """Test that resources with SQL string concatenation are blocked."""
        malicious_content = "Value: ' OR '1'='1"
        response = client.post("/api/resources", json={"uri": "test://sql-concat", "name": "SQL Concat Test", "content": malicious_content}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["violation_type"] == "sql_injection"


class TestPatternValidationConsistency:
    """Test that pattern validation applies consistently across operations."""

    def test_resource_validation_on_create_and_update(self, client, auth_headers):
        """Test pattern validation applies to both create and update operations."""
        # First, create a clean resource
        clean_content = "This is safe content"
        create_response = client.post("/api/resources", json={"uri": "test://update-pattern-test", "name": "Update Pattern Test", "content": clean_content}, headers=auth_headers)
        assert create_response.status_code == 201
        resource_id = create_response.json()["id"]

        # Try to update with malicious content
        malicious_content = "<script>alert('XSS')</script>"
        update_response = client.put(f"/api/resources/{resource_id}", json={"content": malicious_content}, headers=auth_headers)

        # Update should be rejected with 400
        assert update_response.status_code == 400
        data = update_response.json()
        assert "detail" in data
        assert "violation_type" in data["detail"]

    def test_prompt_validation_on_create_and_update(self, client, auth_headers):
        """Test pattern validation applies to both create and update operations."""
        # First, create a clean prompt
        clean_template = "This is a safe template"
        create_response = client.post("/api/prompts", json={"name": "update_pattern_test_prompt", "template": clean_template, "description": "Update test"}, headers=auth_headers)
        assert create_response.status_code == 201
        prompt_id = create_response.json()["id"]

        # Try to update with malicious template
        malicious_template = "{{ config.items() }}"
        update_response = client.put(f"/api/prompts/{prompt_id}", json={"template": malicious_template}, headers=auth_headers)

        # Update should be rejected with 400
        assert update_response.status_code == 400
        data = update_response.json()
        assert "detail" in data
        assert "violation_type" in data["detail"]

    def test_prompt_update_blocks_xss_pattern(self, client, auth_headers):
        """Test that updating a prompt with XSS pattern returns 400 with structured error.

        This test covers:
        - main.py lines 6236-6237 (ContentPatternError handler in PUT /prompts endpoint)
        - prompt_service.py lines 2380-2381 (ContentPatternError handler in update_prompt)
        """
        # Create clean prompt
        create_response = client.post("/api/prompts", json={"name": "xss_update_test", "template": "Hello {{name}}", "description": "Test prompt for XSS update"}, headers=auth_headers)
        assert create_response.status_code == 201
        prompt_id = create_response.json()["id"]

        # Update with XSS pattern
        update_response = client.put(f"/api/prompts/{prompt_id}", json={"template": "<script>alert('XSS')</script>"}, headers=auth_headers)

        # Verify 400 error with structured response
        assert update_response.status_code == 400
        data = update_response.json()
        assert "detail" in data
        assert isinstance(data["detail"], dict)
        assert data["detail"]["error"] == "Malicious pattern detected"
        assert "violation_type" in data["detail"]
        assert data["detail"]["violation_type"] == "xss"
        # NOTE: pattern_matched intentionally omitted from response (CWE-209)
        assert "content_type" in data["detail"]
        assert data["detail"]["content_type"] == "prompt"
        assert "message" in data["detail"]

    def test_prompt_update_blocks_command_injection(self, client, auth_headers):
        """Test that updating a prompt with command injection returns 400.

        Additional coverage for different violation types in UPDATE endpoint.
        """
        # Create clean prompt
        create_response = client.post(
            "/api/prompts", json={"name": "cmd_update_test", "template": "Process {{input}}", "description": "Test prompt for command injection update"}, headers=auth_headers
        )
        assert create_response.status_code == 201
        prompt_id = create_response.json()["id"]

        # Update with command injection
        update_response = client.put(f"/api/prompts/{prompt_id}", json={"template": "Run: ls; rm -rf /"}, headers=auth_headers)

        # Verify 400 error
        assert update_response.status_code == 400
        data = update_response.json()
        assert data["detail"]["violation_type"] == "command_injection"
        assert data["detail"]["content_type"] == "prompt"

    def test_prompt_create_blocks_sql_injection(self, client, auth_headers):
        """Test that creating a prompt with SQL injection returns 400.

        This test covers:
        - main.py lines 6032-6040 (ContentPatternError handler in POST /prompts endpoint)
        - Verifies CREATE endpoint handler works correctly
        """
        response = client.post("/api/prompts", json={"name": "sql_test", "template": "Query: SELECT * FROM users WHERE id={{id}}", "description": "SQL injection test"}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        assert isinstance(data["detail"], dict)
        assert data["detail"]["violation_type"] == "sql_injection"
        assert data["detail"]["content_type"] == "prompt"
        assert data["detail"]["error"] == "Malicious pattern detected"


class TestBulkOperationPatternValidation:
    """Test pattern validation in bulk operations."""

    def test_bulk_resource_registration_with_malicious_patterns(self, test_app, client, auth_headers):
        """Test that bulk resource registration validates patterns for each resource."""
        # First-Party
        from mcpgateway.db import get_db
        from mcpgateway.schemas import ResourceCreate
        from mcpgateway.services.resource_service import ResourceService

        # Create a mix of valid and malicious resources
        resources = [
            ResourceCreate(uri="resource://test/clean1", name="Clean Resource 1", content="This is safe content", description="Clean resource"),
            ResourceCreate(uri="resource://test/xss1", name="XSS Resource 1", content="<script>alert('XSS')</script>", description="Malicious resource"),
            ResourceCreate(uri="resource://test/clean2", name="Clean Resource 2", content="Another safe resource", description="Another clean resource"),
            ResourceCreate(uri="resource://test/sqli1", name="SQLi Resource 1", content="SELECT * FROM users", description="SQL injection attempt"),
        ]

        # Get database session
        db = next(get_db())

        # Call bulk registration
        service = ResourceService()
        # Standard
        import asyncio

        result = asyncio.run(service.register_resources_bulk(db=db, resources=resources, created_by="test@example.com", created_from_ip="127.0.0.1", conflict_strategy="skip"))

        # Verify results
        assert result["created"] == 2, "Should create 2 valid resources"
        assert result["failed"] == 2, "Should fail 2 malicious resources"
        assert len(result["errors"]) == 2, "Should have 2 error messages"

        # Check error messages contain pattern information
        errors_text = " ".join(result["errors"])
        assert "xss" in errors_text.lower() or "sql" in errors_text.lower(), "Errors should mention violation types"


class TestValidationModes:
    """Test different validation modes (strict, moderate, lenient)."""

    def test_strict_mode_blocks_all_patterns(self, client, auth_headers, monkeypatch):
        """Test that strict mode blocks all malicious patterns."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "content_pattern_validation_mode", "strict")

        malicious_content = "<script>alert('test')</script>"
        response = client.post("/api/resources", json={"uri": "test://strict-mode", "name": "Strict Mode Test", "content": malicious_content}, headers=auth_headers)

        assert response.status_code == 400
        assert "violation_type" in response.json()["detail"]

    def test_lenient_mode_logs_but_allows(self, client, auth_headers, monkeypatch):
        """Test that lenient mode logs violations but allows content."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "content_pattern_validation_mode", "lenient")

        malicious_content = "<script>alert('test')</script>"
        response = client.post("/api/resources", json={"uri": "test://lenient-mode", "name": "Lenient Mode Test", "content": malicious_content}, headers=auth_headers)

        # In lenient mode, content should be allowed
        assert response.status_code == 201


class TestCleanContentAllowed:
    """Test that clean content is allowed through validation."""

    def test_resource_with_clean_content_succeeds(self, client, auth_headers):
        """Test that resources with clean content are created successfully."""
        clean_content = """
        This is a legitimate resource with:
        - Normal text
        - Code examples (properly formatted)
        - Documentation
        - No malicious patterns
        """
        response = client.post("/api/resources", json={"uri": "test://clean-resource", "name": "Clean Resource", "content": clean_content}, headers=auth_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["uri"] == "test://clean-resource"

    def test_prompt_with_clean_template_succeeds(self, client, auth_headers):
        """Test that prompts with clean templates are created successfully."""
        clean_template = """
        You are a helpful assistant.
        Please help the user with: {task}
        Provide clear and concise answers.
        """
        response = client.post("/api/prompts", json={"name": "clean_prompt", "template": clean_template, "description": "Clean prompt template"}, headers=auth_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "clean_prompt"


class TestErrorMessageClarity:
    """Test that error messages are clear and helpful."""

    def test_pattern_violation_error_includes_details(self, client, auth_headers):
        """Test that pattern violation errors include helpful details."""
        malicious_content = "<script>alert('XSS')</script>"
        response = client.post("/api/resources", json={"uri": "test://error-details", "name": "Error Details Test", "content": malicious_content}, headers=auth_headers)

        data = response.json()
        detail = data["detail"]

        # Verify error structure (pattern and validation_mode intentionally omitted - CWE-209)
        assert "error" in detail
        assert "message" in detail
        assert "violation_type" in detail
        assert "content_type" in detail

        # Verify error message is human-readable
        message = detail["message"]
        assert "malicious pattern" in message.lower() or "potentially malicious" in message.lower()

    def test_multiple_patterns_reported_clearly(self, client, auth_headers):
        """Test that content with multiple violations is reported clearly."""
        # Content with both XSS and SQL injection
        malicious_content = "<script>alert('XSS')</script> SELECT * FROM users"
        response = client.post("/api/resources", json={"uri": "test://multiple-violations", "name": "Multiple Violations Test", "content": malicious_content}, headers=auth_headers)

        assert response.status_code == 400
        data = response.json()
        # Should report the first violation found
        assert "violation_type" in data["detail"]
