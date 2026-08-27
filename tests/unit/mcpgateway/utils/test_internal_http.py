# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_internal_http.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for internal loopback HTTP helpers.
"""

# Standard
import ssl
from typing import Any
from unittest.mock import patch

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.utils.internal_http import _is_ssl_enabled, internal_loopback_base_url, internal_loopback_verify, post_rpc_in_process, reset_loopback_ssl_context


class TestIsSSLEnabled:
    """Tests for _is_ssl_enabled() edge cases."""

    def test_ssl_true(self, monkeypatch):
        monkeypatch.setenv("SSL", "true")
        assert _is_ssl_enabled() is True

    def test_ssl_false(self, monkeypatch):
        monkeypatch.setenv("SSL", "false")
        assert _is_ssl_enabled() is False

    def test_ssl_unset(self, monkeypatch):
        monkeypatch.delenv("SSL", raising=False)
        assert _is_ssl_enabled() is False

    def test_ssl_empty_string(self, monkeypatch):
        monkeypatch.setenv("SSL", "")
        assert _is_ssl_enabled() is False

    def test_ssl_uppercase_not_truthy(self, monkeypatch):
        """Shell launchers use exact [[ "${SSL}" == "true" ]], so uppercase is not truthy."""
        monkeypatch.setenv("SSL", "TRUE")
        assert _is_ssl_enabled() is False

    def test_ssl_mixed_case_not_truthy(self, monkeypatch):
        """Only exact lowercase 'true' enables SSL, matching run-gunicorn.sh."""
        monkeypatch.setenv("SSL", "True")
        assert _is_ssl_enabled() is False

    def test_ssl_with_whitespace_not_truthy(self, monkeypatch):
        """Whitespace-padded values are not truthy, matching gunicorn.config.py and shell launchers."""
        monkeypatch.setenv("SSL", " true ")
        assert _is_ssl_enabled() is False

    def test_ssl_one_is_not_truthy(self, monkeypatch):
        """Only 'true' is accepted — '1' is not, matching gunicorn.config.py."""
        monkeypatch.setenv("SSL", "1")
        assert _is_ssl_enabled() is False

    def test_ssl_yes_is_not_truthy(self, monkeypatch):
        monkeypatch.setenv("SSL", "yes")
        assert _is_ssl_enabled() is False


class TestInternalLoopbackBaseUrl:
    """Tests for internal_loopback_base_url()."""

    def test_https_when_ssl_enabled(self, monkeypatch):
        monkeypatch.setenv("SSL", "true")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_base_url() == "https://127.0.0.1:4444"

    def test_http_when_ssl_disabled(self, monkeypatch):
        monkeypatch.setenv("SSL", "false")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 8000)
        assert internal_loopback_base_url() == "http://127.0.0.1:8000"

    def test_http_when_ssl_unset(self, monkeypatch):
        monkeypatch.delenv("SSL", raising=False)
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_base_url() == "http://127.0.0.1:4444"

    def test_uses_configured_port(self, monkeypatch):
        monkeypatch.setenv("SSL", "false")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 9999)
        assert internal_loopback_base_url() == "http://127.0.0.1:9999"


class TestInternalLoopbackVerify:
    """Tests for internal_loopback_verify()."""

    def test_verify_disabled_when_ssl_enabled(self, monkeypatch):
        monkeypatch.setenv("SSL", "true")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_verify() is False

    def test_verify_enabled_when_ssl_disabled(self, monkeypatch):
        monkeypatch.setenv("SSL", "false")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_verify() is True

    def test_verify_enabled_when_ssl_unset(self, monkeypatch):
        monkeypatch.delenv("SSL", raising=False)
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_verify() is True


@pytest.fixture(name="client_cert_pair")
def _client_cert_pair(tmp_path):
    """Write a throwaway self-signed cert/key pair and yield their paths."""
    # Standard
    import datetime

    # Third-Party
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "loopback-test-client")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )

    cert_path = tmp_path / "client-cert.pem"
    key_path = tmp_path / "client-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path)


class TestLoopbackClientCertificate:
    """Tests for the loopback client certificate used under inbound mTLS.

    Under ``CERT_REQS>=1`` the gateway requires client certificates, including
    on its own loopback self-calls to ``/rpc``. ``verify=False`` only skips
    validating the server, so without a client certificate those self-calls are
    rejected at the handshake and the SSE/WebSocket transports break.
    """

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        reset_loopback_ssl_context()
        yield
        reset_loopback_ssl_context()

    def test_returns_ssl_context_when_cert_configured(self, monkeypatch, client_cert_pair):
        cert, key = client_cert_pair
        monkeypatch.setenv("SSL", "true")
        monkeypatch.setenv("LOOPBACK_CLIENT_CERT", cert)
        monkeypatch.setenv("LOOPBACK_CLIENT_KEY", key)

        context = internal_loopback_verify()

        assert isinstance(context, ssl.SSLContext)

    def test_context_preserves_existing_trust_posture(self, monkeypatch, client_cert_pair):
        """The context must not impose new server-cert or SAN requirements."""
        cert, key = client_cert_pair
        monkeypatch.setenv("SSL", "true")
        monkeypatch.setenv("LOOPBACK_CLIENT_CERT", cert)
        monkeypatch.setenv("LOOPBACK_CLIENT_KEY", key)

        context = internal_loopback_verify()

        assert context.verify_mode is ssl.CERT_NONE
        assert context.check_hostname is False

    def test_context_is_cached(self, monkeypatch, client_cert_pair):
        """Building a context parses PEM files; it must not happen per request."""
        cert, key = client_cert_pair
        monkeypatch.setenv("SSL", "true")
        monkeypatch.setenv("LOOPBACK_CLIENT_CERT", cert)
        monkeypatch.setenv("LOOPBACK_CLIENT_KEY", key)

        assert internal_loopback_verify() is internal_loopback_verify()

    def test_cache_rebuilds_when_configuration_changes(self, monkeypatch, client_cert_pair, tmp_path):
        cert, key = client_cert_pair
        monkeypatch.setenv("SSL", "true")
        monkeypatch.setenv("LOOPBACK_CLIENT_CERT", cert)
        monkeypatch.setenv("LOOPBACK_CLIENT_KEY", key)
        first = internal_loopback_verify()

        other_cert = tmp_path / "copy-cert.pem"
        other_key = tmp_path / "copy-key.pem"
        other_cert.write_bytes(open(cert, "rb").read())
        other_key.write_bytes(open(key, "rb").read())
        monkeypatch.setenv("LOOPBACK_CLIENT_CERT", str(other_cert))
        monkeypatch.setenv("LOOPBACK_CLIENT_KEY", str(other_key))

        assert internal_loopback_verify() is not first

    def test_falls_back_to_false_when_only_cert_set(self, monkeypatch, client_cert_pair):
        """A half-configured pair must not silently produce a context."""
        cert, _ = client_cert_pair
        monkeypatch.setenv("SSL", "true")
        monkeypatch.setenv("LOOPBACK_CLIENT_CERT", cert)
        monkeypatch.delenv("LOOPBACK_CLIENT_KEY", raising=False)

        assert internal_loopback_verify() is False

    def test_ignored_when_ssl_disabled(self, monkeypatch, client_cert_pair):
        """Plain HTTP loopback never needs a client certificate."""
        cert, key = client_cert_pair
        monkeypatch.setenv("SSL", "false")
        monkeypatch.setenv("LOOPBACK_CLIENT_CERT", cert)
        monkeypatch.setenv("LOOPBACK_CLIENT_KEY", key)

        assert internal_loopback_verify() is True

    def test_context_is_accepted_by_httpx(self, monkeypatch, client_cert_pair):
        """httpx must accept the returned value wherever it accepts verify."""
        cert, key = client_cert_pair
        monkeypatch.setenv("SSL", "true")
        monkeypatch.setenv("LOOPBACK_CLIENT_CERT", cert)
        monkeypatch.setenv("LOOPBACK_CLIENT_KEY", key)

        client = httpx.AsyncClient(verify=internal_loopback_verify())

        assert isinstance(client, httpx.AsyncClient)


class _CapturingAsyncClient:
    """Async-CM ``httpx.AsyncClient`` stand-in that captures construction + post kwargs.

    Records the ``transport`` and ``base_url`` passed to the constructor and the
    ``url``/``content``/``headers``/``timeout`` of the inner ``.post`` call so
    tests can assert on the in-process dispatch contract without touching the
    real FastAPI app.
    """

    last_init_kwargs: dict[str, Any] = {}
    last_post_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).last_init_kwargs = kwargs

    async def __aenter__(self) -> "_CapturingAsyncClient":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def post(self, url: str, **kwargs: Any) -> Any:
        type(self).last_post_kwargs = {"url": url, **kwargs}
        # Return a minimal Response-like sentinel; the executor under test
        # never inspects this object in the unit-test path.
        return object()


class TestPostRpcInProcess:
    """Tests for ``post_rpc_in_process`` (PR #4987).

    The helper centralises in-process ``/rpc`` dispatch so all four affinity
    sites (cross-worker forward + cross-worker SSE/RPC + local-owned + the
    HTTP-affinity-forwarded re-entry) execute on the worker that holds the
    bound upstream session, instead of looping back over the shared gunicorn
    socket and scattering to a random worker. The load-bearing details pinned
    here: the transport is ``httpx.ASGITransport`` (proves in-process, not
    network loopback), the path is exactly ``/_internal/mcp/rpc`` (the
    trusted-internal route, not the public ``/rpc`` and not the original request
    path), ``content``/``timeout`` pass through unchanged, and the caller's
    ``headers`` are preserved while the trust markers are attached on top.
    """

    @pytest.mark.asyncio
    async def test_dispatches_via_asgi_transport_in_process(self):
        """Asserts the AsyncClient is constructed with an ``httpx.ASGITransport``.

        This is the whole point of #4987 — a real ``httpx.AsyncClient(verify=...)``
        to ``127.0.0.1`` would hit the shared gunicorn socket and the kernel
        would route the call to an arbitrary worker that does not hold the
        bound upstream session.
        """
        with patch("mcpgateway.utils.internal_http.httpx.AsyncClient", _CapturingAsyncClient):
            await post_rpc_in_process(content=b"{}", headers={"x-forwarded-internally": "true"}, timeout=1.0, auth_context="ctx")
        assert isinstance(_CapturingAsyncClient.last_init_kwargs.get("transport"), httpx.ASGITransport)

    @pytest.mark.asyncio
    async def test_posts_to_rpc_endpoint(self):
        """The helper targets exactly ``/_internal/mcp/rpc`` — the trusted-internal JSON-RPC route."""
        with patch("mcpgateway.utils.internal_http.httpx.AsyncClient", _CapturingAsyncClient):
            await post_rpc_in_process(content=b"{}", headers={"x-forwarded-internally": "true"}, timeout=1.0, auth_context="ctx")
        assert _CapturingAsyncClient.last_post_kwargs["url"] == "/_internal/mcp/rpc"

    @pytest.mark.asyncio
    async def test_propagates_content_headers_and_timeout(self):
        """``content`` and ``timeout`` reach the inner ``.post`` unchanged, and the
        caller's ``headers`` are preserved with the trust markers attached on top.

        Each caller builds its own loop-stop header set; the helper must not drop
        or replace them, but it does add the trusted-internal runtime markers and
        the encoded auth context.
        """
        headers = {"x-forwarded-internally": "true", "x-mcp-session-id": "abc", "authorization": "Bearer x"}
        body = b'{"jsonrpc":"2.0","method":"tools/list","id":1}'

        with patch("mcpgateway.utils.internal_http.httpx.AsyncClient", _CapturingAsyncClient):
            await post_rpc_in_process(content=body, headers=headers, timeout=7.5, auth_context="edge-ctx")

        captured = _CapturingAsyncClient.last_post_kwargs
        assert captured["content"] == body
        assert captured["timeout"] == 7.5
        # Caller headers preserved untouched...
        for key, value in headers.items():
            assert captured["headers"][key] == value
        # ...and the trust markers attached on top.
        assert captured["headers"]["x-contextforge-mcp-runtime"] == "affinity"
        assert captured["headers"]["x-contextforge-auth-context"] == "edge-ctx"
        assert captured["headers"]["x-contextforge-mcp-runtime-auth"]

    @pytest.mark.asyncio
    async def test_requires_non_empty_auth_context(self):
        """An empty ``auth_context`` is rejected before any dispatch is attempted."""
        with patch("mcpgateway.utils.internal_http.httpx.AsyncClient", _CapturingAsyncClient):
            with pytest.raises(ValueError):
                await post_rpc_in_process(content=b"{}", headers={}, timeout=1.0, auth_context="")

    @pytest.mark.asyncio
    async def test_uses_loopback_base_url(self, monkeypatch):
        """The AsyncClient's ``base_url`` is the gateway's loopback URL.

        ASGITransport ignores ``base_url`` for routing — the FastAPI app sees
        the request directly — but the base URL still appears in logs and in
        observability scopes, so it must be the loopback.
        """
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        monkeypatch.delenv("SSL", raising=False)
        with patch("mcpgateway.utils.internal_http.httpx.AsyncClient", _CapturingAsyncClient):
            await post_rpc_in_process(content=b"{}", headers={}, timeout=1.0, auth_context="ctx")
        assert _CapturingAsyncClient.last_init_kwargs.get("base_url") == "http://127.0.0.1:4444"
