# -*- coding: utf-8 -*-
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.utils.verify_credentials import require_admin_auth


def test_metrics_config_includes_delete_raw_after_rollup_hours(app):
    app.dependency_overrides[require_admin_auth] = lambda: "test_admin"
    client = TestClient(app)

    response = client.get("/api/metrics/config")

    assert response.status_code == 200
    payload = response.json()
    assert "rollup" in payload
    assert "delete_raw_after_rollup_hours" in payload["rollup"]

    app.dependency_overrides.pop(require_admin_auth, None)
