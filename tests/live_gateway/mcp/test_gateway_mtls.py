# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_gateway_mtls.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify mTLS without a gateway CA through real TLS and MCP connections.
"""

# Standard
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
import ipaddress
import json
from pathlib import Path
import ssl
import threading
from typing import Any

# Third-Party
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
import httpx
import pytest

# Local
from tests.live_gateway.e2e import test_candidate_credential_handshake as handshake_fixtures
from tests.live_gateway.plugins._helpers import wait_for_gateway_tools

pytestmark = pytest.mark.e2e
isolated_gateway = handshake_fixtures.isolated_gateway


@pytest.fixture
def certificates(tmp_path):
    """Issue temporary CA, server, and client certificates for real TLS handshakes."""
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    now = datetime.now(timezone.utc)

    def issue(name: str, key: rsa.RSAPrivateKey, *, ca: bool = False, client: bool = False) -> tuple[Path, Path]:
        """Sign a certificate for the requested test identity."""
        builder = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        )
        if not ca:
            usage = ExtendedKeyUsageOID.CLIENT_AUTH if client else ExtendedKeyUsageOID.SERVER_AUTH
            builder = builder.add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
            if not client:
                builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        cert = builder.sign(ca_key, hashes.SHA256())
        cert_path = tmp_path / f"{name}.pem"
        key_path = tmp_path / f"{name}.key"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        key_path.chmod(0o600)
        return cert_path, key_path

    ca, _ = issue("Test CA", ca_key, ca=True)
    server, server_key = issue("server", rsa.generate_private_key(public_exponent=65537, key_size=2048))
    client, client_key = issue("client", rsa.generate_private_key(public_exponent=65537, key_size=2048), client=True)
    return ca, server, server_key, client, client_key


@pytest.fixture
def gateway_environment(certificates, tmp_path):
    """Trust the test CA through the process trust store, without gateway CA configuration."""
    return {
        "TMPDIR": str(tmp_path),
        "SSL_CERT_FILE": str(certificates[0]),
        "ARGON2ID_TIME_COST": "1",
        "ARGON2ID_MEMORY_COST": "1024",
        "MCP_CLIENT_CONNECT_MODE": "legacy",
        "GATEWAY_ASYNC_LIFECYCLE_ENABLED": "false",
        "GATEWAY_TEST_ALLOWED_HOSTS": '["localhost"]',
    }


@pytest.fixture
def upstream(certificates):
    """Require a trusted client certificate for every upstream connection."""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        """Implement the MCP methods needed for registration and invocation."""

        def do_POST(self):  # noqa: N802
            """Handle MCP requests and record tool invocation headers."""
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            method = body["method"]
            if "id" not in body:
                self.send_response(202)
                self.end_headers()
                return
            result: dict[str, Any]
            if method == "initialize":
                result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "echo", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": "echo", "description": "Echo headers", "inputSchema": {"type": "object", "properties": {}}}]}
            elif method == "tools/call":
                headers = {key.lower(): value for key, value in self.headers.items()}
                calls.append(headers)
                result = {"content": [{"type": "text", "text": json.dumps(headers)}], "isError": False}
            else:
                result = {}
            response = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def do_GET(self):  # noqa: N802
            """Reject optional SSE listening on this stateless upstream."""
            self.send_response(405)
            self.end_headers()

        def log_message(self, format, *args):
            """Suppress fixture HTTP logs."""

    server = handshake_fixtures._DualStackThreadingHTTPServer(("::", 0), Handler)
    ca, server_cert, server_key, _, _ = certificates
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(server_cert, server_key)
    context.load_verify_locations(cafile=str(ca))
    context.verify_mode = ssl.CERT_REQUIRED
    server.socket = context.wrap_socket(server.socket, server_side=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"https://localhost:{server.server_port}/mcp", calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_mtls_without_gateway_ca(isolated_gateway, upstream, certificates):
    """Register, handshake, and invoke through system trust while preserving credential isolation."""
    client, _, _, _ = isolated_gateway
    url, calls = upstream
    ca, _, _, client_cert, client_key = certificates
    untrusted = ssl.create_default_context()
    untrusted.load_cert_chain(client_cert, client_key)
    with httpx.Client(verify=untrusted, trust_env=False) as wrong_trust:
        with pytest.raises(httpx.TransportError, match="CERTIFICATE_VERIFY_FAILED"):
            wrong_trust.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    trust = ssl.create_default_context(cafile=str(ca))
    with httpx.Client(verify=trust, trust_env=False) as uncredentialed:
        with pytest.raises(httpx.TransportError):
            uncredentialed.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    response = client.post(
        "/gateways",
        json={"name": "mtls-echo", "url": url, "transport": "STREAMABLEHTTP", "client_cert": client_cert.read_text(), "client_key": client_key.read_text()},
    )
    assert response.status_code in (200, 201), response.text
    gateway_id = response.json()["id"]
    assert response.json().get("caCertificate") is None
    tool = wait_for_gateway_tools(client, gateway_id)[0]
    handshake = {"gateway_id": gateway_id, "base_url": url}
    response = client.post("/v1/mcp-servers/test-handshake", json=handshake)
    assert response.status_code == 200, response.text
    assert response.json()["success"], response.text
    response = client.post("/v1/mcp-servers/test-handshake", json={**handshake, "credential_mode": "candidate_only"})
    assert response.status_code == 200, response.text
    assert not response.json()["success"], response.text
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool["name"], "arguments": {}}}
    for _ in range(2):
        response = client.post("/rpc", json=payload)
        assert response.status_code == 200, response.text
        assert "error" not in response.json(), response.text
        assert not response.json()["result"].get("isError"), response.text
    assert len(calls) == 2
