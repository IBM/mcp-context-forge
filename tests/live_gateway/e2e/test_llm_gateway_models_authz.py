# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_llm_gateway_models_authz.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box tests for the permission check on the gateway model list.

``GET /llm/gateway/models`` and its ``/v1`` alias list the models of the registered
providers. The tests prove that the route requires the ``llm.read`` permission: a caller
with no role or without ``llm.read`` receives 403, a caller with ``llm.read`` receives the
models, and an anonymous caller receives 401.

Every account, role and grant is created through the HTTP API of a private gateway
subprocess (see ``isolated_gateway``). No Docker stack is required.
"""

# Future
from __future__ import annotations

# Standard
from typing import Any

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers
from tests.live_gateway.e2e.test_candidate_credential_handshake import _GatewayFixture, isolated_gateway  # noqa: F401  pylint: disable=unused-import

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.parametrize("isolated_gateway", [{"LLMCHAT_ENABLED": "true", "AUTO_CREATE_PERSONAL_TEAMS": "false"}], ids=["llmchat"], indirect=True),
]

_PASSWORD = "E2eLlmModelsAuthz!42"  # pragma: allowlist secret
_PATHS = ("/v1/llm/gateway/models", "/llm/gateway/models")
_NONE = "none@example.com"
_NOREAD = "noread@example.com"
_READER = "reader@example.com"
_VIEWER = "viewer@example.com"
_MODEL_ID = "authz-model"


def _setup(client: httpx.Client, method: str, path: str, step: str, *, expected: tuple[int, ...] = (200, 201), **kwargs: Any) -> Any:
    """Send a setup request and return its JSON body.

    Raises:
        RuntimeError: If the response status is not in ``expected``.
    """
    response = client.request(method, path, **kwargs)
    if response.status_code not in expected:
        raise RuntimeError(f"setup: {step} {response.status_code} {response.text[:300]}")
    return response.json() if response.content else None


def _login(base_url: str, email: str) -> str:
    """Log in as ``email`` and return the session token."""
    with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as anonymous:
        return _setup(anonymous, "POST", "/auth/email/login", f"login {email}", json={"email": email, "password": _PASSWORD})["access_token"]


def _get(base_url: str, path: str, token: str | None) -> httpx.Response:
    """GET ``path`` with ``token``, or with no credentials when ``token`` is ``None``."""
    headers = make_auth_headers(token) if token else {}
    with httpx.Client(base_url=base_url, headers=headers, timeout=30, trust_env=False) as client:
        return client.get(path)


def test_gateway_models_requires_llm_read(isolated_gateway: _GatewayFixture) -> None:  # noqa: F811  pylint: disable=redefined-outer-name
    """The gateway model list needs ``llm.read`` on both route aliases."""
    admin, _token, base_url, _key = isolated_gateway

    provider = _setup(admin, "POST", "/v1/llm/providers", "provider", json={"name": "authz-provider", "provider_type": "openai", "api_base": "https://llm.invalid/v1", "enabled": True})
    _setup(admin, "POST", "/v1/llm/models", "model", json={"model_id": _MODEL_ID, "model_name": "Authz Model", "provider_id": provider["id"], "supports_chat": True, "enabled": True})

    for email in (_NONE, _NOREAD, _READER, _VIEWER):
        _setup(
            admin,
            "POST",
            "/auth/email/admin/users",
            f"user {email}",
            expected=(201,),
            json={"email": email, "password": _PASSWORD, "full_name": email.split("@")[0], "is_admin": False, "is_active": True, "password_change_required": False},
        )

    viewer_role = next(role for role in _setup(admin, "GET", "/rbac/roles", "list roles") if role["name"] == "platform_viewer")
    for email in (_NONE, _NOREAD, _READER):
        _setup(admin, "DELETE", f"/rbac/users/{email}/roles/{viewer_role['id']}", f"revoke platform_viewer {email}", params={"scope": "global"})
        remaining = _setup(admin, "GET", f"/rbac/users/{email}/roles", f"roles {email}")
        if remaining:
            raise RuntimeError(f"setup: {email} still holds roles {remaining}")

    no_llm_read = _setup(admin, "POST", "/rbac/roles", "role no-llm-read", json={"name": "no-llm-read", "scope": "global", "permissions": ["servers.read", "teams.read", "tools.read"]})
    llm_reader = _setup(admin, "POST", "/rbac/roles", "role llm-reader", json={"name": "llm-reader", "scope": "global", "permissions": ["llm.read"]})
    for email, role in ((_NOREAD, no_llm_read), (_READER, llm_reader)):
        _setup(admin, "POST", f"/rbac/users/{email}/roles", f"grant {role['name']} {email}", json={"role_id": role["id"], "scope": "global", "scope_id": None})

    sessions = {name: _login(base_url, email) for name, email in (("none", _NONE), ("noread", _NOREAD), ("reader", _READER), ("viewer", _VIEWER))}
    expected = {"none": 403, "noread": 403, "reader": 200, "viewer": 200, "admin": 200, "anonymous": 401}
    tokens = {**sessions, "admin": _token, "anonymous": None}

    mismatches = []
    for path in _PATHS:
        for principal, status in expected.items():
            response = _get(base_url, path, tokens[principal])
            if response.status_code != status:
                mismatches.append((principal, path, response.status_code))
            elif principal == "reader":
                assert _MODEL_ID in [model["model_id"] for model in response.json()["models"]], f"reader: {path} omits {_MODEL_ID}: {response.text[:300]}"
    assert not mismatches, f"(principal, path, got) mismatches: {mismatches}"

    control = _get(base_url, "/v1/llmchat/gateway/models", sessions["noread"])
    assert control.status_code == 403, f"llmchat route: expected 403, got {control.status_code}: {control.text[:300]}"
