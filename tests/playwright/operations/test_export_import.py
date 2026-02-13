# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Export/Import E2E Tests.

Tests the export and import workflow including full export, selective export,
import with conflict strategies, and permission checks.
"""

# Future
from __future__ import annotations

# Standard
import logging
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext
import pytest

logger = logging.getLogger(__name__)


class TestExport:
    """Test export functionality."""

    def test_full_export(self, admin_api: APIRequestContext):
        """Admin can perform a full export."""
        resp = admin_api.get("/export")
        assert resp.status == 200
        data = resp.json()
        assert "entities" in data

    def test_export_with_type_filter(self, admin_api: APIRequestContext):
        """Admin can export specific entity types."""
        resp = admin_api.get("/export?types=tools,servers")
        assert resp.status == 200
        data = resp.json()
        assert "entities" in data

    def test_export_includes_inactive(self, admin_api: APIRequestContext):
        """Admin can export including inactive entities."""
        resp = admin_api.get("/export?include_inactive=true")
        assert resp.status == 200

    @pytest.mark.xfail(reason="Server bug: 'Tool' object has no attribute 'rate_limit' (#2916)", strict=True)
    def test_selective_export(self, admin_api: APIRequestContext):
        """Admin can perform a selective export by entity IDs."""
        name = f"export-tool-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/tools/",
            data={
                "tool": {
                    "name": name,
                    "url": "https://httpbin.org/post",
                    "description": "Export test",
                    "integration_type": "REST",
                    "request_type": "POST",
                },
                "team_id": None,
            },
        )
        tool = create_resp.json()

        resp = admin_api.post("/export/selective", data={"tools": [tool["id"]]})
        assert resp.status == 200

        admin_api.delete(f"/tools/{tool['id']}")

    def test_non_admin_cannot_export(self, non_admin_api: APIRequestContext):
        """Non-admin user is denied export."""
        resp = non_admin_api.get("/export")
        assert resp.status in (401, 403), f"Non-admin export should be denied, got {resp.status}"


class TestImport:
    """Test import functionality."""

    def test_dry_run_import(self, admin_api: APIRequestContext):
        """Admin can dry-run an import to preview changes."""
        export_resp = admin_api.get("/export?types=servers")
        if export_resp.status != 200:
            pytest.skip("Export not available")
        export_data = export_resp.json()

        # Import endpoint expects body wrapped in import_data
        resp = admin_api.post("/import?dry_run=true&conflict_strategy=skip", data={"import_data": export_data})
        assert resp.status == 200
        result = resp.json()
        assert "status" in result or "results" in result

    def test_import_with_skip_strategy(self, admin_api: APIRequestContext):
        """Admin can import with skip conflict strategy."""
        export_resp = admin_api.get("/export?types=servers")
        if export_resp.status != 200:
            pytest.skip("Export not available")
        export_data = export_resp.json()

        resp = admin_api.post("/import?conflict_strategy=skip", data={"import_data": export_data})
        assert resp.status == 200

    def test_import_status_list(self, admin_api: APIRequestContext):
        """Admin can list import statuses."""
        resp = admin_api.get("/import/status")
        assert resp.status == 200

    def test_non_admin_cannot_import(self, non_admin_api: APIRequestContext):
        """Non-admin user is denied import."""
        resp = non_admin_api.post("/import", data={})
        assert resp.status in (401, 403, 422), f"Non-admin import should be denied, got {resp.status}"
