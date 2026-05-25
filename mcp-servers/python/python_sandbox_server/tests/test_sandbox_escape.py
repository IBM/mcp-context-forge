# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/python_sandbox_server/tests/test_sandbox_escape.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Regression tests for GHSA-xm98-3vcf-fph7 (RestrictedPython sandbox escape).
These tests must pass — a failure means the sandbox is broken.
"""

import os

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Sandbox escape payload tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escape_via_class_subclasses_blocked():
    """Original GHSA-xm98 payload must be blocked — at compile time or runtime."""
    from python_sandbox_server.server_fastmcp import execute_code

    result = await execute_code(code="().__class__.__bases__[0].__subclasses__()")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_runtime_constructed_dunder_blocked():
    """Runtime string concat for dunder names must still be blocked."""
    from python_sandbox_server.server_fastmcp import execute_code

    # getattr is not in safe_builtins — name lookup fails before guard is even needed
    result = await execute_code(code="getattr((), '__cla' + 'ss__')")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_len_builtin_works():
    """len() builtin must work — sanity check that the sandbox is not over-restrictive."""
    from python_sandbox_server.server_fastmcp import execute_code

    result = await execute_code(code='len("hello")')
    assert result["success"] is True
    assert result["result"] == 5


@pytest.mark.asyncio
async def test_guarded_setattr_blocks_all_dunders():
    """_guarded_setattr must block assignment to any dunder attribute."""
    from python_sandbox_server.server_fastmcp import execute_code

    result = await execute_code(code="class X: pass\nx = X()\nx.__class__ = int")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_hasattr_not_in_safe_builtins():
    """hasattr must not be available — it bypasses _guarded_getattr."""
    from python_sandbox_server.server_fastmcp import execute_code

    result = await execute_code(code="hasattr((), '__class__')")
    assert result["success"] is False


# ---------------------------------------------------------------------------
# HTTP transport auth tests
# ---------------------------------------------------------------------------


def _make_secured_client(token: str) -> TestClient:
    """Build a TestClient for a minimal app wrapped with _BearerAuthMiddleware."""
    from python_sandbox_server.server_fastmcp import _BearerAuthMiddleware

    async def homepage(request):  # type: ignore[misc]
        return PlainTextResponse("OK")

    app = Starlette(routes=[Route("/", homepage)])
    secured = _BearerAuthMiddleware(app)
    return TestClient(secured, raise_server_exceptions=False)


def test_http_server_exits_without_token(monkeypatch):
    """main() must exit(1) when SANDBOX_API_TOKEN is not set."""
    monkeypatch.delenv("SANDBOX_API_TOKEN", raising=False)
    monkeypatch.setattr("sys.argv", ["server", "--transport", "http"])

    import importlib

    import python_sandbox_server.server_fastmcp as mod

    monkeypatch.setattr(mod, "SANDBOX_API_TOKEN", "")

    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 1


def test_http_server_exits_on_weak_token(monkeypatch):
    """main() must exit(1) when SANDBOX_API_TOKEN is shorter than 32 chars."""
    monkeypatch.setattr("sys.argv", ["server", "--transport", "http"])

    import python_sandbox_server.server_fastmcp as mod

    monkeypatch.setattr(mod, "SANDBOX_API_TOKEN", "tooshort")

    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 1


def test_bearer_middleware_rejects_missing_auth(monkeypatch):
    """Request with no Authorization header must get 401."""
    import python_sandbox_server.server_fastmcp as mod

    monkeypatch.setattr(mod, "SANDBOX_API_TOKEN", "a" * 32)

    client = _make_secured_client("a" * 32)
    response = client.get("/")
    assert response.status_code == 401


def test_bearer_middleware_rejects_wrong_token(monkeypatch):
    """Request with incorrect bearer token must get 401."""
    import python_sandbox_server.server_fastmcp as mod

    monkeypatch.setattr(mod, "SANDBOX_API_TOKEN", "a" * 32)

    client = _make_secured_client("a" * 32)
    response = client.get("/", headers={"Authorization": "Bearer " + "b" * 32})
    assert response.status_code == 401


def test_bearer_middleware_accepts_correct_token(monkeypatch):
    """Request with the correct bearer token must pass through."""
    import python_sandbox_server.server_fastmcp as mod

    token = "a" * 32
    monkeypatch.setattr(mod, "SANDBOX_API_TOKEN", token)

    client = _make_secured_client(token)
    response = client.get("/", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
