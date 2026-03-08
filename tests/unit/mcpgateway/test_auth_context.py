# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Behavioral contract tests for AuthContext consolidation.

These tests encode the EXACT same decisions currently scattered across 10 layers.
Each test class maps to a specific existing behavior with comments citing the source.

This file is the TDD anchor for the auth context consolidation. It was written
BEFORE any callers exist. If any test here contradicts an existing test in the
baseline suite, the existing test wins and this file must be corrected.

Baseline source files (current behavior these tests must match):
- mcpgateway/auth.py: normalize_token_teams (lines 303-353)
- mcpgateway/main.py: _get_rpc_filter_context (lines 391-443)
- mcpgateway/main.py: AdminAuthMiddleware (lines 1676-1900)
- mcpgateway/transports/streamablehttp_transport.py: _auth_jwt (lines 2906-3052)
- mcpgateway/middleware/token_scoping.py: TokenScopingMiddleware
- mcpgateway/services/tool_service.py: inline token_teams patterns
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import MagicMock

# Third-Party
import pytest
from sqlalchemy import Column, String, Boolean, or_

# First-Party
from mcpgateway.auth_context import AuthContext, QueryScope


# ═══════════════════════════════════════════════════════════════════════
# Helper: build AuthContext with defaults to reduce test boilerplate
# ═══════════════════════════════════════════════════════════════════════


def _ctx(
    *,
    email: str = "user@test.local",
    is_admin: bool = False,
    teams: object = "REQUIRED",  # force explicit
    token_use: str = "api",
    auth_method: str = "bearer_token",
    scoped_permissions: list | None = None,
    is_active: bool = True,
) -> AuthContext:
    """Build an AuthContext with sensible defaults for testing."""
    assert teams != "REQUIRED", "teams= must be explicit in every test"
    return AuthContext(
        user_email=email,
        is_admin=is_admin,
        effective_teams=teams,
        token_use=token_use,
        auth_method=auth_method,
        scoped_permissions=scoped_permissions or [],
        is_active=is_active,
    )


# ═══════════════════════════════════════════════════════════════════════
# 1. AuthContext property truth table
#    Source: normalize_token_teams + _get_rpc_filter_context
# ═══════════════════════════════════════════════════════════════════════


class TestAuthContextPropertyMatrix:
    """Every combination of (effective_teams, is_admin) and the derived properties.

    This is the central truth table. If ANY of these fail after a refactoring
    change, the refactoring has a security bug.

    Sources:
    - is_admin_bypass: auth.py normalize_token_teams — only teams=None + is_admin=True
    - is_public_only: auth.py normalize_token_teams — teams=[] regardless of is_admin
    - effective_is_admin: main.py:440 _get_rpc_filter_context — public-only forces False
    - allows_admin_paths: main.py:1842 AdminAuthMiddleware — public-only denied
    """

    @pytest.mark.parametrize(
        "teams, is_admin, expect_bypass, expect_public, expect_eff_admin, expect_admin_paths",
        [
            # ── Admin bypass: the ONLY path to unrestricted access ────────
            # Source: normalize_token_teams returns None only for teams=null + is_admin=true
            (None, True, True, False, True, True),
            # ── Non-admin with null teams: NO bypass ──────────────────────
            # Source: normalize_token_teams returns [] for teams=null + is_admin=false
            # NOTE: In practice normalize_token_teams would have returned [],
            # but we test the AuthContext invariant directly: even if someone
            # constructed AuthContext(teams=None, is_admin=False), bypass=False.
            (None, False, False, False, False, False),
            # ── Public-only: empty teams list ─────────────────────────────
            # Source: normalize_token_teams returns [] for missing key, null+non-admin, or explicit []
            # CRITICAL: is_admin=True + teams=[] → is_admin_bypass=False, effective_is_admin=False
            # Source: _get_rpc_filter_context line 440-441
            ([], True, False, True, False, False),
            ([], False, False, True, False, False),
            # ── Team-scoped: has specific teams ───────────────────────────
            # Source: normalize_token_teams returns list for teams=[...]
            (["team-1"], True, False, False, True, True),
            (["team-1"], False, False, False, False, False),
            (["team-1", "team-2"], True, False, False, True, True),
            (["team-1", "team-2"], False, False, False, False, False),
        ],
        ids=[
            "admin-bypass-null-teams",
            "non-admin-null-teams-no-bypass",
            "public-only-admin-override",
            "public-only-non-admin",
            "single-team-admin",
            "single-team-non-admin",
            "multi-team-admin",
            "multi-team-non-admin",
        ],
    )
    def test_property_matrix(self, teams, is_admin, expect_bypass, expect_public, expect_eff_admin, expect_admin_paths):
        ctx = _ctx(teams=teams, is_admin=is_admin)
        assert ctx.is_admin_bypass == expect_bypass, f"is_admin_bypass: expected {expect_bypass}"
        assert ctx.is_public_only == expect_public, f"is_public_only: expected {expect_public}"
        assert ctx.effective_is_admin() == expect_eff_admin, f"effective_is_admin: expected {expect_eff_admin}"
        assert ctx.allows_admin_paths() == expect_admin_paths, f"allows_admin_paths: expected {expect_admin_paths}"


