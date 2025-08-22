# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_version.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

test_version.py - full-coverage unit tests for diagnostics endpoint
This suite drives every code path in :pyfile:`mcpgateway/version.py`.
"""

# Future
from __future__ import annotations

# Standard
import re
import types
from typing import Any, Dict

# Third-Party
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest


# --------------------------------------------------------------------------- #
# Utility - fake psutil so _system_metrics code path runs                     #
# --------------------------------------------------------------------------- #
def _make_fake_psutil() -> types.ModuleType:  # noqa: D401
    """Return an in-memory *psutil* stub implementing just what we need."""

    class _MemInfo:
        def __init__(self, total: int, used: int) -> None:
            self.total, self.used = total, used

    class _CPUFreq:
        current = 2_400

    class _ProcMem:  # noqa: D401 - simple struct
        rss, vms = 10 * 1_048_576, 20 * 1_048_576

    class _Proc:
        pid = 1234

        def num_fds(self) -> int:  # noqa: D401
            return 8

        def cpu_percent(self, interval: float = 0.0) -> float:  # noqa: D401
            return 1.5

        def memory_info(self) -> _ProcMem:  # noqa: D401
            return _ProcMem()

        def num_threads(self) -> int:  # noqa: D401
            return 5

    def _disk_usage(path: str):  # noqa: D401 - simple namespace
        return types.SimpleNamespace(
            total=100 * 1_073_741_824,
            used=40 * 1_073_741_824,
        )

    fake = types.ModuleType("fake_psutil")
    fake.virtual_memory = lambda: _MemInfo(8 * 1_073_741_824, 4 * 1_073_741_824)
    fake.swap_memory = lambda: _MemInfo(2 * 1_073_741_824, 1 * 1_073_741_824)
    fake.cpu_freq = lambda: _CPUFreq()
    fake.cpu_percent = lambda interval=0.0: 12.3
    fake.cpu_count = lambda logical=True: 8
    fake.boot_time = lambda: 0
    fake.Process = _Proc
    fake.disk_usage = _disk_usage
    return fake


# --------------------------------------------------------------------------- #
# Helper - build test app                                                     #
# --------------------------------------------------------------------------- #
def _build_app(monkeypatch: pytest.MonkeyPatch, auth_ok: bool = True) -> FastAPI:
    """Return an isolated FastAPI app with only the diagnostics router."""
    # First-Party
    from mcpgateway import version as ver_mod

    # Stub heavy helpers
    monkeypatch.setattr(ver_mod, "_database_version", lambda: ("db-vX", True))
    monkeypatch.setattr(ver_mod, "_system_metrics", lambda: {"stub": True})
    monkeypatch.setattr(ver_mod, "REDIS_AVAILABLE", False, raising=False)

    # Auth override
    async def _allow() -> Dict[str, str]:
        return {"user": "tester"}

    async def _deny() -> None:
        raise HTTPException(status_code=401)

    app = FastAPI()
    app.include_router(ver_mod.router)
    app.dependency_overrides[ver_mod.require_auth] = _allow if auth_ok else _deny
    return app


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Authenticated *TestClient* fixture."""
    return TestClient(_build_app(monkeypatch, auth_ok=True))


# --------------------------------------------------------------------------- #
# Endpoint - happy path                                                       #
# --------------------------------------------------------------------------- #
def test_version_json_ok(client: TestClient) -> None:
    rsp = client.get("/version")
    assert rsp.status_code == 200
    assert rsp.headers["content-type"].startswith("application/json")
    payload: Dict[str, Any] = rsp.json()
    assert payload["database"]["server_version"] == "db-vX"
    assert payload["system"] == {"stub": True}


def test_version_html_query_param(client: TestClient) -> None:
    rsp = client.get("/version?fmt=html")
    assert rsp.status_code == 200
    assert rsp.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in rsp.text.lower()


def test_version_html_accept_header(client: TestClient) -> None:
    rsp = client.get("/version", headers={"accept": "text/html"})
    assert rsp.status_code == 200
    assert rsp.headers["content-type"].startswith("text/html")
    assert "<h1" in rsp.text


def test_version_html_all_sections(client: TestClient) -> None:
    html = client.get("/version?fmt=html").text
    for sec in ["App", "Platform", "Database", "Redis", "Settings", "System", "Environment"]:
        assert re.search(rf"<h2[^>]*>{sec}</h2>", html)


# --------------------------------------------------------------------------- #
# Authentication                                                              #
# --------------------------------------------------------------------------- #
def test_version_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    unauth_client = TestClient(_build_app(monkeypatch, auth_ok=False))
    rsp = unauth_client.get("/version")
    assert rsp.status_code == 401


# --------------------------------------------------------------------------- #
# Helper functions                                                            #
# --------------------------------------------------------------------------- #
def test_is_secret_and_public_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # First-Party
    from mcpgateway import version as ver_mod

    monkeypatch.setenv("PLAIN", "1")
    monkeypatch.setenv("X_SECRET", "bad")
    assert "PLAIN" in ver_mod._public_env()
    assert "X_SECRET" not in ver_mod._public_env()


def test_sanitize_url() -> None:
    # First-Party
    from mcpgateway import version as ver_mod

    url = "postgres://u:p@host:5432/db"
    assert ver_mod._sanitize_url(url) == "postgres://u@host:5432/db"


# --------------------------------------------------------------------------- #
# _database_version branches                                                  #
# --------------------------------------------------------------------------- #
def test_database_version_success(monkeypatch: pytest.MonkeyPatch) -> None:
    # First-Party
    from mcpgateway import version as ver_mod

    class _Conn:
        def __enter__(self):  # noqa: D401
            return self

        def __exit__(self, *exc):  # noqa: D401
            pass

        def execute(self, stmt):  # noqa: D401
            class _Res:
                scalar = lambda self: "15.0"  # noqa: D401

            return _Res()

    class _Engine:
        dialect = types.SimpleNamespace(name="postgresql")

        def connect(self):  # noqa: D401
            return _Conn()

    monkeypatch.setattr(ver_mod, "engine", _Engine())
    ver, ok = ver_mod._database_version()
    assert ok and ver == "15.0"


def test_database_version_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # First-Party
    from mcpgateway import version as ver_mod

    class _BrokenEngine:
        dialect = types.SimpleNamespace(name="sqlite")

        def connect(self):  # noqa: D401
            raise RuntimeError("boom")

    monkeypatch.setattr(ver_mod, "engine", _BrokenEngine())
    ver, ok = ver_mod._database_version()
    assert not ok and "boom" in ver


# --------------------------------------------------------------------------- #
# _system_metrics with fake psutil                                            #
# --------------------------------------------------------------------------- #
def test_system_metrics_full(monkeypatch: pytest.MonkeyPatch) -> None:
    # First-Party
    from mcpgateway import version as ver_mod

    monkeypatch.setattr(ver_mod, "psutil", _make_fake_psutil())
    metrics = ver_mod._system_metrics()
    assert metrics["process"]["pid"] == 1234
