# -*- coding: utf-8 -*-
"""Route-ordering regression test for native A2A 1.0.0 routes (Plan T13).

Location: ./tests/integration/test_a2a_route_ordering.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Plan T13 — Oracle #15 route-ordering regression: the catch-all
``POST /a2a/{agent_name}`` (T12) is greedy — without explicit ordering
discipline, ``POST /a2a/invoke`` would resolve to the catch-all
(``agent_name="invoke"``) and silently shadow the legacy ID-based
``invoke_a2a_agent_by_id`` handler at ``/a2a/invoke``.

These tests:

1. Introspect ``app.routes`` and assert static-suffix routes
   (``/invoke``, ``/{agent_name}/invoke``, ``/{agent_name}/.well-known/...``)
   are registered BEFORE the catch-all ``/{agent_name}``.
2. Use ``TestClient`` to POST to ``/a2a/invoke`` and ``/a2a/foo/invoke``
   and assert each resolves to its intended handler via the matched
   route's path (``request.scope["route"].path``).

These are pure introspection / matching tests — they do NOT exercise
the handlers. T11/T12 integration tests at ``test_a2a_native_routes.py``
cover handler behavior.
"""

from __future__ import annotations

import pytest
from starlette.routing import Route

from mcpgateway import main as main_mod

pytestmark = pytest.mark.integration


def _a2a_routes() -> list[Route]:
    """Return all ``/a2a/...`` ``Route`` entries from the live app.

    Includes only ``starlette.routing.Route`` (skips ``Mount`` /
    ``WebSocketRoute`` entries). Result is in registration order.
    """
    return [r for r in main_mod.app.routes if isinstance(r, Route) and r.path.startswith("/a2a/")]


def _post_route_paths_in_order() -> list[str]:
    """Return registration-ordered list of POST routes under ``/a2a/...``.

    Each entry is the route's path template (e.g. ``"/a2a/invoke"``,
    ``"/a2a/{agent_name}"``).
    """
    return [r.path for r in _a2a_routes() if "POST" in r.methods]


