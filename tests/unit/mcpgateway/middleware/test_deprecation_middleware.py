# -*- coding: utf-8 -*-
"""tests/unit/mcpgateway/middleware/test_deprecation_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for mcpgateway.middleware.deprecation.DeprecationHeadersMiddleware
and the _is_legacy_path helper.
"""

from __future__ import annotations

# Third-Party
import pytest

# Standard
import logging
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

# Third-Party
from mcpgateway.middleware.deprecation import DeprecationHeadersMiddleware, _is_legacy_path

# ---------------------------------------------------------------------------
# _is_legacy_path unit tests (pure logic, no ASGI needed)
# ---------------------------------------------------------------------------


class TestIsLegacyPath:
    """Verify the path-classification predicate."""

    @pytest.mark.parametrize(
        "path",
        [
            "/tools",
            "/tools/123",
            "/tools/123/execute",
            "/servers",
            "/servers/abc/sse",
            "/resources",
            "/prompts",
            "/gateways",
            "/roots",
            "/metrics",
            "/tags",
            "/export",
            "/import",
            "/admin",
            "/admin/llm",
            "/admin/runtime",
            "/a2a",
            "/observability",
            "/reverse-proxy",
            "/reverse-proxy/ws",
            "/cancellation",
            "/toolops",
            "/auth",
            "/auth/email",
            "/auth/sso",
            "/teams",
            "/tokens",
            "/rbac",
            "/llmchat",
            "/llm",
            "/protocol",
        ],
    )
    def test_legacy_paths_return_true(self, path: str):
        assert _is_legacy_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/v1/tools",
            "/v1/tools/123",
            "/v1/servers",
            "/v1/admin",
            "/v1/a2a",
            "/health",
            "/ready",
            "/health/security",
            "/mcp",
            "/_internal/mcp/transport",
            "/oauth/token",
            "/oauth/authorize",
            "/.well-known/security.txt",
            "/.well-known/agent.json",
            "/servers/abc/.well-known/agent.json",
            "/version",
            "/static/main.js",
            "/",
            "/favicon.ico",
            "/api/logs/search",
            "/api/metrics/rollup",
        ],
    )
    def test_non_legacy_paths_return_false(self, path: str):
        assert _is_legacy_path(path) is False

    def test_servers_well_known_subpath_excluded(self):
        """Ensure /servers/{id}/.well-known/* is never treated as legacy."""
        assert _is_legacy_path("/servers/my-server/.well-known/agent.json") is False

    def test_path_prefix_boundary_respected(self):
        """'/serverside' must NOT match because it doesn't start with '/servers/'."""
        assert _is_legacy_path("/serverside") is False

    def test_exact_prefix_match_included(self):
        """/servers alone (no trailing slash) must match."""
        assert _is_legacy_path("/servers") is True

    def test_path_with_null_byte_returns_false(self):
        """Null byte in path triggers control-char rejection (lines 131-132)."""
        assert _is_legacy_path("/tools\x00evil") is False

    def test_path_with_bell_control_char_returns_false(self):
        """Non-whitespace control char (\\x07) triggers rejection (lines 131-132)."""
        assert _is_legacy_path("/tools\x07") is False


# ---------------------------------------------------------------------------
# Middleware ASGI integration tests
# ---------------------------------------------------------------------------

SUNSET = "Wed, 13 May 2026 00:00:00 GMT"


def _build_app(path: str, status: int = 200):
    """Return a minimal raw-ASGI app that serves *path* with *status*."""

    async def _app(scope, receive, send):
        if scope["type"] == "http" and scope["path"] == path:
            await send({"type": "http.response.start", "status": status, "headers": []})
            await send({"type": "http.response.body", "body": b"ok", "more_body": False})
        else:
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b"not found", "more_body": False})

    return _app


