# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a_compliance/conftest.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

A2A protocol-compliance harness fixtures.
The ``client`` fixture is parametrized over every ``(target, transport)``
pair declared below, so every test body runs across the full matrix
automatically:

    reference-jsonrpc       — direct to the live a2a_echo_agent
    gateway_proxy-jsonrpc   — via ContextForge native passthrough
    gateway_virtual-jsonrpc — via ContextForge virtual server

T30 (Wave 7) closed A2A-GAP-001: the gateway-target placeholders are
gone, both ``gateway_proxy`` and ``gateway_virtual`` now drive the
native A2A passthrough that landed in Waves 3 + 4. The blanket
``pytest_collection_modifyitems`` xfail hook was deleted as part of
the closure — per-test ``xfail_on`` (in ``helpers/compliance.py``)
remains available for narrower gaps that don't have a stable
column-wide pattern.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from a2a.client.client import Client

from tests.helpers.auth import make_test_jwt

from .fixtures.echo_agent import (  # noqa: F401 — re-exported for pytest fixture discovery
    echo_agent_base_url,
    echo_agent_card_url,
)
from .targets.base import Transport
from .targets.gateway_proxy import A2AGatewayProxyTarget
from .targets.gateway_virtual import A2AGatewayVirtualServerTarget
from .targets.reference import A2AReferenceTarget

_CASES: list[tuple[str, Transport]] = [
    ("reference", "jsonrpc"),
    ("gateway_proxy", "jsonrpc"),
    ("gateway_virtual", "jsonrpc"),
]

# ───────────────────────────────────────────────────────────────────────
# T28 Part A — minimal gateway-target fixtures for the gap-closure
# matrix. T29 + T30 (Wave 7) replaced the prior placeholder
# ``_open_client`` raises with real ``ClientFactory.create_from_url``
# bodies; the matrix now drives ContextForge's native A2A passthrough
# end-to-end. Wave 2's gap-closure tests still use raw-HTTP via the
# ``raw_card_url`` and ``raw_dispatch_url`` fixtures because they
# pre-date the SDK-driven matrix and validate wire-level shape.
#
# Part B of T28 added the v-server ``server_id`` fixture so the
# ``gateway_virtual`` URL family is exercisable.
# ───────────────────────────────────────────────────────────────────────

# T28 Part B (Wave 7): ``gateway_virtual`` joined the parametrize after
# T20 + T22 confirmed server-CRUD wiring round-trips through
# ``server_a2a_association``. All three targets now share the gap-closure
# matrix.
_PART_A_GAP_CLOSURE_TARGETS: tuple[str, ...] = ("reference", "gateway_proxy", "gateway_virtual")


def _build_target(target_name: str, request: pytest.FixtureRequest):
    """Construct an A2AComplianceTarget for ``target_name``.

    Reference target pulls the resolved card URL from the
    ``echo_agent_card_url`` fixture (which transitively probes the
    agent's ``/health`` and skips the session if it's unreachable).

    T29 (Wave 7): gateway targets now resolve real fixtures —
    ``gateway_base_url`` + ``auth_token`` + ``registered_agent_id``
    (triggers gateway probe + agent registration), and additionally
    ``server_id`` for ``gateway_virtual``. Their ``_open_client``
    bodies actually connect via the SDK's ``ClientFactory`` so the
    matrix tests run end-to-end against the live native passthrough.
    """
    if target_name == "reference":
        base_url = request.getfixturevalue("echo_agent_base_url")
        return A2AReferenceTarget(base_url=base_url)
    if target_name == "gateway_proxy":
        gateway_base_url = request.getfixturevalue("gateway_base_url")
        auth_token = request.getfixturevalue("auth_token")
        agent_name = request.getfixturevalue("registered_agent_name")
        request.getfixturevalue("registered_agent_id")
        return A2AGatewayProxyTarget(
            base_url=gateway_base_url,
            auth_token=auth_token,
            agent_name=agent_name,
        )
    if target_name == "gateway_virtual":
        gateway_base_url = request.getfixturevalue("gateway_base_url")
        auth_token = request.getfixturevalue("auth_token")
        agent_name = request.getfixturevalue("registered_agent_name")
        server_id_value = request.getfixturevalue("server_id")
        return A2AGatewayVirtualServerTarget(
            base_url=gateway_base_url,
            auth_token=auth_token,
            server_id=server_id_value,
            agent_name=agent_name,
        )
    raise AssertionError(f"unknown target: {target_name!r}")


@pytest_asyncio.fixture(params=_CASES, ids=[f"{t}-{x}" for t, x in _CASES])
async def client(request: pytest.FixtureRequest) -> AsyncIterator[Client]:
    """Yield a connected ``a2a.client.Client`` for the parametrized cell.

    Reference target opens a fresh ``httpx.AsyncClient`` + ``ClientFactory``
    per invocation; the SDK auto-routes via JSON-RPC per the echo
    agent's advertised card interfaces.

    Gateway targets (``gateway_proxy``, ``gateway_virtual``) drive
    ContextForge's native A2A passthrough at ``/a2a/{name}`` and
    ``/servers/{id}/a2a/{name}`` respectively. Their ``_open_client``
    bodies mirror the reference target's shape exactly, with the URL
    pointed at the gateway's synthesized well-known card.
    """
    target_name, transport = request.param
    target = _build_target(target_name, request)
    async with target.client(transport) as connected:
        yield connected


