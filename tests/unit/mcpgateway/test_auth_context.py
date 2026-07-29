# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth_context.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the centralized Layer-1 visibility helpers in ``mcpgateway.auth_context``.

``get_scoped_resource_access_context`` is the single derivation point for the Layer-1
admin-bypass + public-only-secure-default rule that route handlers in ``main.py`` used to
copy inline (issue #4451). These tests pin the rule itself, so endpoint tests are free to
mock the helper and assert only that the handler passes the context through verbatim.

Contract under test:

- ``(email, None)``  - admin bypass. ``user_email`` is deliberately preserved so the service
  layer can still owner-match the admin's own private rows (PR #4341 / issue #4694).
- ``(email, [])``    - public-only token (also the secure default for non-admins).
- ``(email, [...])`` - team-scoped token, passed through unchanged.
"""

# Standard
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.auth_context import get_rpc_filter_context, get_scoped_resource_access_context


def _request(*, jwt_payload=None, token_teams=None, token_use=None):
    """Build a request stub with the auth state the Layer-1 helpers read.

    Args:
        jwt_payload: Value cached at ``request.state._jwt_verified_payload[1]``. ``None``
            simulates a non-JWT context (basic-auth / dev-mode).
        token_teams: Value cached at ``request.state.token_teams``.
        token_use: Value cached at ``request.state.token_use``.

    Returns:
        A ``MagicMock`` request whose ``state`` exposes the attributes above.
    """
    request = MagicMock()
    request.state = MagicMock()
    request.state._jwt_verified_payload = ("token", jwt_payload) if jwt_payload is not None else None
    request.state.token_teams = token_teams
    request.state.token_use = token_use
    request.state.internal_auth_context = None
    return request


class TestScopedResourceAccessContext:
    """Layer-1 rule applied by ``get_scoped_resource_access_context``."""

    def test_jwt_admin_bypass_preserves_email(self):
        """Issue #4694: admin bypass must keep user_email for owner matching, not null it.

        Nulling the email would hand the service ``(None, None)``, which resolves to
        "public + team, but no private rows at all" - silently hiding the admin's own
        private resources. This is the regression the inline copies kept reintroducing.
        """
        request = _request(jwt_payload={"is_admin": True, "teams": None}, token_teams=None)

        user_email, token_teams = get_scoped_resource_access_context(request, {"email": "admin@example.com", "is_admin": True})

        assert user_email == "admin@example.com"
        assert token_teams is None

    def test_non_admin_without_teams_defaults_to_public_only(self):
        """Secure default: a non-admin with no team scope sees public rows only."""
        request = _request(jwt_payload={"is_admin": False, "teams": None}, token_teams=None)

        user_email, token_teams = get_scoped_resource_access_context(request, {"email": "viewer@example.com"})

        assert user_email == "viewer@example.com"
        assert token_teams == []

    def test_team_scoped_token_passes_through(self):
        """An explicit team scope is forwarded unchanged."""
        request = _request(jwt_payload={"is_admin": False, "teams": ["team-a"]}, token_teams=["team-a"])

        user_email, token_teams = get_scoped_resource_access_context(request, {"email": "member@example.com"})

        assert user_email == "member@example.com"
        assert token_teams == ["team-a"]

    def test_admin_with_explicit_team_scope_is_not_widened(self):
        """Least privilege: an admin token carrying an explicit team scope keeps that scope."""
        request = _request(jwt_payload={"is_admin": True, "teams": ["team-a"]}, token_teams=["team-a"])

        user_email, token_teams = get_scoped_resource_access_context(request, {"email": "admin@example.com", "is_admin": True})

        assert token_teams == ["team-a"]

    def test_admin_with_public_only_token_is_not_widened(self):
        """An explicit empty team scope means public-only, even for an admin."""
        request = _request(jwt_payload={"is_admin": True, "teams": []}, token_teams=[])

        user_email, token_teams = get_scoped_resource_access_context(request, {"email": "admin@example.com", "is_admin": True})

        assert token_teams == []

    def test_basic_auth_admin_gets_bypass(self):
        """Issue #4451: non-JWT (basic-auth / dev-mode) admins get Layer-1 admin bypass.

        The superseded inline derivation only consulted the JWT ``is_admin`` claim, so an
        admin authenticating without a JWT was silently narrowed to public-only.
        """
        request = _request(jwt_payload=None, token_teams=None)

        user_email, token_teams = get_scoped_resource_access_context(request, {"email": "admin@example.com", "is_admin": True})

        assert user_email == "admin@example.com"
        assert token_teams is None

    def test_basic_auth_non_admin_stays_public_only(self):
        """The secure default still applies to non-admins in non-JWT contexts."""
        request = _request(jwt_payload=None, token_teams=None)

        user_email, token_teams = get_scoped_resource_access_context(request, {"email": "user@example.com", "is_admin": False})

        assert user_email == "user@example.com"
        assert token_teams == []

    def test_returns_two_tuple(self):
        """The helper's contract is a 2-tuple; callers must not unpack an is_admin flag."""
        request = _request(jwt_payload={"is_admin": False, "teams": []}, token_teams=[])

        result = get_scoped_resource_access_context(request, {"email": "user@example.com"})

        assert isinstance(result, tuple)
        assert len(result) == 2


class TestMalformedJwtPayload:
    """A malformed cached JWT payload must not crash Layer-1 derivation."""

    @pytest.mark.parametrize("payload", ["not-a-dict", 42, ["teams"]])
    def test_non_dict_payload_defers_to_rbac(self, payload):
        """A non-dict payload carries no usable admin claim, so treat the caller as non-admin.

        Route handlers reach this through ``get_scoped_resource_access_context``; raising here
        would surface as a JSON-RPC -32603 Internal error instead of a normal RBAC decision.
        """
        request = _request(jwt_payload=payload, token_teams=None)

        user_email, token_teams = get_scoped_resource_access_context(request, {"email": "user@example.com"})

        assert user_email == "user@example.com"
        assert token_teams == []

    def test_non_dict_payload_reports_non_admin(self):
        """The lower-level helper reports is_admin=False rather than raising."""
        request = _request(jwt_payload="not-a-dict", token_teams=None)

        _email, _teams, is_admin = get_rpc_filter_context(request, {"email": "user@example.com"})

        assert is_admin is False
