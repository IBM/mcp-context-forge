# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_admin_ui_tag_consistency.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Integration tests for Admin UI and backend tag validation consistency.

This module verifies that the Admin UI correctly receives and uses the backend's
tag validation configuration (VALIDATION_MIN_TAG_LENGTH, VALIDATION_MAX_TAG_LENGTH),
ensuring consistent validation behavior across API and UI.

Related bug: Admin UI tag filter ignores VALIDATION_MAX_TAG_LENGTH config - hardcoded 50-char limit
Related issue: #5333
"""

# Standard
import os
import re
import tempfile
from unittest.mock import MagicMock

# Third-Party
import pytest
from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.utils.verify_credentials import require_auth


@pytest.fixture
def test_app():
    """Create test app with proper database setup."""
    mp = MonkeyPatch()

    # Create temp SQLite file
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # Patch settings
    mp.setattr(settings, "database_url", url, raising=False)

    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestingSessionLocal, raising=False)

    db_mod.Base.metadata.create_all(bind=engine)

    app = main_mod.app

    # Override auth dependency
    def override_require_auth():
        return {"email": "admin@example.com", "is_admin": True}

    def override_get_current_user():
        return {"email": "admin@example.com", "is_admin": True}

    app.dependency_overrides[require_auth] = override_require_auth
    app.dependency_overrides[get_current_user] = override_get_current_user

    yield app

    # Cleanup
    mp.undo()
    db_mod.Base.metadata.drop_all(bind=engine)
    engine.dispose()
    try:
        os.close(fd)
        os.unlink(path)
    except Exception:
        pass


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Dummy Bearer token accepted by the overridden dependency."""
    return {"Authorization": "Bearer test.token.tag_consistency"}


@pytest.fixture
def db_session(test_app):
    """Create a test database session."""
    import mcpgateway.db as db_mod
    session = db_mod.SessionLocal()
    try:
        yield session
    finally:
        session.close()