# ───────────────────────────────────────────────────────────────────────
# T28 Part A fixtures (Wave 2 prerequisite — execute BEFORE T8/T9/T10).
# ───────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def gateway_base_url() -> str:
    """Read ``A2A_COMPLIANCE_GATEWAY_URL``, default ``http://localhost:8080``.

    Plan T28 Part A: target-aware URL building for Wave 2 gap-closure
    tests starts from this base. The default targets the nginx router
    on ``:8080`` that ``make compose-up`` brings up — the three gateway
    replicas only expose ``:4444`` inside the docker network, so
    external traffic must enter via nginx. Overridable via env so the
    harness can run against any running ContextForge gateway instance
    (Kubernetes port-forward, single-process ``make dev``, etc.).
    """
    # IPv4 explicit (127.0.0.1) per the same DNS-stub / IPv6-first issue
    # documented for ``echo_agent_base_url``: the nginx port-forward
    # ``0.0.0.0:8080->80/tcp`` binds IPv4 only, and httpx's getaddrinfo
    # may pick ``::1`` first when resolving ``localhost`` — that hangs
    # because nothing listens on IPv6.
    return os.getenv("A2A_COMPLIANCE_GATEWAY_URL", "http://127.0.0.1:8080")


@pytest.fixture(scope="session")
def auth_token() -> str:
    """Session-scoped admin JWT signed with ``JWT_SECRET_KEY`` from env.

    Plan T28 Part A: uses ``tests.helpers.auth.make_test_jwt`` per the
    canonical test-JWT helper per ``tests/AGENTS.md`` (NOT
    ``mcpgateway.utils.create_jwt_token.create_jwt_token`` which is the
    CLI-facing helper). The resulting token has ``is_admin=True`` so it
    can call admin endpoints like ``POST /a2a`` for agent registration.

    The empty-string ``secret`` argument lets ``make_test_jwt`` fall
    through to ``settings.JWT_SECRET_KEY`` from the environment, so a
    real gateway accepts it.

    ``teams=None`` makes the JWT serialize ``"teams": null`` (rather
    than omitting the key entirely), which is the only way to get
    Layer-1 ADMIN BYPASS per the ``normalize_token_teams()`` policy
    in ``AGENTS.md``: with the teams key MISSING, even an admin
    token is treated as PUBLIC-ONLY visibility and cannot create
    team-scoped or private resources. The compliance harness needs
    to create team-scoped agents (Amendment I.2 fixture), so the
    fixture's admin token must be true admin-bypass.
    """
    return make_test_jwt(email="admin@example.com", is_admin=True, teams=None)


@pytest.fixture(scope="session")
def registered_agent_name() -> str:
    """Canonical name of the live echo agent the harness drives.

    Defaults to ``a2a-echo-agent`` (matching the docker-compose
    ``testing`` profile + ``_build_target`` defaults above). Override
    via ``A2A_COMPLIANCE_AGENT_NAME`` env when the gateway has the echo
    agent registered under a different name.
    """
    return os.getenv("A2A_COMPLIANCE_AGENT_NAME", "a2a-echo-agent")


