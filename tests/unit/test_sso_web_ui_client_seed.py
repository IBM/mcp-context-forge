# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_sso_web_ui_client_seed.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Guards the seeded ``contextforge-web-ui`` Keycloak client and the
``compose-sso-seed-audience`` Makefile target.
"""

# Standard
import json
from pathlib import Path
import re
import shutil
import subprocess  # nosec B404

# Third-Party
import pytest

ROOT = Path(__file__).resolve().parents[2]
REALM_EXPORT = ROOT / "infra" / "keycloak" / "realm-export.json"
MAKEFILE = ROOT / "Makefile"
CLIENT_ID = "contextforge-web-ui"


@pytest.fixture(scope="module")
def client() -> dict:
    realm = json.loads(REALM_EXPORT.read_text(encoding="utf-8"))
    return next(c for c in realm["clients"] if c["clientId"] == CLIENT_ID)


def _makefile_default(variable: str) -> str:
    match = re.search(rf"^{variable} \?= (.+)$", MAKEFILE.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"{variable} default missing from Makefile"
    return match.group(1).strip()


def test_client_is_confidential_with_only_the_browser_flow(client: dict) -> None:
    assert client["publicClient"] is False
    assert client["standardFlowEnabled"] is True
    assert client["directAccessGrantsEnabled"] is False
    assert client["serviceAccountsEnabled"] is False


def test_client_requires_pkce_s256(client: dict) -> None:
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"


def test_redirect_uris_are_exact_matches(client: dict) -> None:
    assert client["redirectUris"]
    assert all("*" not in uri for uri in client["redirectUris"])


def test_audience_mapper_matches_makefile_default(client: dict) -> None:
    mapper = next(m for m in client["protocolMappers"] if m["protocolMapper"] == "oidc-audience-mapper")
    assert mapper["config"]["included.custom.audience"] == _makefile_default("SSO_SEED_API_AUDIENCE")
    assert mapper["config"]["access.token.claim"] == "true"


def test_client_carries_role_and_group_mappers(client: dict) -> None:
    claims = {m["config"].get("claim.name") for m in client["protocolMappers"]}
    assert {"groups", "realm_access.roles"} <= claims


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
def test_seed_target_expands_under_dry_run() -> None:
    result = subprocess.run(  # nosec B603 B607
        ["make", "-n", "compose-sso-seed-audience"], cwd=ROOT, capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert "/auth/sso/admin/providers/" in result.stdout
    assert "-H @-" in result.stdout
    assert "trusted_for_api_auth" in result.stdout
