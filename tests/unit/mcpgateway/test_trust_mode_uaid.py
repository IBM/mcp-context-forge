# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_trust_mode_uaid.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

UAID propagation acceptance suite for JWT trust mode (issue #5905, suite d).

Trust-mode claims propagate cross-gateway as forwarded bearer tokens per the
existing UAID rules (docs/security/uaid-cross-gateway-auth.md, Layer 2):

- A trust-mode token (``token_use="trusted"``) is JWT-shaped, so the calling
  gateway forwards it verbatim in the ``Authorization`` header when
  ``UAID_FORWARD_AUTH`` is on.
- Local opaque tokens (``cf_sess_*``, ``cf_pat_*``) are never forwarded, in
  either mode.
- ``UAID_ALLOWED_DOMAINS`` keeps its fail-closed semantics with trust mode
  ON: an empty allowlist blocks all routing; an unlisted domain is blocked.

The remote gateway side of the forwarded call (re-evaluation against the
remote's own ``external_group_mappings``) is covered by suite (f) in
``test_trust_mode_cross_gateway.py``.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import jwt as pyjwt
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.a2a_service import _validate_uaid_endpoint_domain, A2AAgentError, A2AAgentService

# Local
from tests.helpers.auth import make_trusted_test_jwt

CALLER_ID = "trust-uaid-subject-0001"
CALLER_EMAIL = "uaid.trust.user@example.com"
UAID = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"


@pytest.fixture(autouse=True)
def trust_mode_on(monkeypatch):
    """Run every test in this suite with trust mode ON and the bypass OFF."""
    monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
    monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allow_all_domains", False)


@pytest.fixture
def service():
    """Create an A2AAgentService instance."""
    return A2AAgentService()


class TestAllowlistUnchangedInTrustMode:
    """UAID_ALLOWED_DOMAINS fail-closed semantics are unchanged in trust mode."""

    def test_empty_allowlist_fail_closed(self, monkeypatch):
        """Empty allowlist blocks routing even with trust mode ON."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allowed_domains", [])
        with pytest.raises(ValueError, match="UAID_ALLOWED_DOMAINS is empty"):
            _validate_uaid_endpoint_domain("http://external.example.com/api", "cross-gateway routing")

    def test_unlisted_domain_blocked(self, monkeypatch):
        """A domain outside the allowlist is blocked with trust mode ON."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allowed_domains", ["trusted.example.com"])
        with pytest.raises(ValueError, match="not in UAID_ALLOWED_DOMAINS"):
            _validate_uaid_endpoint_domain("http://untrusted.example.net/api", "cross-gateway routing")

    def test_allowlisted_domain_passes(self, monkeypatch):
        """An allowlisted domain passes validation with trust mode ON."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allowed_domains", ["example.com"])
        _validate_uaid_endpoint_domain("http://agent.example.com/api", "cross-gateway routing")

    async def test_invoke_remote_agent_blocked_fail_closed(self, service, monkeypatch):
        """The routing path enforces the same fail-closed gate in trust mode."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allowed_domains", [])
        token = make_trusted_test_jwt(CALLER_ID, email=CALLER_EMAIL, teams=[], roles=[])
        with pytest.raises(A2AAgentError, match="UAID_ALLOWED_DOMAINS is empty"):
            await service._invoke_remote_agent(uaid=UAID, parameters={"q": "test"}, bearer_token=token)


class TestTrustTokenBearerForwarding:
    """A trust-mode token forwards verbatim per the existing UAID rules."""

    @staticmethod
    def _mock_http_client(monkeypatch, captured: dict) -> None:
        """Capture the outbound cross-gateway request; answer 200."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "ok"}'
        mock_response.json.return_value = {"result": "ok"}
        mock_response.text = '{"result": "ok"}'

        mock_client = MagicMock()

        async def _post(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return mock_response

        mock_client.post = AsyncMock(side_effect=_post)

        async def _get_http_client():
            return mock_client

        monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", _get_http_client)
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allowed_domains", ["example.com"])

    async def test_trust_token_forwarded_verbatim(self, service, monkeypatch):
        """The forwarded bearer token is the caller's inbound trust JWT.

        Decoding the forwarded header shows the original claims intact:
        ``sub``, ``token_use=="trusted"``, the groups claim, and the
        revocation claim. The remote gateway re-evaluates them (suite f).
        """
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_forward_auth", True)
        captured: dict = {}
        self._mock_http_client(monkeypatch, captured)

        token = make_trusted_test_jwt(CALLER_ID, email=CALLER_EMAIL, groups=["ext-group-1"], roles=[], revocation_id="uaid-forward-jti-0001")

        result = await service._invoke_remote_agent(
            uaid=UAID,
            parameters={"q": "test"},
            user_id=CALLER_ID,
            user_email=CALLER_EMAIL,
            bearer_token=token,
        )

        assert result == {"result": "ok"}
        headers = captured.get("headers", {})
        assert headers.get("Authorization") == f"Bearer {token}"

        # The forwarded token carries the original claims unchanged.
        secret = settings.jwt_secret_key
        if hasattr(secret, "get_secret_value"):
            secret = secret.get_secret_value()
        forwarded = headers["Authorization"].removeprefix("Bearer ")
        claims = pyjwt.decode(forwarded, secret, algorithms=[settings.jwt_algorithm], options={"verify_aud": False})
        assert claims["sub"] == CALLER_ID
        assert claims["token_use"] == "trusted"
        assert claims["groups"] == ["ext-group-1"]
        assert claims["jti"] == "uaid-forward-jti-0001"

    async def test_opaque_token_not_forwarded(self, service, monkeypatch):
        """Local opaque tokens are never forwarded, in either mode."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_forward_auth", True)
        captured: dict = {}
        self._mock_http_client(monkeypatch, captured)

        result = await service._invoke_remote_agent(
            uaid=UAID,
            parameters={"q": "test"},
            user_id=CALLER_ID,
            user_email=CALLER_EMAIL,
            bearer_token="cf_sess_opaque_local_token",  # pragma: allowlist secret
        )

        assert result == {"result": "ok"}
        assert "Authorization" not in captured.get("headers", {})

    async def test_forward_auth_disabled_not_forwarded(self, service, monkeypatch):
        """UAID_FORWARD_AUTH=false suppresses forwarding of the trust token."""
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_forward_auth", False)
        captured: dict = {}
        self._mock_http_client(monkeypatch, captured)

        token = make_trusted_test_jwt(CALLER_ID, email=CALLER_EMAIL, teams=[], roles=[])

        result = await service._invoke_remote_agent(
            uaid=UAID,
            parameters={"q": "test"},
            user_id=CALLER_ID,
            user_email=CALLER_EMAIL,
            bearer_token=token,
        )

        assert result == {"result": "ok"}
        assert "Authorization" not in captured.get("headers", {})