@pytest.fixture(scope="module")
def registered_agent_id(
    gateway_base_url: str,
    auth_token: str,
    registered_agent_name: str,
    echo_agent_base_url: str,
) -> str:
    """Module-scoped: ensure echo agent is registered, return its UUID.

    Module scope (not session) so the dependency on the module-scoped
    ``echo_agent_base_url`` resolves cleanly. Registration is
    idempotent — modules within the same session reuse the existing
    agent row via the lookup-before-create pattern below.

    Plan T28 Part A: POST /a2a admin API to register the echo agent if
    it is not already known to the gateway; on success or "already
    exists" responses, look up the agent by name to capture its UUID
    ``id``. The captured ID is what server-association tests (T20/T22)
    will pass into ``associated_a2a_agents=[...]`` per Momus v3 #3 —
    the service layer queries ``at.model.id.in_(ids)`` at
    ``server_service.py:226``, so passing the agent NAME would fail.

    Skips the session gracefully when the gateway is unreachable so a
    developer running the harness without a live gateway just sees a
    clean skip rather than a cascade of connection errors. The agent's
    own ``echo_agent_base_url`` fixture transitively skips when the
    underlying echo agent process isn't up.
    """
    # Confirm the gateway is reachable before issuing the registration.
    try:
        probe = httpx.get(f"{gateway_base_url}/health", timeout=httpx.Timeout(5.0))
    except httpx.HTTPError as exc:
        pytest.skip(f"Gateway unreachable at {gateway_base_url}: {exc}")
    if probe.status_code >= 500:
        pytest.skip(f"Gateway at {gateway_base_url} returned {probe.status_code}")

    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}

    # Try to look up the agent first by listing — handles the case where
    # the agent is already registered by docker-compose or a previous run.
    list_resp = httpx.get(f"{gateway_base_url}/a2a", headers=headers, timeout=httpx.Timeout(10.0))
    if list_resp.status_code == 200:
        body = list_resp.json()
        # Some endpoints return a list, others return a pagination dict —
        # accept both shapes.
        agents = body.get("items", body) if isinstance(body, dict) else body
        if isinstance(agents, list):
            for agent in agents:
                if isinstance(agent, dict) and agent.get("name") == registered_agent_name:
                    return str(agent["id"])

    # Not found — register now. The POST /a2a route at main.py:4825 uses
    # FastAPI's multi-body pattern: ``agent: A2AAgentCreate`` Pydantic body
    # plus top-level ``team_id`` and ``visibility`` Body fields. Wire shape
    # therefore needs ``{"agent": {...}, "visibility": "..."}`` with the
    # visibility field hoisted OUT of the agent object.
    payload = {
        "agent": {
            "name": registered_agent_name,
            "description": "A2A 1.0.0 compliance-harness echo agent (T28 Part A registration)",
            "endpoint_url": echo_agent_base_url,
            "agent_type": "jsonrpc",
            "protocol_version": "1.0.0",
            "capabilities": {"streaming": True},
        },
        "visibility": "public",
    }
    create_resp = httpx.post(f"{gateway_base_url}/a2a/", headers=headers, json=payload, timeout=httpx.Timeout(15.0))
    if create_resp.status_code in (200, 201):
        return str(create_resp.json()["id"])

    # 409 conflict (already exists by another path) — re-list and find it.
    if create_resp.status_code == 409:
        list_resp2 = httpx.get(f"{gateway_base_url}/a2a", headers=headers, timeout=httpx.Timeout(10.0))
        if list_resp2.status_code == 200:
            body = list_resp2.json()
            agents = body.get("items", body) if isinstance(body, dict) else body
            if isinstance(agents, list):
                for agent in agents:
                    if isinstance(agent, dict) and agent.get("name") == registered_agent_name:
                        return str(agent["id"])

    pytest.skip(f"Could not register or find agent {registered_agent_name!r} on gateway " f"{gateway_base_url} (POST /a2a status {create_resp.status_code}): {create_resp.text[:200]}")


@pytest.fixture(params=_PART_A_GAP_CLOSURE_TARGETS)
def gap_closure_target(request: pytest.FixtureRequest) -> str:
    """Parametrize gap-closure tests over the three live targets.

    Returns the current target name (``"reference"``, ``"gateway_proxy"``,
    or ``"gateway_virtual"``). All three are live since T29 (gateway
    targets gained real ``_open_client`` bodies) and T30 (A2A-GAP-001
    closed). Per-test ``xfail_on`` from ``helpers/compliance.py``
    remains the right tool for narrower gaps that don't span a whole
    column.
    """
    return request.param


