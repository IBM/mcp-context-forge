# -*- coding: utf-8 -*-
"""Tests for :class:`A2APathRewriteMiddleware` (Plan T16).

Location: ./tests/unit/mcpgateway/middleware/test_a2a_path_rewrite.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Covers the v-server path-rewrite middleware that translates
``/servers/{server_id}/a2a/{agent_name}[/...]`` paths into the canonical
``/a2a/{agent_name}[/...]`` form and stamps
``request.scope["a2a_server_id"]`` for the T11 + T12 handlers.

Plan T16 acceptance:

- (a) ``/servers/X/a2a/Y`` rewrites + scope set.
- (b) ``/servers/X/a2a/Y/.well-known/agent-card.json`` rewrites.
- (c) ``/a2a/Y`` untouched.
- (d) ``/servers/X/mcp`` untouched.

These are pure-ASGI unit tests — no FastAPI / TestClient. The
middleware mutates the scope dict in place; we drive it with a
``MagicMock`` ASGI app and inspect ``scope`` after.
"""

from __future__ import annotations

import pytest

from mcpgateway.middleware.a2a_path_rewrite import A2APathRewriteMiddleware


@pytest.fixture
def call_log() -> list:
    """Capture every ``application(scope, receive, send)`` invocation."""
    return []


@pytest.fixture
def middleware(call_log: list) -> A2APathRewriteMiddleware:
    """Return a fresh middleware wrapping a capture-all downstream app."""

    async def fake_app(scope, receive, send):
        call_log.append({"scope": dict(scope), "receive": receive, "send": send})

    return A2APathRewriteMiddleware(fake_app)


def _http_scope(path: str, *, root_path: str = "", raw_path: bytes | None = None) -> dict:
    """Build a minimal HTTP ASGI scope dict for the middleware."""
    scope: dict = {"type": "http", "path": path, "root_path": root_path}
    if raw_path is not None:
        scope["raw_path"] = raw_path
    return scope


class TestPathRewriteBase:
    """Plan T16 acceptance (a): base dispatch URL rewrites."""

    @pytest.mark.asyncio
    async def test_base_dispatch_url_rewrites_and_sets_scope(self, middleware, call_log) -> None:
        """``/servers/X/a2a/Y`` -> ``/a2a/Y`` + ``a2a_server_id=X``."""
        scope = _http_scope("/servers/srv-123/a2a/echo")
        await middleware(scope, None, None)
        assert scope["path"] == "/a2a/echo"
        assert scope["modified_path"] == "/a2a/echo"
        assert scope["a2a_server_id"] == "srv-123"
        assert len(call_log) == 1

    @pytest.mark.asyncio
    async def test_base_dispatch_url_raw_path_aligned(self, middleware) -> None:
        """``raw_path`` keeps in sync with the rewritten ``path`` (latin-1)."""
        scope = _http_scope("/servers/srv-123/a2a/echo", raw_path=b"/servers/srv-123/a2a/echo")
        await middleware(scope, None, None)
        assert scope["raw_path"] == b"/a2a/echo"

    @pytest.mark.asyncio
    async def test_uuid_server_id_preserved_verbatim(self, middleware) -> None:
        """A UUID-shaped server id round-trips into the scope key untouched."""
        uuid_id = "550e8400-e29b-41d4-a716-446655440000"
        scope = _http_scope(f"/servers/{uuid_id}/a2a/echo")
        await middleware(scope, None, None)
        assert scope["a2a_server_id"] == uuid_id
        assert scope["path"] == "/a2a/echo"


class TestPathRewriteSuffix:
    """Plan T16 acceptance (b): URLs with a path suffix rewrite."""

    @pytest.mark.asyncio
    async def test_well_known_card_url_rewrites(self, middleware) -> None:
        """``/servers/X/a2a/Y/.well-known/agent-card.json`` -> ``/a2a/Y/.well-known/...``."""
        scope = _http_scope("/servers/srv-1/a2a/echo/.well-known/agent-card.json")
        await middleware(scope, None, None)
        assert scope["path"] == "/a2a/echo/.well-known/agent-card.json"
        assert scope["a2a_server_id"] == "srv-1"

    @pytest.mark.asyncio
    async def test_arbitrary_suffix_preserved(self, middleware) -> None:
        """The suffix segment after the agent name is preserved verbatim."""
        scope = _http_scope("/servers/srv-1/a2a/echo/tasks/abc/cancel")
        await middleware(scope, None, None)
        assert scope["path"] == "/a2a/echo/tasks/abc/cancel"


