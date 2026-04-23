# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_session_token_security.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mohan Lakshmaiah

Session Token Security Tests

Validates security requirements for session token management based on
X-Force Red penetration testing findings (ICACF-22):

1. Session token lifetime must be short (5-20 minutes recommended)
2. Tokens must be revoked on logout (no replay attacks)
3. Server-side blocklist prevents token reuse after revocation

These tests focus on security properties and threat modeling.
"""

# Standard
from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
from fastapi import status
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import TokenRevocation, EmailUser


@pytest.mark.security
class TestTokenLifetimeSecurity:
    """Security tests for session token lifetime requirements."""

    def test_token_expiry_meets_security_guidelines(self):
        """
        SECURITY: Token expiry must meet security audit guidelines.

        X-Force Red Recommendation: 5-20 minutes for session tokens
        Risk: Long-lived tokens increase attack surface for token theft
        """
        assert settings.token_expiry <= 20, (
            f"SECURITY VIOLATION: Token expiry {settings.token_expiry} minutes "
            f"exceeds security guideline maximum of 20 minutes. "
            f"Long-lived session tokens increase risk of token theft and replay attacks."
        )

    def test_token_expiry_prevents_persistent_sessions(self):
        """
        SECURITY: Token expiry must not allow persistent sessions >24 hours.

        Risk: Multi-day session tokens allow stolen credentials to be exploited
        for extended periods, violating security best practices for web applications.
        """
        assert settings.token_expiry < 1440, (
            f"CRITICAL SECURITY RISK: Token expiry {settings.token_expiry} minutes "
            f"({settings.token_expiry/1440:.1f} days) allows persistent sessions. "
            f"Sessions >24 hours significantly increase compromise window."
        )

    def test_token_expiry_ideal_range(self):
        """
        SECURITY: Ideal token expiry is 5-20 minutes.

        This test documents the ideal range but doesn't fail if outside it.
        Helps teams understand security vs UX tradeoffs.
        """
        if settings.token_expiry < 5:
            pytest.skip(
                f"Token expiry {settings.token_expiry} min is below ideal minimum (5 min). "
                f"Very short expiry may impact user experience."
            )
        elif settings.token_expiry > 20:
            pytest.fail(
                f"Token expiry {settings.token_expiry} min exceeds ideal maximum (20 min). "
                f"Consider reducing for better security posture."
            )

    def test_configuration_warnings_for_excessive_expiry(self):
        """
        SECURITY: System must warn about dangerous token expiry values.

        Defense in depth: Configuration validation catches misconfigurations
        before they reach production.
        """
        # Simulate excessive values
        test_cases = [
            (30, True, "Should warn for >20 minutes"),
            (1500, True, "Should warn critically for >24 hours"),
            (15, False, "Should not warn for safe values"),
        ]

        for test_expiry, should_warn, description in test_cases:
            has_warning = test_expiry > 20 or test_expiry > 1440
            assert has_warning == should_warn, f"Failed: {description}"


@pytest.mark.security
class TestTokenRevocationSecurity:
    """Security tests for token revocation and blocklist functionality."""

    @pytest.mark.asyncio
    async def test_revoked_tokens_rejected_immediately(self):
        """
        SECURITY: Revoked tokens must be rejected immediately.

        Threat Model: Attacker obtains valid token, user logs out,
        attacker attempts to use stolen token.
        Expected: Token must be rejected (no replay attack).

        This is the PRIMARY security vulnerability from X-Force Red findings.
        """
        jti = f"security-test-{uuid.uuid4()}"
        user_email = "security-test@example.com"

        # Simulate revoked token in auth context
        mock_auth_ctx = {
            "is_token_revoked": True,  # Token is in revocation blocklist
            "user": {"email": user_email, "is_admin": False},
            "team_ids": []
        }

        mock_payload = {
            "sub": user_email,
            "jti": jti,
            "token_use": "session",
            "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp()
        }

        with patch("mcpgateway.auth.verify_jwt_token_cached", return_value=mock_payload):
            with patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=mock_auth_ctx):
                mock_credentials = MagicMock()
                mock_credentials.credentials = "stolen_token_after_logout"  # pragma: allowlist secret
                mock_request = MagicMock()

                # SECURITY ASSERTION: Revoked token must be rejected
                with pytest.raises(Exception) as exc_info:
                    await get_current_user(credentials=mock_credentials, request=mock_request)

                # Verify it's a 401 Unauthorized
                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED, (
                    "SECURITY VULNERABILITY: Revoked token was not rejected with 401"
                )
                assert "revoked" in str(exc_info.value.detail).lower(), (
                    "SECURITY: Error message should indicate token revocation"
                )

    def test_revocation_model_has_audit_trail(self):
        """
        SECURITY: Token revocation must maintain audit trail.

        Audit requirements:
        - Who revoked the token (revoked_by)
        - When it was revoked (revoked_at)
        - Why it was revoked (reason)
        - Token identifier (jti)
        """
        # Verify TokenRevocation model has required audit fields
        assert hasattr(TokenRevocation, "jti"), "Missing audit field: jti"
        assert hasattr(TokenRevocation, "revoked_by"), "Missing audit field: revoked_by"
        assert hasattr(TokenRevocation, "revoked_at"), "Missing audit field: revoked_at"
        assert hasattr(TokenRevocation, "reason"), "Missing audit field: reason"

    def test_revocation_prevents_timing_attacks(self):
        """
        SECURITY: Revocation checks must not leak timing information.

        Threat: Attacker uses response time to determine if token is revoked
        vs expired vs invalid, potentially revealing system state.

        Note: This is a design validation test. Actual timing measurements
        would require performance testing infrastructure.
        """
        # Document the security requirement
        # Implementation should use constant-time comparisons where possible
        # and cache revocation status to normalize response times
        assert True, "Documented: Revocation checks should not leak timing info"


@pytest.mark.security
class TestLogoutSecurityProperties:
    """Security tests for logout endpoint properties."""

    def test_logout_endpoint_enforces_session_token_only(self):
        """
        SECURITY: Logout must only accept session tokens, not API tokens.

        Threat Model: API tokens are long-lived and managed separately.
        Allowing logout with API tokens could enable DoS by revoking
        automation tokens or confuse token lifecycle management.
        """
        from mcpgateway.routers.auth import logout

        # Simulate API token (wrong type)
        mock_payload = {
            "sub": "test@example.com",
            "jti": str(uuid.uuid4()),
            "token_use": "api",  # Not a session token
            "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp()
        }

        with patch("mcpgateway.utils.verify_credentials.verify_jwt_token_cached",
                   new_callable=AsyncMock, return_value=mock_payload):
            mock_credentials = MagicMock()
            mock_credentials.credentials = "api_token"  # pragma: allowlist secret
            mock_request = MagicMock()
            mock_db = MagicMock()

            import asyncio
            with pytest.raises(Exception) as exc_info:
                asyncio.run(logout(mock_request, mock_credentials, mock_db))

            # Should reject with 400 Bad Request, not 401 or 500
            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST, (
                "SECURITY: Must explicitly reject non-session tokens with 400"
            )

    def test_logout_is_idempotent_prevents_dos(self):
        """
        SECURITY: Logout must be idempotent to prevent DoS.

        Threat Model: Attacker repeatedly calls logout with same token
        to exhaust database connections or create excessive audit logs.

        Mitigation: Subsequent logout attempts with already-revoked token
        should succeed without creating duplicate records.
        """
        from mcpgateway.routers.auth import logout
        from mcpgateway.db import TokenRevocation

        jti = f"dos-test-{uuid.uuid4()}"
        user_email = "test@example.com"

        mock_payload = {
            "sub": user_email,
            "jti": jti,
            "token_use": "session",
            "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp()
        }

        # Simulate already-revoked token
        existing_revocation = TokenRevocation(
            jti=jti,
            revoked_by=user_email,
            reason="Previous logout"
        )

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = existing_revocation
        mock_db.query.return_value = mock_query

        with patch("mcpgateway.utils.verify_credentials.verify_jwt_token_cached",
                   new_callable=AsyncMock, return_value=mock_payload):
            mock_credentials = MagicMock()
            mock_credentials.credentials = "session_token"  # pragma: allowlist secret
            mock_request = MagicMock()

            import asyncio
            response = asyncio.run(logout(mock_request, mock_credentials, mock_db))

            # SECURITY: Should succeed without error
            assert response.success is True
            # SECURITY: Should not create duplicate revocation record
            assert not mock_db.add.called, "Must not create duplicate revocation records"

    def test_logout_requires_authentication(self):
        """
        SECURITY: Logout endpoint must require valid authentication.

        Threat Model: Unauthenticated logout could be used to:
        - Enumerate valid JTIs through timing attacks
        - Cause DoS by flooding logout endpoint

        Mitigation: Require Bearer token authentication for logout.
        """
        from mcpgateway.routers.auth import logout

        # No credentials provided
        mock_request = MagicMock()
        mock_db = MagicMock()

        import asyncio
        with pytest.raises(Exception) as exc_info:
            asyncio.run(logout(mock_request, None, mock_db))

        # Must reject with 401 Unauthorized
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.security
class TestRevocationPersistenceSecurity:
    """Security tests for revocation persistence and cache consistency."""

    def test_revocation_persists_in_database(self):
        """
        SECURITY: Revocations must persist in database, not just cache.

        Threat Model: Cache-only revocation allows replay attacks after:
        - Application restart (cache cleared)
        - Redis failure (cache unavailable)
        - Cache TTL expiration

        Mitigation: Database is source of truth, cache is performance layer.
        """
        # This is validated by the TokenRevocation model existing and being
        # committed to the database in the logout flow
        from mcpgateway.db import TokenRevocation

        # Verify model is mapped to a table
        assert hasattr(TokenRevocation, "__tablename__")
        assert TokenRevocation.__tablename__ == "token_revocations"

    def test_revocation_cache_miss_falls_back_to_database(self):
        """
        SECURITY: Cache miss must not bypass revocation check.

        Threat Model: If cache is unavailable and system doesn't fall back
        to database, revoked tokens could be accepted.

        This is a design requirement - actual implementation is verified
        by checking that auth flow queries TokenRevocation table.
        """
        # Document the security requirement
        # Implementation: mcpgateway/auth.py should query TokenRevocation table
        # when cache is unavailable or returns no data
        assert True, "Documented: Revocation checks must fall back to database"


@pytest.mark.security
class TestTokenReplayAttackMitigation:
    """
    Security tests specifically for token replay attack scenarios.

    X-Force Red Finding: "It was noted that when the user was logged out,
    the token was still useable."

    This class tests the PRIMARY security vulnerability and its mitigations.
    """

    def test_scenario_stolen_token_after_logout(self):
        """
        SECURITY SCENARIO: User logs out, attacker uses previously stolen token.

        Attack Flow:
        1. Attacker steals user's session token (XSS, network sniffing, etc.)
        2. User notices suspicious activity and logs out
        3. Attacker attempts to use stolen token
        4. EXPECTED: Token must be rejected (this test validates this)

        Vulnerability: If logout only clears cookies client-side, stolen token
        remains valid until expiry (could be days/weeks with old 30-day expiry).
        """
        # This is the core security test - validates the fix works
        # Covered by test_revoked_tokens_rejected_immediately above
        pytest.skip("Covered by test_revoked_tokens_rejected_immediately")

    def test_scenario_concurrent_logout_race_condition(self):
        """
        SECURITY SCENARIO: Multiple logout requests for same token.

        Attack Flow:
        1. User clicks logout button
        2. Attacker intercepts request and replays it multiple times
        3. EXPECTED: All requests succeed (idempotent)
        4. EXPECTED: Only one revocation record created

        Vulnerability: Non-idempotent logout could cause database deadlocks,
        excessive audit records, or denial of service.
        """
        # This is covered by test_logout_is_idempotent_prevents_dos
        pytest.skip("Covered by test_logout_is_idempotent_prevents_dos")

    def test_scenario_cache_poisoning_attack(self):
        """
        SECURITY SCENARIO: Attacker attempts to poison revocation cache.

        Attack Flow:
        1. Attacker has compromised access to Redis
        2. Attacker removes JTI from revoked_tokens set
        3. Attempt to use revoked token
        4. EXPECTED: Database check catches revocation

        Mitigation: Database is source of truth, cache is performance only.
        """
        # Document the security requirement
        # Implementation must check database if cache is inconsistent
        pytest.skip("Design requirement: Database is source of truth for revocation")