@pytest.fixture(scope="module")
def server_id(
    gateway_base_url: str,
    auth_token: str,
    registered_agent_id: str,
) -> str:
    """Module-scoped: ensure an A2A bundling server exists, return its UUID.

    Module scope (not session) so the dependency on the module-scoped
    ``registered_agent_id`` resolves cleanly. Server creation is
    idempotent — modules within the same session reuse the existing
    bundling server via the lookup-before-create pattern below.

    Plan T28 Part B (Wave 7): create a virtual server via
    ``POST /servers`` with ``associated_a2a_agents=[registered_agent_id]``
    so the v-server-scoped card and dispatch URLs
    (``/servers/{server_id}/a2a/{name}``) resolve to the registered
    echo agent. Returns the server's UUID for use by the
    ``gateway_virtual`` URL builders below.

    Passes the agent ID (UUID), NOT the name, per Momus v3 #3: the
    service layer queries ``at.model.id.in_(ids)`` at
    ``server_service.py:226``, so passing the agent NAME would yield
    a server with no bound agents.

    Re-list before creating: if a previous run already created the
    bundling server, reuse its UUID rather than failing on a unique
    constraint or creating a parallel server.

    Skips the session gracefully when the gateway is unreachable so
    a developer running the harness without a live gateway sees a
    clean skip rather than a cascade of connection errors.
    """
    server_name = os.getenv("A2A_COMPLIANCE_SERVER_NAME", "a2a-compliance-bundle")

    try:
        probe = httpx.get(f"{gateway_base_url}/health", timeout=httpx.Timeout(5.0))
    except httpx.HTTPError as exc:
        pytest.skip(f"Gateway unreachable at {gateway_base_url}: {exc}")
    if probe.status_code >= 500:
        pytest.skip(f"Gateway at {gateway_base_url} returned {probe.status_code}")

    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}

    list_resp = httpx.get(f"{gateway_base_url}/servers", headers=headers, timeout=httpx.Timeout(10.0))
    if list_resp.status_code == 200:
        body = list_resp.json()
        servers = body.get("items", body) if isinstance(body, dict) else body
        if isinstance(servers, list):
            for srv in servers:
                if isinstance(srv, dict) and srv.get("name") == server_name:
                    return str(srv["id"])

    # POST /servers at main.py:4100 uses FastAPI's multi-body pattern:
    # ``server: ServerCreate`` Pydantic body plus top-level ``team_id``
    # and ``visibility`` Body fields. Wire shape needs
    # ``{"server": {...}, "visibility": "..."}`` with visibility hoisted
    # OUT of the server object.
    payload = {
        "server": {
            "name": server_name,
            "description": "A2A 1.0.0 compliance-harness bundling server (T28 Part B)",
            "associated_a2a_agents": [registered_agent_id],
        },
        "visibility": "public",
    }
    create_resp = httpx.post(f"{gateway_base_url}/servers/", headers=headers, json=payload, timeout=httpx.Timeout(15.0))
    if create_resp.status_code in (200, 201):
        return str(create_resp.json()["id"])

    if create_resp.status_code == 409:
        list_resp2 = httpx.get(f"{gateway_base_url}/servers", headers=headers, timeout=httpx.Timeout(10.0))
        if list_resp2.status_code == 200:
            body = list_resp2.json()
            servers = body.get("items", body) if isinstance(body, dict) else body
            if isinstance(servers, list):
                for srv in servers:
                    if isinstance(srv, dict) and srv.get("name") == server_name:
                        return str(srv["id"])

    pytest.skip(f"Could not register or find server {server_name!r} on gateway " f"{gateway_base_url} (POST /servers status {create_resp.status_code}): {create_resp.text[:200]}")


@pytest.fixture
def raw_card_url(
    gap_closure_target: str,
    gateway_base_url: str,
    registered_agent_name: str,
    echo_agent_base_url: str,
    request: pytest.FixtureRequest,
) -> str:
    """Target-aware well-known card URL for raw-HTTP gap-closure tests.

    Plan T28 Part A + Part B: lets T9 card-discovery tests parametrize
    over ``{reference, gateway_proxy, gateway_virtual}`` and exercise
    the same raw HTTP path that ``ClientFactory.create_from_url``
    would. Per-agent gateway URL follows the F8 + T11 convention
    ``/a2a/{name}/.well-known/agent-card.json``; v-server-scoped
    gateway URL follows the F8 + T16 convention
    ``/servers/{server_id}/a2a/{name}/.well-known/agent-card.json``.

    Args:
        gap_closure_target: Current parametrize cell.
        gateway_base_url: Gateway base for gateway-target URLs.
        registered_agent_name: Agent name used in the URL path.
        echo_agent_base_url: Reference target's base URL (echo agent).
        request: pytest fixture request used to lazily resolve
            ``server_id`` only when the parametrize cell needs it
            (avoids a session-level server creation when no
            gateway_virtual test runs).

    Returns:
        The well-known card URL for the parametrized target.
    """
    if gap_closure_target == "reference":
        return f"{echo_agent_base_url}/.well-known/agent-card.json"
    if gap_closure_target == "gateway_proxy":
        return f"{gateway_base_url}/a2a/{registered_agent_name}/.well-known/agent-card.json"
    if gap_closure_target == "gateway_virtual":
        sid = request.getfixturevalue("server_id")
        return f"{gateway_base_url}/servers/{sid}/a2a/{registered_agent_name}/.well-known/agent-card.json"
    raise AssertionError(f"unsupported gap-closure target {gap_closure_target!r}")


@pytest.fixture
def raw_dispatch_url(
    gap_closure_target: str,
    gateway_base_url: str,
    registered_agent_name: str,
    echo_agent_base_url: str,
    request: pytest.FixtureRequest,
) -> str:
    """Target-aware dispatch URL for raw-HTTP gap-closure tests.

    Plan T28 Part A + Part B: lets T10 dispatch-tests parametrize over
    ``{reference, gateway_proxy, gateway_virtual}``. Per-agent gateway
    URL follows the F8 + T12 convention ``/a2a/{name}``; v-server-scoped
    gateway URL follows the F8 + T16 convention
    ``/servers/{server_id}/a2a/{name}``. Reference target uses the
    echo agent's bare base URL.
    """
    if gap_closure_target == "reference":
        return echo_agent_base_url
    if gap_closure_target == "gateway_proxy":
        return f"{gateway_base_url}/a2a/{registered_agent_name}"
    if gap_closure_target == "gateway_virtual":
        sid = request.getfixturevalue("server_id")
        return f"{gateway_base_url}/servers/{sid}/a2a/{registered_agent_name}"
    raise AssertionError(f"unsupported gap-closure target {gap_closure_target!r}")


