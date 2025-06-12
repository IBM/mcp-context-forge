#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jwt_cli.py - generate, inspect, **and be imported** for token helpers.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

* **Run as a script** - friendly CLI (works with *no* flags).
* **Import as a library** - drop-in async functions `create_jwt_token` & `get_jwt_token`
  kept for backward-compatibility, now delegating to the shared core helper.

Quick usage
-----------
CLI (default secret, default payload):
    $ python3 jwt_cli.py

Library (unchanged API):
```python
from mcpgateway.utils.create_jwt_token import create_jwt_token, get_jwt_token

# inside async context
jwt = await create_jwt_token({"username": "alice"})
```
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import sys
from typing import Any, Dict, List, Sequence

import jwt  # PyJWT

from mcpgateway.config import settings

__all__: Sequence[str] = (
    "create_jwt_token",
    "get_jwt_token",
    "_create_jwt_token",
)

# ---------------------------------------------------------------------------
# Defaults & constants
# ---------------------------------------------------------------------------
DEFAULT_SECRET: str = settings.jwt_secret_key
DEFAULT_ALGO: str = settings.jwt_algorithm
DEFAULT_EXP_MINUTES: int = settings.token_expiry  # 7 days (in minutes)
DEFAULT_USERNAME: str = settings.basic_auth_user


# ---------------------------------------------------------------------------
# Core sync helper (used by both CLI & async wrappers)
# ---------------------------------------------------------------------------


def _create_jwt_token(
    data: Dict[str, Any],
    expires_in_minutes: int = DEFAULT_EXP_MINUTES,
    secret: str = DEFAULT_SECRET,
    algorithm: str = DEFAULT_ALGO,
) -> str:
    """Return a signed JWT string (synchronous, timezone-aware).

    Args:
        data: Dictionary containing payload data to encode in the token.
        expires_in_minutes: Token expiration time in minutes. Default is 7 days.
            Set to 0 to disable expiration.
        secret: Secret key used for signing the token.
        algorithm: Signing algorithm to use.

    Returns:
        The JWT token string.
    """
    payload = data.copy()
    if expires_in_minutes > 0:
        expire = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=expires_in_minutes)
        payload["exp"] = int(expire.timestamp())
    return jwt.encode(payload, secret, algorithm=algorithm)


# ---------------------------------------------------------------------------
# **Async** wrappers for backward compatibility
# ---------------------------------------------------------------------------


async def create_jwt_token(
    data: Dict[str, Any],
    expires_in_minutes: int = DEFAULT_EXP_MINUTES,
    *,
    secret: str = DEFAULT_SECRET,
    algorithm: str = DEFAULT_ALGO,
) -> str:
    """Async facade for historic code. Internally synchronous—almost instant.

    Args:
        data: Dictionary containing payload data to encode in the token.
        expires_in_minutes: Token expiration time in minutes. Default is 7 days.
            Set to 0 to disable expiration.
        secret: Secret key used for signing the token.
        algorithm: Signing algorithm to use.

    Returns:
        The JWT token string.
    """
    return _create_jwt_token(data, expires_in_minutes, secret, algorithm)


async def get_jwt_token() -> str:
    """Return a token for ``{"username": "admin"}``, mirroring old behaviour.

    Returns:
        The JWT token string with default admin username.
    """
    user_data = {"username": DEFAULT_USERNAME}
    return await create_jwt_token(user_data)


# ---------------------------------------------------------------------------
# **Decode** helper (non-verifying) - used by the CLI
# ---------------------------------------------------------------------------


def _decode_jwt_token(token: str, algorithms: List[str] | None = None) -> Dict[str, Any]:
    """Decode *without* signature verification—handy for inspection.

    Args:
        token: JWT token string to decode.
        algorithms: List of allowed algorithms for decoding. Defaults to [DEFAULT_ALGO].

    Returns:
        Dictionary containing the decoded payload.
    """
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=algorithms or [DEFAULT_ALGO],
        # options={"require": ["exp"]},  # Require expiration
    )


# ---------------------------------------------------------------------------
# CLI Parsing & helpers
# ---------------------------------------------------------------------------


def _parse_args():
    p = argparse.ArgumentParser(
        description="Generate or inspect JSON Web Tokens.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    group = p.add_mutually_exclusive_group()
    group.add_argument("-u", "--username", help="Add username=<value> to the payload.")
    group.add_argument("-d", "--data", help="Raw JSON payload or comma-separated key=value pairs.")
    group.add_argument("--decode", metavar="TOKEN", help="Token string to decode (no verification).")

    p.add_argument(
        "-e",
        "--exp",
        type=int,
        default=DEFAULT_EXP_MINUTES,
        help="Expiration in minutes (0 disables the exp claim).",
    )
    p.add_argument("-s", "--secret", default=DEFAULT_SECRET, help="Secret key for signing.")
    p.add_argument("--algo", default=DEFAULT_ALGO, help="Signing algorithm to use.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print payload before encoding.")

    return p.parse_args()


def _payload_from_cli(args) -> Dict[str, Any]:
    if args.username is not None:
        return {"username": args.username}

    if args.data is not None:
        # Attempt JSON first
        try:
            return json.loads(args.data)
        except json.JSONDecodeError:
            pairs = [kv.strip() for kv in args.data.split(",") if kv.strip()]
            payload: Dict[str, Any] = {}
            for pair in pairs:
                if "=" not in pair:
                    raise ValueError(f"Invalid key=value pair: '{pair}'")
                k, v = pair.split("=", 1)
                payload[k.strip()] = v.strip()
            return payload

    # Fallback default payload
    return {"username": DEFAULT_USERNAME}


# ---------------------------------------------------------------------------
# Entry point for ``python jwt_cli.py``
# ---------------------------------------------------------------------------


def main() -> None:  # pragma: no cover
    args = _parse_args()

    # Decode mode takes precedence
    if args.decode:
        decoded = _decode_jwt_token(args.decode, algorithms=[args.algo])
        json.dump(decoded, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return

    payload = _payload_from_cli(args)

    if args.pretty:
        print("Payload:")
        print(json.dumps(payload, indent=2, default=str))
        print("-")

    token = _create_jwt_token(payload, args.exp, args.secret, args.algo)
    print(token)


if __name__ == "__main__":
    # Support being run via ``python3 -m mcpgateway.utils.create_jwt_token`` too
    try:
        # Respect existing asyncio loop if present (e.g. inside uvicorn dev server)
        loop = asyncio.get_running_loop()
        loop.run_until_complete(asyncio.sleep(0))  # no-op to ensure loop alive
    except RuntimeError:
        # No loop; we're just a simple CLI call - run main synchronously
        main()
    else:
        # We're inside an active asyncio program - delegate to executor to avoid blocking
        loop.run_in_executor(None, main)
