"""Keycloak fixture — Realm/client matches the bundled ``infra/keycloak/realm-export.json``.

The ``sso`` docker-compose profile brings this up on ``localhost:8180``.
Start it via ``docker compose --profile sso up keycloak`` before running
the OAuth tests here; otherwise every test that requests this fixture
skips with a readable reason.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import httpx
import pytest


@dataclass(frozen=True)
class KeycloakConfig:
    base_url: str
    realm: str
    client_id: str
    client_secret: str
    token_endpoint: str

    def fetch_client_credentials_token(self) -> Optional[str]:
        """Fetch a token via the client_credentials grant. Returns None on failure."""
        try:
            resp = httpx.post(
                self.token_endpoint,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=5,
            )
        except Exception:  # noqa: BLE001 — any network error means unreachable
            return None
        if resp.status_code != 200:
            return None
        body = resp.json()
        return body.get("access_token")


def _is_keycloak_reachable(base_url: str, timeout: float = 2.0) -> bool:
    # Keycloak's realm discovery is a reliable "is it up" probe.
    try:
        resp = httpx.get(f"{base_url}/realms/master", timeout=timeout)
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def keycloak() -> KeycloakConfig:
    """Return a configured Keycloak handle or skip the test if KC isn't reachable."""
    base_url = os.getenv("KEYCLOAK_BASE_URL", "http://localhost:8180")
    if not _is_keycloak_reachable(base_url):
        pytest.skip(f"Keycloak not reachable at {base_url}. Start it via " "`docker compose --profile sso up -d keycloak` and rerun.")
    realm = os.getenv("KEYCLOAK_REALM", "mcp-gateway")
    return KeycloakConfig(
        base_url=base_url,
        realm=realm,
        client_id=os.getenv("KEYCLOAK_CLIENT_ID", "mcp-gateway"),
        client_secret=os.getenv("KEYCLOAK_CLIENT_SECRET", "keycloak-dev-secret"),
        token_endpoint=f"{base_url}/realms/{realm}/protocol/openid-connect/token",
    )