class TestPublicOnlyAdminOverride:
    """Dedicated tests for the critical public-only admin override.

    This is the most dangerous security invariant in the system. An admin who
    creates a public-only token (teams=[]) MUST NOT get admin bypass through
    that token. This protects against token-scope escalation.

    Source: main.py _get_rpc_filter_context lines 438-441:
        if token_teams is not None and len(token_teams) == 0:
            is_admin = False
    """

    def test_public_only_token_disables_admin_bypass(self):
        """Admin + teams=[] → is_admin_bypass MUST be False."""
        ctx = _ctx(teams=[], is_admin=True)
        assert ctx.is_admin_bypass is False

    def test_public_only_token_disables_effective_admin(self):
        """Admin + teams=[] → effective_is_admin MUST be False."""
        ctx = _ctx(teams=[], is_admin=True)
        assert ctx.effective_is_admin() is False

    def test_public_only_token_blocks_admin_paths(self):
        """Admin + teams=[] → allows_admin_paths MUST be False."""
        ctx = _ctx(teams=[], is_admin=True)
        assert ctx.allows_admin_paths() is False

    def test_public_only_token_is_public_only(self):
        """Admin + teams=[] → is_public_only MUST be True."""
        ctx = _ctx(teams=[], is_admin=True)
        assert ctx.is_public_only is True

    def test_raw_is_admin_still_true(self):
        """The raw is_admin field is still True — it's the derived properties that override."""
        ctx = _ctx(teams=[], is_admin=True)
        assert ctx.is_admin is True  # raw field
        assert ctx.effective_is_admin() is False  # derived — the one callers should use


# ═══════════════════════════════════════════════════════════════════════
# 2. AuthContext is frozen (immutable)
# ═══════════════════════════════════════════════════════════════════════


class TestAuthContextImmutability:
    """AuthContext must be frozen — no field can be changed after creation.

    This prevents middleware or services from mutating auth state, which is
    a class of bugs the consolidation is designed to eliminate.
    """

    def test_cannot_mutate_is_admin(self):
        ctx = _ctx(teams=None, is_admin=True)
        with pytest.raises(AttributeError):
            ctx.is_admin = False  # type: ignore[misc]

    def test_cannot_mutate_effective_teams(self):
        ctx = _ctx(teams=["t1"], is_admin=False)
        with pytest.raises(AttributeError):
            ctx.effective_teams = None  # type: ignore[misc]

    def test_cannot_mutate_user_email(self):
        ctx = _ctx(teams=[], is_admin=False)
        with pytest.raises(AttributeError):
            ctx.user_email = "evil@attacker.com"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════
# 3. to_transport_dict — bridge to StreamableHTTP ContextVar
#    Source: streamablehttp_transport.py _auth_jwt user_context_var.set()
# ═══════════════════════════════════════════════════════════════════════


