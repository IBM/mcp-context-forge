#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/create_jwt_token.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

jwt_cli.py - generate, inspect, **and be imported** for token helpers.
* **Run as a script** - friendly CLI (works with *no* flags).
* **Import as a library** - drop-in async functions `create_jwt_token` & `get_jwt_token`
  kept for backward-compatibility, now delegating to the shared core helper.

Quick usage
-----------
CLI (default secret, default payload):
    $ python3 jwt_cli.py

Library:
    from mcpgateway.utils.create_jwt_token import create_jwt_token, get_jwt_token

    # inside async context
    jwt = await create_jwt_token({"username": "alice"})

Doctest examples
----------------
>>> from mcpgateway.utils import create_jwt_token as jwt_util
>>> from mcpgateway.utils.jwt_config_helper import clear_jwt_caches
>>> clear_jwt_caches()
>>> jwt_util.settings.jwt_secret_key = 'secret'
>>> jwt_util.settings.jwt_algorithm = 'HS256'
>>> token = jwt_util._create_jwt_token({'sub': 'alice'}, expires_in_minutes=1, secret='secret', algorithm='HS256')
>>> import jwt
>>> jwt.decode(token, 'secret', algorithms=['HS256'], audience=jwt_util.settings.jwt_audience, issuer=jwt_util.settings.jwt_issuer)['sub'] == 'alice'
True
>>> import asyncio
>>> t = asyncio.run(jwt_util.create_jwt_token({'sub': 'bob'}, expires_in_minutes=1, secret='secret', algorithm='HS256'))
>>> jwt.decode(t, 'secret', algorithms=['HS256'], audience=jwt_util.settings.jwt_audience, issuer=jwt_util.settings.jwt_issuer)['sub'] == 'bob'
True
"""

# Future
from __future__ import annotations

# Standard
import argparse
import asyncio
import datetime as _dt
import sys
from typing import Any, Dict, List, Optional, Sequence
import uuid

# Third-Party
import jwt  # PyJWT
import orjson

# First-Party
from mcpgateway.config import settings

__all__: Sequence[str] = (
    "create_jwt_token",
    "get_jwt_token",
    "_create_jwt_token",
)

# ---------------------------------------------------------------------------
# Defaults & constants
# ---------------------------------------------------------------------------
# Note: DEFAULT_SECRET is retrieved at runtime to support dynamic configuration changes
DEFAULT_ALGO: str = settings.jwt_algorithm
DEFAULT_EXP_MINUTES: int = settings.token_expiry
DEFAULT_USERNAME: str = settings.basic_auth_user


# ---------------------------------------------------------------------------
# Core sync helper (used by both CLI & async wrappers)
# ---------------------------------------------------------------------------


def _create_jwt_token(
    data: Dict[str, Any],
    expires_in_minutes: int = DEFAULT_EXP_MINUTES,
    secret: str = "",  # nosec B107 - Optional override; uses config if empty
    algorithm: str = "",  # Optional override; uses config if empty
    user_data: Optional[Dict[str, Any]] = None,
    teams: Optional[List[str]] = None,
    scopes: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a signed JWT token with automatic key selection and validation.

    This internal function handles JWT token creation with both symmetric (HMAC) and
    asymmetric (RSA/ECDSA) algorithms. It automatically validates the JWT configuration,
    selects the appropriate signing key based on the configured algorithm, and creates
    a properly formatted JWT token with standard claims.

    Supports both simple tokens (minimal claims) and rich tokens (with user, teams,
    and scopes). This enables consistent token format across CLI and API
    token creation paths.

    Args:
        data: Dictionary containing payload data to encode in the token.
        expires_in_minutes: Token expiration time in minutes. Set to 0 to disable expiration.
        secret: Optional secret key for signing. If empty, uses JWT_SECRET_KEY from config.
        algorithm: Optional signing algorithm. If empty, uses JWT_ALGORITHM from config.
        user_data: Optional user information dict with keys: email, full_name, is_admin, auth_provider.
        teams: Optional list of team IDs the token is scoped to.
        scopes: Optional scopes dict with keys: server_id, permissions, ip_restrictions, time_restrictions.

    Returns:
        str: The signed JWT token string.

    Raises:
        JWTConfigurationError: If JWT configuration is invalid or keys are missing.
        FileNotFoundError: If asymmetric key files don't exist.

    Note:
        This is an internal function. Use create_jwt_token() for the async interface.
        When secret/algorithm are provided, they override the configuration values.
        When not provided (empty), configuration values are used as defaults.
    """
    # First-Party
    from mcpgateway.utils.jwt_config_helper import get_jwt_private_key_or_secret, validate_jwt_algo_and_keys

    # Use provided secret/algorithm or fall back to configuration
    if not secret:
        validate_jwt_algo_and_keys()
        secret = get_jwt_private_key_or_secret()
    if not algorithm:
        algorithm = settings.jwt_algorithm

    payload = data.copy()
    now = _dt.datetime.now(_dt.timezone.utc)

    # Add standard JWT claims
    payload["iat"] = int(now.timestamp())  # Issued at
    payload["iss"] = settings.jwt_issuer  # Issuer
    payload["aud"] = settings.jwt_audience  # Audience
    payload["jti"] = payload.get("jti") or str(uuid.uuid4())  # JWT ID for revocation support

    # Optionally embed environment claim for cross-environment isolation
    if settings.embed_environment_in_tokens:
        payload["env"] = settings.environment

    # Handle legacy username format - convert to sub for consistency
    if "username" in payload and "sub" not in payload:
        payload["sub"] = payload["username"]

    # Add rich claims if provided (for API/CLI token parity)
    if user_data:
        payload["user"] = user_data

    if teams is not None:
        payload["teams"] = teams

    if scopes is not None:
        payload["scopes"] = scopes

    payload_exp = payload.get("exp", 0)
    if payload_exp > 0:
        pass  # The token already has a valid expiration time
    elif expires_in_minutes > 0:
        expire = now + _dt.timedelta(minutes=expires_in_minutes)
        payload["exp"] = int(expire.timestamp())
    else:
        # Warn about non-expiring token
        print(
            "⚠️  WARNING: Creating token without expiration. This is a security risk!\n"
            "   Consider using --exp with a value > 0 for production use.\n"
            "   Once JWT API (#425) is available, use it for automatic token renewal.",
            file=sys.stderr,
        )

    return jwt.encode(payload, secret, algorithm=algorithm)


