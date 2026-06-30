# -*- coding: utf-8 -*-
"""tests/helpers/router_helpers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Shared helper functions for testing FastAPI router assembly and path extraction.
"""

from fastapi import APIRouter


def _route_paths(router: APIRouter) -> list[str]:
    """Collect all route paths registered on a router, including nested routers.

    This helper handles both direct APIRoute objects and nested _IncludedRouter
    objects, recursively extracting paths with their full prefixes.

    Args:
        router: APIRouter to extract paths from.

    Returns:
        List of all route paths including nested router paths with prefixes.

    Example:
        >>> from fastapi import APIRouter
        >>> router = APIRouter()
        >>> router.add_api_route("/test", lambda: "ok")
        >>> paths = _route_paths(router)
        >>> "/test" in paths
        True
    """
    paths = []
    for route in router.routes:
        if hasattr(route, 'path'):
            # Direct APIRoute
            paths.append(route.path)
        elif hasattr(route, 'original_router'):
            # _IncludedRouter - recurse into it with its prefix
            prefix = route.include_context.prefix
            for nested_route in route.original_router.routes:
                if hasattr(nested_route, 'path'):
                    paths.append(prefix + nested_route.path)
                elif hasattr(nested_route, 'original_router'):
                    # Nested _IncludedRouter - recurse further
                    nested_prefix = prefix + nested_route.include_context.prefix
                    paths.extend(_collect_paths_recursive(nested_route.original_router, nested_prefix))
    return paths


def _collect_paths_recursive(router: APIRouter, prefix: str) -> list[str]:
    """Helper to recursively collect paths from deeply nested routers.

    Args:
        router: APIRouter to extract paths from.
        prefix: Current accumulated prefix from parent routers.

    Returns:
        List of route paths with the accumulated prefix applied.
    """
    paths = []
    for route in router.routes:
        if hasattr(route, 'path'):
            paths.append(prefix + route.path)
        elif hasattr(route, 'original_router'):
            nested_prefix = prefix + route.include_context.prefix
            paths.extend(_collect_paths_recursive(route.original_router, nested_prefix))
    return paths
