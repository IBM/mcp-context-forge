# -*- coding: utf-8 -*-
"""
Full-coverage unit tests for **mcpgateway.utils.create_jwt_token**

All paths are exercised, including:
* sync core (`_create_jwt_token`) with / without ``exp`` claim
* async wrappers (`create_jwt_token`, `get_jwt_token`)
* helper `_decode_jwt_token`
* CLI helpers: `_payload_from_cli`, `_parse_args`, and `main()` in both
  encode (`--pretty`) and decode (`--decode`) modes.

No subprocesses – we invoke `main()` directly, patching ``sys.argv`` and
capturing stdout with ``capsys``.

Running:

    pytest -q --cov=mcpgateway.utils.create_jwt_token --cov-report=term-missing

should show **100 %** statement coverage for the target module.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Author: Your Name
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any, Dict

import jwt
import pytest

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
    dec1 = jwt.decode(tok1, TEST_SECRET, algorithms=[TEST_ALGO])
    assert dec1["foo"] == "bar" and "exp" in dec1

    tok2 = _create(payload, expires_in_minutes=0, secret=TEST_SECRET, algorithm=TEST_ALGO)
    assert jwt.decode(tok2, TEST_SECRET, algorithms=[TEST_ALGO]) == payload


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
    assert _decode(token) == {"k": "v"}

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
    assert jwt.decode(token, TEST_SECRET, algorithms=[TEST_ALGO])["username"] == "cliuser"


def test_main_decode_mode(capsys):
    """main() in decode mode prints JSON payload."""
    token = _create({"z": 9}, 0, TEST_SECRET, TEST_ALGO)
    sys.argv = ["prog", "--decode", token, "--algo", TEST_ALGO]

    main_cli()

    printed = capsys.readouterr().out.strip()
    assert json.loads(printed) == {"z": 9}
