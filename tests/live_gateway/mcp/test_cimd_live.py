# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_cimd_live.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box test for the public Client ID Metadata Document (CIMD) endpoints.

An authorization server fetches these URLs without credentials, so the test
sends no ``Authorization`` header.
"""

# Third-Party
import httpx
import pytest

# Local
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

DOCUMENT_PATH = "/oauth/client-metadata.json"
JWKS_PATH = "/oauth/client-metadata/jwks.json"


def test_client_metadata_document_is_public_and_self_describing() -> None:
    response = httpx.get(f"{BASE_URL}{DOCUMENT_PATH}", timeout=10)

    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("public, max-age=")
    document = response.json()
    assert document["client_id"].endswith(DOCUMENT_PATH)
    assert document["redirect_uris"] == [document["client_id"].removesuffix(DOCUMENT_PATH) + "/oauth/callback"]
    assert document["response_types"] == ["code"]
    assert "client_secret" not in document


def test_client_metadata_jwks_is_public_and_holds_only_public_members() -> None:
    response = httpx.get(f"{BASE_URL}{JWKS_PATH}", timeout=10)

    assert response.status_code == 200
    keys = response.json()["keys"]
    assert isinstance(keys, list)
    for key in keys:
        assert not {"d", "p", "q", "dp", "dq", "qi"} & key.keys()