# ───────────────────────────────────────────────────────────────────────
# Plan Amendment I.2 — RBAC + team-scoped visibility fixtures (closes
# the F1 deferred-fixture-work addendum). These power the two previously
# skipped tests in v1_0_0/test_rbac_extra.py: wrong-team Layer-1
# visibility hide (HTTP 404) and per-permission RBAC via a non-admin
# user with only ``a2a.read`` granted (HTTP 200 on
# ``GetExtendedAgentCard``, proves the route did NOT use a route-level
# ``@require_permission("a2a.invoke")``).
#
# Both fixtures self-skip on gateway-unreachable / API-failure so a
# developer running the harness without a live gateway sees a clean
# skip rather than a cascade of errors.
# ───────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def team_scoped_agent_name() -> str:
    """Canonical name of the team-scoped echo agent for the I.2 fixtures.

    Distinct from ``registered_agent_name`` so the public agent and the
    team-scoped agent can coexist on the gateway without name collisions.
    Overridable via ``A2A_COMPLIANCE_TEAM_AGENT_NAME``.
    """
    return os.getenv("A2A_COMPLIANCE_TEAM_AGENT_NAME", "a2a-echo-agent-team-a")


@pytest.fixture(scope="module")
def team_scoped_agent_id(
    gateway_base_url: str,
    auth_token: str,
    team_scoped_agent_name: str,
    echo_agent_base_url: str,
) -> str:
    """Module-scoped: ensure a team-scoped echo agent exists, return its UUID.

    Module scope (not session) so the dependency on the module-scoped
    ``echo_agent_base_url`` resolves cleanly. The gateway and team
    creation work is still idempotent — subsequent modules within the
    same session reuse the existing team/agent rows.

    Plan Amendment I.2: drives the Layer-1 visibility-hide test. Creates
    (or reuses) a real team named ``a2a-compliance-team-a`` and registers
    a team-scoped echo agent under it with ``visibility="team"``. The
    agent is functionally identical to the public ``registered_agent_id``
    fixture's agent — it differs only in visibility scope so the
    wrong-team-token test can assert HTTP 404 collapse per D14.

    Idempotent: re-lists agents + teams before creating, so a previous
    run's leftovers are reused rather than colliding on the unique
    name constraint.

    Skips the session gracefully when the gateway is unreachable so
    developers running the harness without a live gateway see a clean
    skip rather than a cascade of connection errors.

    Args:
        gateway_base_url: Gateway base URL.
        auth_token: Admin JWT (admin bypass needed to set ``team_id``).
        team_scoped_agent_name: Agent name from
            :func:`team_scoped_agent_name`.
        echo_agent_base_url: Reference echo agent's base URL — used as
            the team-scoped agent's ``endpoint_url`` so it actually
            responds to dispatch.

    Returns:
        UUID of the team-scoped agent.
    """
    team_name = os.getenv("A2A_COMPLIANCE_TEAM_NAME", "a2a-compliance-team-a")

    try:
        probe = httpx.get(f"{gateway_base_url}/health", timeout=httpx.Timeout(5.0))
    except httpx.HTTPError as exc:
        pytest.skip(f"Gateway unreachable at {gateway_base_url}: {exc}")
    if probe.status_code >= 500:
        pytest.skip(f"Gateway at {gateway_base_url} returned {probe.status_code}")

    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}

    # Step 1: ensure the team exists. The /teams listing requires the
    # trailing slash (``GET /teams`` returns a 307 redirect that httpx
    # follows but loses the path), and the response shape is
    # ``{"teams": [...], "total": N}`` rather than the ``{"items": [...]}``
    # convention other endpoints use.
    list_teams = httpx.get(f"{gateway_base_url}/teams/", headers=headers, timeout=httpx.Timeout(10.0))
    team_id = None
    if list_teams.status_code == 200:
        body = list_teams.json()
        if isinstance(body, dict):
            teams = body.get("teams") or body.get("items") or []
        elif isinstance(body, list):
            teams = body
        else:
            teams = []
        if isinstance(teams, list):
            for t in teams:
                if isinstance(t, dict) and t.get("name") == team_name:
                    team_id = str(t["id"])
                    break

    if team_id is None:
        create_team_resp = httpx.post(
            f"{gateway_base_url}/teams/",
            headers=headers,
            json={"name": team_name, "description": "A2A I.2 visibility-hide fixture team"},
            timeout=httpx.Timeout(15.0),
        )
        if create_team_resp.status_code in (200, 201):
            team_id = str(create_team_resp.json()["id"])
        else:
            pytest.skip(f"Could not create team {team_name!r} on gateway {gateway_base_url} " f"(POST /teams/ status {create_team_resp.status_code}): {create_team_resp.text[:200]}")

    # Step 2: ensure the team-scoped agent exists under that team.
    list_agents = httpx.get(f"{gateway_base_url}/a2a", headers=headers, timeout=httpx.Timeout(10.0))
    if list_agents.status_code == 200:
        body = list_agents.json()
        agents = body.get("items", body) if isinstance(body, dict) else body
        if isinstance(agents, list):
            for a in agents:
                if isinstance(a, dict) and a.get("name") == team_scoped_agent_name:
                    return str(a["id"])

    # POST /a2a uses FastAPI multi-body: agent Pydantic body + top-level
    # team_id + visibility. Hoist team_id and visibility out of the
    # agent object so the route's Body(...) extractors see them.
    payload = {
        "agent": {
            "name": team_scoped_agent_name,
            "description": "A2A I.2 team-scoped echo agent (visibility-hide test fixture)",
            "endpoint_url": echo_agent_base_url,
            "agent_type": "jsonrpc",
            "protocol_version": "1.0.0",
            "capabilities": {"streaming": True, "extendedAgentCard": True},
        },
        "team_id": team_id,
        "visibility": "team",
    }
    create_resp = httpx.post(f"{gateway_base_url}/a2a/", headers=headers, json=payload, timeout=httpx.Timeout(15.0))
    if create_resp.status_code in (200, 201):
        return str(create_resp.json()["id"])

    if create_resp.status_code == 409:
        list_resp2 = httpx.get(f"{gateway_base_url}/a2a", headers=headers, timeout=httpx.Timeout(10.0))
        if list_resp2.status_code == 200:
            body = list_resp2.json()
            agents = body.get("items", body) if isinstance(body, dict) else body
            if isinstance(agents, list):
                for a in agents:
                    if isinstance(a, dict) and a.get("name") == team_scoped_agent_name:
                        return str(a["id"])

    pytest.skip(f"Could not register team-scoped agent {team_scoped_agent_name!r} on gateway " f"{gateway_base_url} (POST /a2a status {create_resp.status_code}): {create_resp.text[:200]}")


