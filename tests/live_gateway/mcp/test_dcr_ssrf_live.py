# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_dcr_ssrf_live.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box DCR SSRF regression against an isolated running gateway.
"""

from __future__ import annotations

# Standard
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from typing import cast, Generator

# Third-Party
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# First-Party
from mcpgateway.db import Gateway, RegisteredOAuthClient
from mcpgateway.services.encryption_service import get_encryption_service
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]


class _DcrAuthorizationServer(ThreadingHTTPServer):
    """HTTP server carrying authorization server fixture configuration."""

    issuer: str
    registration_endpoint: str
    redirect_uri: str


@dataclass(frozen=True)
class _LiveDcrStack:
    """Resources exposed by the live DCR fixture."""

    client: httpx.Client
    db: Session
    log_path: Path
    malicious_authority: str
    encryption_secret: str


class _AuthorizationServerHandler(BaseHTTPRequestHandler):
    """Serve OAuth metadata and accept valid client registrations."""

    requests: list[tuple[str, str, str]] = []

    def _send_json(self, status_code: int, payload: dict[str, object]) -> None:
        """Send one JSON response."""
        body = json.dumps(payload).encode()
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        """Return RFC 8414 metadata for this test server."""
        self.requests.append((self.command, self.path, self.headers.get("Host", "")))
        if self.path != "/.well-known/oauth-authorization-server":
            self._send_json(404, {"error": "not_found"})
            return

        server = cast(_DcrAuthorizationServer, self.server)
        self._send_json(
            200,
            {
                "issuer": server.issuer,
                "registration_endpoint": server.registration_endpoint,
                "authorization_endpoint": f"{server.issuer}/authorize",
                "token_endpoint": f"{server.issuer}/token",
                "grant_types_supported": ["authorization_code"],
                "response_types_supported": ["code"],
            },
        )

    def do_POST(self) -> None:
        """Record registration and return client credentials."""
        server = cast(_DcrAuthorizationServer, self.server)
        content_length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(content_length)
        self.requests.append((self.command, self.path, self.headers.get("Host", "")))
        self._send_json(
            201,
            {
                "client_id": "live-dcr-client",
                "client_secret": "live-dcr-secret",  # pragma: allowlist secret
                "registration_access_token": "live-registration-token",  # pragma: allowlist secret
                "registration_client_uri": f"{server.issuer}/register/live-dcr-client",
                "redirect_uris": [server.redirect_uri],
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        """Keep test HTTP server quiet."""


class _BlockedReceiverHandler(BaseHTTPRequestHandler):
    """Record requests that must never reach blocked receiver."""

    requests: list[tuple[str, str]] = []

    def do_POST(self) -> None:
        """Record unexpected SSRF request and return attacker-controlled JSON."""
        self.requests.append((self.command, self.path))
        body = b'{"client_id":"attacker-obtained-client-id"}'
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Keep test HTTP server quiet."""


def _free_port(host: str = "127.0.0.1") -> int:
    """Reserve and return one free TCP port on host."""
    with socket.socket() as listener:
        listener.bind((host, 0))
        return cast(tuple[str, int], listener.getsockname())[1]