async def _call(middleware, path: str) -> tuple[int, dict[str, str]]:
    """Drive *middleware* with a synthetic HTTP scope and return (status, headers)."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [],
    }
    received_status: list[int] = []
    received_headers: list[dict[str, str]] = []

    async def _receive():
        return {"type": "http.request", "body": b""}

    async def _send(message):
        if message.get("type") == "http.response.start":
            received_status.append(message["status"])
            received_headers.append({k.decode(): v.decode() for k, v in message.get("headers", [])})

    await middleware(scope, _receive, _send)
    return received_status[0], received_headers[0]


class TestDeprecationHeadersMiddlewareHeaders:
    """Middleware stamps the correct headers on legacy paths."""

    def setup_method(self):
        self.mw = DeprecationHeadersMiddleware(_build_app("/tools"), sunset_date=SUNSET)

    @pytest.mark.asyncio
    async def test_sunset_header_present_on_legacy_path(self):
        status, headers = await _call(self.mw, "/tools")
        assert status == 200
        assert headers.get("sunset") == SUNSET

    @pytest.mark.asyncio
    async def test_deprecation_header_present_on_legacy_path(self):
        _, headers = await _call(self.mw, "/tools")
        assert headers.get("deprecation") == "true"

    @pytest.mark.asyncio
    async def test_link_header_points_to_v1_equivalent(self):
        _, headers = await _call(self.mw, "/tools")
        assert headers.get("link") == '</v1/tools>; rel="successor-version"'

    @pytest.mark.asyncio
    async def test_x_deprecated_endpoint_header_present(self):
        _, headers = await _call(self.mw, "/tools")
        msg = headers.get("x-deprecated-endpoint", "")
        assert "/v1/tools" in msg
        assert SUNSET in msg

    @pytest.mark.asyncio
    async def test_no_headers_on_v1_path(self):
        mw = DeprecationHeadersMiddleware(_build_app("/v1/tools"), sunset_date=SUNSET)
        _, headers = await _call(mw, "/v1/tools")
        assert "sunset" not in headers
        assert "deprecation" not in headers

    @pytest.mark.asyncio
    async def test_no_headers_on_health_path(self):
        mw = DeprecationHeadersMiddleware(_build_app("/health"), sunset_date=SUNSET)
        _, headers = await _call(mw, "/health")
        assert "sunset" not in headers

    @pytest.mark.asyncio
    async def test_no_headers_on_well_known_path(self):
        mw = DeprecationHeadersMiddleware(_build_app("/.well-known/security.txt"), sunset_date=SUNSET)
        _, headers = await _call(mw, "/.well-known/security.txt")
        assert "sunset" not in headers

    @pytest.mark.asyncio
    async def test_no_headers_on_servers_well_known(self):
        path = "/servers/abc/.well-known/agent.json"
        mw = DeprecationHeadersMiddleware(_build_app(path), sunset_date=SUNSET)
        _, headers = await _call(mw, path)
        assert "sunset" not in headers

    @pytest.mark.asyncio
    async def test_no_headers_on_oauth_path(self):
        mw = DeprecationHeadersMiddleware(_build_app("/oauth/token"), sunset_date=SUNSET)
        _, headers = await _call(mw, "/oauth/token")
        assert "sunset" not in headers

    @pytest.mark.asyncio
    async def test_no_headers_on_mcp_path(self):
        mw = DeprecationHeadersMiddleware(_build_app("/mcp"), sunset_date=SUNSET)
        _, headers = await _call(mw, "/mcp")
        assert "sunset" not in headers

    @pytest.mark.asyncio
    async def test_link_header_includes_full_path(self):
        mw = DeprecationHeadersMiddleware(_build_app("/servers/123"), sunset_date=SUNSET)
        _, headers = await _call(mw, "/servers/123")
        assert headers.get("link") == '</v1/servers/123>; rel="successor-version"'

    @pytest.mark.asyncio
    async def test_websocket_scope_passed_through_unchanged(self):
        """Non-HTTP scopes must be forwarded without any modification."""
        inner_called: list[bool] = []

        async def _ws_app(scope, receive, send):
            inner_called.append(True)

        mw = DeprecationHeadersMiddleware(_ws_app, sunset_date=SUNSET)
        scope = {"type": "websocket", "path": "/tools"}
        await mw(scope, None, None)
        assert inner_called == [True]

    @pytest.mark.asyncio
    async def test_existing_headers_preserved(self):
        """Deprecation headers must be appended, not replace existing headers."""

        async def _app_with_header(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": [(b"x-custom", b"existing")]})
            await send({"type": "http.response.body", "body": b"ok", "more_body": False})

        mw = DeprecationHeadersMiddleware(_app_with_header, sunset_date=SUNSET)
        _, headers = await _call(mw, "/tools")
        assert headers.get("x-custom") == "existing"
        assert headers.get("sunset") == SUNSET


# ---------------------------------------------------------------------------
# DeprecationHeadersMiddleware __init__ sunset-date parsing branches
# ---------------------------------------------------------------------------


class TestDeprecationHeadersMiddlewareInit:
    """Verify __init__ logging branches based on sunset proximity."""

    def test_sunset_approaching_within_30_days_logs_warning(self, caplog):
        """Sunset ≤30 days away triggers approaching-warning log (line 203)."""
        soon = datetime.now(timezone.utc) + timedelta(days=15)
        sunset_str = format_datetime(soon)

        with caplog.at_level(logging.WARNING, logger="mcpgateway.middleware.deprecation"):
            DeprecationHeadersMiddleware(_build_app("/tools"), sunset_date=sunset_str)

        messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("sunset approaching" in m.lower() for m in messages)

    def test_invalid_sunset_date_logs_error(self, caplog):
        """Unparseable sunset date logs an error (lines 214-215)."""
        with caplog.at_level(logging.ERROR, logger="mcpgateway.middleware.deprecation"):
            DeprecationHeadersMiddleware(_build_app("/tools"), sunset_date="not-a-valid-date")

        messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
        assert any("Failed to parse sunset date" in m for m in messages)


# ---------------------------------------------------------------------------
# Data-consistency tests
# ---------------------------------------------------------------------------


class TestConfigConsistency:
    """Verify sunset date and comment consistency across config sources."""

    def test_env_example_sunset_date_matches_config_default(self):
        """LEGACY_API_SUNSET_DATE in .env.example must equal config.py default.

        Operators who copy .env.example (documented first step in README) must
        get the same sunset date as those who rely on config defaults.
        """
        import os
        import re

        from mcpgateway.config import Settings

        # Read .env.example from repo root (two levels above tests/)
        repo_root = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
        env_example_path = os.path.normpath(os.path.join(repo_root, ".env.example"))

        assert os.path.exists(env_example_path), f".env.example not found at {env_example_path}"

        with open(env_example_path) as f:
            content = f.read()

        match = re.search(r"^LEGACY_API_SUNSET_DATE=(.+)$", content, re.MULTILINE)
        assert match, "LEGACY_API_SUNSET_DATE not found in .env.example"
        env_example_value = match.group(1).strip()

        # Get the config.py field default without instantiating (avoids env var pollution)
        field = Settings.model_fields["legacy_api_sunset_date"]
        config_default = field.default
        assert config_default is not None, "legacy_api_sunset_date has no default in config.py"

        assert env_example_value == config_default, (
            f".env.example LEGACY_API_SUNSET_DATE={env_example_value!r} "
            f"differs from config.py default={config_default!r}. "
            "Keep both in sync so operators copying .env.example get the expected sunset window."
        )

    def test_legacy_prefixes_auth_comments_use_email_auth_flag(self):
        """_LEGACY_PREFIXES comments for auth paths must reference EMAIL_AUTH_ENABLED.

        The /auth, /teams, /tokens, /rbac prefixes are gated on email_auth_enabled
        in _assemble_routers, not on AUTH_REQUIRED. Wrong comments mislead maintainers
        adding new routers.
        """
        import inspect

        from mcpgateway.middleware import deprecation

        source = inspect.getsource(deprecation)

        auth_prefixes = ["/auth", "/teams", "/tokens", "/rbac"]
        for prefix in auth_prefixes:
            # Find the line containing this prefix in _LEGACY_PREFIXES
            for line in source.splitlines():
                if f'"{prefix}"' in line or f"'{prefix}'" in line:
                    assert "AUTH_REQUIRED" not in line, (
                        f"Line for {prefix!r} still uses '# AUTH_REQUIRED' comment. "
                        "Change to '# EMAIL_AUTH_ENABLED' — these routes are gated on "
                        "settings.email_auth_enabled in _assemble_routers, not AUTH_REQUIRED."
                    )
                    assert "EMAIL_AUTH_ENABLED" in line, (
                        f"Line for {prefix!r} missing '# EMAIL_AUTH_ENABLED' comment. "
                        "Add it so maintainers know the correct feature flag."
                    )
                    break
