# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_oidc_tls.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the per-provider TLS trust policy used by SSO/OIDC outbound calls.
"""

# Standard
import ast
import datetime
import ipaddress
import json
from pathlib import Path
from types import SimpleNamespace
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import httpx
import jwt
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.services import oidc_tls
from mcpgateway.services.oidc_tls import _NoRedirectPyJWKClient, provider_http_client, provider_ssl_context, tls_cache_key, validate_ca_certificate
from mcpgateway.services.sso_service import SSOService


def _self_signed_pem() -> tuple[bytes, bytes]:
    """Return (cert_pem, key_pem) for a self-signed localhost certificate."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()),
    )


@pytest.fixture
def tls_server(tmp_path):
    """Serve a JWKS document over HTTPS; yield (url, ca_pem) for its self-signed certificate."""
    cert_pem, key_pem = _self_signed_pem()
    cert_file = tmp_path / "cert.pem"
    key_file = tmp_path / "key.pem"
    cert_file.write_bytes(cert_pem)
    key_file.write_bytes(key_pem)

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps({"keys": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_address[1]}/jwks", cert_pem.decode()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _verify_on(monkeypatch):
    """Keep global TLS verification on so only the provider CA can make a self-signed server pass."""
    monkeypatch.setattr(settings, "skip_ssl_verify", False)


def test_jwks_fetch_trusts_provider_ca(tls_server):
    """A JWKS fetch succeeds against a self-signed server when its certificate is the provider CA."""
    url, ca_pem = tls_server
    assert _NoRedirectPyJWKClient(url, ssl_context=provider_ssl_context(ca_pem)).fetch_data() == {"keys": []}


def test_jwks_fetch_rejects_server_not_signed_by_provider_ca(tls_server):
    """A provider CA does not make an unrelated self-signed server trusted."""
    url, _ = tls_server
    other_ca_pem, _ = _self_signed_pem()
    with pytest.raises(jwt.exceptions.PyJWKClientConnectionError):
        _NoRedirectPyJWKClient(url, ssl_context=provider_ssl_context(other_ca_pem.decode())).fetch_data()


@pytest.mark.asyncio
async def test_provider_http_client_trusts_provider_ca_and_does_not_follow_redirects(tls_server):
    """The CA-pinned client reaches a self-signed server and keeps follow_redirects off."""
    url, ca_pem = tls_server
    async with provider_http_client(ca_pem) as client:
        assert client.follow_redirects is False
        assert (await client.get(url)).json() == {"keys": []}


@pytest.mark.asyncio
async def test_provider_http_client_rejects_self_signed_server_without_ca(tls_server):
    """Without a provider CA the shared client rejects the self-signed server."""
    url, _ = tls_server
    async with provider_http_client(None) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get(url)


@pytest.mark.asyncio
async def test_provider_http_client_without_ca_uses_shared_client():
    """No provider CA means the shared pooled client, not a new isolated one."""
    shared = MagicMock()
    with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=shared):
        async with provider_http_client(None) as client:
            assert client is shared


def test_tls_cache_key_separates_trust_anchors():
    """Same URI under different CAs never shares a cache entry; no CA keeps the plain key."""
    assert tls_cache_key("https://idp/jwks", None) == "https://idp/jwks"
    assert tls_cache_key("https://idp/jwks", "A") != tls_cache_key("https://idp/jwks", "B")
    assert tls_cache_key("https://idp/jwks", "A") != "https://idp/jwks"


def test_jwks_client_cache_is_keyed_by_ca(tls_server):
    """SSOService hands out distinct JWKS clients per CA for the same jwks_uri."""
    _, ca_pem = tls_server
    other_pem = _self_signed_pem()[0].decode()
    service = SSOService(MagicMock())
    service._jwks_client_cache.clear()
    uri = "https://idp.example.com/jwks"
    plain = service._get_jwks_client(uri)
    pinned = service._get_jwks_client(uri, ca_pem)
    assert plain is not pinned
    assert service._get_jwks_client(uri, ca_pem) is pinned
    assert service._get_jwks_client(uri, other_pem) is not pinned
    service._jwks_client_cache.clear()


def test_validate_ca_certificate(tls_server):
    """Empty input clears the setting, garbage is rejected, a real PEM is returned stripped."""
    _, ca_pem = tls_server
    assert validate_ca_certificate(None) is None
    assert validate_ca_certificate("  \n") is None
    assert validate_ca_certificate(f"\n{ca_pem}\n") == ca_pem.strip()
    with pytest.raises(ValueError, match="valid PEM CA bundle"):
        validate_ca_certificate("-----BEGIN CERTIFICATE-----\nnot base64\n-----END CERTIFICATE-----")


@pytest.mark.asyncio
async def test_update_provider_rejects_invalid_ca_certificate():
    """update_provider raises ValueError for a CA bundle that cannot be loaded."""
    service = SSOService(MagicMock())
    service.get_provider = MagicMock(return_value=MagicMock())
    with pytest.raises(ValueError):
        await service.update_provider("github", {"ca_certificate": "garbage-but-not-empty"})


@pytest.mark.asyncio
async def test_update_provider_ca_change_evicts_stale_cache_and_logs_fingerprint_only(tls_server, caplog):
    """Replacing the CA drops the old CA's cache keys and logs the fingerprint, never the PEM."""
    _, ca_pem = tls_server
    service = SSOService(MagicMock())
    service.get_provider = MagicMock(return_value=SimpleNamespace(id="p", ca_certificate=ca_pem.strip(), trusted_for_api_auth=False, api_audience=None))
    stale = tls_cache_key("https://idp/jwks", ca_pem.strip())
    service._jwks_client_cache[stale] = MagicMock()
    with caplog.at_level("INFO", logger="mcpgateway.services.sso_service"):
        await service.update_provider("p", {"ca_certificate": ""})
    assert stale not in service._jwks_client_cache
    assert "CA cleared" in caplog.text
    assert "BEGIN CERTIFICATE" not in caplog.text


def test_sso_oidc_modules_resolve_tls_only_through_oidc_tls():
    """Guard: SSO/OIDC code never builds its own httpx client.

    Provider-bound calls must go through ``provider_http_client`` so the provider CA applies.
    The only direct shared-client uses allowed are the two calls to fixed public SaaS hosts.
    """
    root = Path(oidc_tls.__file__).resolve().parents[1]
    allowed_shared_client_callers = {"sso_service.py": {"_fetch_entra_groups_from_graph_api", "_enrich_user_data_from_claims"}}
    guarded = [p for p in root.rglob("*.py") if p != Path(oidc_tls.__file__).resolve() and "mcpgateway.services.oidc_tls import" in p.read_text(encoding="utf-8")]
    assert {"sso_service.py", "verify_credentials.py"} <= {p.name for p in guarded}
    for path in guarded:
        filename = path.name
        allowed = allowed_shared_client_callers.get(filename, set())
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders = set()
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                callee = ast.unparse(node.func)
                if callee in {"httpx.Client", "httpx.AsyncClient", "get_isolated_http_client"}:
                    offenders.add(f"{func.name}:{callee}")
                elif callee == "get_http_client" and func.name not in allowed:
                    offenders.add(f"{func.name}:{callee}")
        assert not offenders, f"{filename} bypasses provider TLS policy in: {sorted(offenders)}"