class TestToTransportDict:
    """Verify the dict shape matches what _auth_jwt currently writes to user_context_var.

    Source: streamablehttp_transport.py line 3039:
        auth_user_ctx = {
            "email": user_email,
            "teams": final_teams,
            "is_authenticated": True,
            "is_admin": is_admin,
            "token_use": token_use,
        }
    Plus optional "scoped_permissions" key.
    """

    def test_keys_match_transport_shape(self):
        """The dict must have exactly the keys the transport currently writes."""
        ctx = _ctx(teams=["t1"], is_admin=False, token_use="api", scoped_permissions=["tools.read"])
        d = ctx.to_transport_dict()
        assert set(d.keys()) == {"email", "teams", "is_admin", "token_use", "scoped_permissions", "is_authenticated"}

    def test_uses_teams_key_not_token_teams(self):
        """Key name standardization: transport uses 'teams', not 'token_teams'.

        Source: the existing key-name drift documented in the design.
        """
        ctx = _ctx(teams=["t1"], is_admin=False)
        d = ctx.to_transport_dict()
        assert "teams" in d
        assert "token_teams" not in d

    def test_admin_bypass_teams_none(self):
        """Admin bypass → teams=None in transport dict."""
        ctx = _ctx(teams=None, is_admin=True, token_use="session", auth_method="cookie")
        d = ctx.to_transport_dict()
        assert d["teams"] is None
        assert d["is_admin"] is True
        assert d["is_authenticated"] is True

    def test_public_only_teams_empty(self):
        """Public-only → teams=[] in transport dict."""
        ctx = _ctx(teams=[], is_admin=False, token_use="api")
        d = ctx.to_transport_dict()
        assert d["teams"] == []

    def test_team_scoped(self):
        """Team-scoped → teams=["t1","t2"] in transport dict."""
        ctx = _ctx(teams=["t1", "t2"], is_admin=False, token_use="api")
        d = ctx.to_transport_dict()
        assert d["teams"] == ["t1", "t2"]

    def test_scoped_permissions_included(self):
        """Scoped permissions from JWT are passed through."""
        ctx = _ctx(teams=["t1"], is_admin=False, scoped_permissions=["tools.read", "prompts.read"])
        d = ctx.to_transport_dict()
        assert d["scoped_permissions"] == ["tools.read", "prompts.read"]

    def test_scoped_permissions_empty_by_default(self):
        """No scoped permissions → empty list (not missing key)."""
        ctx = _ctx(teams=["t1"], is_admin=False)
        d = ctx.to_transport_dict()
        assert d["scoped_permissions"] == []

    def test_anonymous_user(self):
        """Anonymous users have email=None, is_admin=False, teams=[]."""
        ctx = _ctx(email=None, teams=[], is_admin=False, token_use="anonymous", auth_method="anonymous")
        d = ctx.to_transport_dict()
        assert d["email"] is None
        assert d["teams"] == []
        assert d["is_admin"] is False
        assert d["is_authenticated"] is True  # still authenticated (as anonymous)


# ═══════════════════════════════════════════════════════════════════════
# 4. to_query_scope — bridge to services
# ═══════════════════════════════════════════════════════════════════════


class TestToQueryScope:
    """Verify QueryScope construction from AuthContext."""

    def test_admin_bypass_creates_unrestricted_scope(self):
        ctx = _ctx(teams=None, is_admin=True)
        scope = ctx.to_query_scope()
        assert scope.is_unrestricted is True

    def test_public_only_creates_restricted_scope(self):
        ctx = _ctx(teams=[], is_admin=False)
        scope = ctx.to_query_scope()
        assert scope.is_unrestricted is False
        assert scope._effective_teams == []

    def test_public_only_admin_creates_restricted_scope(self):
        """Admin + teams=[] → restricted scope. The admin override propagates."""
        ctx = _ctx(teams=[], is_admin=True)
        scope = ctx.to_query_scope()
        assert scope.is_unrestricted is False  # NOT unrestricted despite is_admin=True

    def test_team_scoped_creates_team_scope(self):
        ctx = _ctx(teams=["t1", "t2"], is_admin=False)
        scope = ctx.to_query_scope()
        assert scope.is_unrestricted is False
        assert scope._effective_teams == ["t1", "t2"]

    def test_preserves_user_email(self):
        ctx = _ctx(email="dev@example.com", teams=["t1"], is_admin=False)
        scope = ctx.to_query_scope()
        assert scope.user_email == "dev@example.com"


# ═══════════════════════════════════════════════════════════════════════
# 5. QueryScope.apply_visibility_filter
#    Source: inline patterns in tool_service.py, resource_service.py, etc.
# ═══════════════════════════════════════════════════════════════════════


class _FakeModel:
    """Minimal model stub for testing QueryScope filters."""

    visibility = Column("visibility", String)
    team_id = Column("team_id", String)


class _FakeModelIsPublic:
    """Model stub using is_public boolean instead of visibility."""

    is_public = Column("is_public", Boolean)
    team_id = Column("team_id", String)


class _FakeModelNoVisibility:
    """Model stub with no visibility or is_public column."""

    team_id = Column("team_id", String)


class _MockQuery:
    """Mock query that records filter calls for assertion."""

    def __init__(self):
        self.filters = []

    def filter(self, *args):
        self.filters.extend(args)
        return self  # chainable