@pytest.fixture(scope="session")
def wrong_team_auth_token(gateway_base_url: str, auth_token: str) -> str:
    """Session-scoped: non-admin JWT carrying a fake team UUID, for a
    user that actually exists in the gateway DB.

    Plan Amendment I.2: drives the Layer-1 visibility-hide test
    (F3 scenario (j.3) +
    :func:`tests.live_gateway.a2a_compliance.v1_0_0.test_rbac_extra.test_team_scoped_agent_wrong_team_returns_404`).
    The token carries ``teams=["<fake-team-uuid>"]`` which deliberately
    won't match the real team-a UUID. With the user provisioned in the
    DB, auth passes, then Layer-1 visibility evaluates the team-scoped
    agent against the empty intersection and returns HTTP 404 per D11
    (visibility hides, never 403s).

    Provisioning the user is required because the token-scoping
    middleware was previously masking this scenario with a 403 from
    the team-membership check; now that the native A2A routes opt out
    of that check (see ``token_scoping.py`` team_check_exempt), the
    request reaches the route's ``Depends(get_current_user_with_permissions)``,
    which 401s if the JWT subject is unknown.

    Uses a structurally valid UUID for the team value so any downstream
    validation that expects UUID shape doesn't reject the token before
    it reaches the visibility check.
    """
    user_email = os.getenv("A2A_COMPLIANCE_WRONG_TEAM_EMAIL", "a2a-wrong-team@example.com")
    # Random-style password to satisfy the gateway's password-policy
    # ``_has_sequential_chars`` check (rejects passwords like
    # "DummyWrongTeamP@ss" with too many consecutive sequential
    # characters).
    user_password = "Mb5#nP@4Vy8jXc2LqRtZ"  # pragma: allowlist secret
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    # Idempotent provisioning: 200/201 = created, 409 = already exists;
    # any other status is a real problem (e.g., password policy 400) we
    # need to surface rather than silently let auth fail downstream.
    try:
        create_resp = httpx.post(
            f"{gateway_base_url}/auth/email/admin/users",
            headers=headers,
            json={"email": user_email, "password": user_password, "full_name": "A2A Wrong-Team Test User", "is_admin": False, "is_active": True},
            timeout=httpx.Timeout(15.0),
        )
    except httpx.HTTPError:
        # Gateway unreachable — surrounding test fixtures will skip first.
        create_resp = None
    if create_resp is not None and create_resp.status_code not in (200, 201, 409):
        pytest.skip(f"Could not provision wrong-team user {user_email!r} on gateway {gateway_base_url} (POST /auth/email/admin/users status {create_resp.status_code}): {create_resp.text[:200]}")
    return make_test_jwt(email=user_email, is_admin=False, teams=["00000000-0000-0000-0000-000000000fff"])


