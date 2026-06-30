# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_internal_mcp_auth_context_validation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Pratik Gandhi

Unit tests for ``_validate_internal_mcp_auth_context``.

The public-only RBAC early-return in ``_ensure_rpc_permission`` trusts the decoded
trusted-internal auth context. These tests pin the fail-closed contract: a public-only
context (``is_authenticated is False``) must carry only public privileges, and field
types must be well-formed, otherwise the dispatch is rejected with HTTP 400.
"""

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.main import _validate_internal_mcp_auth_context


def test_valid_public_only_context_passes():
    """A well-formed public-only context (no identity, no teams, not admin) is accepted."""
    _validate_internal_mcp_auth_context({"email": None, "teams": [], "is_authenticated": False, "is_admin": False, "permission_is_admin": False})


def test_valid_authenticated_context_may_carry_privileges():
    """An authenticated context is allowed to carry teams, admin, and an identity."""
    _validate_internal_mcp_auth_context({"email": "u@example.com", "teams": ["t1"], "is_authenticated": True, "is_admin": True, "scoped_permissions": ["tools.read"]})


@pytest.mark.parametrize(
    "ctx",
    [
        {"is_authenticated": False, "teams": ["t1"]},  # public-only must not carry teams
        {"is_authenticated": False, "is_admin": True},  # public-only must not be admin
        {"is_authenticated": False, "permission_is_admin": True},  # nor via permission_is_admin
        {"is_authenticated": False, "email": "attacker@evil.com"},  # public-only must not carry an identity
    ],
)
def test_contradictory_public_only_context_is_rejected(ctx):
    """A public-only context that claims teams, admin, or an identity is rejected with 400."""
    with pytest.raises(HTTPException) as exc:
        _validate_internal_mcp_auth_context(ctx)
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "ctx",
    [
        {"is_authenticated": True, "teams": "t1"},  # teams must be a list
        {"is_authenticated": True, "scoped_permissions": "tools.read"},  # scoped_permissions must be a list
    ],
)
def test_malformed_types_are_rejected(ctx):
    """Non-list ``teams`` / ``scoped_permissions`` are rejected with 400 (avoids downstream type confusion)."""
    with pytest.raises(HTTPException) as exc:
        _validate_internal_mcp_auth_context(ctx)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("bad", ["false", "true", "False", 0, 1])
def test_non_bool_is_authenticated_is_rejected(bad):
    """A non-bool ``is_authenticated`` (e.g. ``"false"`` or ``0``) is rejected so the downstream ``is False`` checks stay reliable."""
    with pytest.raises(HTTPException) as exc:
        _validate_internal_mcp_auth_context({"is_authenticated": bad})
    assert exc.value.status_code == 400


def test_public_only_with_none_teams_is_accepted():
    """``teams: None`` on a public-only context is fine (normalised to no teams downstream)."""
    _validate_internal_mcp_auth_context({"is_authenticated": False, "teams": None, "is_admin": False, "email": None})