class TestQueryScopeVisibilityFilter:
    """Test apply_visibility_filter against the 3 service patterns.

    Pattern 1 (admin bypass):
        if token_teams is None and user_email is None: → return all
    Pattern 2 (public-only):
        if len(token_teams) == 0: → filter visibility=="public"
    Pattern 3 (team-scoped):
        filter(or_(visibility=="public", team_id.in_(teams)))
    """

    def test_unrestricted_returns_query_unchanged(self):
        """Source: 'if token_teams is None and user_email is None: return all'"""
        scope = AuthContext(
            user_email=None, is_admin=True, effective_teams=None,
            token_use="api", auth_method="bearer_token",
        ).to_query_scope()
        query = _MockQuery()
        result = scope.apply_visibility_filter(query, _FakeModel)
        assert result is query  # same object, no filter applied
        assert len(query.filters) == 0

    def test_public_only_filters_to_public(self):
        """Source: 'if is_public_only_token: query.filter(visibility == "public")'"""
        scope = AuthContext(
            user_email="u@t.com", is_admin=False, effective_teams=[],
            token_use="api", auth_method="bearer_token",
        ).to_query_scope()
        query = _MockQuery()
        result = scope.apply_visibility_filter(query, _FakeModel)
        assert result is query  # chainable
        assert len(query.filters) == 1
        # The filter should be a BinaryExpression comparing visibility == "public"
        clause = query.filters[0]
        assert str(clause.compile(compile_kwargs={"literal_binds": True})) == "visibility = 'public'"

    def test_team_scoped_filters_public_or_team(self):
        """Source: 'query.filter(or_(visibility == "public", team_id.in_(teams)))'"""
        scope = AuthContext(
            user_email="u@t.com", is_admin=False, effective_teams=["t1", "t2"],
            token_use="api", auth_method="bearer_token",
        ).to_query_scope()
        query = _MockQuery()
        result = scope.apply_visibility_filter(query, _FakeModel)
        assert result is query
        assert len(query.filters) == 1
        clause_str = str(query.filters[0].compile(compile_kwargs={"literal_binds": True}))
        assert "visibility = 'public'" in clause_str
        assert "team_id IN" in clause_str

    def test_is_public_boolean_fallback(self):
        """For models using is_public instead of visibility."""
        scope = AuthContext(
            user_email="u@t.com", is_admin=False, effective_teams=[],
            token_use="api", auth_method="bearer_token",
        ).to_query_scope()
        query = _MockQuery()
        result = scope.apply_visibility_filter(query, _FakeModelIsPublic)
        assert result is query
        assert len(query.filters) == 1
        clause_str = str(query.filters[0].compile(compile_kwargs={"literal_binds": True}))
        assert "is_public" in clause_str

    def test_no_visibility_column_returns_unfiltered(self):
        """Models with no visibility/is_public column pass through."""
        scope = AuthContext(
            user_email="u@t.com", is_admin=False, effective_teams=[],
            token_use="api", auth_method="bearer_token",
        ).to_query_scope()
        query = _MockQuery()
        result = scope.apply_visibility_filter(query, _FakeModelNoVisibility)
        assert result is query
        assert len(query.filters) == 0

    def test_admin_with_teams_still_filters(self):
        """Admin with explicit teams (not None) → still applies team filter.

        This is NOT admin bypass. Admin bypass requires teams=None.
        Source: normalize_token_teams — teams=["t1"] + is_admin=True → still scoped.
        """
        scope = AuthContext(
            user_email="admin@t.com", is_admin=True, effective_teams=["t1"],
            token_use="api", auth_method="bearer_token",
        ).to_query_scope()
        query = _MockQuery()
        result = scope.apply_visibility_filter(query, _FakeModel)
        assert len(query.filters) == 1  # filter applied, not bypassed


# ═══════════════════════════════════════════════════════════════════════
# 6. QueryScope.apply_ownership_filter
# ═══════════════════════════════════════════════════════════════════════


class _FakeModelWithOwner:
    """Model stub with owner_email column."""

    visibility = Column("visibility", String)
    team_id = Column("team_id", String)
    owner_email = Column("owner_email", String)


