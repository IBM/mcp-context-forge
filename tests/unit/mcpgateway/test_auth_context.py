# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth_context.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the centralized Layer-1 visibility helpers in ``mcpgateway.auth_context``.

``get_scoped_resource_access_context`` is the single derivation point for the Layer-1
admin-bypass + public-only-secure-default rule that route handlers in ``main.py`` used to
copy inline. Endpoint tests mock this helper and assert only that the handler forwards its
result, so the rule itself is pinned here.

Contract under test:

- ``(email, None)``  - admin bypass. ``user_email`` is deliberately preserved so the service
  layer can still owner-match the admin's own private rows.
- ``(email, [])``    - public-only token (also the secure default for non-admins).
- ``(email, [...])`` - team-scoped token, passed through unchanged.
"""

# Standard
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway import auth_context
from mcpgateway.auth_context import get_request_identity, get_rpc_filter_context, get_scoped_resource_access_context


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
        """Admin bypass must keep user_email for owner matching, not null it.

        Nulling the email hands the service ``(None, None)``, which resolves to "public +
        team, but no private rows at all" - silently hiding the admin's own private
        resources. This is the regression the inline copies kept reintroducing.
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

        _user_email, token_teams = get_scoped_resource_access_context(request, {"email": "admin@example.com", "is_admin": True})

        assert token_teams == ["team-a"]

    def test_admin_with_public_only_token_is_not_widened(self):
        """An explicit empty team scope means public-only, even for an admin."""
        request = _request(jwt_payload={"is_admin": True, "teams": []}, token_teams=[])

        _user_email, token_teams = get_scoped_resource_access_context(request, {"email": "admin@example.com", "is_admin": True})

        assert token_teams == []

    def test_basic_auth_admin_gets_bypass(self):
        """Non-JWT (basic-auth / dev-mode) admins get Layer-1 admin bypass.

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


class TestRequestScopedMemoization:
    """The derived triple is cached per request, per principal.

    Handlers that need both the visibility scope and the requester identity call
    ``get_scoped_resource_access_context`` and ``get_request_identity`` back to back.
    Both derive through ``get_rpc_filter_context``, which can issue a live ``EmailUser``
    lookup for session tokens, so without memoization those handlers pay it twice.
    """

    @staticmethod
    def _counting_teams_reader(monkeypatch):
        """Count how many times a full derivation runs.

        ``get_token_teams_from_request`` is called exactly once per uncached derivation,
        which makes it a faithful proxy for "how many times did we derive".

        Args:
            monkeypatch: Fixture used to install the counting wrapper.

        Returns:
            A single-element list whose value is the derivation count.
        """
        calls = []
        real = auth_context.get_token_teams_from_request

        def counting(request):
            calls.append(1)
            return real(request)

        monkeypatch.setattr(auth_context, "get_token_teams_from_request", counting)
        return calls

    def test_scope_and_identity_derive_once_for_same_user(self, monkeypatch):
        """Asking for the scope and then the identity costs one derivation, not two."""
        calls = self._counting_teams_reader(monkeypatch)
        request = _request(jwt_payload={"is_admin": True, "teams": None}, token_teams=None)
        user = {"email": "admin@example.com", "is_admin": True}

        scope = get_scoped_resource_access_context(request, user)
        identity = get_request_identity(request, user)

        assert len(calls) == 1
        assert scope == ("admin@example.com", None)
        assert identity == ("admin@example.com", True)

    def test_repeated_calls_reuse_the_cached_triple(self, monkeypatch):
        """Repeated derivations for the same principal on one request stay at one."""
        calls = self._counting_teams_reader(monkeypatch)
        request = _request(jwt_payload={"is_admin": False, "teams": ["team-a"]}, token_teams=["team-a"])
        user = {"email": "member@example.com"}

        first = get_rpc_filter_context(request, user)
        second = get_rpc_filter_context(request, user)

        assert len(calls) == 1
        assert first == second

    def test_a_different_principal_is_not_served_from_cache(self, monkeypatch):
        """A second principal on the same request derives separately.

        Trusted internal A2A dispatch builds a synthetic forwarded user and derives with it
        on a request that may already have derived for the real caller. Keying the cache on
        the request alone would hand the synthetic user the real caller's context.
        """
        calls = self._counting_teams_reader(monkeypatch)
        request = _request(jwt_payload={"is_admin": False, "teams": ["team-a"]}, token_teams=["team-a"])

        real_caller = get_rpc_filter_context(request, {"email": "caller@example.com"})
        forwarded = get_rpc_filter_context(request, {"email": "forwarded@example.com"})

        assert len(calls) == 2
        assert real_caller[0] == "caller@example.com"
        assert forwarded[0] == "forwarded@example.com"
