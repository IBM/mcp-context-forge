# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/helpers/local_oidc_issuer.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Local Entra-compatible OIDC issuer for live-gateway trust-mode tests.

The gateway's external-IdP verifier (``verify_oauth_access_token``)
discovers keys via RFC 8414 / OIDC metadata and enforces that the
``jwks_uri`` is HTTPS and same-origin with the issuer (SSRF defense).
This harness therefore serves its discovery and JWKS endpoints over TLS
with a self-signed certificate:

- ``ensure_tls_material()`` writes a reusable self-signed cert/key pair to
  ``LOCAL_OIDC_MATERIAL_DIR`` (default ``/tmp/cf-local-oidc-issuer``). The
  gateway under test must be started with
  ``SSL_CERT_FILE=<material dir>/issuer-tls-cert.pem`` so its outbound
  httpx clients (httpx >= 0.28 honors ``SSL_CERT_FILE``) trust the issuer.
  Materialize it once before starting the gateway:

      uv run python -m tests.live_gateway.helpers.local_oidc_issuer ensure-material

- The ``local_oidc_issuer`` session fixture starts the issuer on an
  ephemeral port (uvicorn in a thread, TLS) plus a plain-HTTP stub A2A
  agent endpoint on a second ephemeral port, and yields a namespace with
  the issuer URL, a ``mint_token`` helper (RS256, generated in-memory key)
  and the stub agent URL.

Token material is never logged by this module.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timedelta, timezone
import ipaddress
import os
from pathlib import Path
import socket
import threading
import time
from typing import Any, Dict, Optional

# Third-Party
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import jwt
import pytest

MATERIAL_DIR = Path(os.getenv("LOCAL_OIDC_MATERIAL_DIR", "/tmp/cf-local-oidc-issuer"))
TLS_CERT_FILE = MATERIAL_DIR / "issuer-tls-cert.pem"
TLS_KEY_FILE = MATERIAL_DIR / "issuer-tls-key.pem"
TOKEN_KID = "local-oidc-test-key-1"


# ---------------------------------------------------------------------------
# TLS material (issuer HTTPS requirement)
# ---------------------------------------------------------------------------
def ensure_tls_material() -> Path:
    """Write (or reuse) the self-signed TLS cert/key for the local issuer.

    The certificate is its own trust root (CA:TRUE, self-signed) with SANs
    for ``localhost`` / ``127.0.0.1``; the gateway trusts it via
    ``SSL_CERT_FILE``. Existing material is reused so a previously started
    gateway keeps working across test runs.

    Returns:
        Path to the PEM certificate file (the ``SSL_CERT_FILE`` value).
    """
    if TLS_CERT_FILE.is_file() and TLS_KEY_FILE.is_file():
        return TLS_CERT_FILE

    MATERIAL_DIR.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "cf-local-oidc-issuer")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    TLS_KEY_FILE.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    TLS_CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return TLS_CERT_FILE


