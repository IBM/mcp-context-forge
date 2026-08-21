#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_container_scanner/test_api.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Integration tests for the external plugin server's HTTP endpoints.

Routes under test (all on the plugin server, not the mcpgateway main app):
    GET  /        — dashboard HTML
    GET  /health  — liveness probe
    GET  /scans   — list recent scan results
    POST /scan    — trigger a manual scan
"""

from __future__ import annotations

from datetime import datetime, timezone

# Third-Party
import pytest

# Local
from plugins.container_scanner.types import ScanResult, Summary


def make_scan_result(
    image_ref: str = "ghcr.io/org/app:v1",
    blocked: bool = False,
    image_digest: str | None = None,
) -> ScanResult:
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


class TestUIEndpoint:
    def test_root_serves_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Container Scanner" in response.text


class TestHealthEndpoint:
    def test_health_returns_healthy(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestListScansEndpoint:
    def test_list_scans_empty(self, client):
        response = client.get("/scans")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_scans_with_result(self, client, clean_repo):
        clean_repo.save(make_scan_result("ghcr.io/org/app:v1"))
        response = client.get("/scans")
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
        response = client.get("/scans")
        assert response.status_code == 200
        results = response.json()
        assert len(results) == 2
        assert results[0]["image_ref"] == "ghcr.io/org/app:v2"
        assert results[1]["image_ref"] == "ghcr.io/org/app:v1"

    def test_list_scans_blocked_result(self, client, clean_repo):
        clean_repo.save(make_scan_result("ghcr.io/org/app:bad", blocked=True))
        response = client.get("/scans")
        assert response.status_code == 200
        results = response.json()
        assert results[0]["blocked"] is True


class TestManualScanEndpoint:
    def test_scan_missing_image_ref_returns_400(self, client_with_plugin):
        client, _ = client_with_plugin
        response = client.post("/scan", json={})
        assert response.status_code == 400
        assert "image_ref" in response.json()["error"]

    def test_scan_empty_image_ref_returns_400(self, client_with_plugin):
        client, _ = client_with_plugin
        response = client.post("/scan", json={"image_ref": "   "})
        assert response.status_code == 400

    def test_scan_invalid_json_returns_400(self, client_with_plugin):
        client, _ = client_with_plugin
        response = client.post("/scan", content=b"not-json", headers={"content-type": "application/json"})
        assert response.status_code == 400

    def test_scan_allowed_result(self, client_with_plugin):
        client, mock_plugin = client_with_plugin
        mock_plugin.scan.return_value = make_scan_result("ghcr.io/org/app:v1")
        response = client.post("/scan", json={"image_ref": "ghcr.io/org/app:v1"})
        assert response.status_code == 200
        data = response.json()
        assert data["image_ref"] == "ghcr.io/org/app:v1"
        assert data["blocked"] is False

    def test_scan_blocked_result(self, client_with_plugin):
        client, mock_plugin = client_with_plugin
        mock_plugin.scan.return_value = make_scan_result("ghcr.io/org/app:bad", blocked=True)
        response = client.post("/scan", json={"image_ref": "ghcr.io/org/app:bad"})
        assert response.status_code == 200
        assert response.json()["blocked"] is True

    def test_scan_forwards_digest(self, client_with_plugin):
        digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        client, mock_plugin = client_with_plugin
        mock_plugin.scan.return_value = make_scan_result("ghcr.io/org/app:v1", image_digest=digest)
        client.post("/scan", json={"image_ref": "ghcr.io/org/app:v1", "image_digest": digest})
        mock_plugin.scan.assert_called_once_with("ghcr.io/org/app:v1", digest)

    def test_scan_no_server_returns_503(self, client):
        """Without a server wired in, POST /scan returns 503."""
        import plugins.container_scanner.server as srv
        original = srv._server  # pylint: disable=protected-access
        srv._server = None  # pylint: disable=protected-access
        try:
            response = client.post("/scan", json={"image_ref": "ghcr.io/org/app:v1"})
            assert response.status_code == 503
        finally:
            srv._server = original  # pylint: disable=protected-access
