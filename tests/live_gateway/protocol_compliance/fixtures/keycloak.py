# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/protocol_compliance/fixtures/keycloak.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Keycloak fixture — Realm/client matches the bundled ``infra/keycloak/realm-export.json``.

The ``sso`` docker-compose profile brings this up on ``localhost:8180``.
Start it via ``docker compose --profile sso up keycloak`` before running
the OAuth tests here; otherwise every test that requests this fixture
skips with a readable reason.
"""

from __future__ import annotations

import os
import sys
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

    @property
    def token_endpoint(self) -> str:
        """Derived from ``base_url`` + ``realm`` — kept here so the two
        can't drift (previously stored as a separate field and computed
        at fixture-build time, which invited bugs if either source
        changed after construction)."""
        return f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token"

    def fetch_client_credentials_token(self) -> Optional[str]:
        """Fetch a token via the client_credentials grant.

        Returns the token string on success, ``None`` on failure.

        Failure modes (network error / non-200 / missing access_token field)
        write a short diagnostic to stderr so tests that skip with
        "couldn't obtain token" point at the actual root cause — e.g. a
        realm-export change that disabled service accounts would otherwise
        look identical to Keycloak being unreachable.
        """
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
        except Exception as exc:  # noqa: BLE001 — any network error means unreachable
            print(f"[keycloak] client_credentials fetch network error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return None
        if resp.status_code != 200:
            print(f"[keycloak] client_credentials grant returned {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
            return None
        body = resp.json()
        token = body.get("access_token")
        if not token:
            print(f"[keycloak] grant returned 200 but no access_token in body: {body!r}", file=sys.stderr)
        return token

    def __repr__(self) -> str:
        # fmt: off
        return (  # redacts secret; placeholder literal not a real credential
            f"KeycloakConfig(base_url={self.base_url!r}, realm={self.realm!r}, "
            f"client_id={self.client_id!r}, client_secret='***', "  # pragma: allowlist secret
            f"token_endpoint={self.token_endpoint!r})"
        )
        # fmt: on


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
    )
