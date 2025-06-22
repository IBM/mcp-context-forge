# -*- coding: utf-8 -*-
"""
Unit tests for mcpgateway.utils.create_jwt_token

Covered behaviour
-----------------
* _create_jwt_token round-trip (with exp claim present)
* create_jwt_token async wrapper (with exp disabled)
* get_jwt_token default helper
* _decode_jwt_token convenience decoder

No CLI tests here—the CLI path is just thin plumbing around the same core
functions and would add subprocess complexity for little gain.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Author: Your Name
"""
import asyncio

import jwt
import pytest

# --------------------------------------------------------------------------- #
# Import the module under test                                                 #
# --------------------------------------------------------------------------- #
from mcpgateway.utils import create_jwt_token as jwt_util  # noqa: E402

# Simple aliases to keep the tests tidy
_create_jwt_token = jwt_util._create_jwt_token  # pylint: disable=protected-access
create_jwt_token = jwt_util.create_jwt_token
get_jwt_token = jwt_util.get_jwt_token
_decode_jwt_token = jwt_util._decode_jwt_token  # pylint: disable=protected-access

# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
TEST_SECRET = "unit-test-secret"
TEST_ALGO = "HS256"


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #
def test_sync_token_roundtrip_with_exp():
    """_create_jwt_token ➜ jwt.decode should reproduce original payload (plus exp)."""
    payload = {"foo": "bar"}

    token = _create_jwt_token(
        payload,
        expires_in_minutes=1,
        secret=TEST_SECRET,
        algorithm=TEST_ALGO,
    )

    decoded = jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGO])

    # Original data retained
    for k, v in payload.items():
        assert decoded[k] == v

    # exp claim present and is int
    assert isinstance(decoded["exp"], int)


@pytest.mark.asyncio
async def test_async_wrapper_without_exp():
    """create_jwt_token async wrapper works and omits exp when minutes==0."""
    payload = {"a": 1}

    token = await create_jwt_token(
        payload,
        expires_in_minutes=0,  # disable exp claim
        secret=TEST_SECRET,
        algorithm=TEST_ALGO,
    )

    decoded = jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGO])
    assert decoded == payload  # no extra keys


@pytest.mark.asyncio
async def test_get_default_admin_token(monkeypatch):
    """get_jwt_token should emit a token containing DEFAULT_USERNAME."""
    # The helper relies on module-level DEFAULT_* constants initialised at import
    # time; we therefore *decode* with whatever secret the module already holds.
    token = await get_jwt_token()

    decoded = _decode_jwt_token(token)

    assert decoded["username"] == jwt_util.DEFAULT_USERNAME
