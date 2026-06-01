# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_internal_http.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for internal loopback HTTP helpers.
"""

# Standard
from typing import Any
from unittest.mock import patch

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.utils.internal_http import _is_ssl_enabled, internal_loopback_base_url, internal_loopback_verify, post_rpc_in_process


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
        """Only exact lowercase 'true' enables SSL, matching run-gunicorn.sh / run-granian.sh."""
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
    network loopback), the path is exactly ``/rpc`` (not the original request
    path), and ``content``/``headers``/``timeout`` pass through unchanged.
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
            await post_rpc_in_process(content=b"{}", headers={"x-forwarded-internally": "true"}, timeout=1.0)
        assert isinstance(_CapturingAsyncClient.last_init_kwargs.get("transport"), httpx.ASGITransport)

    @pytest.mark.asyncio
    async def test_posts_to_rpc_endpoint(self):
        """The helper targets exactly ``/rpc`` — the public JSON-RPC handler."""
        with patch("mcpgateway.utils.internal_http.httpx.AsyncClient", _CapturingAsyncClient):
            await post_rpc_in_process(content=b"{}", headers={"x-forwarded-internally": "true"}, timeout=1.0)
        assert _CapturingAsyncClient.last_post_kwargs["url"] == "/rpc"

    @pytest.mark.asyncio
    async def test_propagates_content_headers_and_timeout(self):
        """``content``, ``headers``, and ``timeout`` reach the inner ``.post`` unchanged.

        Each caller builds its own loop-stop header set; the helper must not
        mutate or replace them.
        """
        headers = {"x-forwarded-internally": "true", "x-mcp-session-id": "abc", "authorization": "Bearer x"}
        body = b'{"jsonrpc":"2.0","method":"tools/list","id":1}'

        with patch("mcpgateway.utils.internal_http.httpx.AsyncClient", _CapturingAsyncClient):
            await post_rpc_in_process(content=body, headers=headers, timeout=7.5)

        captured = _CapturingAsyncClient.last_post_kwargs
        assert captured["content"] == body
        assert captured["headers"] == headers
        assert captured["timeout"] == 7.5

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
            await post_rpc_in_process(content=b"{}", headers={}, timeout=1.0)
        assert _CapturingAsyncClient.last_init_kwargs.get("base_url") == "http://127.0.0.1:4444"