# ---------------------------------------------------------------------------
# **Async** wrappers for backward compatibility
# ---------------------------------------------------------------------------


async def create_jwt_token(
    data: Dict[str, Any],
    expires_in_minutes: int = DEFAULT_EXP_MINUTES,
    *,
    secret: str = None,
    algorithm: str = None,
    user_data: Optional[Dict[str, Any]] = None,
    teams: Optional[List[str]] = None,
    scopes: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Async facade for historic code. Internally synchronous-almost instant.

    Args:
        data: Dictionary containing payload data to encode in the token.
        expires_in_minutes: Token expiration time in minutes. Default is 7 days.
            Set to 0 to disable expiration.
        secret: Optional secret key for signing. If None/empty, uses JWT_SECRET_KEY from config.
        algorithm: Optional signing algorithm. If None/empty, uses JWT_ALGORITHM from config.
        user_data: Optional user information dict with keys: email, full_name, is_admin, auth_provider.
        teams: Optional list of team IDs the token is scoped to.
        scopes: Optional scopes dict with keys: server_id, permissions, ip_restrictions, time_restrictions.

    Returns:
        The JWT token string.

    Doctest:
    >>> from mcpgateway.utils import create_jwt_token as jwt_util
    >>> from mcpgateway.utils.jwt_config_helper import clear_jwt_caches
    >>> clear_jwt_caches()
    >>> jwt_util.settings.jwt_secret_key = 'secret'
    >>> jwt_util.settings.jwt_algorithm = 'HS256'
    >>> import asyncio
    >>> t = asyncio.run(jwt_util.create_jwt_token({'sub': 'bob'}, expires_in_minutes=1))
    >>> import jwt
    >>> jwt.decode(t, jwt_util.settings.jwt_secret_key, algorithms=[jwt_util.settings.jwt_algorithm], audience=jwt_util.settings.jwt_audience, issuer=jwt_util.settings.jwt_issuer)['sub'] == 'bob'
    True
    """
    # Pass through secret/algorithm; _create_jwt_token will use config as fallback
    return _create_jwt_token(data, expires_in_minutes, secret or "", algorithm or "", user_data, teams, scopes)


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
    """Decode with proper audience and issuer verification.

    Args:
        token: JWT token string to decode.
        algorithms: List of allowed algorithms for decoding. Defaults to [DEFAULT_ALGO].

    Returns:
        Dictionary containing the decoded payload.

    Examples:
        >>> # Test algorithm parameter handling
        >>> algs = ['HS256', 'HS512']
        >>> len(algs)
        2
        >>> 'HS256' in algs
        True
        >>> # Test None algorithms handling
        >>> default_algo = [DEFAULT_ALGO]
        >>> isinstance(default_algo, list)
        True
    """
    # Get the actual string value from SecretStr if needed
    secret_key = settings.jwt_secret_key.get_secret_value() if hasattr(settings.jwt_secret_key, "get_secret_value") else settings.jwt_secret_key
    return jwt.decode(
        token,
        secret_key,
        algorithms=algorithms or [DEFAULT_ALGO],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        # options={"require": ["exp"]},  # Require expiration
    )


# ---------------------------------------------------------------------------
# CLI Parsing & helpers
# ---------------------------------------------------------------------------


def _parse_args():
    """Parse command line arguments for JWT token operations.

    Sets up an argument parser with mutually exclusive options for:
    - Creating tokens with username (-u/--username)
    - Creating tokens with custom data (-d/--data)
    - Decoding existing tokens (--decode)

    Additional options control expiration, secret key, algorithm, and output format.

    Returns:
        argparse.Namespace: Parsed command line arguments containing:
            - username: Optional username for simple payload
            - data: Optional JSON or key=value pairs for custom payload
            - decode: Optional token string to decode
            - exp: Expiration time in minutes (default: DEFAULT_EXP_MINUTES)
            - secret: Secret key for signing (default: "" - uses JWT_SECRET_KEY from config)
            - algo: Signing algorithm (default: "" - uses JWT_ALGORITHM from config)
            - pretty: Whether to pretty-print payload before encoding

    Examples:
        >>> # Simulating command line args
        >>> import sys
        >>> sys.argv = ['jwt_cli.py', '-u', 'alice', '-e', '60']
        >>> args = _parse_args()  # doctest: +SKIP
        >>> args.username  # doctest: +SKIP
        'alice'
        >>> args.exp  # doctest: +SKIP
        60
    """
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
    p.add_argument("-s", "--secret", default="", help="Secret key for signing. If not provided, uses JWT_SECRET_KEY from config.")
    p.add_argument("--algo", default="", help="Signing algorithm (e.g., HS256, RS256). If not provided, uses JWT_ALGORITHM from config.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print payload before encoding.")

    # Rich token creation arguments (requires JWT_SECRET_KEY)
    p.add_argument("--admin", action="store_true", help="Mark user as admin (DEV/TEST ONLY - requires JWT_SECRET_KEY)")
    p.add_argument("--teams", help="Comma-separated team IDs (e.g., team-123,team-456). DEV/TEST ONLY")
    p.add_argument("--scopes", help='JSON scopes object for permission restrictions (e.g., \'{"permissions": ["tools.read"]}\'). DEV/TEST ONLY')
    p.add_argument("--full-name", help="User's full name for the token")

    return p.parse_args()


def _payload_from_cli(args) -> Dict[str, Any]:
    """Extract JWT payload from parsed command line arguments.

    Processes arguments in priority order:
    1. If username is specified, creates {"username": <value>}
    2. If data is specified, parses as JSON or key=value pairs
    3. Otherwise, returns default payload with admin username

    The data argument supports two formats:
    - JSON string: '{"key": "value", "foo": "bar"}'
    - Comma-separated pairs: 'key=value,foo=bar'

    Args:
        args: Parsed command line arguments from argparse containing
              username, data, and other JWT options.

    Returns:
        Dict[str, Any]: The payload dictionary to encode in the JWT.

    Raises:
        ValueError: If data contains invalid key=value pairs (missing '=').

    Examples:
        >>> from argparse import Namespace
        >>> args = Namespace(username='alice', data=None)
        >>> _payload_from_cli(args)
        {'username': 'alice'}
        >>> args = Namespace(username=None, data='{"role": "admin", "id": 123}')
        >>> _payload_from_cli(args)
        {'role': 'admin', 'id': 123}
        >>> args = Namespace(username=None, data='name=bob,role=user')
        >>> _payload_from_cli(args)
        {'name': 'bob', 'role': 'user'}
        >>> args = Namespace(username=None, data='invalid_format')
        >>> _payload_from_cli(args)  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        ValueError: Invalid key=value pair: 'invalid_format'
    """
    if args.username is not None:
        return {"username": args.username}

    if args.data is not None:
        # Attempt JSON first
        try:
            return orjson.loads(args.data)
        except orjson.JSONDecodeError:
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
# Entry point for ``python3 jwt_cli.py``
# ---------------------------------------------------------------------------


def main() -> None:  # pragma: no cover
    """Entry point for JWT command line interface.

    Provides two main modes of operation:
    1. Token creation: Generates a new JWT with specified payload
    2. Token decoding: Decodes and displays an existing JWT (without verification)

    In creation mode, supports:
    - Simple username payload (-u/--username)
    - Custom JSON or key=value payload (-d/--data)
    - Rich tokens with admin/team/scope claims (--admin, --teams, --scopes)
    - Configurable expiration, secret, and algorithm
    - Optional pretty-printing of payload before encoding

    In decode mode, displays the decoded payload as formatted JSON.

    The function handles being run in different contexts:
    - Direct script execution: Runs synchronously
    - Within existing asyncio loop: Delegates to executor to avoid blocking

    Examples:
        Command line usage::

            # Create token with username
            $ python jwt_cli.py -u alice
            eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...

            # Create admin token (DEV/TEST ONLY)
            $ python jwt_cli.py -u admin@example.com --admin --full-name "Admin User"
            ⚠️  WARNING: Creating token with elevated claims...
            eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...

            # Create team-scoped token (DEV/TEST ONLY)
            $ python jwt_cli.py -u user@example.com --teams team-123,team-456
            ⚠️  WARNING: Creating token with elevated claims...
            eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...

            # Decode existing token
            $ python jwt_cli.py --decode eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
            {
              "username": "alice",
              "exp": 1234567890
            }
    """
    args = _parse_args()

    # Decode mode takes precedence
    if args.decode:
        decoded = _decode_jwt_token(args.decode, algorithms=[args.algo or DEFAULT_ALGO])
        sys.stdout.write(orjson.dumps(decoded, default=str, option=orjson.OPT_INDENT_2).decode())
        sys.stdout.write("\n")
        return

    # Validate: --algo requires --secret to avoid algorithm/key mismatch
    if args.algo and not args.secret:
        print(
            "ERROR: --algo requires --secret to be specified.\n"
            "       Using --algo alone would mix config-based keys with a different algorithm,\n"
            "       which can produce invalid tokens. Either:\n"
            "       - Provide both --secret and --algo for full override\n"
            "       - Omit both to use JWT_SECRET_KEY and JWT_ALGORITHM from config",
            file=sys.stderr,
        )
        sys.exit(1)

    # Security warning for rich tokens
    if args.admin or args.teams or args.scopes:
        print(
            "⚠️  WARNING: Creating token with elevated claims (admin/teams/scopes)\n"
            "   This requires JWT_SECRET_KEY and is intended for development/testing only.\n"
            "   For production token management, use the /tokens API endpoint.\n",
            file=sys.stderr,
        )

    payload = _payload_from_cli(args)

    # Build rich token parameters if provided
    user_data = None
    teams = None
    scopes_dict = None

    if args.admin or args.teams or args.scopes or args.full_name:
        user_email = payload.get("sub") or payload.get("username", "admin@example.com")

        # Build user data
        user_data = {
            "email": user_email,
            "full_name": args.full_name or "CLI User",
            "is_admin": bool(args.admin),
            "auth_provider": "cli",  # Mark as CLI-generated for auditing
        }

        # Build teams list
        if args.teams:
            teams = [t.strip() for t in args.teams.split(",") if t.strip()]

        # Build scopes
        if args.scopes:
            try:
                scopes_dict = orjson.loads(args.scopes)
            except orjson.JSONDecodeError as e:
                print(f"ERROR: Invalid JSON for --scopes: {e}", file=sys.stderr)
                sys.exit(1)

    if args.pretty:
        print("Payload:")
        print(orjson.dumps(payload, default=str, option=orjson.OPT_INDENT_2).decode())
        if user_data:
            print("User Data:")
            print(orjson.dumps(user_data, default=str, option=orjson.OPT_INDENT_2).decode())
        if teams:
            print(f"Teams: {teams}")
        if scopes_dict:
            print("Scopes:")
            print(orjson.dumps(scopes_dict, default=str, option=orjson.OPT_INDENT_2).decode())
        print("-")

    token = _create_jwt_token(payload, args.exp, args.secret, args.algo, user_data, teams, scopes_dict)
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
