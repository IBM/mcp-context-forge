#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_container_scanner/test_api.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Integration tests for container scanner REST API endpoints.
Verifies that the router reads from the shared singleton repository.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Third-Party
import pytest

# Local
from plugins.container_scanner.types import ScanResult, Summary


def make_scan_result(image_ref: str = "ghcr.io/org/app:v1", blocked: bool = False, image_digest: str | None = None) -> ScanResult:
    return ScanResult(
        image_ref=image_ref,
        image_digest=image_digest,
        scanners="trivy",
        scan_time=datetime.now(timezone.utc),
        duration_ms=100,
        vulnerabilities=[],
        summary=Summary(critical_count=0, high_count=0, medium_count=0, low_count=0),
        blocked=blocked,
        reason=None,
        scan_error=None,
    )


class TestHealthEndpoint:
    def test_health_empty(self, client, clean_repo):
        response = client.get("/container-scanner/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["count"] == 0

    def test_health_with_results(self, client, clean_repo):
        clean_repo.save(make_scan_result())
        response = client.get("/container-scanner/health")
        assert response.status_code == 200
        assert response.json()["count"] == 1


class TestListScansEndpoint:
    def test_list_scans_empty(self, client):
        response = client.get("/container-scanner/scans")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_scans_with_result(self, client, clean_repo):
        clean_repo.save(make_scan_result("ghcr.io/org/app:v1"))
        response = client.get("/container-scanner/scans")
        assert response.status_code == 200
        results = response.json()
        assert len(results) == 1
        assert results[0]["image_ref"] == "ghcr.io/org/app:v1"
        assert results[0]["blocked"] is False
        assert "scan_time" in results[0]
        assert "summary" in results[0]

    def test_list_scans_most_recent_first(self, client, clean_repo):
        clean_repo.save(make_scan_result("ghcr.io/org/app:v1"))
        clean_repo.save(make_scan_result("ghcr.io/org/app:v2"))
        response = client.get("/container-scanner/scans")
        assert response.status_code == 200
        results = response.json()
        assert len(results) == 2
        assert results[0]["image_ref"] == "ghcr.io/org/app:v2"
        assert results[1]["image_ref"] == "ghcr.io/org/app:v1"


class TestGetScanEndpoint:
    def test_get_scan_not_found(self, client, clean_repo):
        response = client.get("/container-scanner/scans/unknown:tag")
        assert response.status_code == 404

    def test_get_scan_by_image_ref(self, client, clean_repo):
        clean_repo.save(make_scan_result("ghcr.io/org/app:v1"))
        response = client.get("/container-scanner/scans/ghcr.io/org/app:v1")
        assert response.status_code == 200
        assert response.json()["image_ref"] == "ghcr.io/org/app:v1"

    def test_get_scan_by_digest(self, client, clean_repo):
        digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        clean_repo.save(make_scan_result("ghcr.io/org/app:v1", image_digest=digest))
        response = client.get(f"/container-scanner/scans/{digest}")
        assert response.status_code == 200
        assert response.json()["image_digest"] == digest

    def test_get_scan_blocked_result(self, client, clean_repo):
        clean_repo.save(make_scan_result("ghcr.io/org/app:bad", blocked=True))
        response = client.get("/container-scanner/scans/ghcr.io/org/app:bad")
        assert response.status_code == 200
        assert response.json()["blocked"] is True


class TestAuthentication:
    def test_unauthenticated_returns_401(self, clean_repo):
        """Requests without auth override are rejected."""
        from fastapi.testclient import TestClient
        from mcpgateway.main import app

        unauthenticated_client = TestClient(app, raise_server_exceptions=False)
        response = unauthenticated_client.get("/container-scanner/health")
        assert response.status_code in (401, 403)