# ---------------------------------------------------------------------------
# Token signing key + JWKS
# ---------------------------------------------------------------------------
def generate_signing_key():
    """Generate the RSA private key used to sign test tokens (in-memory only)."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64url_uint(value: int) -> str:
    """Base64url-encode an unsigned integer per JWK (RFC 7518 §6.3)."""
    # Standard
    import base64

    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def public_jwk(signing_key, kid: str = TOKEN_KID) -> Dict[str, Any]:
    """Build the public JWK for the signing key."""
    numbers = signing_key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64url_uint(numbers.n),
        "e": _b64url_uint(numbers.e),
    }


def mint_token(claims: Dict[str, Any], signing_key, kid: str = TOKEN_KID) -> str:
    """Mint an RS256 token from the local issuer.

    Args:
        claims: Claim set; callers supply iss/aud/sub/exp/jti per scenario.
        signing_key: RSA private key from :func:`generate_signing_key`.
        kid: Key id placed in the JWT header (must match the JWKS entry).

    Returns:
        The encoded JWT. NEVER log the return value.
    """
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": kid})


# ---------------------------------------------------------------------------
# Issuer application (discovery + JWKS + stub A2A agent)
# ---------------------------------------------------------------------------
def build_issuer_app(issuer_url: str, jwk: Dict[str, Any]) -> FastAPI:
    """Build the FastAPI app serving OIDC discovery, JWKS, and a stub A2A agent.

    The gateway probes RFC 8414 (``/.well-known/oauth-authorization-server``)
    first, then OIDC discovery; both are served. The stub agent endpoint
    answers A2A JSON-RPC invocations with a completed task so a fully
    authorized ``POST /a2a/<agent>/invoke`` on the gateway yields 200.
    """
    app = FastAPI(title="cf-local-oidc-issuer")
    metadata = {
        "issuer": issuer_url,
        "jwks_uri": f"{issuer_url}/jwks",
        "token_endpoint": f"{issuer_url}/token",
        "authorization_endpoint": f"{issuer_url}/authorize",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }

    @app.get("/.well-known/openid-configuration")
    async def oidc_configuration() -> Dict[str, Any]:  # noqa: D103
        return metadata

    @app.get("/.well-known/oauth-authorization-server")
    async def oauth_authorization_server() -> Dict[str, Any]:  # noqa: D103
        return metadata

    @app.get("/jwks")
    async def jwks() -> Dict[str, Any]:  # noqa: D103
        return {"keys": [jwk]}

    @app.post("/stub-agent/invoke")
    async def stub_agent_invoke(request: Request) -> JSONResponse:
        """Stub A2A agent: complete every JSON-RPC invocation immediately."""
        try:
            body = await request.json()
        except Exception:  # pylint: disable=broad-except
            body = {}
        request_id = body.get("id", 1) if isinstance(body, dict) else 1
        result = {
            "id": "task-local-oidc-1",
            "contextId": "ctx-local-oidc-1",
            "status": {"state": "completed"},
            "artifacts": [],
            "history": [],
        }
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})

    return app


# ---------------------------------------------------------------------------
# uvicorn-in-a-thread helpers
# ---------------------------------------------------------------------------
def _free_port() -> int:
    """Reserve an ephemeral loopback port (small reuse race, fine for tests)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_server(app: FastAPI, port: int, *, tls: bool) -> tuple[Any, threading.Thread]:
    """Start uvicorn serving ``app`` on 127.0.0.1:port in a daemon thread.

    Returns ``(server, thread)`` once the server reports started. TLS servers
    use the material from :func:`ensure_tls_material`.
    """
    uvicorn = pytest.importorskip("uvicorn", reason="uvicorn is required for the local OIDC issuer fixture")

    config_kwargs: Dict[str, Any] = {}
    if tls:
        ensure_tls_material()
        config_kwargs = {"ssl_certfile": str(TLS_CERT_FILE), "ssl_keyfile": str(TLS_KEY_FILE)}

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", **config_kwargs)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name=f"local-oidc-issuer:{port}", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError(f"local OIDC issuer failed to start on port {port}")
        time.sleep(0.05)
    return server, thread


def _stop_server(server: Any, thread: threading.Thread) -> None:
    """Signal the uvicorn server to exit and join its thread."""
    server.should_exit = True
    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Session fixture
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def local_oidc_issuer():
    """Start the local OIDC issuer (TLS) and stub A2A agent (plain HTTP).

    Yields a namespace with:

    - ``issuer``: the issuer URL (``https://127.0.0.1:<port>``) to seed as
      the SSO provider's issuer and to place in token ``iss`` claims.
    - ``tls_cert_file``: path the gateway must trust via ``SSL_CERT_FILE``.
    - ``stub_agent_url``: plain-HTTP endpoint for the seeded A2A agent.
    - ``mint_token(claims)``: RS256 token minter bound to this issuer's key.
    """
    pytest.importorskip("uvicorn", reason="uvicorn is required for the local OIDC issuer fixture")

    # Standard
    from types import SimpleNamespace

    ensure_tls_material()
    signing_key = generate_signing_key()
    jwk = public_jwk(signing_key)

    tls_port = _free_port()
    issuer_url = f"https://127.0.0.1:{tls_port}"
    app = build_issuer_app(issuer_url, jwk)

    issuer_server, issuer_thread = _start_server(app, tls_port, tls=True)
    agent_port = _free_port()
    agent_server, agent_thread = _start_server(app, agent_port, tls=False)

    namespace = SimpleNamespace(
        issuer=issuer_url,
        jwks_uri=f"{issuer_url}/jwks",
        tls_cert_file=TLS_CERT_FILE,
        stub_agent_url=f"http://127.0.0.1:{agent_port}/stub-agent/invoke",
        kid=TOKEN_KID,
        mint_token=lambda claims: mint_token(claims, signing_key),
    )
    try:
        yield namespace
    finally:
        _stop_server(issuer_server, issuer_thread)
        _stop_server(agent_server, agent_thread)


# ---------------------------------------------------------------------------
# CLI: materialize the TLS cert before starting the gateway under test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Standard
    import sys

    if len(sys.argv) == 2 and sys.argv[1] == "ensure-material":
        cert_path = ensure_tls_material()
        print(f"local OIDC issuer TLS material ready; start the gateway with SSL_CERT_FILE={cert_path}")
    else:
        print(__doc__)
        raise SystemExit(2)
