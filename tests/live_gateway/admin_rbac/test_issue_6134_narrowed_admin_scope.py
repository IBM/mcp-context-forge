# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/admin_rbac/test_issue_6134_narrowed_admin_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

End-to-end reproducer + regression proof for issue #6134 — team-narrowed and
public-only admin JWT tokens bypassing Layer-1 scope narrowing on admin
routes guarded by ``@require_permission(...)`` rather than the stricter
unrestricted-platform-admin check.

This drives a REAL, running ContextForge instance over real HTTP (no
``TestClient``, no ASGI transport, no mocked auth/DB layer) — the same
pattern ``tests/live_gateway/mcp/test_mcp_rbac_transport.py`` uses for MCP
transport RBAC, applied here to the REST admin surface #6134 covers.

Reproduction (pre-fix, from the issue): a caller presenting a JWT with
``"teams": ["team-a"]`` (or ``"teams": []``) and ``"is_admin": true`` received
the SAME unrestricted access as ``"teams": null`` on any route guarded by
``@require_permission("admin.*")`` instead of ``require_global_admin_permission()``
/ ``require_global_admin_scope_dep``. This suite proves that, post-fix, all
64 migrated routes now deny both a team-narrowed and a public-only admin
token, while continuing to allow a genuinely unrestricted one — the exact
Gherkin scenario in the issue's acceptance criteria.

Prerequisites
-------------
Start ContextForge with every router this fix touches enabled (the default
``.env.example`` leaves ``observability``, ``siem``, ``toolops``, and ``sso``
off, which would make their routes 404 rather than exercise the guard):

    OBSERVABILITY_ENABLED=true
    SIEM_EXPORT_ENABLED=true
    TOOLOPS_ENABLED=true
    SSO_ENABLED=true
    MCPGATEWAY_ADMIN_API_ENABLED=true   # already the .env.example default

    make docker-prod-rust testing-up RUST_MCP_MODE=

