# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/sso/test_sso_provider_ca_certificate_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks for the per-provider ``ca_certificate`` field against an externally started gateway.

The checks cover the admin API only: create, read, replace, clear, invalid PEM and the deny path.
A live self-signed IdP is not part of this test. The accept and reject behavior over real TLS is covered by
``tests/unit/mcpgateway/services/test_oidc_tls.py``.
"""

# Standard
import datetime
from uuid import uuid4

# Third-Party
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import httpx
import pytest

# Local
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]
PROVIDERS = "/v1/auth/sso/admin/providers"


def _ca_pem(common_name: str) -> str:
    """Return a self-signed CA certificate in PEM form."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode().strip()


def _client(token: str) -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30)


@pytest.fixture(scope="module")
def admin_client():
    """Authenticate with the stack's platform administrator."""
    with _client(make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)) as client:
        yield client


@pytest.fixture
def provider_id(admin_client):
    """Create a provider without a CA and remove it afterwards."""
    pid = f"ca-test-{uuid4().hex[:12]}"
    response = admin_client.post(
        PROVIDERS,
        json={
            "id": pid,
            "name": pid,
            "display_name": "CA test provider",
            "provider_type": "oidc",
            "client_id": "ca-test-client",
            "client_secret": "ca-test-value",  # pragma: allowlist secret
            "authorization_url": "https://example.com/authorize",
            "token_url": "https://example.com/token",
            "userinfo_url": "https://example.com/userinfo",
            "auto_create_users": False,
        },
    )
    assert response.status_code == 200, response.text
    yield pid
    assert admin_client.delete(f"{PROVIDERS}/{pid}").status_code == 200


def test_ca_certificate_is_stored_replaced_and_cleared(admin_client, provider_id):
    """A valid PEM persists, a new PEM replaces it, and an empty string clears it."""
    first, second = _ca_pem("first-ca"), _ca_pem("second-ca")

    assert admin_client.put(f"{PROVIDERS}/{provider_id}", json={"ca_certificate": first}).status_code == 200
    assert admin_client.get(f"{PROVIDERS}/{provider_id}").json()["ca_certificate"] == first

    assert admin_client.put(f"{PROVIDERS}/{provider_id}", json={"ca_certificate": second}).status_code == 200
    assert admin_client.get(f"{PROVIDERS}/{provider_id}").json()["ca_certificate"] == second

    assert admin_client.put(f"{PROVIDERS}/{provider_id}", json={"ca_certificate": ""}).status_code == 200
    assert admin_client.get(f"{PROVIDERS}/{provider_id}").json()["ca_certificate"] is None


def test_invalid_ca_certificate_returns_400_and_keeps_the_stored_value(admin_client, provider_id):
    """An unloadable PEM is rejected with the specific message and leaves the old CA in place."""
    good = _ca_pem("good-ca")
    assert admin_client.put(f"{PROVIDERS}/{provider_id}", json={"ca_certificate": good}).status_code == 200

    response = admin_client.put(f"{PROVIDERS}/{provider_id}", json={"ca_certificate": "-----BEGIN CERTIFICATE-----\nnot base64\n-----END CERTIFICATE-----"})
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "ca_certificate is not a valid PEM CA bundle"
    assert admin_client.get(f"{PROVIDERS}/{provider_id}").json()["ca_certificate"] == good


def test_oversized_ca_certificate_is_rejected(admin_client, provider_id):
    """A bundle over the size limit fails request validation."""
    response = admin_client.put(f"{PROVIDERS}/{provider_id}", json={"ca_certificate": "A" * 65537})
    assert response.status_code == 422, response.text


def test_ca_certificate_write_requires_permission(provider_id):
    """A token without the SSO provider permission cannot set the CA."""
    token = make_test_jwt("viewer@example.com", is_admin=False, teams=[], secret=JWT_SECRET)
    with _client(token) as client:
        response = client.put(f"{PROVIDERS}/{provider_id}", json={"ca_certificate": _ca_pem("denied-ca")})
    assert response.status_code in {401, 403}, response.text
