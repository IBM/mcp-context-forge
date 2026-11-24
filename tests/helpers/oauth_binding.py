# -*- coding: utf-8 -*-
"""Location: ./tests/helpers/oauth_binding.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Isolated OAuth provider and gateway servers for transaction-binding tests.
"""

# Future
from __future__ import annotations

# Standard
from collections.abc import Callable, Iterator
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlencode, urlparse

# Third-Party
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _certificate(directory: Path) -> tuple[Path, Path]:
    """Create a temporary certificate for both local test sites."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "certificate.pem", directory / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cert_path, key_path


@dataclass
class BindingEnvironment:
    """Expose isolated HTTP clients and recorded upstream identities."""

    base_url: str
    gateway_id: str
    token: str = field(repr=False)
    certificate: Path
    provider_url: str
    exchanges: list[str]
    upstream_identities: list[str]
    enable_probe: Callable[[], None] = field(repr=False)

    def client(self, authenticated: bool = True) -> httpx.Client:
        """Create an independent cookie jar with optional caller authentication."""
        return httpx.Client(
            base_url=self.base_url, headers=make_auth_headers(self.token) if authenticated else {}, verify=ssl.create_default_context(cafile=str(self.certificate)), trust_env=False, timeout=20
        )

    def authorize(self, client: httpx.Client, popup: bool = True) -> httpx.Response:
        """Start a real downstream authorization transaction."""
        response = client.get(f"{self.base_url}/oauth/authorize/{self.gateway_id}", params={"popup": str(popup).lower()})
        assert response.status_code in (302, 307), response.status_code
        return response

    def probe(self, client: httpx.Client) -> dict:
        """Exercise production token lookup through the stored-token handshake."""
        self.enable_probe()
        response = client.post(f"{self.base_url}/v1/mcp-servers/test-handshake", json={"base_url": self.provider_url + "/mcp", "gateway_id": self.gateway_id, "validation_mode": "post_authorization"})
        assert response.status_code == 200, response.status_code
        return response.json()


@contextlib.contextmanager
def _gateway(tmp_path: Path, certificate: Path, key: Path, root_path: str) -> Iterator[tuple[httpx.Client, str, str, str]]:
    """Start a private, single-tenant gateway subprocess for this test module.

    Use a temporary SQLite database and random HTTPS port.

    Yields:
        A tuple of ``(httpx.Client, admin_token_str, base_url, signing_key)``.
    """
    with socket.socket() as _sock:
        _sock.bind(("127.0.0.1", 0))
        port = _sock.getsockname()[1]

    signing_key = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.pathsep.join(
            [
                str(_REPO_ROOT),
                *[str(Path(p).resolve()) for p in os.getenv("PYTHONPATH", "").split(os.pathsep) if p],
            ]
        ),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'gateway.db'}",
        "CACHE_TYPE": "database",
        "REDIS_URL": "",
        "JWT_SECRET_KEY": signing_key,
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "PLATFORM_ADMIN_EMAIL": "admin@example.com",
        "AUTH_REQUIRED": "true",
        "REQUIRE_USER_IN_DB": "false",
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "false",
        # Restrict the isolated subprocess to localhost while permitting its test stub.
        "SSRF_PROTECTION_ENABLED": "false",
        "SSRF_ALLOW_LOCALHOST": "true",
        "GATEWAY_TEST_ALLOW_REGISTERED_ONLY": "false",
        "GATEWAY_TEST_ALLOWED_HOSTS": '["localhost"]',
        "MCP_CLIENT_CONNECT_MODE": "auto",
        "GATEWAY_ASYNC_LIFECYCLE_ENABLED": "true",
        "PLUGINS_ENABLED": "false",
        "LOG_LEVEL": "ERROR",
        "NO_PROXY": "localhost,127.0.0.1",
        "SECURE_COOKIES": "true",
        "APP_ROOT_PATH": root_path,
        "APP_DOMAIN": f"https://127.0.0.1:{port}",
        "PYTHONUNBUFFERED": "1",
    }

    token = make_test_jwt(
        "admin@example.com",
        is_admin=True,
        teams=None,
        secret=signing_key,
        algorithm="HS256",
    )
    log_path = tmp_path / "gateway.log"

    with log_path.open("w") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "mcpgateway.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--ssl-certfile",
                str(certificate),
                "--ssl-keyfile",
                str(key),
            ],
            cwd=tmp_path,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            base_url = f"https://127.0.0.1:{port}{root_path}"
            with httpx.Client(
                base_url=base_url,
                headers=make_auth_headers(token),
                timeout=20,
                trust_env=False,
                verify=ssl.create_default_context(cafile=str(certificate)),
            ) as client:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    assert process.poll() is None, f"Gateway crashed:\n{log_path.read_text()[-5000:]}"
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail(f"Gateway startup timed out:\n{log_path.read_text()[-5000:]}")
                yield client, token, base_url, signing_key
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@contextlib.contextmanager
def binding_environment(tmp_path: Path, root_path: str = "", custom_redirect: bool = False) -> Iterator[BindingEnvironment]:
    """Run real OAuth routes with a local provider and encrypted token database."""
    certificate, key = _certificate(tmp_path)
    exchanges, upstream_identities = [], []

    class Provider(BaseHTTPRequestHandler):
        """Serve consent, token exchange, and identity-marked MCP responses."""

        def reply(self, status: int, body: object, content_type: str = "application/json") -> None:
            """Return a bounded response."""
            payload = (json.dumps(body) if content_type == "application/json" else body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            """Render consent or redirect a consenting user to the real callback."""
            query = parse_qs(urlparse(self.path).query)
            if urlparse(self.path).path == "/consent":
                target = query["redirect_uri"][0] + "?" + urlencode({"state": query["state"][0], "code": query.get("identity", ["attacker"])[0]})
                self.send_response(302)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            # Standard
            from html import escape

            target = "/consent?" + urlencode({k: v[0] for k, v in query.items()})
            self.reply(200, f'<html><a id="consent" href="{escape(target, quote=True)}">Approve access</a></html>', "text/html")

        def do_POST(self) -> None:
            """Issue identity-specific tokens and record authenticated MCP usage."""
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path == "/token":
                identity = parse_qs(body.decode())["code"][0]
                exchanges.append(identity)
                self.reply(200, {"access_token": "binding-" + identity, "refresh_token": "refresh-" + identity, "token_type": "Bearer", "expires_in": 3600, "scope": "tools:read"})
                return
            token = self.headers.get("Authorization", "")
            if not token.startswith("Bearer binding-"):
                self.reply(401, {"error": "invalid_token"})
                return
            request = json.loads(body)
            method = request.get("method")
            if method == "notifications/initialized":
                self.reply(202, {})
                return
            if method == "server/discover":
                result = {"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}}
            elif method == "initialize":
                result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "binding", "version": "1"}}
            elif method == "tools/list":
                upstream_identities.append(token.removeprefix("Bearer binding-"))
                result = {"tools": [{"name": "binding_echo", "inputSchema": {"type": "object"}}]}
            else:
                result = {}
            self.reply(200, {"jsonrpc": "2.0", "id": request.get("id"), "result": result})

        def log_message(self, _format: str, *args: object) -> None:
            """Keep authorization codes and tokens out of test output."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider_url = f"https://localhost:{server.server_port}"
    try:
        with _gateway(tmp_path, certificate, key, root_path) as (admin, _, base_url, signing_key):
            email = "binding-user@example.com"
            response = admin.post(
                base_url + "/auth/email/admin/users",
                json={
                    "email": email,
                    "password": "BindingTest!42Aa9Zp7",  # pragma: allowlist secret
                    "full_name": "Binding User",
                    "is_admin": False,
                    "is_active": True,
                    "password_change_required": False,
                },
            )
            assert response.status_code == 201, response.status_code
            assignments = admin.get(base_url + f"/rbac/users/{email}/roles").json()
            roles = admin.get(base_url + "/rbac/roles").json()
            role_id = next(role["id"] for role in roles if role["name"] == "platform_viewer")
            if not any(assignment["role_id"] == role_id for assignment in assignments):
                response = admin.post(base_url + f"/rbac/users/{email}/roles", json={"role_id": role_id, "scope": "global"})
                assert response.is_success, response.text
            response = admin.post(
                base_url + "/gateways",
                json={
                    "name": "binding-provider",
                    "url": provider_url + "/mcp",
                    "transport": "STREAMABLEHTTP",
                    "visibility": "public",
                    "auth_type": "oauth",
                    "ca_certificate": certificate.read_text(),
                    "oauth_config": {
                        "grant_type": "authorization_code",
                        "client_id": "binding-client",
                        "authorization_url": provider_url + "/authorize",
                        "token_url": provider_url + "/token",
                        "redirect_uri": base_url + "/oauth/callback",
                        "scopes": ["tools:read"],
                        **({"redirect_uri_after_oauth": base_url + "/health"} if custom_redirect else {}),
                    },
                },
            )
            assert response.status_code in (200, 201, 202), response.status_code
            data = response.json()
            gateway_id = data.get("id") or data["gateway"]["id"]
            token = make_test_jwt(email, teams=[], secret=signing_key, algorithm="HS256", include_email_claim=True)
            probe_enabled = False

            def enable_probe() -> None:
                """Grant only the read/update permissions required by the post-attack probe."""
                nonlocal probe_enabled
                if probe_enabled:
                    return
                response = admin.post(base_url + "/rbac/roles", json={"name": "binding_probe", "scope": "global", "permissions": ["gateways.read", "gateways.update"]})
                assert response.is_success, response.text
                response = admin.post(base_url + f"/rbac/users/{email}/roles", json={"role_id": response.json()["id"], "scope": "global"})
                assert response.is_success, response.text
                probe_enabled = True

            yield BindingEnvironment(base_url, gateway_id, token, certificate, provider_url, exchanges, upstream_identities, enable_probe)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
