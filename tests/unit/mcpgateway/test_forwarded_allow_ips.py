# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_forwarded_allow_ips.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for FORWARDED_ALLOW_IPS: forwarded client headers are honored only from configured proxies.
"""

# Third-Party
from pydantic import ValidationError
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# First-Party
from mcpgateway.config import Settings, settings
from mcpgateway.middleware.token_scoping import TokenScopingMiddleware

UNTRUSTED_PEER = "192.0.2.10"
SPOOFED_IP = "198.51.100.7"


def _client(trusted_hosts: str, peer: str = UNTRUSTED_PEER) -> TestClient:
    """Return a client for an app that reports the resolved client address and IP-restriction verdict."""
    scoping = TokenScopingMiddleware()

    async def whoami(request: Request) -> JSONResponse:
        ip = scoping._get_client_ip(request)  # pylint: disable=protected-access
        allowed = scoping._check_ip_restrictions(ip, [f"{SPOOFED_IP}/32"])  # pylint: disable=protected-access
        return JSONResponse({"host": request.client.host, "scheme": request.url.scheme, "ip": ip, "allowed": allowed})

    app = Starlette(routes=[Route("/", whoami)])
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted_hosts)
    return TestClient(app, client=(peer, 1234))


def test_default_forwarded_allow_ips_is_loopback():
    assert Settings.model_fields["forwarded_allow_ips"].default == "127.0.0.1,::1"


@pytest.mark.parametrize("value", ["*", "10.0.0.0/8, 192.0.2.1", "::1"])
def test_forwarded_allow_ips_accepts_valid(value):
    assert Settings(forwarded_allow_ips=value, _env_file=None).forwarded_allow_ips == value


@pytest.mark.parametrize("value", ["10.0.0.1/24", "not-an-ip"])
def test_forwarded_allow_ips_rejects_invalid(value):
    with pytest.raises(ValidationError, match="FORWARDED_ALLOW_IPS"):
        Settings(forwarded_allow_ips=value, _env_file=None)


def test_app_registers_proxy_headers_with_setting():
    # First-Party
    from mcpgateway.main import app  # pylint: disable=import-outside-toplevel

    proxy = [m for m in app.user_middleware if m.cls is ProxyHeadersMiddleware]
    assert len(proxy) == 1
    assert proxy[0].kwargs["trusted_hosts"] == settings.forwarded_allow_ips


def test_untrusted_peer_xff_ignored():
    body = _client("127.0.0.1,::1").get("/", headers={"X-Forwarded-For": SPOOFED_IP}).json()
    assert body["host"] == UNTRUSTED_PEER


def test_untrusted_peer_proto_ignored():
    body = _client("127.0.0.1,::1").get("/", headers={"X-Forwarded-Proto": "https"}).json()
    assert body["scheme"] == "http"


def test_trusted_peer_xff_honored():
    body = _client(UNTRUSTED_PEER).get("/", headers={"X-Forwarded-For": SPOOFED_IP}).json()
    assert body["host"] == SPOOFED_IP


def test_trusted_proxy_uses_rightmost_untrusted_hop():
    body = _client(f"{UNTRUSTED_PEER}, 192.0.2.11").get("/", headers={"X-Forwarded-For": f"203.0.113.9, {SPOOFED_IP}"}).json()
    assert body["host"] == SPOOFED_IP


def test_token_ip_restriction_not_bypassed_by_untrusted_xff():
    body = _client("127.0.0.1,::1").get("/", headers={"X-Forwarded-For": SPOOFED_IP}).json()
    assert body["ip"] == UNTRUSTED_PEER
    assert body["allowed"] is False


def test_garbage_hop_fails_ip_restriction():
    body = _client(UNTRUSTED_PEER).get("/", headers={"X-Forwarded-For": "evil"}).json()
    assert body["ip"] == "evil"
    assert TokenScopingMiddleware()._check_ip_restrictions("evil", ["0.0.0.0/0"]) is False  # pylint: disable=protected-access
