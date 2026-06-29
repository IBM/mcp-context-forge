# -*- coding: utf-8 -*-
"""Cross-environment token isolation config tests (GHSA-vgf8-3685-66j9)."""

# First-Party
from mcpgateway.config import Settings


def test_derive_key_per_environment_defaults_off():
    assert Settings().derive_key_per_environment is False


def test_environment_isolation_defaults_on():
    s = Settings()
    assert s.embed_environment_in_tokens is True
    assert s.validate_token_environment is True


def _has(warnings, needle="indistinguishable"):
    return any(needle in w.lower() for w in warnings)


def test_warns_when_hs_indistinguishable():
    s = Settings(environment="development", jwt_algorithm="HS256", jwt_audience="mcpgateway-api", jwt_issuer="mcpgateway", derive_key_per_environment=False)
    assert _has(s.get_security_warnings())


def test_no_warning_when_audience_distinct():
    s = Settings(environment="development", jwt_algorithm="HS256", jwt_audience="mcpgateway-api-dev", jwt_issuer="mcpgateway", derive_key_per_environment=False)
    assert not _has(s.get_security_warnings())


def test_no_indistinguishable_warning_when_derivation_enabled():
    s = Settings(environment="development", jwt_algorithm="HS256", jwt_audience="mcpgateway-api", jwt_issuer="mcpgateway", derive_key_per_environment=True)
    assert not _has(s.get_security_warnings())


def test_warns_when_derivation_on_default_environment():
    """Derivation enabled but ENVIRONMENT is still the default 'development'."""
    s = Settings(environment="development", jwt_algorithm="HS256", jwt_audience="mcpgateway-api", jwt_issuer="mcpgateway", derive_key_per_environment=True)
    assert _has(s.get_security_warnings(), needle="environment='development'")


def test_no_default_env_warning_when_derivation_on_distinct_environment():
    """Derivation enabled with non-default ENVIRONMENT — no default-env warning."""
    s = Settings(
        environment="staging",
        jwt_algorithm="HS256",
        jwt_secret_key="a-strong-test-secret-key-for-staging-32ch",  # pragma: allowlist secret
        auth_encryption_secret="a-strong-test-encryption-secret-32chars",  # pragma: allowlist secret
        basic_auth_password="Str0ng!StagingP@ssw0rd#2026",  # pragma: allowlist secret
        jwt_audience="mcpgateway-api",
        jwt_issuer="mcpgateway",
        derive_key_per_environment=True,
    )
    assert not _has(s.get_security_warnings(), needle="environment='development'")


def test_warns_when_asymmetric_keys_default():
    s = Settings(environment="development", jwt_algorithm="RS256", jwt_public_key_path="", jwt_private_key_path="")
    assert _has(s.get_security_warnings())