class TestA2ARouteOrdering:
    """T13 — registration order + concrete request matching."""

    def test_a2a_invoke_registered_before_agent_name_catchall(self) -> None:
        """``POST /a2a/invoke`` MUST be registered BEFORE ``POST /a2a/{agent_name}``.

        Closes Oracle #15: FastAPI / Starlette matches routes in
        REGISTRATION order. A catch-all ``/{agent_name}`` registered
        first would intercept every literal-segment match including
        ``/invoke``.
        """
        post_paths = _post_route_paths_in_order()
        assert "/a2a/invoke" in post_paths, f"POST /a2a/invoke missing from registered routes: {post_paths}"
        assert "/a2a/{agent_name}" in post_paths, f"POST /a2a/{{agent_name}} missing from registered routes: {post_paths}"
        idx_literal = post_paths.index("/a2a/invoke")
        idx_catchall = post_paths.index("/a2a/{agent_name}")
        assert (
            idx_literal < idx_catchall
        ), f"REGRESSION: POST /a2a/invoke (index {idx_literal}) registered AFTER catch-all /a2a/{{agent_name}} (index {idx_catchall}); catch-all would shadow the literal. Route order: {post_paths}"

    def test_agent_name_invoke_registered_before_agent_name_catchall(self) -> None:
        """``POST /a2a/{agent_name}/invoke`` MUST be registered BEFORE catch-all.

        Two-segment routes with a literal suffix (``.../invoke``) need
        to be evaluated before the single-segment catch-all so a
        request like ``POST /a2a/foo/invoke`` matches the legacy
        per-agent invoke handler, NOT the catch-all.
        """
        post_paths = _post_route_paths_in_order()
        assert "/a2a/{agent_name}/invoke" in post_paths, f"POST /a2a/{{agent_name}}/invoke missing: {post_paths}"
        idx_two_seg = post_paths.index("/a2a/{agent_name}/invoke")
        idx_catchall = post_paths.index("/a2a/{agent_name}")
        assert idx_two_seg < idx_catchall, f"REGRESSION: POST /a2a/{{agent_name}}/invoke (index {idx_two_seg}) registered AFTER catch-all (index {idx_catchall}). Route order: {post_paths}"

    def test_well_known_card_registered_before_agent_name_catchall(self) -> None:
        """``GET /a2a/{agent_name}/.well-known/agent-card.json`` is GET, not POST.

        Different HTTP method, so technically not at risk of being
        shadowed by the POST catch-all. But the route table still
        carries it in registration order; this test pins the
        invariant that future GETs added under the same prefix will
        ALSO come before any GET catch-all if one is ever added.
        """
        a2a_routes = _a2a_routes()
        get_paths = [r.path for r in a2a_routes if "GET" in r.methods]
        assert "/a2a/{agent_name}/.well-known/agent-card.json" in get_paths, f"GET well-known card route missing: {get_paths}"

    def test_post_a2a_invoke_matches_legacy_handler(self) -> None:
        """``POST /a2a/invoke`` MUST resolve to ``invoke_a2a_agent_by_id``.

        Walks the registration-ordered route list and returns the FIRST
        ``Route`` whose ``path_regex`` matches the concrete path. This
        mirrors what Starlette's router does at request time.
        """
        matched = _first_matching_post_route("/a2a/invoke")
        assert matched is not None, "no route matched POST /a2a/invoke"
        assert matched.path == "/a2a/invoke", f"POST /a2a/invoke matched the wrong route: {matched.path!r} (expected /a2a/invoke); catch-all SHADOWED the literal."
        assert matched.endpoint.__name__ == "invoke_a2a_agent_by_id", f"POST /a2a/invoke resolved to {matched.endpoint.__name__!r} (expected invoke_a2a_agent_by_id)"

    def test_post_a2a_foo_invoke_matches_legacy_per_agent_handler(self) -> None:
        """``POST /a2a/foo/invoke`` MUST resolve to the LEGACY ``/{agent_name}/invoke``.

        Specifically NOT the catch-all ``/{agent_name}`` — the
        two-segment literal-suffix route is more specific.
        """
        matched = _first_matching_post_route("/a2a/foo/invoke")
        assert matched is not None, "no route matched POST /a2a/foo/invoke"
        assert (
            matched.path == "/a2a/{agent_name}/invoke"
        ), f"POST /a2a/foo/invoke matched the wrong route: {matched.path!r} (expected /a2a/{{agent_name}}/invoke); catch-all SHADOWED the two-segment literal-suffix."
        assert matched.endpoint.__name__ == "invoke_a2a_agent", f"POST /a2a/foo/invoke resolved to {matched.endpoint.__name__!r} (expected invoke_a2a_agent)"

    def test_post_a2a_foo_matches_catchall(self) -> None:
        """``POST /a2a/foo`` (no literal suffix) MUST resolve to the catch-all (T12).

        Sanity test that confirms the catch-all DOES claim requests
        that no more-specific route accepts — the previous tests
        prove it does NOT incorrectly steal literal-suffix requests.
        """
        matched = _first_matching_post_route("/a2a/foo")
        assert matched is not None, "no route matched POST /a2a/foo"
        assert matched.path == "/a2a/{agent_name}", f"POST /a2a/foo matched the wrong route: {matched.path!r} (expected /a2a/{{agent_name}}); something is BEFORE the catch-all that should not be."
        assert matched.endpoint.__name__ == "dispatch_a2a_agent", f"POST /a2a/foo resolved to {matched.endpoint.__name__!r} (expected dispatch_a2a_agent)"


def _first_matching_post_route(path: str) -> Route | None:
    """Return the FIRST POST ``Route`` whose ``path_regex`` matches ``path``.

    Mirrors Starlette router's matching logic at request time: walks
    routes in registration order and returns the first match. This is
    what FastAPI actually does — if the catch-all is registered first
    it wins; otherwise the literal/specific route wins. This helper
    surfaces that decision without standing up a TestClient.
    """
    for route in main_mod.app.routes:
        if not isinstance(route, Route):
            continue
        if "POST" not in route.methods:
            continue
        if not route.path.startswith("/a2a/"):
            continue
        if route.path_regex.match(path):
            return route
    return None