def _start_server(host: str, handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start one local test HTTP server."""
    server = ThreadingHTTPServer((host, 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    return server, worker


def _start_authorization_server() -> tuple[_DcrAuthorizationServer, threading.Thread]:
    """Start one local authorization server."""
    server = _DcrAuthorizationServer(("127.0.0.1", 0), _AuthorizationServerHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    return server, worker


@pytest.fixture
def live_dcr_stack(tmp_path: Path) -> Generator[_LiveDcrStack, None, None]:
    """Start authorization servers, blocked receiver, and isolated gateway."""
    _AuthorizationServerHandler.requests.clear()
    _BlockedReceiverHandler.requests.clear()
    malicious_as, malicious_worker = _start_authorization_server()
    valid_as, valid_worker = _start_authorization_server()
    blocked_receiver, blocked_worker = _start_server("127.0.0.1", _BlockedReceiverHandler)

    malicious_issuer = f"http://127.0.0.1:{malicious_as.server_port}"
    valid_issuer = f"http://127.0.0.1:{valid_as.server_port}"
    redirect_uri = "http://gateway.example.test/oauth/callback"
    malicious_as.issuer = malicious_issuer
    malicious_as.registration_endpoint = f"http://127.0.0.1:{blocked_receiver.server_port}/imds/register"
    malicious_as.redirect_uri = redirect_uri
    valid_as.issuer = valid_issuer
    valid_as.registration_endpoint = f"{valid_issuer}/register"
    valid_as.redirect_uri = redirect_uri

    gateway_port = _free_port()
    signing_key = secrets.token_urlsafe(48)
    encryption_secret = secrets.token_urlsafe(48)
    database_url = f"sqlite:///{tmp_path / 'gateway.db'}"
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), *[str(Path(path).resolve()) for path in os.getenv("PYTHONPATH", "").split(os.pathsep) if path]]),
        "DATABASE_URL": database_url,
        "CACHE_TYPE": "memory",
        "REDIS_URL": "",
        "JWT_SECRET_KEY": signing_key,
        "AUTH_ENCRYPTION_SECRET": encryption_secret,
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "PLATFORM_ADMIN_EMAIL": "admin@example.com",
        "AUTH_REQUIRED": "true",
        "REQUIRE_USER_IN_DB": "false",
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "false",
        "DCR_ENABLED": "true",
        "DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS": "true",
        "SSRF_PROTECTION_ENABLED": "true",
        "SSRF_ALLOW_LOCALHOST": "true",
        "SSRF_ALLOW_PRIVATE_NETWORKS": "false",
        "SSRF_BLOCKED_NETWORKS": "[]",
        "SSRF_BLOCKED_HOSTS": "[]",
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
    }
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key)
    log_path = tmp_path / "gateway.log"
    with log_path.open("w") as log_file:
        process = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(gateway_port)],
            cwd=tmp_path,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        engine = None
        db = None
        try:
            client = httpx.Client(base_url=f"http://127.0.0.1:{gateway_port}", headers=make_auth_headers(token), timeout=15, trust_env=False, follow_redirects=False)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                assert process.poll() is None, log_path.read_text()[-5000:]
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail(f"Gateway startup timed out: {log_path.read_text()[-5000:]}")

            engine = create_engine(database_url)
            db = sessionmaker(bind=engine)()
            for gateway_id, issuer in (("dcr-ssrf-live", malicious_issuer), ("dcr-valid-live", valid_issuer)):
                db.add(
                    Gateway(
                        id=gateway_id,
                        name=gateway_id,
                        slug=gateway_id,
                        url="http://127.0.0.1:1/mcp",
                        transport="SSE",
                        auth_type="oauth",
                        capabilities={},
                        visibility="public",
                        oauth_config={"grant_type": "authorization_code", "issuer": issuer, "redirect_uri": redirect_uri, "scopes": ["mcp:read"]},
                    )
                )
            db.commit()
            yield _LiveDcrStack(
                client=client,
                db=db,
                log_path=log_path,
                malicious_authority=f"127.0.0.1:{malicious_as.server_port}",
                encryption_secret=encryption_secret,
            )
        finally:
            if db is not None:
                db.close()
            if engine is not None:
                engine.dispose()
            if "client" in locals():
                client.close()
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            for server, worker in ((malicious_as, malicious_worker), (valid_as, valid_worker), (blocked_receiver, blocked_worker)):
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)


def test_live_gateway_blocks_dcr_ssrf_and_allows_valid_registration(live_dcr_stack: _LiveDcrStack) -> None:
    """Patched gateway blocks exploit receiver and completes valid DCR."""
    client = live_dcr_stack.client
    db = live_dcr_stack.db

    blocked_response = client.get("/oauth/authorize/dcr-ssrf-live")
    assert blocked_response.status_code == 500, blocked_response.text
    assert any(
        method == "GET" and path == "/.well-known/oauth-authorization-server" and host == live_dcr_stack.malicious_authority
        for method, path, host in _AuthorizationServerHandler.requests
    )
    assert "DCR registration_endpoint must share the issuer origin" in live_dcr_stack.log_path.read_text()
    assert _BlockedReceiverHandler.requests == []
    assert db.query(RegisteredOAuthClient).filter_by(gateway_id="dcr-ssrf-live").count() == 0

    valid_response = client.get("/oauth/authorize/dcr-valid-live")
    assert valid_response.status_code == 307, valid_response.text
    assert valid_response.headers["location"].startswith("http://127.0.0.1:")
    assert "client_id=live-dcr-client" in valid_response.headers["location"]
    assert any(method == "POST" and path == "/register" and host.startswith("127.0.0.1:") for method, path, host in _AuthorizationServerHandler.requests)

    db.expire_all()
    registered_client = db.query(RegisteredOAuthClient).filter_by(gateway_id="dcr-valid-live").one()
    assert registered_client.client_secret_encrypted
    assert registered_client.registration_access_token_encrypted

    encryption = get_encryption_service(live_dcr_stack.encryption_secret)
    assert encryption.decrypt_secret(registered_client.client_secret_encrypted) == "live-dcr-secret"  # pragma: allowlist secret
    assert encryption.decrypt_secret(registered_client.registration_access_token_encrypted) == "live-registration-token"  # pragma: allowlist secret