class TestAdminUITagConsistency:
    """Test suite for Admin UI and backend tag validation consistency."""

    def test_admin_ui_receives_tag_length_config(self, client: TestClient, auth_headers: dict) -> None:
        """Admin UI template should receive validation_max_tag_length and validation_min_tag_length."""
        response = client.get("/admin", headers=auth_headers)
        assert response.status_code == 200

        # Check that GATEWAY_CONFIG object is present in the HTML
        assert "window.GATEWAY_CONFIG" in response.text

        # Extract the config object using regex
        config_match = re.search(
            r"window\.GATEWAY_CONFIG\s*=\s*\{[^}]+\}",
            response.text,
            re.DOTALL
        )
        assert config_match is not None, "GATEWAY_CONFIG object not found in admin page"

        config_text = config_match.group(0)

        # Verify validationMinTagLength is present and matches config
        assert "validationMinTagLength" in config_text
        assert str(settings.validation_min_tag_length) in config_text

        # Verify validationMaxTagLength is present and matches config
        assert "validationMaxTagLength" in config_text
        assert str(settings.validation_max_tag_length) in config_text

    def test_admin_ui_config_values_match_backend_settings(self, client: TestClient, auth_headers: dict) -> None:
        """Verify that the config values in the UI exactly match the backend settings."""
        response = client.get("/admin", headers=auth_headers)
        assert response.status_code == 200

        # Extract the actual numeric values from the JavaScript
        min_match = re.search(r"validationMinTagLength:\s*(\d+)", response.text)
        max_match = re.search(r"validationMaxTagLength:\s*(\d+)", response.text)

        assert min_match is not None, "validationMinTagLength value not found"
        assert max_match is not None, "validationMaxTagLength value not found"

        ui_min_length = int(min_match.group(1))
        ui_max_length = int(max_match.group(1))

        # Assert exact match with backend settings
        assert ui_min_length == settings.validation_min_tag_length, (
            f"UI min tag length ({ui_min_length}) does not match "
            f"backend setting ({settings.validation_min_tag_length})"
        )
        assert ui_max_length == settings.validation_max_tag_length, (
            f"UI max tag length ({ui_max_length}) does not match "
            f"backend setting ({settings.validation_max_tag_length})"
        )

    def test_backend_accepts_tags_up_to_configured_limit(
        self,
        client: TestClient,
        auth_headers: dict
    ) -> None:
        """Verify backend accepts tags up to VALIDATION_MAX_TAG_LENGTH."""
        max_length = settings.validation_max_tag_length

        # Create a tag at the maximum length
        long_tag = "a" * max_length

        # Create a resource with the long tag
        resource_data = {
            "uri": "resource://test/long-tag-test",
            "name": "Test Resource",
            "content": "Test content",
            "tags": [long_tag, "short-tag"]
        }

        response = client.post("/resources", json=resource_data, headers=auth_headers)
        assert response.status_code == 201, f"Backend rejected tag at max length: {response.text}"

        resource = response.json()
        # Extract tag IDs from response
        tag_ids = [tag["id"] for tag in resource.get("tags", [])]

        # Both tags should be present (normalized to lowercase)
        assert long_tag.lower() in tag_ids
        assert "short-tag" in tag_ids

    def test_backend_rejects_tags_exceeding_configured_limit(
        self,
        client: TestClient,
        auth_headers: dict
    ) -> None:
        """Verify backend rejects tags exceeding VALIDATION_MAX_TAG_LENGTH."""
        max_length = settings.validation_max_tag_length

        # Create a tag that exceeds the maximum length
        too_long_tag = "a" * (max_length + 1)

        # Attempt to create a resource with the too-long tag
        resource_data = {
            "uri": "resource://test/too-long-tag-test",
            "name": "Test Resource",
            "content": "Test content",
            "tags": [too_long_tag, "short-tag"]
        }

        response = client.post("/resources", json=resource_data, headers=auth_headers)

        # The backend silently filters out invalid tags, so the request succeeds
        # but the too-long tag is not included
        assert response.status_code == 201

        resource = response.json()
        tag_ids = [tag["id"] for tag in resource.get("tags", [])]

        # Only the short tag should be present
        assert "short-tag" in tag_ids
        assert too_long_tag.lower() not in tag_ids

    @pytest.mark.parametrize("tag_length", [50, 100, 150])
    def test_ui_consistency_with_various_tag_lengths(
        self,
        client: TestClient,
        auth_headers: dict,
        tag_length: int
    ) -> None:
        """Verify UI and backend remain consistent for various tag lengths."""
        # This test verifies that for any configured limit, both UI and backend agree

        # Get current configured max length
        configured_max = settings.validation_max_tag_length

        # Create a tag at the test length
        test_tag = "x" * tag_length

        # Backend behavior
        resource_data = {
            "uri": f"resource://test/tag-length-{tag_length}",
            "name": f"Test Resource {tag_length}",
            "content": "Test content",
            "tags": [test_tag]
        }

        response = client.post("/resources", json=resource_data, headers=auth_headers)
        assert response.status_code == 201

        resource = response.json()
        tag_ids = [tag["id"] for tag in resource.get("tags", [])]

        # Verify backend behavior matches expected
        if tag_length <= configured_max:
            # Tag should be accepted
            assert test_tag.lower() in tag_ids, (
                f"Backend rejected {tag_length}-char tag despite "
                f"configured limit of {configured_max}"
            )
        else:
            # Tag should be rejected (silently filtered)
            assert test_tag.lower() not in tag_ids, (
                f"Backend accepted {tag_length}-char tag despite "
                f"configured limit of {configured_max}"
            )

        # UI behavior - verify the config is exposed correctly
        admin_response = client.get("/admin", headers=auth_headers)
        assert response.status_code == 200
        assert str(configured_max) in admin_response.text


class TestTagValidationConfigDefaults:
    """Test default tag validation configuration values."""

    def test_validation_max_tag_length_default(self) -> None:
        """Verify VALIDATION_MAX_TAG_LENGTH has correct default."""
        assert settings.validation_max_tag_length == 100, (
            "Default VALIDATION_MAX_TAG_LENGTH should be 100"
        )

    def test_validation_min_tag_length_default(self) -> None:
        """Verify VALIDATION_MIN_TAG_LENGTH has correct default."""
        assert settings.validation_min_tag_length == 2, (
            "Default VALIDATION_MIN_TAG_LENGTH should be 2"
        )

    def test_validation_tag_length_ranges(self) -> None:
        """Verify tag length config values are within valid ranges."""
        # Min tag length: 1-10
        assert 1 <= settings.validation_min_tag_length <= 10, (
            f"VALIDATION_MIN_TAG_LENGTH ({settings.validation_min_tag_length}) "
            "must be between 1 and 10"
        )

        # Max tag length: 10-255
        assert 10 <= settings.validation_max_tag_length <= 255, (
            f"VALIDATION_MAX_TAG_LENGTH ({settings.validation_max_tag_length}) "
            "must be between 10 and 255"
        )
