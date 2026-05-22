# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/scripts/init_secrets.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Eleni Kechrioti

Secrets Initialization Script.
This script generates cryptographically secure secrets for JWT signing,
encryption, and administrative passwords. It supports writing to a file,
overwriting existing configurations, or piping to stdout.

Usage:
    python -m mcpgateway.scripts.init_secrets --output .env.secrets
    python -m mcpgateway.scripts.init_secrets --stdout --force
"""

# Standard
import argparse
import os
import secrets
import sys

# First-Party
from mcpgateway._security_constants import WEAK_VALUES as _CANONICAL_WEAK_VALUES


def _secure_open_flags(force: bool) -> int:
    """
    Build secure file-open flags for writing generated secrets.

    Args:
        force: Whether an existing file may be overwritten.

    Returns:
        int: Flags suitable for os.open().
    """
    flags = os.O_WRONLY | os.O_CREAT
    flags |= os.O_TRUNC if force else os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _write_secrets_file(output_path: str, output_content: str, force: bool) -> None:
    """
    Write generated secrets to a file with owner-only permissions from creation.

    Args:
        output_path: File path to write.
        output_content: Generated environment content.
        force: Whether an existing file may be overwritten.
    """
    fd = os.open(output_path, _secure_open_flags(force), 0o600)
    try:
        os.fchmod(fd, 0o600)
        f = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        with f:
            f.write("# Generated via: python -m mcpgateway.scripts.init_secrets\n")
            f.write(output_content)
    except Exception:
        if fd != -1:
            os.close(fd)
        raise


_WEAK_VALUES: frozenset[str] = frozenset(v.lower() for v in _CANONICAL_WEAK_VALUES)

_SECRET_FIELDS: dict[str, int] = {
    "JWT_SECRET_KEY": 32,  # nosec B105 — value is minimum byte length, not a password
    "AUTH_ENCRYPTION_SECRET": 32,  # nosec B105 — value is minimum byte length, not a password
}


def _read_env_file(path: str) -> dict[str, str]:
    """Parse KEY=VALUE pairs from an env file, skipping comments and blank lines.

    Handles: quoted values, ``export KEY=val`` prefix, inline ``# comments``,
    and spaces around ``=``.  Matches python-dotenv parsing semantics so that
    weak-value detection fires on the same string pydantic-settings would see.
    """
    result: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :]
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                # Strip inline comment (space + #)
                if " #" in val:
                    val = val[: val.index(" #")].strip()
                # Strip matching surrounding quotes
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                result[key] = val
    except FileNotFoundError:
        pass
    return result


def _merge_env_file(path: str, updates: dict[str, str]) -> None:
    """Merge key=value pairs into an env file.

    Existing keys in *updates* are replaced in-place; new keys are appended.
    All other content (comments, blanks, other keys) is preserved.
    File is written with owner-only permissions (0o600).
    """
    existing_lines: list[str] = []
    try:
        with open(path, encoding="utf-8") as fh:
            existing_lines = fh.readlines()
    except FileNotFoundError:
        pass

    updated_keys: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}\n")

    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        f = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1  # ownership transferred to f
        with f:
            f.writelines(new_lines)
    except Exception:
        if fd != -1:
            os.close(fd)
        raise


def ensure_env_file_secrets(
    env_file: str = ".env",
    weak_values: frozenset[str] | None = None,
) -> dict[str, str]:
    """Check JWT_SECRET_KEY and AUTH_ENCRYPTION_SECRET for weak or placeholder values.

    If weak values are detected, generates cryptographically strong replacements,
    merges them into *env_file* (creating the file if it does not exist), and
    patches ``os.environ`` so the running process picks them up without restart.

    Set ``MCPGATEWAY_AUTO_INIT_SECRETS=false`` to disable this behaviour (e.g.
    when secrets are injected via Vault or Kubernetes secrets and disk writes
    are undesirable).

    Returns a dict of ``{KEY: generated_value}`` for every key that was regenerated.
    Returns ``{}`` if all secrets are already strong or auto-init is disabled.
    """
    if os.environ.get("MCPGATEWAY_AUTO_INIT_SECRETS", "true").lower() == "false":
        return {}

    if weak_values is None:
        weak_values = _WEAK_VALUES

    env_file_values = _read_env_file(env_file)
    # Keys whose weak value came from os.environ only — patch environ, skip disk write.
    env_only: dict[str, str] = {}
    # Keys whose weak value came from .env (or was absent) — write to disk + environ.
    file_generated: dict[str, str] = {}

    for field, nbytes in _SECRET_FIELDS.items():
        # os.environ takes priority over .env (mirrors pydantic-settings behaviour)
        env_val = os.environ.get(field)
        current = env_val if env_val is not None else env_file_values.get(field, "changeme")
        if current.lower() in weak_values or current.lower().startswith("__replace_me__"):
            new_val = generate_token(nbytes)
            if env_val is not None and field not in env_file_values:
                # Weak value came from os.environ; patching environ is enough.
                # Writing to .env would shadow subsequent env-var injections (Docker/K8s).
                env_only[field] = new_val
            else:
                file_generated[field] = new_val

    # Patch environ for os.environ-sourced values immediately (no disk state to keep
    # consistent).
    for field, val in env_only.items():
        os.environ[field] = val

    # For .env-sourced values: write disk FIRST so that memory and disk are either
    # both updated or neither is (F5 — avoids inconsistent state on write failure).
    if file_generated:
        _merge_env_file(env_file, file_generated)
        for field, val in file_generated.items():
            os.environ[field] = val

    return {**env_only, **file_generated}


def generate_token(nbytes: int) -> str:
    """
    Generate a cryptographically secure token.

    Args:
        nbytes (int): Number of bytes for the token generation.

    Returns:
        str: A URL-safe base64 encoded string.
    """
    return secrets.token_urlsafe(nbytes)


def main() -> None:
    """
    Main entry point for the secrets generation CLI.

    Parses arguments, generates required secrets for the Gateway,
    and handles file I/O operations or stdout printing.
    """
    parser = argparse.ArgumentParser(description="Generate secure secrets for MCP Gateway deployment.")
    parser.add_argument("--output", type=str, default=".env.secrets", help="Output file path")
    parser.add_argument("--force", action="store_true", help="Overwrite existing file if it exists")
    parser.add_argument("--stdout", action="store_true", help="Print secrets to stdout instead of a file")

    args = parser.parse_args()

    # Define the required secrets and their byte lengths
    # 32 bytes -> 43 chars (Keys), 18 bytes -> 24 chars (Passwords)
    secrets_map = {
        "JWT_SECRET_KEY": generate_token(32),
        "AUTH_ENCRYPTION_SECRET": generate_token(32),
        "BASIC_AUTH_PASSWORD": generate_token(18),
        "PLATFORM_ADMIN_PASSWORD": generate_token(18),
    }

    output_lines = [f"{key}={val}" for key, val in secrets_map.items()]
    output_content = "\n".join(output_lines) + "\n"

    # Handle Standard Output
    if args.stdout:
        print(output_content, end="")
        return

    try:
        _write_secrets_file(args.output, output_content, args.force)

        print(f"Secrets written to {args.output}")
        print("\nHow to use this file:")
        print(f"1. Review the generated secrets in {args.output}")
        print("2. Merge these into your production environment or .env file.")
        print("3. IMPORTANT: Keep this file secure and never commit it to Git.")

    except FileExistsError:
        print("Error: File already exists")
        print("Suggest using --force to overwrite")
        sys.exit(1)
    except OSError as e:
        print(f"Error: Could not write to file {args.output}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