class TestPathPassThrough:
    """Plan T16 acceptance (c) + (d): non-matching paths pass through."""

    @pytest.mark.asyncio
    async def test_per_agent_url_untouched(self, middleware, call_log) -> None:
        """Plain ``/a2a/Y`` is NOT matched and NOT rewritten."""
        scope = _http_scope("/a2a/echo")
        await middleware(scope, None, None)
        assert scope["path"] == "/a2a/echo"
        assert "a2a_server_id" not in scope
        assert len(call_log) == 1

    @pytest.mark.asyncio
    async def test_per_agent_well_known_url_untouched(self, middleware) -> None:
        """``/a2a/Y/.well-known/...`` does NOT match the v-server regex."""
        scope = _http_scope("/a2a/echo/.well-known/agent-card.json")
        await middleware(scope, None, None)
        assert scope["path"] == "/a2a/echo/.well-known/agent-card.json"
        assert "a2a_server_id" not in scope

    @pytest.mark.asyncio
    async def test_servers_mcp_url_untouched(self, middleware) -> None:
        """``/servers/X/mcp`` is owned by MCP middleware, NOT rewritten here."""
        scope = _http_scope("/servers/srv-1/mcp")
        await middleware(scope, None, None)
        assert scope["path"] == "/servers/srv-1/mcp"
        assert "a2a_server_id" not in scope

    @pytest.mark.asyncio
    async def test_unrelated_route_untouched(self, middleware) -> None:
        """Other routes (``/tools``, ``/health``, etc.) pass through."""
        scope = _http_scope("/health")
        await middleware(scope, None, None)
        assert scope["path"] == "/health"
        assert "a2a_server_id" not in scope


class TestScopeGuards:
    """Edge cases that MUST be passed through untouched."""

    @pytest.mark.asyncio
    async def test_websocket_scope_passes_through(self, middleware, call_log) -> None:
        """Non-HTTP scope is forwarded verbatim — no rewrite or scope mutation."""
        scope = {"type": "websocket", "path": "/servers/srv-1/a2a/echo"}
        await middleware(scope, None, None)
        assert scope["path"] == "/servers/srv-1/a2a/echo"
        assert "a2a_server_id" not in scope
        assert len(call_log) == 1

    @pytest.mark.asyncio
    async def test_lifespan_scope_passes_through(self, middleware) -> None:
        """``lifespan`` scope (startup/shutdown) is forwarded verbatim."""
        scope = {"type": "lifespan"}
        await middleware(scope, None, None)
        # No path key was set/mutated.
        assert scope == {"type": "lifespan"}


class TestRootPathHandling:
    """Reverse-proxy ``root_path`` correctness."""

    @pytest.mark.asyncio
    async def test_root_path_prefix_stripped_before_match(self, middleware) -> None:
        """Behind a proxy at ``/gw``, ``/gw/servers/X/a2a/Y`` still matches.

        The rewritten path KEEPS the ``root_path`` prefix so downstream
        routes / mounts see the same proxy-aware structure.
        """
        scope = _http_scope("/gw/servers/srv-1/a2a/echo", root_path="/gw")
        await middleware(scope, None, None)
        assert scope["path"] == "/gw/a2a/echo"
        assert scope["modified_path"] == "/a2a/echo"
        assert scope["a2a_server_id"] == "srv-1"

    @pytest.mark.asyncio
    async def test_root_path_with_trailing_slash_normalized(self, middleware) -> None:
        """``root_path="/gw/"`` (with trailing slash) is handled cleanly."""
        scope = _http_scope("/gw/servers/srv-2/a2a/echo", root_path="/gw/")
        await middleware(scope, None, None)
        # The trailing slash is stripped from root_path before prefix matching.
        assert scope["a2a_server_id"] == "srv-2"
        # Path retains the original root_path prefix (without our normalization
        # forcing a particular trailing-slash form).
        assert scope["path"].endswith("/a2a/echo")


class TestNoMembershipEnforcement:
    """Plan T16 must-not-do: middleware does NOT enforce v-server membership."""

    @pytest.mark.asyncio
    async def test_middleware_does_not_query_database(self, middleware, call_log) -> None:
        """A URL with a clearly bogus server id still rewrites successfully.

        Membership is the HANDLER's responsibility (T2 + T3 + T12 step 2 → 404
        per D14). The middleware MUST NOT short-circuit here, even when the
        server_id obviously cannot exist.
        """
        scope = _http_scope("/servers/this-server-id-does-not-exist/a2a/echo")
        await middleware(scope, None, None)
        # Rewrite went through; downstream app was called.
        assert scope["path"] == "/a2a/echo"
        assert scope["a2a_server_id"] == "this-server-id-does-not-exist"
        assert len(call_log) == 1

    @pytest.mark.asyncio
    async def test_middleware_does_not_match_outside_a2a_prefix(self, middleware) -> None:
        """``/servers/X/something-else`` is NOT rewritten."""
        scope = _http_scope("/servers/srv-1/tools/echo")
        await middleware(scope, None, None)
        assert scope["path"] == "/servers/srv-1/tools/echo"
        assert "a2a_server_id" not in scope