class TestQueryScopeOwnershipFilter:
    """Test ownership-based filtering."""

    def test_unrestricted_returns_query_unchanged(self):
        scope = AuthContext(
            user_email="admin@t.com", is_admin=True, effective_teams=None,
            token_use="api", auth_method="bearer_token",
        ).to_query_scope()
        query = _MockQuery()
        result = scope.apply_ownership_filter(query, _FakeModelWithOwner)
        assert len(query.filters) == 0

    def test_team_scoped_with_owner(self):
        """Team-scoped user sees own resources + team resources."""
        scope = AuthContext(
            user_email="dev@t.com", is_admin=False, effective_teams=["t1"],
            token_use="api", auth_method="bearer_token",
        ).to_query_scope()
        query = _MockQuery()
        scope.apply_ownership_filter(query, _FakeModelWithOwner)
        assert len(query.filters) == 1
        clause_str = str(query.filters[0].compile(compile_kwargs={"literal_binds": True}))
        assert "owner_email" in clause_str
        assert "team_id IN" in clause_str

    def test_no_owner_column_falls_back_to_visibility(self):
        """Models without owner_email use visibility filter."""
        scope = AuthContext(
            user_email="dev@t.com", is_admin=False, effective_teams=["t1"],
            token_use="api", auth_method="bearer_token",
        ).to_query_scope()
        query = _MockQuery()
        scope.apply_ownership_filter(query, _FakeModel)
        assert len(query.filters) == 1
        clause_str = str(query.filters[0].compile(compile_kwargs={"literal_binds": True}))
        assert "visibility" in clause_str


# ═══════════════════════════════════════════════════════════════════════
# 7. Auth method coverage
#    Source: Constraint 7 — four extraction paths + anonymous
# ═══════════════════════════════════════════════════════════════════════


class TestAuthMethodVariants:
    """Each auth_method value that AuthResolver will produce."""

    @pytest.mark.parametrize(
        "auth_method",
        ["bearer_token", "cookie", "api_token_hash", "proxy", "anonymous", "basic"],
    )
    def test_valid_auth_methods(self, auth_method):
        """All supported auth methods produce valid AuthContext."""
        ctx = _ctx(teams=[], is_admin=False, auth_method=auth_method)
        assert ctx.auth_method == auth_method

    def test_anonymous_defaults(self):
        """Anonymous auth → public-only, not admin, email may be None.

        Source: rbac.py anonymous path returns email="anonymous", is_admin=False.
        """
        ctx = _ctx(email=None, teams=[], is_admin=False, token_use="anonymous", auth_method="anonymous")
        assert ctx.is_public_only is True
        assert ctx.is_admin_bypass is False
        assert ctx.effective_is_admin() is False
        assert ctx.allows_admin_paths() is False


# ═══════════════════════════════════════════════════════════════════════
# 8. Session vs API token semantics
#    Source: _auth_jwt session/API branching (transport lines 2953-2974)
# ═══════════════════════════════════════════════════════════════════════


class TestSessionVsApiTokenSemantics:
    """Verify that token_use is correctly represented in AuthContext.

    The resolver (future) will:
    - session + admin → teams=None (bypass)
    - session + non-admin → teams from DB
    - session + no email → teams=[] (public-only)
    - api → teams from normalize_token_teams

    These tests verify the AuthContext correctly represents each case.
    """

    def test_session_admin_bypass(self):
        """Source: _auth_jwt line 2959 — if is_admin_flag: final_teams = None."""
        ctx = _ctx(teams=None, is_admin=True, token_use="session", auth_method="cookie")
        assert ctx.is_admin_bypass is True
        assert ctx.token_use == "session"

    def test_session_non_admin_team_scoped(self):
        """Source: _auth_jwt line 2963 — resolve from DB."""
        ctx = _ctx(teams=["t1", "t2"], is_admin=False, token_use="session", auth_method="cookie")
        assert ctx.is_admin_bypass is False
        assert ctx.effective_teams == ["t1", "t2"]

    def test_session_no_email_public_only(self):
        """Source: _auth_jwt line 2970 — no email → teams=[]."""
        ctx = _ctx(email=None, teams=[], is_admin=False, token_use="session", auth_method="cookie")
        assert ctx.is_public_only is True

    def test_api_token_uses_embedded_teams(self):
        """Source: _auth_jwt line 2974 — normalize_token_teams on payload."""
        ctx = _ctx(teams=["team-a"], is_admin=False, token_use="api", auth_method="bearer_token")
        assert ctx.effective_teams == ["team-a"]
        assert ctx.token_use == "api"


# ═══════════════════════════════════════════════════════════════════════
# 9. Inactive user handling
# ═══════════════════════════════════════════════════════════════════════


