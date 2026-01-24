# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_create_jwt_token.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Full-coverage unit tests for **mcpgateway.utils.create_jwt_token**
All paths are exercised, including:
* sync core (`_create_jwt_token`) with / without ``exp`` claim
* async wrappers (`create_jwt_token`, `get_jwt_token`)
* helper `_decode_jwt_token`
* CLI helpers: `_payload_from_cli`, `_parse_args`, and `main()` in both
  encode (`--pretty`) and decode (`--decode`) modes.
No subprocesses - we invoke `main()` directly, patching ``sys.argv`` and
capturing stdout with ``capsys``.
Running:
    pytest -q --cov=mcpgateway.utils.create_jwt_token --cov-report=term-missing
should show **100 %** statement coverage for the target module.
Author: Your Name
"""

# Future
from __future__ import annotations

# Standard
import json
import sys
from types import SimpleNamespace
from typing import Any, Dict

# Third-Party
import jwt
import pytest

# First-Party
from mcpgateway.utils import create_jwt_token as jwt_util  # noqa: E402

# --------------------------------------------------------------------------- #
# Patch module-level constants **before** we start calling helpers            #
# --------------------------------------------------------------------------- #
TEST_SECRET = "unit-test-secret"
TEST_ALGO = "HS256"

jwt_util.DEFAULT_SECRET = TEST_SECRET
jwt_util.DEFAULT_ALGO = TEST_ALGO
# NB: settings.jwt_secret_key is read at *runtime* in _decode(), so patch too
jwt_util.settings.jwt_secret_key = TEST_SECRET
jwt_util.settings.jwt_algorithm = TEST_ALGO

# Short aliases keep test lines tidy
_create: Any = jwt_util._create_jwt_token  # pylint: disable=protected-access
_decode: Any = jwt_util._decode_jwt_token  # pylint: disable=protected-access
_payload: Any = jwt_util._payload_from_cli  # pylint: disable=protected-access
_parse_args: Any = jwt_util._parse_args  # pylint: disable=protected-access
create_async = jwt_util.create_jwt_token
get_default = jwt_util.get_jwt_token
main_cli = jwt_util.main


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _ns(**kw) -> SimpleNamespace:
    """Namespace helper for _payload_from_cli tests."""
    defaults = {"username": None, "data": None}
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# --------------------------------------------------------------------------- #
# Core token helpers                                                          #
# --------------------------------------------------------------------------- #
def test_create_token_paths():
    """_create_jwt_token with and without exp claim."""
    payload: Dict[str, Any] = {"foo": "bar"}

    tok1 = _create(payload, expires_in_minutes=1, secret=TEST_SECRET, algorithm=TEST_ALGO)
    dec1 = jwt.decode(tok1, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")
    assert dec1["foo"] == "bar" and "exp" in dec1

    tok2 = _create(payload, expires_in_minutes=0, secret=TEST_SECRET, algorithm=TEST_ALGO)
    dec2 = jwt.decode(tok2, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")
    # Check that the original payload keys are present
    assert dec2["foo"] == "bar"


def test_create_token_includes_jti():
    """_create_jwt_token always includes a JTI claim for revocation support."""
    payload: Dict[str, Any] = {"sub": "test@example.com"}

    # Create token without providing JTI
    tok1 = _create(payload, expires_in_minutes=1, secret=TEST_SECRET, algorithm=TEST_ALGO)
    dec1 = jwt.decode(tok1, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")
    assert "jti" in dec1, "Token should include JTI claim"
    assert len(dec1["jti"]) == 36, "JTI should be a UUID (36 chars with hyphens)"

    # Create another token and verify JTI is unique
    tok2 = _create(payload, expires_in_minutes=1, secret=TEST_SECRET, algorithm=TEST_ALGO)
    dec2 = jwt.decode(tok2, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")
    assert dec1["jti"] != dec2["jti"], "Each token should have a unique JTI"


def test_create_token_preserves_provided_jti():
    """_create_jwt_token preserves JTI if already provided in payload."""
    custom_jti = "custom-jti-12345"
    payload: Dict[str, Any] = {"sub": "test@example.com", "jti": custom_jti}

    tok = _create(payload, expires_in_minutes=1, secret=TEST_SECRET, algorithm=TEST_ALGO)
    dec = jwt.decode(tok, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")
    assert dec["jti"] == custom_jti, "Token should preserve provided JTI"


def test_create_token_embeds_environment_when_enabled():
    """_create_jwt_token embeds environment claim when EMBED_ENVIRONMENT_IN_TOKENS=true."""
    original_embed = jwt_util.settings.embed_environment_in_tokens
    original_env = jwt_util.settings.environment
    try:
        jwt_util.settings.embed_environment_in_tokens = True
        jwt_util.settings.environment = "production"

        payload: Dict[str, Any] = {"sub": "test@example.com"}
        tok = _create(payload, expires_in_minutes=1, secret=TEST_SECRET, algorithm=TEST_ALGO)
        dec = jwt.decode(tok, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")

        assert "env" in dec, "Token should include env claim when embed_environment_in_tokens is enabled"
        assert dec["env"] == "production", "Token env claim should match settings.environment"
    finally:
        jwt_util.settings.embed_environment_in_tokens = original_embed
        jwt_util.settings.environment = original_env


def test_create_token_omits_environment_when_disabled():
    """_create_jwt_token omits environment claim when EMBED_ENVIRONMENT_IN_TOKENS=false."""
    original_embed = jwt_util.settings.embed_environment_in_tokens
    try:
        jwt_util.settings.embed_environment_in_tokens = False

        payload: Dict[str, Any] = {"sub": "test@example.com"}
        tok = _create(payload, expires_in_minutes=1, secret=TEST_SECRET, algorithm=TEST_ALGO)
        dec = jwt.decode(tok, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")

        assert "env" not in dec, "Token should not include env claim when embed_environment_in_tokens is disabled"
    finally:
        jwt_util.settings.embed_environment_in_tokens = original_embed


@pytest.mark.asyncio
async def test_async_wrappers():
    """create_jwt_token & get_jwt_token wrappers work end-to-end."""

    # Explicit secret/algorithm keep this token verifiable with _decode()
    token = await create_async(
        {"k": "v"},
        expires_in_minutes=0,
        secret=TEST_SECRET,
        algorithm=TEST_ALGO,
    )
    decoded = _decode(token)
    assert decoded["k"] == "v"  # Check the custom claim is present

    # get_jwt_token uses the original secret captured at definition time;
    # just decode without verifying the signature to inspect the payload.
    admin_token = await get_default()
    payload = jwt.decode(admin_token, options={"verify_signature": False})
    assert payload["username"] == jwt_util.DEFAULT_USERNAME


# --------------------------------------------------------------------------- #
# _payload_from_cli variants                                                  #
# --------------------------------------------------------------------------- #
def test_payload_username():
    assert _payload(_ns(username="alice")) == {"username": "alice"}


def test_payload_json():
    assert _payload(_ns(data='{"a": 1}')) == {"a": 1}


def test_payload_keyvals():
    assert _payload(_ns(data="x=1, y=two")) == {"x": "1", "y": "two"}


def test_payload_invalid_pair():
    with pytest.raises(ValueError):
        _payload(_ns(data="oops"))


def test_payload_default():
    assert _payload(_ns()) == {"username": jwt_util.DEFAULT_USERNAME}


# --------------------------------------------------------------------------- #
# CLI arg-parsing & main()                                                    #
# --------------------------------------------------------------------------- #
def test_parse_args():
    sys.argv = ["prog", "-u", "bob", "-e", "10"]
    args = _parse_args()
    assert args.username == "bob" and args.exp == 10 and args.data is None


def test_main_encode_pretty(capsys):
    """main() in encode mode prints payload then token."""
    sys.argv = [
        "prog",
        "-u",
        "cliuser",
        "-e",
        "0",
        "-s",
        TEST_SECRET,
        "--algo",
        TEST_ALGO,
        "--pretty",
    ]
    main_cli()

    out_lines = capsys.readouterr().out.strip().splitlines()
    assert out_lines[0] == "Payload:"
    token = out_lines[-1]
    assert jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")["username"] == "cliuser"


def test_main_decode_mode(capsys):
    """main() in decode mode prints JSON payload."""
    token = _create({"z": 9}, 0, TEST_SECRET, TEST_ALGO)
    sys.argv = ["prog", "--decode", token, "--algo", TEST_ALGO]

    main_cli()

    printed = capsys.readouterr().out.strip()
    decoded = json.loads(printed)
    assert decoded["z"] == 9  # Check the custom claim is present


# --------------------------------------------------------------------------- #
# Rich token creation tests                                                    #
# --------------------------------------------------------------------------- #
def test_create_token_with_user_data():
    """_create_jwt_token includes user data when provided."""
    payload: Dict[str, Any] = {"sub": "test@example.com"}
    user_data = {
        "email": "test@example.com",
        "full_name": "Test User",
        "is_admin": True,
        "auth_provider": "cli",
    }

    tok = _create(payload, expires_in_minutes=1, secret=TEST_SECRET, algorithm=TEST_ALGO, user_data=user_data)
    dec = jwt.decode(tok, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")

    assert "user" in dec, "Token should include user claim"
    assert dec["user"]["email"] == "test@example.com"
    assert dec["user"]["full_name"] == "Test User"
    assert dec["user"]["is_admin"] is True
    assert dec["user"]["auth_provider"] == "cli"


def test_create_token_with_teams():
    """_create_jwt_token includes teams when provided."""
    payload: Dict[str, Any] = {"sub": "test@example.com"}
    teams = ["team-123", "team-456"]

    tok = _create(payload, expires_in_minutes=1, secret=TEST_SECRET, algorithm=TEST_ALGO, teams=teams)
    dec = jwt.decode(tok, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")

    assert "teams" in dec, "Token should include teams claim"
    assert dec["teams"] == ["team-123", "team-456"]


def test_create_token_with_namespaces():
    """_create_jwt_token includes explicit namespaces when provided."""
    payload: Dict[str, Any] = {"sub": "test@example.com"}
    namespaces = ["user:test@example.com", "public", "team:team-123"]

    tok = _create(payload, expires_in_minutes=1, secret=TEST_SECRET, algorithm=TEST_ALGO, namespaces=namespaces)
    dec = jwt.decode(tok, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")

    assert "namespaces" in dec, "Token should include namespaces claim"
    assert dec["namespaces"] == ["user:test@example.com", "public", "team:team-123"]


def test_create_token_auto_generates_namespaces_from_teams():
    """_create_jwt_token auto-generates namespaces from teams when not provided."""
    payload: Dict[str, Any] = {"sub": "test@example.com"}
    teams = ["team-123", "team-456"]

    tok = _create(payload, expires_in_minutes=1, secret=TEST_SECRET, algorithm=TEST_ALGO, teams=teams)
    dec = jwt.decode(tok, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")

    assert "namespaces" in dec, "Token should include auto-generated namespaces"
    assert "user:test@example.com" in dec["namespaces"]
    assert "public" in dec["namespaces"]
    assert "team:team-123" in dec["namespaces"]
    assert "team:team-456" in dec["namespaces"]


def test_create_token_with_scopes():
    """_create_jwt_token includes scopes when provided."""
    payload: Dict[str, Any] = {"sub": "test@example.com"}
    scopes = {
        "server_id": "server-123",
        "permissions": ["tools.read", "resources.read"],
        "ip_restrictions": ["192.168.1.0/24"],
        "time_restrictions": {"business_hours_only": True},
    }

    tok = _create(payload, expires_in_minutes=1, secret=TEST_SECRET, algorithm=TEST_ALGO, scopes=scopes)
    dec = jwt.decode(tok, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")

    assert "scopes" in dec, "Token should include scopes claim"
    assert dec["scopes"]["server_id"] == "server-123"
    assert dec["scopes"]["permissions"] == ["tools.read", "resources.read"]
    assert dec["scopes"]["ip_restrictions"] == ["192.168.1.0/24"]
    assert dec["scopes"]["time_restrictions"]["business_hours_only"] is True


def test_create_rich_token_all_fields():
    """_create_jwt_token includes all rich token fields when provided."""
    payload: Dict[str, Any] = {"sub": "admin@example.com", "jti": "custom-jti"}
    user_data = {
        "email": "admin@example.com",
        "full_name": "Admin User",
        "is_admin": True,
        "auth_provider": "cli",
    }
    teams = ["team-123"]
    namespaces = ["user:admin@example.com", "public", "team:team-123"]
    scopes = {
        "server_id": None,
        "permissions": [],
        "ip_restrictions": [],
        "time_restrictions": {},
    }

    tok = _create(payload, expires_in_minutes=60, secret=TEST_SECRET, algorithm=TEST_ALGO, user_data=user_data, teams=teams, namespaces=namespaces, scopes=scopes)
    dec = jwt.decode(tok, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")

    # Verify all standard claims
    assert dec["sub"] == "admin@example.com"
    assert dec["jti"] == "custom-jti"
    assert "iat" in dec
    assert "exp" in dec

    # Verify rich claims
    assert dec["user"]["email"] == "admin@example.com"
    assert dec["user"]["is_admin"] is True
    assert dec["teams"] == ["team-123"]
    assert dec["namespaces"] == ["user:admin@example.com", "public", "team:team-123"]
    assert dec["scopes"]["permissions"] == []


@pytest.mark.asyncio
async def test_async_create_with_rich_claims():
    """create_jwt_token async wrapper accepts rich token parameters."""
    user_data = {
        "email": "test@example.com",
        "full_name": "Test User",
        "is_admin": False,
        "auth_provider": "api_token",
    }
    teams = ["team-789"]
    scopes = {"server_id": "server-456", "permissions": ["tools.execute"], "ip_restrictions": [], "time_restrictions": {}}

    token = await create_async({"sub": "test@example.com"}, expires_in_minutes=30, secret=TEST_SECRET, algorithm=TEST_ALGO, user_data=user_data, teams=teams, scopes=scopes)

    dec = jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")

    assert dec["user"]["email"] == "test@example.com"
    assert dec["teams"] == ["team-789"]
    assert dec["scopes"]["server_id"] == "server-456"


def test_backward_compatibility_simple_tokens():
    """_create_jwt_token maintains backward compatibility with simple tokens."""
    # Old-style token creation should still work
    payload: Dict[str, Any] = {"username": "alice"}

    tok = _create(payload, expires_in_minutes=10, secret=TEST_SECRET, algorithm=TEST_ALGO)
    dec = jwt.decode(tok, TEST_SECRET, algorithms=[TEST_ALGO], audience="mcpgateway-api", issuer="mcpgateway")

    # Should convert username to sub
    assert dec["sub"] == "alice"
    # Should not have rich claims when not provided
    assert "user" not in dec
    assert "teams" not in dec
    assert "namespaces" not in dec
    assert "scopes" not in dec
