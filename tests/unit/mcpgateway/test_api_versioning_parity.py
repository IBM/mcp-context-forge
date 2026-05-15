"""Test parity between _LEGACY_PREFIXES and _assemble_routers.

This test ensures that the _LEGACY_PREFIXES set in deprecation middleware
stays synchronized with the actual routers mounted by _assemble_routers.

If this test fails, it means a new router was added to _assemble_routers
but _LEGACY_PREFIXES was not updated, which would cause deprecation headers
to be missing on that router's legacy routes.
"""

import pytest
from fastapi import APIRouter

from mcpgateway.api.v1 import _assemble_routers
from mcpgateway.config import settings
from mcpgateway.middleware.deprecation import _LEGACY_PREFIXES


def extract_router_prefixes(router: APIRouter) -> set[str]:
    """Extract all route prefixes from an assembled router.

    Args:
        router: APIRouter to extract prefixes from.

    Returns:
        Set of unique prefixes (e.g., {"/tools", "/servers"}).
    """
    prefixes = set()
    for route in router.routes:
        path = route.path
        # Extract first path segment as prefix
        if path.startswith("/"):
            parts = path.split("/")
            if len(parts) > 1 and parts[1]:
                prefixes.add(f"/{parts[1]}")
    return prefixes


def test_legacy_prefixes_match_assembled_routers():
    """Verify _LEGACY_PREFIXES contains all routers from _assemble_routers.

    This test creates a temporary router, assembles all sub-routers into it,
    and verifies that every prefix in the assembled router exists in
    _LEGACY_PREFIXES.

    Note: Extra prefixes in _LEGACY_PREFIXES are acceptable (feature-flagged
    routers may not be mounted in all configurations).
    """
    # Create test router and mock sub-routers
    test_router = APIRouter()

    # Create minimal mock routers with at least one route each
    # Use the actual prefix names from main.py (plural forms)
    mock_routers = {}
    router_prefixes = {
        "protocol": "/protocol",
        "tool": "/tools",           # Note: router name is singular, prefix is plural
        "resource": "/resources",
        "prompt": "/prompts",
        "gateway": "/gateways",
        "root": "/roots",
        "server": "/servers",
        "metrics": "/metrics",
        "tag": "/tags",
        "a2a": "/a2a",
    }

    for name, prefix in router_prefixes.items():
        mock_router = APIRouter(prefix=prefix)
        # Add a dummy route so the router has a path
        mock_router.add_api_route("/test", lambda: {"status": "ok"})
        mock_routers[name] = mock_router

    # Export/import router is special - it has no prefix but routes under /export and /import
    export_import_router = APIRouter()
    export_import_router.add_api_route("/export/test", lambda: {"status": "ok"})
    export_import_router.add_api_route("/import/test", lambda: {"status": "ok"})
    mock_routers["export_import"] = export_import_router

    # Assemble routers into test router
    _assemble_routers(
        test_router,
        settings,
        protocol_router=mock_routers["protocol"],
        tool_router=mock_routers["tool"],
        resource_router=mock_routers["resource"],
        prompt_router=mock_routers["prompt"],
        gateway_router=mock_routers["gateway"],
        root_router=mock_routers["root"],
        server_router=mock_routers["server"],
        metrics_router=mock_routers["metrics"],
        tag_router=mock_routers["tag"],
        export_import_router=mock_routers["export_import"],
        a2a_router=mock_routers["a2a"],
    )

    # Extract prefixes from assembled router
    assembled_prefixes = extract_router_prefixes(test_router)

    # Exclude permanently unversioned prefixes that should NOT have deprecation headers
    # These are intentionally not in _LEGACY_PREFIXES
    permanently_unversioned = {
        "/.well-known",  # RFC 9116 - permanently unversioned
        "/api",          # Internal API prefix (if present)
    }

    # Only check prefixes that should be in _LEGACY_PREFIXES
    prefixes_to_check = assembled_prefixes - permanently_unversioned

    # Verify all assembled prefixes (except permanently unversioned) are in _LEGACY_PREFIXES
    missing = prefixes_to_check - _LEGACY_PREFIXES

    assert not missing, (
        f"Prefixes in _assemble_routers but not in _LEGACY_PREFIXES: {missing}\n"
        f"Update mcpgateway/middleware/deprecation.py to include these prefixes.\n"
        f"Assembled prefixes: {sorted(assembled_prefixes)}\n"
        f"Permanently unversioned (excluded): {sorted(permanently_unversioned)}\n"
        f"_LEGACY_PREFIXES: {sorted(_LEGACY_PREFIXES)}"
    )

    # Extra prefixes are OK (feature-flagged routers may not be mounted)
    extra = _LEGACY_PREFIXES - assembled_prefixes
    if extra:
        # This is informational, not a failure
        print(f"Note: _LEGACY_PREFIXES contains prefixes not in test assembly: {extra}")
        print("This is expected for feature-flagged routers (e.g., A2A, plugins)")


def test_legacy_prefixes_documented():
    """Verify _LEGACY_PREFIXES has documentation explaining maintenance.

    The deprecation module should document that _LEGACY_PREFIXES must be
    kept in sync with _assemble_routers.
    """
    from mcpgateway.middleware import deprecation

    # Check module docstring mentions synchronization requirement
    module_doc = deprecation.__doc__ or ""
    module_doc_lower = module_doc.lower()

    # Look for keywords indicating synchronization requirement
    sync_keywords = ["sync", "mirror", "match", "parity", "assemble"]
    has_sync_doc = any(keyword in module_doc_lower for keyword in sync_keywords)

    assert has_sync_doc, (
        "deprecation.py module docstring should document that _LEGACY_PREFIXES "
        "must be kept in sync with _assemble_routers. Add documentation explaining "
        "the synchronization requirement."
    )


@pytest.mark.parametrize(
    "prefix",
    [
        "/tools",
        "/servers",
        "/prompts",
        "/resources",
        "/gateways",
    ],
)
def test_core_prefixes_present(prefix: str):
    """Verify core API prefixes are in _LEGACY_PREFIXES.

    Args:
        prefix: Core API prefix that must be present.
    """
    assert prefix in _LEGACY_PREFIXES, (
        f"Core prefix {prefix} missing from _LEGACY_PREFIXES. "
        f"This would cause deprecation headers to be missing on legacy routes."
    )