@pytest.fixture(scope="session")
def no_perm_user_token(gateway_base_url: str, auth_token: str) -> str:
    """Session-scoped: JWT for a non-admin user that EXISTS in the DB
    but has NO role assignments.

    Drives F3 scenarios that need to distinguish "user lacks permission"
    (HTTP 403) from "user does not exist" (HTTP 401). Without this
    fixture, tests using ``make_test_jwt(email="some-fake-user@...")``
    get rejected by the auth middleware with 401, never reaching the
    per-method RBAC check that should return 403.

    Used by:

    * F3 scenario (i.2) — ``GetExtendedAgentCard`` without ``a2a.read``
      permission → 403.
    * Equivalent v1_0_0 ``test_rbac_extra`` scenarios.

    The user is created idempotently; the role-assignment step is
    intentionally skipped so the user has zero RBAC permissions.
    """
    user_email = os.getenv("A2A_COMPLIANCE_NO_PERM_EMAIL", "a2a-no-perm@example.com")
    # Random-style password to satisfy the gateway's password-policy
    # ``_has_sequential_chars`` check (rejects passwords containing
    # patterns like "Perm" with sequential lowercase characters).
    user_password = "Zx9$mQ!7Lq3wHv8KrTpY"  # pragma: allowlist secret
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    try:
        create_resp = httpx.post(
            f"{gateway_base_url}/auth/email/admin/users",
            headers=headers,
            json={"email": user_email, "password": user_password, "full_name": "A2A No-Permission Test User", "is_admin": False, "is_active": True},
            timeout=httpx.Timeout(15.0),
        )
    except httpx.HTTPError:
        create_resp = None
    if create_resp is not None and create_resp.status_code not in (200, 201, 409):
        pytest.skip(f"Could not provision no-perm user {user_email!r} on gateway {gateway_base_url} (POST /auth/email/admin/users status {create_resp.status_code}): {create_resp.text[:200]}")

    # The gateway's bootstrap auto-assigns ``platform_viewer`` (global)
    # and a team-scoped role to every newly-created user. Both grant
    # ``a2a.read``, which defeats this fixture's purpose ("user with
    # NO a2a permissions"). Revoke ALL active role assignments here
    # so the user genuinely fails every per-method RBAC check.
    #
    # The DELETE endpoint at ``/rbac/users/{email}/roles/{role_id}``
    # requires ``scope`` (and ``scope_id`` for team-scoped grants) as
    # query params to disambiguate the assignment row — without them
    # the service-layer lookup returns 404 "Role assignment not found".
    list_resp = httpx.get(f"{gateway_base_url}/rbac/users/{user_email}/roles", headers=headers, timeout=httpx.Timeout(10.0))
    if list_resp.status_code == 200:
        roles_body = list_resp.json()
        roles = roles_body if isinstance(roles_body, list) else (roles_body.get("roles") or roles_body.get("items") or [])
        for ur in roles:
            if not isinstance(ur, dict) or not ur.get("is_active") or not ur.get("role_id"):
                continue
            params = {"scope": ur.get("scope")} if ur.get("scope") else {}
            if ur.get("scope_id"):
                params["scope_id"] = ur["scope_id"]
            httpx.delete(
                f"{gateway_base_url}/rbac/users/{user_email}/roles/{ur['role_id']}",
                headers=headers,
                params=params,
                timeout=httpx.Timeout(10.0),
            )

    return make_test_jwt(email=user_email, is_admin=False)


