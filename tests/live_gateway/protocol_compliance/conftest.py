# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/protocol_compliance/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Protocol-compliance harness fixtures.

The ``client`` fixture is parametrized over every ``(target, transport)``
pair declared below, so every test body runs across the full matrix
automatically:

    reference-stdio           — in-process Client(mcp) against reference server
    gateway_proxy-http        — ASGI transport to in-process gateway /mcp
    gateway_virtual-http      — ASGI transport to /servers/{id}/mcp

Gateway rows require a session-scoped in-process gateway app plus a
subprocess reference server registered as an upstream (see fixtures/).

The reference server is normally available as an editable install via the
root ``pyproject.toml``. The sys.path fallback below only fires when
``compliance_reference_server`` isn't already importable — e.g. ad-hoc
``uv run --with-editable ...`` invocations.
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from importlib.util import find_spec
from pathlib import Path
from typing import AsyncIterator, Callable

import pytest
import pytest_asyncio
from fastmcp.client import Client


# ---------------------------------------------------------------------------
# XPASS capture (compliance-matrix integration)
#
# The compliance matrix needs to detect XPASS events — an xfail-marked test
# that passes anyway, signaling a documented gap may have closed. Standard
# pytest JUnit XML omits this information when ``strict=False`` (the test
# reports as a plain pass with only a console warning).
#
# When the env var ``COMPLIANCE_XPASS_LOG`` is set, this hook appends one
# nodeid per line to that file for every XPASS observed in the ``call``
# phase. The matrix script reads the file after pytest exits.
# ---------------------------------------------------------------------------
def pytest_runtest_logreport(report):  # noqa: D401 — pytest hook
    if report.when != "call":
        return
    if not (report.passed and getattr(report, "wasxfail", "")):
        return
    sidecar = os.environ.get("COMPLIANCE_XPASS_LOG")
    if not sidecar:
        return
    sidecar_path = Path(sidecar)
    try:
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        with sidecar_path.open("a") as f:
            reason = getattr(report, "wasxfail", "") or ""
            f.write(f"{report.nodeid}\t{reason}\n")
    except OSError as exc:
        # An unwriteable sidecar (permissions, full disk, racing cleanup)
        # shouldn't poison the whole pytest run — warn and continue. The
        # compliance matrix will see a low XPASS count and log a bookkeeping
        # drift warning of its own.
        print(f"[conftest] XPASS sidecar write failed ({type(exc).__name__}: {exc}); " f"nodeid={report.nodeid}", file=sys.stderr)


if find_spec("compliance_reference_server") is None:
    _REFERENCE_SRC = Path(__file__).resolve().parents[2] / "mcp-servers" / "python" / "compliance_reference_server" / "src"
    if _REFERENCE_SRC.is_dir():
        sys.path.insert(0, str(_REFERENCE_SRC))

from .fixtures.gateway_live import (  # noqa: E402, F401
    admin_jwt,
    flip_runtime_mode,
    gateway_base_url,
    gateway_http_client,
    runtime_mode_state,
)
from .fixtures.reference_upstream import reference_upstream  # noqa: E402, F401
from .fixtures.upstream_registration import (  # noqa: E402, F401
    registered_reference_upstream,
    virtual_server,
)
from .targets.base import Transport  # noqa: E402
from .targets.gateway_proxy import GatewayProxyTarget  # noqa: E402
from .targets.gateway_virtual import GatewayVirtualServerTarget  # noqa: E402
from .targets.reference import ReferenceTarget  # noqa: E402

# (target_name, transport) pairs — parametrize IDs.
_CASES: list[tuple[str, Transport]] = [
    ("reference", "stdio"),
    ("gateway_proxy", "http"),
    ("gateway_virtual", "http"),
]


def _gateway_fixture_or_skip(request: pytest.FixtureRequest, name: str):
    """Resolve a gateway-side fixture or pytest.skip with a readable reason.

    Scope: this only swallows runtime unreachability / refusal — connection
    errors, httpx transport errors, and pytest.skip from dependent fixtures.
    Programming errors (ImportError, NameError, SyntaxError, AttributeError
    on the fixture body, TypeError from a bad signature) propagate so a
    broken fixture definition surfaces as a real test error rather than
    pretending every gateway row is "unavailable". Without this narrowing,
    a typo in ``gateway_live.py`` would silently skip every gateway row
    across the entire matrix and the bug would escape notice.
    """
    try:
        return request.getfixturevalue(name)
    except pytest.skip.Exception:
        raise  # pytest.skip() from a dependency — let it through verbatim
    except (ImportError, NameError, SyntaxError, AttributeError, TypeError):
        raise  # broken fixture definition — real test error
    except Exception as exc:  # noqa: BLE001 — runtime unreachability / refusal
        pytest.skip(f"gateway fixture {name!r} unavailable: {type(exc).__name__}: {str(exc)[:200]}")


def _build_target(target_name: str, request: pytest.FixtureRequest):
    """Construct a ComplianceTarget for ``target_name``, skipping gateway rows on failure."""
    if target_name == "reference":
        return ReferenceTarget()
    if target_name == "gateway_proxy":
        base_url = _gateway_fixture_or_skip(request, "gateway_base_url")
        token = _gateway_fixture_or_skip(request, "admin_jwt")
        # Ensures the reference server is registered as an upstream so the
        # gateway federates its tools — otherwise echo/add/boom etc. are absent
        # and every gateway_proxy test body fails with "tool not found".
        _gateway_fixture_or_skip(request, "registered_reference_upstream")
        return GatewayProxyTarget(base_url=base_url, auth_token=token)
    if target_name == "gateway_virtual":
        base_url = _gateway_fixture_or_skip(request, "gateway_base_url")
        token = _gateway_fixture_or_skip(request, "admin_jwt")
        server = _gateway_fixture_or_skip(request, "virtual_server")
        return GatewayVirtualServerTarget(base_url=base_url, auth_token=token, server_id=server["id"])
    raise AssertionError(f"unknown target: {target_name!r}")


@pytest_asyncio.fixture(params=_CASES, ids=[f"{t}-{x}" for t, x in _CASES])
async def client(request: pytest.FixtureRequest) -> AsyncIterator[Client]:
    """Yield a connected FastMCP Client for the parametrized (target, transport) cell.

    Gateway-side fixtures are pulled *lazily* via ``request.getfixturevalue`` so
    reference-stdio tests don't pay the gateway boot cost, and gateway-side
    boot failures skip (not error) the affected rows.
    """
    target_name, transport = request.param
    target = _build_target(target_name, request)
    async with target.client(transport) as connected:
        yield connected


@pytest.fixture(params=_CASES, ids=[f"{t}-{x}" for t, x in _CASES])
def connect(request: pytest.FixtureRequest) -> Callable:
    """Parametrized factory: returns an async context manager that takes handler kwargs.

    Used by tests that need to register client-side handlers (sampling,
    elicitation, roots, progress, log) before the FastMCP Client connects.

    Example::

        async def test_X(connect):
            async with connect(sampling_handler=stub) as client:
                ...
    """
    target_name, transport = request.param

    @asynccontextmanager
    async def _connect(**client_kwargs):
        target = _build_target(target_name, request)
        async with target.client(transport, **client_kwargs) as c:
            yield c

    return _connect