class TestInactiveUser:
    """Verify is_active flag is carried through.

    Source: _auth_jwt checks user_record.is_active and rejects if False.
    Source: AdminAuthMiddleware checks user is_active and rejects.
    AuthResolver will set is_active=False; middleware/transport rejects.
    """

    def test_inactive_user_flag_preserved(self):
        ctx = _ctx(teams=["t1"], is_admin=False, is_active=False)
        assert ctx.is_active is False

    def test_inactive_admin_flag_preserved(self):
        """Even admins can be deactivated."""
        ctx = _ctx(teams=None, is_admin=True, is_active=False)
        assert ctx.is_active is False
        # Still admin bypass by teams/is_admin rules — but carrier will reject
        assert ctx.is_admin_bypass is True


# ═══════════════════════════════════════════════════════════════════════
# 10. QueryScope immutability
# ═══════════════════════════════════════════════════════════════════════


class TestQueryScopeImmutability:
    """QueryScope must be frozen."""

    def test_cannot_mutate_teams(self):
        scope = _ctx(teams=["t1"], is_admin=False).to_query_scope()
        with pytest.raises(AttributeError):
            scope._effective_teams = None  # type: ignore[misc]

    def test_cannot_mutate_unrestricted(self):
        scope = _ctx(teams=["t1"], is_admin=False).to_query_scope()
        with pytest.raises(AttributeError):
            scope._is_unrestricted = True  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════
# 11. Cross-channel equivalence contract
#     The SAME token must produce the SAME AuthContext regardless of
#     whether it enters via HTTP or StreamableHTTP.
# ═══════════════════════════════════════════════════════════════════════


class TestCrossChannelEquivalence:
    """Prove that to_transport_dict round-trips correctly.

    When AuthResolver.resolve(request) produces an AuthContext, and that
    context is written to user_context_var via to_transport_dict(), the
    transport-side code must be able to reconstruct equivalent access
    decisions from the dict.
    """

    @pytest.mark.parametrize(
        "teams, is_admin, token_use",
        [
            (None, True, "session"),       # admin bypass
            (None, True, "api"),           # admin bypass via API token
            ([], False, "api"),            # public-only
            ([], True, "api"),             # public-only admin (override)
            (["t1"], False, "api"),        # single team
            (["t1", "t2"], False, "session"),  # multi-team session
        ],
        ids=[
            "admin-session-bypass",
            "admin-api-bypass",
            "public-only",
            "public-only-admin",
            "single-team",
            "multi-team-session",
        ],
    )
    def test_transport_dict_preserves_access_decisions(self, teams, is_admin, token_use):
        """The transport dict must carry enough info for equivalent access decisions."""
        ctx = _ctx(teams=teams, is_admin=is_admin, token_use=token_use)
        d = ctx.to_transport_dict()

        # Reconstruct access decisions from the dict (what transport code does)
        dict_teams = d["teams"]
        dict_is_admin = d["is_admin"]

        # Admin bypass: teams is None AND is_admin
        dict_bypass = dict_teams is None and dict_is_admin
        assert dict_bypass == ctx.is_admin_bypass

        # Public-only: teams is not None and empty
        dict_public = dict_teams is not None and len(dict_teams) == 0
        assert dict_public == ctx.is_public_only

        # Effective is_admin (with public-only override)
        dict_eff_admin = dict_is_admin and not dict_public
        assert dict_eff_admin == ctx.effective_is_admin()


# ═══════════════════════════════════════════════════════════════════════
# 12. PermissionService public-only guard
#     Source: permission_service.py lines 122-126
# ═══════════════════════════════════════════════════════════════════════


class TestPermissionServiceInvariant:
    """Public-only tokens must NEVER satisfy admin.* permissions.

    Source: permission_service.py:
        if permission.startswith("admin.") and token_teams is not None and len(token_teams) == 0:
            return False

    AuthContext encodes this: is_public_only=True → effective_is_admin()=False.
    """

    def test_public_only_token_cannot_have_admin_permissions(self):
        ctx = _ctx(teams=[], is_admin=True)
        # The permission service check is: if public-only, deny admin.* perms
        # AuthContext equivalent: effective_is_admin() is False
        assert ctx.effective_is_admin() is False
        assert ctx.is_public_only is True

    def test_team_scoped_admin_can_have_admin_permissions(self):
        ctx = _ctx(teams=["t1"], is_admin=True)
        assert ctx.effective_is_admin() is True
        assert ctx.is_public_only is False