@pytest.fixture(scope="session")
def a2a_read_only_token(gateway_base_url: str, auth_token: str) -> str:
    """Session-scoped: JWT for a non-admin user with only ``a2a.read`` granted.

    Plan Amendment I.2: drives the per-permission test
    (:func:`tests.live_gateway.a2a_compliance.v1_0_0.test_rbac_extra.test_extended_card_with_read_permission_returns_200`).
    Proves the dispatch route did NOT use a route-level
    ``@require_permission("a2a.invoke")`` decorator that would 403
    every ``GetExtendedAgentCard`` call (Oracle v3 #1).

    Fixture flow:

    1. Create the non-admin user via ``POST /auth/email/admin/users``
       (reuses on 409 conflict).
    2. Look up the ``platform_viewer`` system role via
       ``GET /rbac/roles?scope=global``. ``platform_viewer`` carries
       ``a2a.read`` but NOT ``a2a.invoke`` (see
       :mod:`mcpgateway.bootstrap_db` default-role table).
    3. Assign that role globally to the user via
       ``POST /rbac/users/{email}/roles``.
    4. Return a JWT bound to the user.

    Skips cleanly on any API failure — the surrounding tests then
    skip too, mirroring the existing fixture pattern.

    Args:
        gateway_base_url: Gateway base URL.
        auth_token: Admin JWT — only an admin can call
            ``admin.user_management``-gated endpoints.

    Returns:
        JWT string for the non-admin read-only user.
    """
    user_email = os.getenv("A2A_COMPLIANCE_READ_ONLY_EMAIL", "a2a-read-only@example.com")
    user_password = "DummyReadOnlyP@ss"  # pragma: allowlist secret

    try:
        probe = httpx.get(f"{gateway_base_url}/health", timeout=httpx.Timeout(5.0))
    except httpx.HTTPError as exc:
        pytest.skip(f"Gateway unreachable at {gateway_base_url}: {exc}")
    if probe.status_code >= 500:
        pytest.skip(f"Gateway at {gateway_base_url} returned {probe.status_code}")

    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}

    # Step 1: create the non-admin user (idempotent on 409).
    create_user_resp = httpx.post(
        f"{gateway_base_url}/auth/email/admin/users",
        headers=headers,
        json={"email": user_email, "password": user_password, "full_name": "A2A Read-Only Test User", "is_admin": False, "is_active": True},
        timeout=httpx.Timeout(15.0),
    )
    if create_user_resp.status_code not in (200, 201, 409):
        pytest.skip(f"Could not create user {user_email!r} on gateway {gateway_base_url} " f"(POST /auth/email/admin/users status {create_user_resp.status_code}): {create_user_resp.text[:200]}")

    # Step 2: look up the platform_viewer system role (scope=global).
    list_roles_resp = httpx.get(f"{gateway_base_url}/rbac/roles", headers=headers, params={"scope": "global"}, timeout=httpx.Timeout(10.0))
    if list_roles_resp.status_code != 200:
        pytest.skip(f"Could not list global roles on gateway {gateway_base_url} " f"(GET /rbac/roles?scope=global status {list_roles_resp.status_code}): {list_roles_resp.text[:200]}")

    body = list_roles_resp.json()
    roles_payload = body.get("items", body) if isinstance(body, dict) else body
    platform_viewer_id = None
    if isinstance(roles_payload, list):
        for r in roles_payload:
            if isinstance(r, dict) and r.get("name") == "platform_viewer":
                platform_viewer_id = str(r["id"])
                break

    if platform_viewer_id is None:
        pytest.skip(f"platform_viewer system role not found on gateway {gateway_base_url} — has bootstrap_db run?")

    # Step 3: assign the role to the user. The role service rejects
    # duplicate assignments with HTTP 400 ("User already has this role
    # assignment"), so check existing assignments first and skip the
    # POST when the user-role mapping is already present.
    list_user_roles = httpx.get(
        f"{gateway_base_url}/rbac/users/{user_email}/roles",
        headers=headers,
        timeout=httpx.Timeout(10.0),
    )
    already_assigned = False
    if list_user_roles.status_code == 200:
        body = list_user_roles.json()
        roles = body if isinstance(body, list) else (body.get("roles") or body.get("items") or [])
        if isinstance(roles, list):
            for ur in roles:
                if isinstance(ur, dict) and ur.get("role_id") == platform_viewer_id and ur.get("scope") == "global" and ur.get("is_active"):
                    already_assigned = True
                    break

    if not already_assigned:
        assign_resp = httpx.post(
            f"{gateway_base_url}/rbac/users/{user_email}/roles",
            headers=headers,
            json={"role_id": platform_viewer_id, "scope": "global"},
            timeout=httpx.Timeout(15.0),
        )
        if assign_resp.status_code not in (200, 201, 409):
            pytest.skip(
                f"Could not assign platform_viewer role to {user_email!r} on gateway " f"{gateway_base_url} (POST /rbac/users/.../roles status {assign_resp.status_code}): {assign_resp.text[:200]}"
            )

    # Step 4: JWT bound to the user. Non-admin, empty teams (public-only
    # Layer 1) — platform_viewer is a global-scope role so the RBAC
    # check resolves through the global role assignment, not via team.
    return make_test_jwt(email=user_email, is_admin=False)


@pytest.fixture
def team_scoped_raw_dispatch_url(
    gap_closure_target: str,
    gateway_base_url: str,
    team_scoped_agent_name: str,
    team_scoped_agent_id: str,  # noqa: ARG001 — triggers team-scoped agent registration
) -> str:
    """Target-aware dispatch URL for the team-scoped agent.

    Plan Amendment I.2: parallel to :func:`raw_dispatch_url` but
    pointed at the team-scoped agent rather than the public one. Only
    the gateway-proxy form is exercised — the team-scoped agent is
    not bound to the v-server bundle from :func:`server_id`, so the
    v-server URL would 404 for all callers regardless of team. The
    wire-level visibility-hide contract is the same on either URL
    family per D14, so testing it on gateway_proxy is sufficient.

    Reference and gateway_virtual targets skip — see the per-test
    body for the explicit skip reason.

    Args:
        gap_closure_target: Current parametrize cell.
        gateway_base_url: Gateway base URL.
        team_scoped_agent_name: Team-scoped agent name.
        team_scoped_agent_id: Unused directly, but referencing it
            triggers the team-scoped agent registration before URL
            construction so the test's request actually has a target.

    Returns:
        Dispatch URL for the team-scoped agent on the gateway-proxy
        form, or an empty string when the test will skip anyway.
    """
    if gap_closure_target == "gateway_proxy":
        return f"{gateway_base_url}/a2a/{team_scoped_agent_name}"
    return ""