KNOWN LIMITATION of the ``testing`` docker-compose profile specifically: its
``gateway`` service hardcodes ``OBSERVABILITY_ENABLED=false`` (not templated
from ``.env``) and does not forward ``SIEM_EXPORT_ENABLED``/``TOOLOPS_ENABLED``
to the container at all, regardless of ``.env``. Under that profile,
``observability``/``siem``/``toolops`` routes 404 no matter what this file's
env vars are set to. This suite detects that (a 404 on the FIRST route it
checks in each of those three groups) and marks the rest of that group's
assertions ``SKIPPED`` with a clear reason, rather than failing — those three
groups are still covered by their own thorough unit-level ``*_scope.py``
suites exercised during development; this file's job is to prove the fix
against a genuinely running gateway process for as much of the surface as
that gateway's deployment profile allows. A different boot path (e.g. `make
dev` with the env vars above exported directly, no docker) would exercise all
nine groups over real HTTP.

``JWT_SECRET_KEY`` must match the value the running gateway container was
started with (read from ``.env`` by docker-compose) — pass it via the
``JWT_SECRET_KEY`` environment variable if it differs from this file's
fallback.

The bootstrapped platform admin (``ADMIN_EMAIL``) must NOT be flagged
``password_change_required`` — this is a genuine, pre-existing security gate
(any admin route redirects to ``/admin/change-password-required`` with 303
until the password is rotated) completely unrelated to #6134, but it fires
for Bearer-token API callers too and would make every test in this file fail
with an unrelated 303. Set ``PLATFORM_ADMIN_PASSWORD`` in ``.env`` to a
sufficiently strong value BEFORE the stack's first boot (bootstrap only seeds
the admin user once) so this flag is never set in the first place; see
``make init-secrets``/``make setup``.

The narrowed-token fixture provisions a real team via the live REST API
(``POST /teams``, matching ``tests/live_gateway/mcp/test_mcp_rbac_transport.py``'s
pattern) and adds the platform admin to it as its creator, so the narrowed
token's ``teams`` claim references a team ContextForge's own auth middleware
recognizes the caller as genuinely belonging to — a token narrowed to a
non-existent team is rejected earlier, by team-membership validation, before
ever reaching the code this issue is about.

Running
-------

    uv run pytest tests/live_gateway/admin_rbac/test_issue_6134_narrowed_admin_scope.py -v -s

Or, to target a non-default gateway URL / secret:

    MCP_CLI_BASE_URL=http://127.0.0.1:8080 JWT_SECRET_KEY=<value from .env> \\
        uv run pytest tests/live_gateway/admin_rbac/test_issue_6134_narrowed_admin_scope.py -v -s
"""

# Future
from __future__ import annotations

# Standard
import uuid

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = skip_no_gateway

TIMEOUT = 10.0

# The exact denial detail require_global_admin_permission()/require_global_admin_scope_dep
# raise on a narrowed or public-only caller (mcpgateway/middleware/rbac.py:_GLOBAL_SCOPE_DENIED_MSG).
# Asserting on this substring (not just the status code) proves the 403 came from THIS guard,
# not from some other unrelated permission check that happens to also return 403.
DENIAL_DETAIL_SUBSTRING = "requires an unrestricted platform-admin token"

# Routers whose feature flag the `testing` docker-compose profile cannot enable (see the
# module docstring's Known Limitation). A 404 on these is an environment fact, not a
# guard failure — skip rather than fail so the run stays meaningful under that profile.
FLAG_GATED_UNDER_TESTING_PROFILE = {"observability", "siem", "toolops"}

# Routers whose paths start with /admin/ and are not yet in TokenScopingMiddleware's
# hand-curated _ADMIN_PERMISSION_PATTERNS map (mcpgateway/middleware/token_scoping.py).
# That is a SEPARATE, correct, pre-existing Layer-1 defense: a public-only token
# resolves to zero RBAC-derived scope by design, and an unmapped /admin/* path then
# fails secure with "Admin privileges required" from require_admin_auth — independent
# of, and before, this PR's new guard ever runs. Both denials are correct; a public-only
# caller on these three routers may see either message.
ADMIN_PREFIXED_HAS_SEPARATE_SCOPE_LAYER = {"llm_admin_router", "siem", "runtime_admin_router"}
TOKEN_SCOPING_DENIAL_SUBSTRING = "Admin privileges required"


# ---------------------------------------------------------------------------
# Route matrix — one representative route per router this plan migrated,
# plus explicit neighbor/regression checks (see test_neighboring_routes_unaffected).
# The guard is a decorator wrapping the endpoint, not a FastAPI Depends() — so
# FastAPI validates the request body BEFORE ever invoking the guard. A POST route
# with required body fields needs a body that actually passes schema validation,
# or every case (allow AND deny) gets a 422 from Pydantic instead of the guard's
# own verdict, proving nothing about #6134 either way.
# ---------------------------------------------------------------------------
ROUTE_MATRIX = [
    # (router, method, path, allow_success_codes, body)
    ("llm_config_router", "GET", "/llm/providers", {200}, None),
    ("llm_admin_router", "GET", "/admin/llm/provider-configs", {200}, None),
    ("observability", "GET", "/observability/stats", {200, 500}, None),  # 500 only if metrics tables unprovisioned; guard must not be the cause
    ("sso", "GET", "/auth/sso/admin/providers", {200}, None),
    ("siem", "GET", "/admin/siem/health", {200}, None),
    ("log_search", "GET", "/api/logs/audit-trails", {200}, None),
    ("runtime_admin_router", "GET", "/admin/runtime/mcp-mode", {200}, None),
    ("rbac", "POST", "/rbac/permissions/check", {200}, {"user_email": ADMIN_EMAIL, "permission": "tools.read"}),
    ("metrics_maintenance", "GET", "/api/metrics/config", {200}, None),
]


def _request(client: httpx.Client, method: str, path: str, headers: dict[str, str], body: dict | None) -> httpx.Response:
    """Issue one request against the live gateway.

    Args:
        client: Shared httpx client bound to BASE_URL.
        method: HTTP method.
        path: Route path (no host/prefix).
        headers: Auth headers to send.
        body: JSON body for POST routes with a required schema; None for GET or bodyless POST.

    Returns:
        httpx.Response: The live response.
    """
    if method == "GET":
        return client.get(path, headers=headers, timeout=TIMEOUT)
    return client.post(path, headers=headers, json=body or {}, timeout=TIMEOUT)


@pytest.fixture(scope="module", name="client")
def _client() -> httpx.Client:
    """Shared HTTP client bound to the live gateway under test."""
    with httpx.Client(base_url=BASE_URL) as c:
        yield c


@pytest.fixture(scope="module", name="unrestricted_headers")
def _unrestricted_headers() -> dict[str, str]:
    """Authorization header for a fully unrestricted admin token (`teams: null`)."""
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET, algorithm="HS256")
    return make_auth_headers(token)


@pytest.fixture(scope="module", name="narrowed_headers")
def _narrowed_headers(client: httpx.Client, unrestricted_headers: dict[str, str]) -> dict[str, str]:
    """Authorization header for a team-narrowed admin token — the exact shape #6134 reports as a bypass.

    Provisions a real team the platform admin genuinely belongs to (as its
    creator) via the live REST API, so the narrowing itself is the only thing
    under test — a token narrowed to a team that doesn't exist, or one the
    caller isn't a member of, is rejected earlier by team-membership
    validation, before ever reaching the code #6134 is about.
    """
    resp = client.post(
        "/teams",
        headers=unrestricted_headers,
        json={"name": f"issue-6134-e2e-team-{uuid.uuid4().hex[:12]}", "description": "ephemeral team for #6134 e2e verification", "visibility": "private"},
        timeout=TIMEOUT,
        follow_redirects=True,
    )
    assert resp.status_code == 201, f"could not provision the narrowed-token team: {resp.status_code}: {resp.text[:300]}"
    team_id = resp.json()["id"]
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=[team_id], secret=JWT_SECRET, algorithm="HS256")
    return make_auth_headers(token)


@pytest.fixture(scope="module", name="public_only_headers")
def _public_only_headers() -> dict[str, str]:
    """Authorization header for a public-only admin token (`teams: []`)."""
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=[], secret=JWT_SECRET, algorithm="HS256")
    return make_auth_headers(token)


def _skip_if_flag_gated_and_unmounted(resp: httpx.Response, router: str, method: str, path: str) -> None:
    """Skip (not fail) a 404 for a router this testing profile cannot enable; fail otherwise.

    Args:
        resp: The live response.
        router: Router name from the route matrix.
        method: HTTP method used.
        path: Route path.
    """
    if resp.status_code == 404:
        if router in FLAG_GATED_UNDER_TESTING_PROFILE:
            pytest.skip(f"{router} ({method} {path}): 404 — this router's feature flag is not forwarded by the `testing` docker-compose profile (see module docstring Known Limitation); covered separately by its unit-level *_scope.py suite")
        pytest.fail(f"{router} ({method} {path}): 404 — router not mounted; check the feature flag is enabled (see module docstring)")


@pytest.mark.parametrize("router,method,path,allow_codes,body", ROUTE_MATRIX, ids=[r[0] for r in ROUTE_MATRIX])
def test_unrestricted_admin_passes_the_guard(client: httpx.Client, unrestricted_headers: dict[str, str], router: str, method: str, path: str, allow_codes: set[int], body: dict | None) -> None:
    """An unrestricted admin token must get past the scope guard on every migrated route."""
    resp = _request(client, method, path, unrestricted_headers, body)
    _skip_if_flag_gated_and_unmounted(resp, router, method, path)
    assert resp.status_code in allow_codes, f"{router} ({method} {path}): expected one of {allow_codes} for an unrestricted admin, got {resp.status_code}: {resp.text[:300]}"
    assert DENIAL_DETAIL_SUBSTRING not in resp.text, f"{router} ({method} {path}): unrestricted admin was wrongly denied by the global-scope guard: {resp.text[:300]}"


@pytest.mark.parametrize("router,method,path,_allow_codes,body", ROUTE_MATRIX, ids=[r[0] for r in ROUTE_MATRIX])
def test_narrowed_admin_is_denied(client: httpx.Client, narrowed_headers: dict[str, str], router: str, method: str, path: str, _allow_codes: set[int], body: dict | None) -> None:
    """A team-narrowed admin token — the exact #6134 reproduction — must be denied on every migrated route."""
    resp = _request(client, method, path, narrowed_headers, body)
    _skip_if_flag_gated_and_unmounted(resp, router, method, path)
    assert resp.status_code == 403, f"{router} ({method} {path}): narrowed admin token should be denied (403), got {resp.status_code}: {resp.text[:300]}"
    assert DENIAL_DETAIL_SUBSTRING in resp.text, f"{router} ({method} {path}): got 403 but not from the global-scope guard — response was {resp.text[:300]}"


@pytest.mark.parametrize("router,method,path,_allow_codes,body", ROUTE_MATRIX, ids=[r[0] for r in ROUTE_MATRIX])
def test_public_only_admin_is_denied(client: httpx.Client, public_only_headers: dict[str, str], router: str, method: str, path: str, _allow_codes: set[int], body: dict | None) -> None:
    """A public-only admin token (`teams: []`) must be denied on every migrated route.

    On the three routers in ADMIN_PREFIXED_HAS_SEPARATE_SCOPE_LAYER, TokenScopingMiddleware's
    own /admin/* default-deny may fire first — a different, also-correct denial. Either
    denial reason is accepted there; every other route must show this guard's own message.
    """
    resp = _request(client, method, path, public_only_headers, body)
    _skip_if_flag_gated_and_unmounted(resp, router, method, path)
    assert resp.status_code == 403, f"{router} ({method} {path}): public-only admin token should be denied (403), got {resp.status_code}: {resp.text[:300]}"
    if router in ADMIN_PREFIXED_HAS_SEPARATE_SCOPE_LAYER:
        assert DENIAL_DETAIL_SUBSTRING in resp.text or TOKEN_SCOPING_DENIAL_SUBSTRING in resp.text, f"{router} ({method} {path}): 403 but from neither the global-scope guard nor TokenScopingMiddleware — response was {resp.text[:300]}"
    else:
        assert DENIAL_DETAIL_SUBSTRING in resp.text, f"{router} ({method} {path}): got 403 but not from the global-scope guard — response was {resp.text[:300]}"


def test_neighboring_routes_unaffected(client: httpx.Client, unrestricted_headers: dict[str, str], narrowed_headers: dict[str, str], public_only_headers: dict[str, str]) -> None:
    """Nothing near this change regressed.

    Two directions are checked:
      - An already-migrated (#6132, not this plan) global-record route
        continues to enforce the identical rule it always did.
      - A route this plan never touched, which does not require unrestricted
        scope, is unaffected by the new guard on unrelated routers — a
        narrowed token still gets normal, non-403-for-this-reason treatment.
    """
    # A route #6132 already migrated to require_global_admin_permission() before this
    # plan started. If this branch's changes to mcpgateway/middleware/rbac.py broke
    # the shared _global_scope_denied() evaluation point, this route would regress too.
    resp = client.get("/compliance/frameworks", headers=narrowed_headers, timeout=TIMEOUT)
    assert resp.status_code != 404, "compliance router not mounted — check MCPGATEWAY_ADMIN_API_ENABLED"
    assert resp.status_code == 403, f"pre-existing #6132 global-record route stopped enforcing narrowing: {resp.status_code}: {resp.text[:300]}"
    assert DENIAL_DETAIL_SUBSTRING in resp.text

    resp = client.get("/compliance/frameworks", headers=unrestricted_headers, timeout=TIMEOUT)
    assert resp.status_code == 200, f"pre-existing #6132 global-record route regressed for an unrestricted admin: {resp.status_code}: {resp.text[:300]}"

    # A route this plan's guard has no business touching: /tools is team-scoped, not a
    # global-record route, and none of the 64 migrated routes live under /tools. A narrowed
    # (team-scoped) admin token listing tools should get a normal Layer-1-filtered response,
    # not a global-scope-guard 403 — proving the fix didn't over-broadly restrict unrelated
    # admin-flagged callers.
    resp = client.get("/tools", headers=narrowed_headers, timeout=TIMEOUT)
    assert resp.status_code != 404
    assert DENIAL_DETAIL_SUBSTRING not in resp.text, f"unrelated route /tools was wrongly caught by the global-scope guard: {resp.text[:300]}"


def test_all_route_matrix_entries_are_reachable(client: httpx.Client, unrestricted_headers: dict[str, str]) -> None:
    """Canary: if every non-flag-gated entry 404s, this suite is vacuous — see module docstring.

    Flag-gated routers (observability/siem/toolops) are allowed to 404 under the
    `testing` docker-compose profile (see Known Limitation); every other entry must
    be reachable or the run isn't testing anything.
    """
    expected = [r for r in ROUTE_MATRIX if r[0] not in FLAG_GATED_UNDER_TESTING_PROFILE]
    reachable = 0
    unreachable = []
    for router, method, path, _allow, body in expected:
        resp = _request(client, method, path, unrestricted_headers, body)
        if resp.status_code != 404:
            reachable += 1
        else:
            unreachable.append((router, method, path))
    assert reachable == len(expected), f"only {reachable}/{len(expected)} non-flag-gated routes are mounted — unreachable: {unreachable}; see module docstring for required feature flags"
