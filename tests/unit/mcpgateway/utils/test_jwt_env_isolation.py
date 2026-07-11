# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_jwt_env_isolation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Per-environment JWT key derivation tests (GHSA-vgf8-3685-66j9).
"""

# Standard
import asyncio

# Third-Party
import jwt as pyjwt
import pytest

# First-Party
import mcpgateway.utils.jwt_config_helper as jch
import mcpgateway.utils.verify_credentials as vc
from mcpgateway.utils import create_jwt_token as cjt
from mcpgateway.utils.jwt_config_helper import JWTConfigurationError, _derive_env_key

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches():
    jch.clear_jwt_caches()
    yield
    jch.clear_jwt_caches()


def _set(monkeypatch, **kw):
    from pydantic import SecretStr

    for k, v in kw.items():
        monkeypatch.setattr(jch.settings, k, SecretStr(v) if k == "jwt_secret_key" else v)


# ---------------------------------------------------------------------------
# Task 2: _derive_env_key tests
# ---------------------------------------------------------------------------


def test_derive_env_key_is_deterministic():
    assert _derive_env_key("base-secret", "production") == _derive_env_key("base-secret", "production")


def test_derive_env_key_differs_per_environment():
    assert _derive_env_key("base-secret", "development") != _derive_env_key("base-secret", "production")


def test_derive_env_key_differs_per_base_secret():
    assert _derive_env_key("secret-one", "production") != _derive_env_key("secret-two", "production")


def test_derive_env_key_is_hex_sha256():
    k = _derive_env_key("base-secret", "production")
    assert len(k) == 64
    int(k, 16)


def test_derive_env_key_rejects_empty_secret():
    with pytest.raises(JWTConfigurationError):
        _derive_env_key("", "production")


def test_derive_env_key_handles_unicode_environment():
    assert _derive_env_key("base-secret", "préprod") != _derive_env_key("base-secret", "production")


def test_derive_env_key_handles_long_secret():
    long_secret = "s" * 4096
    k1 = _derive_env_key(long_secret, "production")
    k2 = _derive_env_key(long_secret, "production")
    assert k1 == k2
    assert len(k1) == 64


# ---------------------------------------------------------------------------
# Task 3: key getter tests
# ---------------------------------------------------------------------------


def test_resolved_key_raw_when_off(monkeypatch):
    _set(monkeypatch, jwt_algorithm="HS256", jwt_secret_key="base-secret", derive_key_per_environment=False, environment="production")
    assert jch.get_jwt_private_key_or_secret() == "base-secret"
    assert jch.get_jwt_public_key_or_secret() == "base-secret"


def test_resolved_key_derived_when_on(monkeypatch):
    _set(monkeypatch, jwt_algorithm="HS256", jwt_secret_key="base-secret", derive_key_per_environment=True, environment="production")
    expected = jch._derive_env_key("base-secret", "production")
    assert jch.get_jwt_private_key_or_secret() == expected
    assert jch.get_jwt_public_key_or_secret() == expected


def test_derived_sign_and_verify_match(monkeypatch):
    _set(monkeypatch, jwt_algorithm="HS256", jwt_secret_key="base-secret", derive_key_per_environment=True, environment="staging")
    assert jch.get_jwt_private_key_or_secret() == jch.get_jwt_public_key_or_secret()


# ---------------------------------------------------------------------------
# Task 4: explicit-secret derivation
# ---------------------------------------------------------------------------


def test_explicit_secret_is_derived_when_on(monkeypatch):
    _set(monkeypatch, jwt_algorithm="HS256", jwt_secret_key="ignored", derive_key_per_environment=True, environment="production")
    monkeypatch.setattr(cjt.settings, "derive_key_per_environment", True, raising=False)
    monkeypatch.setattr(cjt.settings, "environment", "production", raising=False)
    monkeypatch.setattr(cjt.settings, "jwt_algorithm", "HS256", raising=False)
    token = cjt._create_jwt_token({"sub": "alice"}, 1, "explicit-secret", "HS256")
    derived = jch._derive_env_key("explicit-secret", "production")
    assert pyjwt.decode(token, derived, algorithms=["HS256"], options={"verify_aud": False})["sub"] == "alice"
    with pytest.raises(pyjwt.InvalidSignatureError):
        pyjwt.decode(token, "explicit-secret", algorithms=["HS256"], options={"verify_aud": False})


# ---------------------------------------------------------------------------
# Task 5: real-mint round-trip + asymmetric-skip
# ---------------------------------------------------------------------------


def test_real_mint_embeds_env_when_on(monkeypatch):
    _set(monkeypatch, jwt_algorithm="HS256", jwt_secret_key="base", derive_key_per_environment=False, environment="production", embed_environment_in_tokens=True)
    monkeypatch.setattr(cjt.settings, "embed_environment_in_tokens", True, raising=False)
    monkeypatch.setattr(cjt.settings, "environment", "production", raising=False)
    token = asyncio.run(cjt.create_jwt_token({"sub": "x"}, expires_in_minutes=1, secret="base", algorithm="HS256"))  # pragma: allowlist secret
    payload = pyjwt.decode(token, "base", algorithms=["HS256"], options={"verify_aud": False})
    assert payload["env"] == "production"


def test_real_mint_omits_env_when_off(monkeypatch):
    monkeypatch.setattr(cjt.settings, "embed_environment_in_tokens", False, raising=False)
    monkeypatch.setattr(cjt.settings, "jwt_algorithm", "HS256", raising=False)
    token = asyncio.run(cjt.create_jwt_token({"sub": "x"}, expires_in_minutes=1, secret="base", algorithm="HS256"))  # pragma: allowlist secret
    payload = pyjwt.decode(token, "base", algorithms=["HS256"], options={"verify_aud": False})
    assert "env" not in payload


def test_asymmetric_skips_derivation(monkeypatch, tmp_path):
    monkeypatch.setattr(jch.settings, "jwt_algorithm", "RS256", raising=False)
    monkeypatch.setattr(jch.settings, "derive_key_per_environment", True, raising=False)
    key_file = tmp_path / "pub.pem"
    key_file.write_text("-----BEGIN PUBLIC KEY-----\nFAKE\n-----END PUBLIC KEY-----\n")
    monkeypatch.setattr(jch.settings, "jwt_public_key_path", str(key_file), raising=False)
    assert "BEGIN PUBLIC KEY" in jch.get_jwt_public_key_or_secret()


# ---------------------------------------------------------------------------
# Task 6: cross-environment rejection
# ---------------------------------------------------------------------------


def _mint_for_env(monkeypatch, environment):
    _set(monkeypatch, jwt_algorithm="HS256", jwt_secret_key="shared-base", derive_key_per_environment=True, environment=environment)
    jch.clear_jwt_caches()
    key = jch.get_jwt_private_key_or_secret()
    return pyjwt.encode({"sub": "alice", "exp": 9999999999}, key, algorithm="HS256")  # legacy: no env claim


def _verifier_env(monkeypatch, environment):
    _set(
        monkeypatch,
        jwt_algorithm="HS256",
        jwt_secret_key="shared-base",
        derive_key_per_environment=True,
        environment=environment,
        jwt_audience_verification=False,
        jwt_issuer_verification=False,
        require_jti=False,
        require_token_expiration=False,
    )
    jch.clear_jwt_caches()


def test_legacy_token_rejected_cross_environment(monkeypatch):
    token = _mint_for_env(monkeypatch, "development")
    _verifier_env(monkeypatch, "production")
    with pytest.raises(vc.HTTPException) as exc:
        asyncio.run(vc.verify_jwt_token(token))
    assert exc.value.status_code == 401


def test_legacy_token_accepted_home_environment(monkeypatch):
    token = _mint_for_env(monkeypatch, "development")
    _verifier_env(monkeypatch, "development")
    assert asyncio.run(vc.verify_jwt_token(token))["sub"] == "alice"


# ---------------------------------------------------------------------------
# Task 7: claim defense-in-depth + cached-path
# ---------------------------------------------------------------------------


def test_env_claim_mismatch_rejected(monkeypatch):
    _set(
        monkeypatch,
        jwt_algorithm="HS256",
        jwt_secret_key="same",
        derive_key_per_environment=False,
        environment="production",
        validate_token_environment=True,
        jwt_audience_verification=False,
        jwt_issuer_verification=False,
        require_jti=False,
        require_token_expiration=False,
    )
    jch.clear_jwt_caches()
    token = pyjwt.encode({"sub": "a", "env": "development", "exp": 9999999999}, jch.get_jwt_private_key_or_secret(), algorithm="HS256")
    with pytest.raises(vc.HTTPException) as exc:
        asyncio.run(vc.verify_jwt_token(token))
    assert exc.value.status_code == 401


def test_missing_env_claim_allowed(monkeypatch):
    _set(
        monkeypatch,
        jwt_algorithm="HS256",
        jwt_secret_key="same",
        derive_key_per_environment=False,
        environment="production",
        validate_token_environment=True,
        jwt_audience_verification=False,
        jwt_issuer_verification=False,
        require_jti=False,
        require_token_expiration=False,
    )
    jch.clear_jwt_caches()
    token = pyjwt.encode({"sub": "a", "exp": 9999999999}, jch.get_jwt_private_key_or_secret(), algorithm="HS256")
    assert asyncio.run(vc.verify_jwt_token(token))["sub"] == "a"


def test_cached_verify_no_cross_env_poisoning(monkeypatch):
    token = _mint_for_env(monkeypatch, "development")
    _verifier_env(monkeypatch, "production")
    for _ in range(2):
        with pytest.raises(vc.HTTPException):
            asyncio.run(vc.verify_jwt_token_cached(token))


# ---------------------------------------------------------------------------
# Task 8: operator logging
# ---------------------------------------------------------------------------


def test_signature_failure_logs_cross_env_hint(monkeypatch, caplog):
    import logging

    token = _mint_for_env(monkeypatch, "development")
    _verifier_env(monkeypatch, "production")
    with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.verify_credentials"):
        with pytest.raises(vc.HTTPException):
            asyncio.run(vc.verify_jwt_token(token))
    assert any("cross-environment" in r.message.lower() for r in caplog.records)


def test_env_mismatch_logs_warning(monkeypatch, caplog):
    import logging

    _set(
        monkeypatch,
        jwt_algorithm="HS256",
        jwt_secret_key="same",
        derive_key_per_environment=False,
        environment="production",
        validate_token_environment=True,
        jwt_audience_verification=False,
        jwt_issuer_verification=False,
        require_jti=False,
        require_token_expiration=False,
    )
    jch.clear_jwt_caches()
    token = pyjwt.encode({"sub": "a", "env": "development", "exp": 9999999999}, jch.get_jwt_private_key_or_secret(), algorithm="HS256")
    with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.verify_credentials"):
        with pytest.raises(vc.HTTPException):
            asyncio.run(vc.verify_jwt_token(token))
    assert any("environment mismatch" in r.message.lower() for r in caplog.records)
