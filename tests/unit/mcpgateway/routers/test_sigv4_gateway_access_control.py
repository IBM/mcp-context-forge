# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_sigv4_gateway_access_control.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Access control of SigV4 gateway create and update.

Developers keep ``gateways.create`` and ``gateways.update``, so these tests pin the deny paths
(unauthenticated, insufficient permission, wrong team, public-only token) and the positive
developer path. RBAC, token scoping and persistence are real. Only the upstream handshake is stubbed.
"""

# Future
from __future__ import annotations

# Standard
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.utils.sigv4 import access_key_fingerprint, decrypt_sigv4_secret

# Local
from tests.unit.mcpgateway.routers.test_mcp_servers_test_endpoint_authz import HANDSHAKE

pytest_plugins = ["tests.unit.mcpgateway.routers.test_mcp_servers_test_endpoint_authz"]

SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"  # pragma: allowlist secret
ROTATED_SECRET = "rotatedSecretAccessKeyValue0123456789ABCD"  # pragma: allowlist secret
ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret
CONFIG = {"access_key_id": ACCESS_KEY_ID, "secret_access_key": SECRET, "region": "us-east-1", "service": "execute-api"}  # pragma: allowlist secret
GATEWAYS = "/gateways"


def _payload(name: str, **overrides: Any) -> Dict[str, Any]:
    body = {"name": name, "url": f"https://{name}.example.com/mcp", "transport": "STREAMABLEHTTP", "auth_type": "sigv4", "sigv4_config": dict(CONFIG)}
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def stub_handshake():
    """Replace the upstream handshake so registration and update need no network."""
    empty = ({"prompts": {}, "resources": {}, "tools": {}}, [], [], [], [], None)
    with patch.object(GatewayService, "_initialize_gateway", AsyncMock(return_value=empty)):
        yield


def _stored_config(env, gateway_id: str) -> Dict[str, Any]:
    with env.session_factory() as db:
        return dict(db.get(DbGateway, gateway_id).sigv4_config)


def _gateway_count(env, name: str) -> int:
    with env.session_factory() as db:
        return db.query(DbGateway).filter(DbGateway.name == name).count()


def _add_sigv4_gateway(env, gateway_id: str, *, owner_email: str, team_id: str, visibility: str = "team") -> None:
    """Persist a SigV4 gateway the way registration stores it."""
    # First-Party
    from mcpgateway.services.encryption_service import protect_sigv4_config_sync

    with env.session_factory() as db:
        db.add(
            DbGateway(
                id=gateway_id,
                name=gateway_id,
                slug=gateway_id,
                url=f"https://{gateway_id}.example.com/mcp",
                description="synthetic",
                transport="STREAMABLEHTTP",
                capabilities={},
                enabled=True,
                reachable=True,
                auth_type="sigv4",
                sigv4_config=protect_sigv4_config_sync(dict(CONFIG)),
                visibility=visibility,
                owner_email=owner_email,
                team_id=team_id,
            )
        )
        db.commit()


class TestCreateDenyPaths:
    def test_unauthenticated_caller_is_rejected(self, env):
        r = env.client.post(GATEWAYS, json=_payload("aws-anon"))

        assert r.status_code == 401, r.text
        assert _gateway_count(env, "aws-anon") == 0

    def test_caller_without_gateways_create_is_rejected(self, env):
        r = env.client.post(GATEWAYS, headers=env.token("viewer@example.com"), json=_payload("aws-viewer"))

        assert r.status_code == 403, r.text
        assert _gateway_count(env, "aws-viewer") == 0

    def test_api_token_scoped_without_gateways_create_is_rejected(self, env, teams):
        headers = env.token("dev-a1@example.com", "api", teams=[teams["a"]], scopes={"permissions": ["gateways.read"]})

        r = env.client.post(GATEWAYS, headers=headers, json=_payload("aws-scoped"))

        assert r.status_code == 403, r.text
        assert _gateway_count(env, "aws-scoped") == 0

    @pytest.mark.parametrize("visibility", ["public", "team", "private"])
    def test_developer_with_a_public_only_token_is_rejected(self, env, teams, visibility):
        """A team developer holds ``gateways.create`` only inside a team, so a public-only token has none."""
        headers = env.token("dev-a1@example.com", "api", teams=[])

        r = env.client.post(GATEWAYS, headers=headers, json=_payload(f"aws-dev-public-only-{visibility}", visibility=visibility))

        assert r.status_code == 403, r.text
        assert _gateway_count(env, f"aws-dev-public-only-{visibility}") == 0

    @pytest.mark.parametrize("visibility", ["team", "private"])
    def test_public_only_token_cannot_create_a_non_public_gateway(self, env, teams, visibility):
        """The route rejects a non-public gateway for a caller whose permission is global but whose token is public-only."""
        headers = env.token("admin@example.com", "api", teams=[])

        r = env.client.post(GATEWAYS, headers=headers, json=_payload(f"aws-public-only-{visibility}", visibility=visibility))

        assert r.status_code == 403, r.text
        assert "Public-only" in r.json()["message"]
        assert _gateway_count(env, f"aws-public-only-{visibility}") == 0

    def test_public_only_token_cannot_place_a_gateway_in_a_team(self, env, teams):
        headers = env.token("admin@example.com", "api", teams=[])

        r = env.client.post(GATEWAYS, headers=headers, json=_payload("aws-public-only-team", visibility="public", team_id=teams["a"]))

        assert r.status_code == 200, r.text
        with env.session_factory() as db:
            assert db.query(DbGateway).filter(DbGateway.name == "aws-public-only-team").one().team_id is None

    def test_token_for_another_team_cannot_create_in_a_team(self, env, teams):
        headers = env.token("dev-b@example.com", "api", teams=[teams["b"]])

        r = env.client.post(GATEWAYS, headers=headers, json=_payload("aws-cross-team", visibility="team", team_id=teams["a"]))

        assert r.status_code == 403, r.text
        assert _gateway_count(env, "aws-cross-team") == 0


class TestUpdateDenyPaths:
    @pytest.fixture
    def team_gateway(self, env, teams):
        _add_sigv4_gateway(env, "aws-team-a", owner_email="dev-a1@example.com", team_id=teams["a"])
        return "aws-team-a"

    def _rotate(self, env, headers, gateway_id):
        return env.client.put(f"{GATEWAYS}/{gateway_id}", headers=headers, json={"auth_type": "sigv4", "sigv4_config": {**CONFIG, "secret_access_key": ROTATED_SECRET}})

    def _assert_credential_untouched(self, env, gateway_id, before):
        after = _stored_config(env, gateway_id)
        assert after == before
        assert decrypt_sigv4_secret("secret_access_key", after["secret_access_key"]) == SECRET

    def test_unauthenticated_caller_is_rejected(self, env, team_gateway):
        before = _stored_config(env, team_gateway)

        r = env.client.put(f"{GATEWAYS}/{team_gateway}", json={"description": "x"})

        assert r.status_code == 401, r.text
        self._assert_credential_untouched(env, team_gateway, before)

    def test_caller_without_gateways_update_is_rejected(self, env, teams, team_gateway):
        before = _stored_config(env, team_gateway)

        r = self._rotate(env, env.token("viewer@example.com"), team_gateway)

        assert r.status_code == 403, r.text
        self._assert_credential_untouched(env, team_gateway, before)

    def test_api_token_scoped_without_gateways_update_is_rejected(self, env, teams, team_gateway):
        before = _stored_config(env, team_gateway)
        headers = env.token("dev-a1@example.com", "api", teams=[teams["a"]], scopes={"permissions": ["gateways.read"]})

        r = self._rotate(env, headers, team_gateway)

        assert r.status_code == 403, r.text
        self._assert_credential_untouched(env, team_gateway, before)

    def test_developer_of_another_team_cannot_rotate_the_credential(self, env, teams, team_gateway):
        before = _stored_config(env, team_gateway)

        r = self._rotate(env, env.token("dev-b@example.com", teams=[teams["b"]]), team_gateway)

        assert r.status_code == 403, r.text
        self._assert_credential_untouched(env, team_gateway, before)

    def test_same_team_developer_who_is_not_the_owner_cannot_rotate_the_credential(self, env, teams, team_gateway):
        before = _stored_config(env, team_gateway)

        r = self._rotate(env, env.token("dev-a2@example.com", teams=[teams["a"]]), team_gateway)

        assert r.status_code == 403, r.text
        self._assert_credential_untouched(env, team_gateway, before)

    def test_public_only_token_cannot_rotate_a_team_gateway_credential(self, env, teams, team_gateway):
        before = _stored_config(env, team_gateway)

        r = self._rotate(env, env.token("dev-a1@example.com", "api", teams=[]), team_gateway)

        assert r.status_code == 403, r.text
        self._assert_credential_untouched(env, team_gateway, before)


class TestDeveloperKeepsAccess:
    """A developer can create, rotate and read back a SigV4 gateway they own."""

    def test_developer_creates_and_rotates_a_sigv4_gateway(self, env, teams):
        headers = env.token("dev-a1@example.com", teams=[teams["a"]])

        created = env.client.post(GATEWAYS, headers=headers, json=_payload("aws-dev", visibility="team", team_id=teams["a"]))

        assert created.status_code == 200, created.text
        gateway_id = created.json()["id"]
        stored = _stored_config(env, gateway_id)
        assert stored["access_key_id"] == ACCESS_KEY_ID
        assert decrypt_sigv4_secret("secret_access_key", stored["secret_access_key"]) == SECRET
        assert SECRET not in created.text

        rotated = env.client.put(f"{GATEWAYS}/{gateway_id}", headers=headers, json={"auth_type": "sigv4", "sigv4_config": {**CONFIG, "secret_access_key": ROTATED_SECRET}})

        assert rotated.status_code == 200, rotated.text
        assert decrypt_sigv4_secret("secret_access_key", _stored_config(env, gateway_id)["secret_access_key"]) == ROTATED_SECRET
        assert ROTATED_SECRET not in rotated.text

    def test_registration_and_rotation_are_attributed_to_the_key_fingerprint(self, env, teams):
        headers = env.token("dev-a1@example.com", teams=[teams["a"]])
        fingerprint = access_key_fingerprint(ACCESS_KEY_ID)

        with patch("mcpgateway.services.gateway_service.audit_trail") as audit:
            created = env.client.post(GATEWAYS, headers=headers, json=_payload("aws-dev-audit", visibility="team", team_id=teams["a"]))
            gateway_id = created.json()["id"]
            env.client.put(f"{GATEWAYS}/{gateway_id}", headers=headers, json={"auth_type": "sigv4", "sigv4_config": {**CONFIG, "secret_access_key": ROTATED_SECRET}})

        entries = {call.kwargs["action"]: call.kwargs for call in audit.log_action.call_args_list}
        assert entries["create_gateway"]["new_values"]["sigv4_key_fingerprint"] == fingerprint
        assert entries["update_gateway"]["new_values"]["sigv4_credential_rotated"] is True
        assert entries["update_gateway"]["new_values"]["sigv4_previous_key_fingerprint"] == fingerprint
        rendered = repr(entries)
        for forbidden in (SECRET, ROTATED_SECRET, ACCESS_KEY_ID):
            assert forbidden not in rendered


class TestCredentialsAreEncryptedAtRest:
    """No stored column of a SigV4 gateway row holds a plaintext secret."""

    def test_raw_row_holds_no_plaintext_secret_or_session_token(self, env, teams):
        # Third-Party
        from sqlalchemy import text

        session_token = "FwoGZXIvYXdzEXAMPLESESSIONTOKEN0123456789"  # pragma: allowlist secret
        headers = env.token("dev-a1@example.com", teams=[teams["a"]])
        body = _payload("aws-at-rest", visibility="team", team_id=teams["a"])
        body["sigv4_config"]["session_token"] = session_token

        created = env.client.post(GATEWAYS, headers=headers, json=body)
        assert created.status_code == 200, created.text

        with env.session_factory() as db:
            row = db.execute(text("SELECT * FROM gateways WHERE id = :id"), {"id": created.json()["id"]}).mappings().one()
        rendered = repr(dict(row))
        assert SECRET not in rendered
        assert session_token not in rendered
        assert ACCESS_KEY_ID in rendered


class TestStoredCredentialConfusedDeputy:
    """The handshake endpoint signs with the stored credential only for a caller who owns the gateway."""

    def _handshake(self, env, auth, gateway_url, **payload):
        return env.client.post(HANDSHAKE, headers=auth, json={"base_url": gateway_url, **payload})

    def test_caller_without_ownership_cannot_use_the_stored_credential(self, env, teams):
        _add_sigv4_gateway(env, "aws-handshake", owner_email="dev-a1@example.com", team_id=teams["a"], visibility="public")
        url = "https://aws-handshake.example.com/mcp"

        r = self._handshake(env, env.token("viewer@example.com"), url, path="admin/x")

        assert r.status_code == 403, r.text
        assert env.recorder.calls == []

    def test_caller_supplied_headers_do_not_unlock_the_stored_credential(self, env, teams):
        _add_sigv4_gateway(env, "aws-handshake", owner_email="dev-a1@example.com", team_id=teams["a"], visibility="public")
        url = "https://aws-handshake.example.com/mcp"

        r = self._handshake(env, env.token("dev-b@example.com", teams=[teams["b"]]), url, headers={"X-Custom": "1"})

        assert r.status_code == 403, r.text
        assert env.recorder.calls == []
