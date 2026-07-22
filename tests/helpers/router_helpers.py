# -*- coding: utf-8 -*-
"""Location: ./tests/helpers/router_helpers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

FastAPI router introspection helpers shared across the test suite.

These utilities abstract over the ``_IncludedRouter`` lazy-wrapper introduced
in FastAPI 0.137.0 so that tests work correctly against both FastAPI ≤ 0.136
(eager route expansion) and ≥ 0.137 (lazy ``_IncludedRouter`` wrappers).
"""

from __future__ import annotations


def collect_routes(router) -> list[tuple[str, object, list]]:
    """Return ``(full_path, route, include_deps)`` triples for every leaf route on *router*.

    ``include_deps`` is the list of :class:`fastapi.params.Depends` objects
    accumulated from enclosing ``_IncludedRouter`` wrappers (FastAPI ≥ 0.137).
    On FastAPI ≤ 0.136 this list is always empty because ``include_router``
    copies dependencies directly onto each leaf route's ``.dependencies``.

    This covers both FastAPI versions for tests that inspect route dependencies:

    * FastAPI ≤ 0.136: check ``getattr(route, "dependencies", [])``
    * FastAPI ≥ 0.137: check ``include_deps``

    To get paths only: ``[p for p, *_ in collect_routes(router)]``.

    Args:
        router: Any ``fastapi.APIRouter`` instance.

    Returns:
        A list of ``(path_str, route_object, include_deps)`` triples.
    """
    try:
        from fastapi.routing import _IncludedRouter  # type: ignore[attr-defined]
    except ImportError:
        _IncludedRouter = None  # type: ignore[assignment,misc]

    if _IncludedRouter is None:
        # FastAPI ≤ 0.136: include_router eagerly expands routes; paths already
        # contain the fully-qualified prefix and deps are on the route itself.
        return [(r.path, r, []) for r in router.routes]

    # FastAPI 0.137+: include_router stores lazy _IncludedRouter wrappers.
    # Accumulate include_context.dependencies as we descend so callers see the
    # full effective dependency set without knowing about _IncludedRouter.
    def _collect(routes: list, prefix: str, acc_deps: list) -> list[tuple[str, object, list]]:
        result: list[tuple[str, object, list]] = []
        for r in routes:
            if isinstance(r, _IncludedRouter):
                combined_deps = acc_deps + list(r.include_context.dependencies or [])
                result.extend(_collect(
                    r.original_router.routes,
                    prefix + r.include_context.prefix,
                    combined_deps,
                ))
            else:
                result.append((prefix + r.path, r, acc_deps))
        return result

    items: list[tuple[str, object, list]] = []
    for r in router.routes:
        if isinstance(r, _IncludedRouter):
            # include_context.prefix already contains the parent router prefix.
            # include_context.dependencies already includes the parent router deps.
            top_deps = list(r.include_context.dependencies or [])
            items.extend(_collect(r.original_router.routes, r.include_context.prefix, top_deps))
        else:
            # Direct routes already have the router's own prefix embedded.
            items.append((r.path, r, []))
    return items
