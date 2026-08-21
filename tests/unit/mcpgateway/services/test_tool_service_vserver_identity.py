# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_service_vserver_identity.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for identity propagation on the cached virtual-server invocation path.

The cached tool-call path (``streamablehttp_transport`` -> ``ToolService.invoke_tool``)
does not pass a ``plugin_global_context``. Identity propagation must therefore fall
back to the per-request ``user_identity_var`` set by the transport auth layer,
otherwise ``X-<prefix>-*`` identity headers are silently dropped for vServer calls.
"""

# Standard
from datetime import datetime, timezone

# Third-Party
import pytest

# First-Party
from mcpgateway.services.tool_service import _resolve_propagation_identity
from mcpgateway.transports.context import UserContext, user_identity_var


class _GC:
    """Minimal stand-in for the plugin GlobalContext (only ``user_context`` is read)."""

    def __init__(self, user_context):
        self.user_context = user_context


@pytest.fixture(autouse=True)
def _clear_identity_var():
    """Reset the identity contextvar around each test."""
    token = user_identity_var.set(None)
    try:
        yield
    finally:
        user_identity_var.reset(token)


def _uc(email):
    return UserContext(user_id=email, email=email, teams=["team-it"], auth_method="bearer", authenticated_at=datetime.now(timezone.utc))


def test_prefers_global_context_user_context():
    """When a plugin global context carries a user_context, it wins."""
    gc_uc = _uc("from-gc@example.com")
    user_identity_var.set(_uc("from-var@example.com"))
    assert _resolve_propagation_identity(_GC(gc_uc)) is gc_uc


def test_falls_back_to_contextvar_when_no_global_context():
    """Cached vServer path: global_context is None -> use user_identity_var."""
    var_uc = _uc("from-var@example.com")
    user_identity_var.set(var_uc)
    assert _resolve_propagation_identity(None) is var_uc


def test_falls_back_when_global_context_has_no_user_context():
    """A global context without user_context still falls back to the contextvar."""
    var_uc = _uc("from-var@example.com")
    user_identity_var.set(var_uc)
    assert _resolve_propagation_identity(_GC(None)) is var_uc


def test_returns_none_when_no_identity_anywhere():
    """No global context and no contextvar -> nothing to propagate."""
    assert _resolve_propagation_identity(None) is None
    assert _resolve_propagation_identity(_GC(None)) is None
