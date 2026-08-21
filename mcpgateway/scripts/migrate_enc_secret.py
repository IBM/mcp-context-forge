# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/scripts/migrate_enc_secret.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

AUTH_ENCRYPTION_SECRET migration script — 1.0.7 → 1.0.8+ upgrade path.

Operators who deployed 1.0.7 with a weak ``AUTH_ENCRYPTION_SECRET`` (e.g.
``my-test-salt``) and then upgrade to 1.0.8 face two failure modes:

1. **Startup failure** — the gateway refuses to start because the weak value no
   longer passes the unconditional guardrail.  Fix: set a strong
   ``AUTH_ENCRYPTION_SECRET`` in ``.env`` before starting.

2. **Silent decryption failure** — stored credentials were encrypted under the
   old weak key and will fail to decrypt under the new strong key.  Fix: run
   this script BEFORE starting the gateway with the new key.

Usage::

    # Preferred: supply keys via arguments
    python -m mcpgateway.scripts.migrate_enc_secret \\
        --old-key <old_weak_key> \\
        --new-key <new_strong_key>

    # Falls back to environment variables when arguments are omitted
    OLD_AUTH_ENCRYPTION_SECRET=<old> NEW_AUTH_ENCRYPTION_SECRET=<new> \\
        python -m mcpgateway.scripts.migrate_enc_secret

    # Dry run (read-only, no writes)
    python -m mcpgateway.scripts.migrate_enc_secret \\
        --old-key <old> --new-key <new> --dry-run

    # Override database URL
    python -m mcpgateway.scripts.migrate_enc_secret \\
        --old-key <old> --new-key <new> \\
        --database-url postgresql+psycopg://user:pass@host/db

Affected columns (all encrypted under ``AUTH_ENCRYPTION_SECRET``):

EncryptionService path (``v2:{...}`` format):

+---------------------------+-------------------------------------+
| Table                     | Column(s)                           |
+===========================+=====================================+
| oauth_tokens              | access_token, refresh_token         |
+---------------------------+-------------------------------------+
| registered_oauth_clients  | client_secret_encrypted,            |
|                           | registration_access_token_encrypted |
+---------------------------+-------------------------------------+
| sso_providers             | client_secret_encrypted             |
+---------------------------+-------------------------------------+
| gateways                  | client_key, oauth_config (JSON)     |
+---------------------------+-------------------------------------+
| servers                   | oauth_config (JSON, recursive)      |
+---------------------------+-------------------------------------+
| a2a_agents                | oauth_config (JSON, recursive)      |
+---------------------------+-------------------------------------+
| a2a_agent_auth            | oauth_config (JSON, recursive)      |
+---------------------------+-------------------------------------+

services_auth path (``base64url(nonce+ciphertext)`` format — AES-GCM):

+------------------------------+--------------------------------------------------+
| Table                        | Column(s)                                        |
+==============================+==================================================+
| gateways                     | auth_value (JSON scalar), auth_query_params      |
+------------------------------+--------------------------------------------------+
| tools                        | auth_value, headers (nested envelope JSON)       |
+------------------------------+--------------------------------------------------+
| a2a_agents                   | auth_value, auth_query_params (JSON dict)        |
+------------------------------+--------------------------------------------------+
| a2a_agent_auth               | auth_value, auth_query_params (JSON dict)        |
+------------------------------+--------------------------------------------------+
| a2a_push_notification_configs| auth_token                                       |
+------------------------------+--------------------------------------------------+
| llm_providers                | api_key, config (nested envelope JSON)           |
+------------------------------+--------------------------------------------------+

Note: ``gateways.auth_value`` is ``mapped_column(JSON)`` — the blob is stored
JSON-quoted on disk.  It is handled by a dedicated helper
(``_migrate_services_auth_json_scalar_columns``) that strips the outer JSON
quotes on read and re-applies them on write.  All other ``sa_simple_targets``
entries are ``mapped_column(Text)`` and are handled by the plain helper.

Note: ``tools.headers`` and ``llm_providers.config`` store encrypted values
as nested sentinel-keyed envelopes within a JSON dict:

- ``tools.headers``: ``{"header_name": {"_mcpgateway_encrypted_header_value_v1": "<blob>"}}``
- ``llm_providers.config``: ``{"key": {"_mcpgateway_encrypted_value_v1": "<blob>"}}``

These are handled by ``_migrate_services_auth_sentinel_json_columns``, which
recursively traverses the JSON structure, detects the sentinel dict, and
re-encrypts only the inner blob string.

The script is **idempotent**: if a value is already encrypted under the new key
(or is plaintext / NULL) it is skipped.  Running it twice is safe.

Exit codes:
    0  — all rows migrated successfully (or nothing to migrate)
    1  — one or more rows failed; details printed to stderr
"""

# Standard
import argparse
import base64
import hashlib
import json
import logging
import math
import os
import sys
from typing import Any, Optional

# Third-Party
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# ---------------------------------------------------------------------------
# Security constants — inlined so the script runs against any installed version
# of mcpgateway (including main, which pre-dates the _security_constants refactor).
# ---------------------------------------------------------------------------
_MIN_SECRET_LENGTH: int = 32
_MIN_ENTROPY: float = 3.5
_WEAK_VALUES: tuple = (
    "my-test-key",
    "my-test-key-but-now-longer-than-32-bytes",
    "my-test-salt",
    "changeme",
    "secret",
    "password",
    "test-secret",
    "my-secret",
    "12345678",
)


def calculate_entropy(value: str) -> float:
    """Calculate Shannon entropy of *value*."""
    if not value:
        return 0.0
    probabilities = [value.count(c) / len(value) for c in set(value)]
    return -sum(p * math.log2(p) for p in probabilities)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_Counter = dict  # alias for readability in return types


def _make_services_auth_aesgcm(secret: str):
    """Return an AESGCM instance keyed by SHA-256(secret), matching services_auth.py.

    Args:
        secret: The ``AUTH_ENCRYPTION_SECRET`` passphrase.

    Returns:
        cryptography.hazmat.primitives.ciphers.aead.AESGCM: Cipher instance.
    """
    # Third-Party
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # pylint: disable=import-outside-toplevel

    key = hashlib.sha256(secret.encode()).digest()
    return AESGCM(key)


def _try_decode_services_auth(encoded: str, aesgcm) -> Optional[dict]:
    """Attempt to decode a services_auth ciphertext blob with the given AESGCM instance.

    Args:
        encoded: Base64url-encoded ``nonce(12) + ciphertext`` string.
        aesgcm: An AESGCM instance keyed to the secret being tried.

    Returns:
        dict: Decrypted payload, or ``None`` if decryption fails.
    """
    # Third-Party
    import orjson  # pylint: disable=import-outside-toplevel

    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        combined = base64.urlsafe_b64decode(padded)
        if len(combined) < 13:  # 12-byte nonce + at least 1 byte ciphertext
            return None
        nonce = combined[:12]
        ciphertext = combined[12:]
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return orjson.loads(plaintext)
    except Exception:  # pylint: disable=broad-except
        return None


def _is_services_auth_blob(value: str) -> bool:
    """Return True when *value* looks like a services_auth ciphertext blob.

    services_auth blobs are base64url strings (no padding) that decode to at
    least 13 bytes (12-byte nonce + 1-byte ciphertext minimum).  We check the
    character set and minimum decoded length rather than attempting decryption,
    so this function is cheap and does not require the secret.

    Args:
        value: String to test.

    Returns:
        bool: True when the value matches the services_auth ciphertext shape.
    """
    if not value or len(value) < 18:  # shortest plausible: ceil((12+1)*4/3)=18 chars
        return False
    # base64url alphabet: A-Z a-z 0-9 - _   (no + / or whitespace, no = padding)
    b64url_chars = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    if not all(c in b64url_chars for c in value):
        return False
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        return len(decoded) >= 13
    except Exception:  # pylint: disable=broad-except
        return False


def _reencrypt_services_auth_value(
    value: Optional[str],
    old_secret: str,
    new_secret: str,
) -> tuple[Optional[str], str]:
    """Re-encrypt a single ``services_auth`` ciphertext from *old_secret* to *new_secret*.

    The ``services_auth`` format stores a random-nonce AES-GCM ciphertext of a
    JSON dictionary as a base64url string.  Unlike the ``EncryptionService``
    ``v2:{...}`` format there is no magic prefix — detection is done by shape
    (base64url-decodable, ≥13 bytes) and by attempting decryption with both keys.

    Args:
        value: Raw column value (may be NULL / plaintext / ciphertext).
        old_secret: The ``AUTH_ENCRYPTION_SECRET`` that was used to encrypt *value*.
        new_secret: The new ``AUTH_ENCRYPTION_SECRET`` to re-encrypt under.

    Returns:
        tuple: ``(new_value, status)`` where *status* is one of
        ``"migrated"``, ``"skipped_null"``, ``"skipped_plaintext"``,
        ``"skipped_already_new"``, or ``"error:<message>"``.
    """
    # Third-Party
    import orjson  # pylint: disable=import-outside-toplevel

    if value is None:
        return value, "skipped_null"
    if not isinstance(value, str) or value.strip() == "":
        return value, "skipped_null"

    if not _is_services_auth_blob(value):
        return value, "skipped_plaintext"

    old_aesgcm = _make_services_auth_aesgcm(old_secret)
    new_aesgcm = _make_services_auth_aesgcm(new_secret)

    # Already migrated: decrypts under new key → skip (idempotent).
    payload = _try_decode_services_auth(value, new_aesgcm)
    if payload is not None:
        return value, "skipped_already_new"

    # Decrypt with old key.
    payload = _try_decode_services_auth(value, old_aesgcm)
    if payload is None:
        return value, "error:decrypt_failed:could not decrypt with old key"

    # Re-encrypt with new key using a fresh random nonce.
    try:
        plaintext_bytes = orjson.dumps(payload)
        nonce = os.urandom(12)
        ciphertext = new_aesgcm.encrypt(nonce, plaintext_bytes, None)
        combined = nonce + ciphertext
        encoded = base64.urlsafe_b64encode(combined).rstrip(b"=").decode()
        return encoded, "migrated"
    except Exception as exc:  # pylint: disable=broad-except
        return value, f"error:encrypt_failed:{exc}"


def _migrate_services_auth_simple_columns(
    session: Session,
    table: str,
    id_col: str,
    columns: list[str],
    old_secret: str,
    new_secret: str,
    dry_run: bool,
) -> _Counter:
    """Re-encrypt plain services_auth columns in *table*.

    Args:
        session: Active SQLAlchemy session (no autocommit).
        table: Database table name.
        id_col: Primary key column name for the UPDATE statement.
        columns: List of column names to re-encrypt.
        old_secret: The old ``AUTH_ENCRYPTION_SECRET`` passphrase.
        new_secret: The new ``AUTH_ENCRYPTION_SECRET`` passphrase.
        dry_run: When True, no writes are performed.

    Returns:
        dict: Counters with keys ``found``, ``migrated``, ``skipped``, ``errors``.
    """
    counts: _Counter = {"found": 0, "migrated": 0, "skipped": 0, "errors": 0}

    col_list = ", ".join(columns)
    rows = session.execute(text(f"SELECT {id_col}, {col_list} FROM {table}")).fetchall()  # nosec B608
    counts["found"] = len(rows)

    for row in rows:
        row_id = row[0]
        updates: dict[str, str] = {}
        row_had_error = False

        for i, col in enumerate(columns):
            raw_val = row[i + 1]
            new_val, status = _reencrypt_services_auth_value(raw_val, old_secret, new_secret)
            if status == "migrated":
                updates[col] = new_val
                counts["migrated"] += 1
            elif status.startswith("error:"):
                counts["errors"] += 1
                row_had_error = True
                logger.error("  %s.%s id=%r: %s", table, col, row_id, status)
            else:
                counts["skipped"] += 1

        if updates and not dry_run and not row_had_error:
            set_clause = ", ".join(f"{c} = :{c}" for c in updates)
            params = {**updates, "_id": row_id}
            session.execute(text(f"UPDATE {table} SET {set_clause} WHERE {id_col} = :_id"), params)  # nosec B608

    return counts


def _migrate_services_auth_json_scalar_columns(
    session: Session,
    table: str,
    id_col: str,
    columns: list[str],
    old_secret: str,
    new_secret: str,
    dry_run: bool,
) -> _Counter:
    """Re-encrypt services_auth blobs stored as JSON-quoted scalars.

    Some columns (e.g. ``gateways.auth_value``) are declared
    ``mapped_column(JSON)`` in ``db.py``.  SQLAlchemy serialises the Python
    string value through ``json.dumps()`` on write, so the on-disk
    representation is a JSON-quoted string: ``'"<base64url-blob>"'``.
    A raw ``SELECT`` via ``text()`` returns those outer quotes, which contain
    ``"`` characters that are not in the base64url alphabet, causing
    ``_is_services_auth_blob()`` to classify the value as plaintext and skip it
    — a silent fail-open that leaves the blob under the old key.

    This helper strips the outer JSON quotes on read, re-encrypts the inner
    blob, and writes ``json.dumps(new_blob)`` back so the column round-trips
    correctly under both SQLite and PostgreSQL.

    Args:
        session: Active SQLAlchemy session (no autocommit).
        table: Database table name.
        id_col: Primary key column name for the UPDATE statement.
        columns: List of JSON-scalar column names to re-encrypt.
        old_secret: The old ``AUTH_ENCRYPTION_SECRET`` passphrase.
        new_secret: The new ``AUTH_ENCRYPTION_SECRET`` passphrase.
        dry_run: When True, no writes are performed.

    Returns:
        dict: Counters with keys ``found``, ``migrated``, ``skipped``, ``errors``.
    """
    counts: _Counter = {"found": 0, "migrated": 0, "skipped": 0, "errors": 0}

    col_list = ", ".join(columns)
    rows = session.execute(text(f"SELECT {id_col}, {col_list} FROM {table}")).fetchall()  # nosec B608
    counts["found"] = len(rows)

    for row in rows:
        row_id = row[0]
        updates: dict[str, str] = {}
        row_had_error = False

        for i, col in enumerate(columns):
            raw_val = row[i + 1]

            if raw_val is None:
                counts["skipped"] += 1
                continue

            # Unwrap JSON-quoted scalar: raw_val is either the Python str already
            # (PostgreSQL/psycopg deserialises on read) or a JSON string literal
            # (SQLite raw text). Normalise to bare str in both cases.
            if isinstance(raw_val, str):
                try:
                    inner = json.loads(raw_val)
                except (json.JSONDecodeError, ValueError):
                    inner = raw_val  # already a bare string (PostgreSQL path)
            else:
                inner = raw_val

            if not isinstance(inner, str):
                counts["skipped"] += 1
                continue

            new_val, status = _reencrypt_services_auth_value(inner, old_secret, new_secret)
            if status == "migrated":
                # Re-wrap as JSON scalar so the write round-trips correctly
                # through the JSON column on both SQLite and PostgreSQL.
                updates[col] = json.dumps(new_val)
                counts["migrated"] += 1
            elif status.startswith("error:"):
                counts["errors"] += 1
                row_had_error = True
                logger.error("  %s.%s id=%r: %s", table, col, row_id, status)
            else:
                counts["skipped"] += 1

        if updates and not dry_run and not row_had_error:
            set_clause = ", ".join(f"{c} = :{c}" for c in updates)
            params = {**updates, "_id": row_id}
            session.execute(text(f"UPDATE {table} SET {set_clause} WHERE {id_col} = :_id"), params)  # nosec B608

    return counts


def _migrate_services_auth_json_columns(
    session: Session,
    table: str,
    id_col: str,
    columns: list[str],
    old_secret: str,
    new_secret: str,
    dry_run: bool,
) -> _Counter:
    """Re-encrypt ``auth_query_params`` JSON dicts whose values are services_auth blobs.

    The JSON structure is ``{param_key: services_auth_blob}``.  Each blob value
    is re-encrypted independently; the key is left untouched.

    Args:
        session: Active SQLAlchemy session (no autocommit).
        table: Database table name.
        id_col: Primary key column name.
        columns: List of JSON column names (typically ``auth_query_params``).
        old_secret: The old ``AUTH_ENCRYPTION_SECRET`` passphrase.
        new_secret: The new ``AUTH_ENCRYPTION_SECRET`` passphrase.
        dry_run: When True, no writes are performed.

    Returns:
        dict: Counters with keys ``found``, ``migrated``, ``skipped``, ``errors``.
    """
    counts: _Counter = {"found": 0, "migrated": 0, "skipped": 0, "errors": 0}

    col_list = ", ".join(columns)
    rows = session.execute(text(f"SELECT {id_col}, {col_list} FROM {table}")).fetchall()  # nosec B608
    counts["found"] = len(rows)

    for row in rows:
        row_id = row[0]
        updates: dict = {}

        for i, col in enumerate(columns):
            raw_val = row[i + 1]
            if raw_val is None:
                counts["skipped"] += 1
                continue

            # raw_val may be a dict (SQLAlchemy JSON) or a JSON string
            if isinstance(raw_val, str):
                try:
                    param_dict = json.loads(raw_val)
                except (json.JSONDecodeError, ValueError):
                    counts["skipped"] += 1
                    continue
            else:
                param_dict = raw_val

            if not isinstance(param_dict, dict):
                counts["skipped"] += 1
                continue

            new_dict = {}
            col_migrated = 0
            col_errors = 0
            for param_key, blob in param_dict.items():
                if not isinstance(blob, str):
                    new_dict[param_key] = blob
                    counts["skipped"] += 1
                    continue
                new_blob, status = _reencrypt_services_auth_value(blob, old_secret, new_secret)
                new_dict[param_key] = new_blob
                if status == "migrated":
                    col_migrated += 1
                    counts["migrated"] += 1
                elif status.startswith("error:"):
                    col_errors += 1
                    counts["errors"] += 1
                    logger.error("  %s.%s[%r] id=%r: %s", table, col, param_key, row_id, status)
                else:
                    counts["skipped"] += 1

            if col_migrated > 0 and col_errors == 0:
                updates[col] = json.dumps(new_dict)

        if updates and not dry_run:
            set_clause = ", ".join(f"{c} = :{c}" for c in updates)
            params = {**updates, "_id": row_id}
            session.execute(text(f"UPDATE {table} SET {set_clause} WHERE {id_col} = :_id"), params)  # nosec B608

    return counts


def _reencrypt_sentinel_json(
    node: Any,
    sentinel_key: str,
    old_secret: str,
    new_secret: str,
) -> tuple[Any, int, int, int]:
    """Recursively re-encrypt services_auth blobs stored in sentinel-keyed envelopes.

    Some JSON columns store encrypted values as a dict with a fixed sentinel key:

    - ``tools.headers``:
      ``{"header_name": {"_mcpgateway_encrypted_header_value_v1": "<blob>"}}``
    - ``llm_providers.config``:
      ``{"key": {"_mcpgateway_encrypted_value_v1": "<blob>"}}``

    When a dict node whose **only** key matches *sentinel_key* is encountered,
    its string value is treated as a services_auth blob and re-encrypted.
    All other nodes (dicts, lists, scalars) are traversed recursively.

    Args:
        node: Parsed JSON value (dict, list, or scalar).
        sentinel_key: The marker key that identifies an encrypted envelope.
        old_secret: The old ``AUTH_ENCRYPTION_SECRET`` passphrase.
        new_secret: The new ``AUTH_ENCRYPTION_SECRET`` passphrase.

    Returns:
        tuple: ``(new_node, migrated, skipped, errors)`` counts.
    """
    if isinstance(node, dict):
        # Detect sentinel envelope: exactly one key matching sentinel_key with a str value.
        if list(node.keys()) == [sentinel_key] and isinstance(node.get(sentinel_key), str):
            blob = node[sentinel_key]
            new_blob, status = _reencrypt_services_auth_value(blob, old_secret, new_secret)
            if status == "migrated":
                return {sentinel_key: new_blob}, 1, 0, 0
            if status.startswith("error:"):
                return node, 0, 0, 1
            return node, 0, 1, 0  # skipped_null / skipped_plaintext / skipped_already_new

        # Regular dict — recurse into values.
        result: dict = {}
        migrated = skipped = errors = 0
        for k, v in node.items():
            new_v, m, s, e = _reencrypt_sentinel_json(v, sentinel_key, old_secret, new_secret)
            result[k] = new_v
            migrated += m
            skipped += s
            errors += e
        return result, migrated, skipped, errors

    if isinstance(node, list):
        result_list: list = []
        migrated = skipped = errors = 0
        for item in node:
            new_item, m, s, e = _reencrypt_sentinel_json(item, sentinel_key, old_secret, new_secret)
            result_list.append(new_item)
            migrated += m
            skipped += s
            errors += e
        return result_list, migrated, skipped, errors

    return node, 0, 0, 0


def _migrate_services_auth_sentinel_json_columns(
    session: Session,
    table: str,
    id_col: str,
    columns: list[str],
    sentinel_key: str,
    old_secret: str,
    new_secret: str,
    dry_run: bool,
) -> _Counter:
    """Re-encrypt services_auth blobs nested inside sentinel-envelope JSON columns.

    Handles ``tools.headers`` and ``llm_providers.config`` where the encrypted
    value is wrapped as ``{sentinel_key: "<blob>"}``.  Traverses the full JSON
    structure recursively and re-encrypts every matching envelope.

    Args:
        session: Active SQLAlchemy session (no autocommit).
        table: Database table name.
        id_col: Primary key column name.
        columns: List of JSON column names to process.
        sentinel_key: The envelope marker key (e.g. ``_mcpgateway_encrypted_header_value_v1``).
        old_secret: The old ``AUTH_ENCRYPTION_SECRET`` passphrase.
        new_secret: The new ``AUTH_ENCRYPTION_SECRET`` passphrase.
        dry_run: When True, no writes are performed.

    Returns:
        dict: Counters with keys ``found``, ``migrated``, ``skipped``, ``errors``.
    """
    counts: _Counter = {"found": 0, "migrated": 0, "skipped": 0, "errors": 0}

    col_list = ", ".join(columns)
    rows = session.execute(text(f"SELECT {id_col}, {col_list} FROM {table}")).fetchall()  # nosec B608
    counts["found"] = len(rows)

    for row in rows:
        row_id = row[0]
        updates: dict = {}

        for i, col in enumerate(columns):
            raw_val = row[i + 1]
            if raw_val is None:
                counts["skipped"] += 1
                continue

            if isinstance(raw_val, str):
                try:
                    node = json.loads(raw_val)
                except (json.JSONDecodeError, ValueError):
                    counts["skipped"] += 1
                    continue
            else:
                node = raw_val

            new_node, m, s, e = _reencrypt_sentinel_json(node, sentinel_key, old_secret, new_secret)
            counts["migrated"] += m
            counts["skipped"] += s
            counts["errors"] += e

            if m > 0 and e == 0:
                updates[col] = json.dumps(new_node)

        if updates and not dry_run:
            set_clause = ", ".join(f"{c} = :{c}" for c in updates)
            params = {**updates, "_id": row_id}
            session.execute(text(f"UPDATE {table} SET {set_clause} WHERE {id_col} = :_id"), params)  # nosec B608

    return counts


def _make_engine(database_url: str):
    """Create a SQLAlchemy engine for the given URL.

    Args:
        database_url: SQLAlchemy-compatible database connection URL.

    Returns:
        sqlalchemy.engine.Engine: Connected engine instance.
    """
    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args, echo=False, future=True)


def _reencrypt_value(
    value: Optional[str],
    old_svc,
    new_svc,
) -> tuple[Optional[str], str]:
    """Re-encrypt a single ciphertext value from *old_svc* key to *new_svc* key.

    Args:
        value: Raw column value (may be NULL / plaintext / encrypted).
        old_svc: EncryptionService initialised with the old key.
        new_svc: EncryptionService initialised with the new key.

    Returns:
        tuple: ``(new_value, status)`` where *status* is one of
        ``"migrated"``, ``"skipped_null"``, ``"skipped_plaintext"``,
        ``"skipped_already_new"``, or ``"error:<message>"``.
    """
    if value is None:
        return value, "skipped_null"

    if not isinstance(value, str) or value.strip() == "":
        return value, "skipped_null"

    # Check if this value looks like an encrypted bundle at all.
    if not old_svc.is_encrypted(value) and not new_svc.is_encrypted(value):
        # Plaintext — nothing to do.
        return value, "skipped_plaintext"

    # Already migrated: decrypts successfully under the NEW key → skip (idempotent).
    # Use decrypt_secret() in a silent try/except rather than decrypt_secret_or_plaintext()
    # to avoid the ERROR log that encryption_service emits when decryption fails — this
    # is an expected probe failure (value was encrypted under the old key), not an error.
    if new_svc.is_encrypted(value):
        try:
            new_svc.decrypt_secret(value)
            return value, "skipped_already_new"
        except Exception:  # pylint: disable=broad-except
            pass  # expected: encrypted under old key, not new — fall through

    # Decrypt with old key, re-encrypt with new key.
    try:
        plaintext = old_svc.decrypt_secret(value)
    except Exception as exc:  # pylint: disable=broad-except
        return value, f"error:decrypt_failed:{exc}"

    try:
        new_ciphertext = new_svc.encrypt_secret(plaintext)
    except Exception as exc:  # pylint: disable=broad-except
        return value, f"error:encrypt_failed:{exc}"

    return new_ciphertext, "migrated"


def _reencrypt_oauth_config(config: Any, old_svc, new_svc) -> tuple[Any, int, int, int]:
    """Recursively re-encrypt sensitive keys inside an oauth_config JSON blob.

    Args:
        config: Parsed oauth_config value (dict, list, or scalar).
        old_svc: EncryptionService initialised with the old key.
        new_svc: EncryptionService initialised with the new key.

    Returns:
        tuple: ``(new_config, migrated, skipped, errors)`` counts.
    """
    # First-Party
    from mcpgateway.common.oauth import is_sensitive_oauth_key  # pylint: disable=import-outside-toplevel

    if isinstance(config, dict):
        result: dict = {}
        migrated = skipped = errors = 0
        for key, val in config.items():
            if is_sensitive_oauth_key(key) and isinstance(val, str):
                new_val, status = _reencrypt_value(val, old_svc, new_svc)
                result[key] = new_val
                if status == "migrated":
                    migrated += 1
                elif status.startswith("error:"):
                    errors += 1
                    logger.warning("oauth_config key %r: %s", key, status)
                else:
                    skipped += 1
            elif isinstance(val, (dict, list)):
                new_val, m, s, e = _reencrypt_oauth_config(val, old_svc, new_svc)
                result[key] = new_val
                migrated += m
                skipped += s
                errors += e
            else:
                result[key] = val
        return result, migrated, skipped, errors

    if isinstance(config, list):
        result_list: list = []
        migrated = skipped = errors = 0
        for item in config:
            new_item, m, s, e = _reencrypt_oauth_config(item, old_svc, new_svc)
            result_list.append(new_item)
            migrated += m
            skipped += s
            errors += e
        return result_list, migrated, skipped, errors

    return config, 0, 0, 0


# ---------------------------------------------------------------------------
# Per-table migration functions
# ---------------------------------------------------------------------------


def _migrate_simple_columns(
    session: Session,
    table: str,
    id_col: str,
    columns: list[str],
    old_svc,
    new_svc,
    dry_run: bool,
) -> _Counter:
    """Migrate plain text columns encrypted under *old_svc* to *new_svc*.

    Args:
        session: Active SQLAlchemy session (no autocommit).
        table: Database table name.
        id_col: Primary key column name for the UPDATE statement.
        columns: List of column names to re-encrypt.
        old_svc: EncryptionService initialised with the old key.
        new_svc: EncryptionService initialised with the new key.
        dry_run: When True, no writes are performed.

    Returns:
        dict: Counters with keys ``found``, ``migrated``, ``skipped``, ``errors``.
    """
    counts: _Counter = {"found": 0, "migrated": 0, "skipped": 0, "errors": 0}

    col_list = ", ".join(columns)
    rows = session.execute(text(f"SELECT {id_col}, {col_list} FROM {table}")).fetchall()  # nosec B608 - table/columns are internal constants, not user input
    counts["found"] = len(rows)

    for row in rows:
        row_id = row[0]
        updates: dict[str, str] = {}
        row_had_error = False

        for i, col in enumerate(columns):
            raw_val = row[i + 1]
            new_val, status = _reencrypt_value(raw_val, old_svc, new_svc)
            if status == "migrated":
                updates[col] = new_val
                counts["migrated"] += 1
            elif status.startswith("error:"):
                counts["errors"] += 1
                row_had_error = True
                logger.error("  %s.%s id=%r: %s", table, col, row_id, status)
            else:
                counts["skipped"] += 1

        if updates and not dry_run and not row_had_error:
            set_clause = ", ".join(f"{c} = :{c}" for c in updates)
            params = {**updates, "_id": row_id}
            session.execute(text(f"UPDATE {table} SET {set_clause} WHERE {id_col} = :_id"), params)  # nosec B608

    return counts


def _migrate_json_columns(
    session: Session,
    table: str,
    id_col: str,
    columns: list[str],
    old_svc,
    new_svc,
    dry_run: bool,
) -> _Counter:
    """Migrate JSON oauth_config columns by recursively re-encrypting sensitive keys.

    Args:
        session: Active SQLAlchemy session (no autocommit).
        table: Database table name.
        id_col: Primary key column name for the UPDATE statement.
        columns: List of JSON column names to process.
        old_svc: EncryptionService initialised with the old key.
        new_svc: EncryptionService initialised with the new key.
        dry_run: When True, no writes are performed.

    Returns:
        dict: Counters with keys ``found``, ``migrated``, ``skipped``, ``errors``.
    """
    counts: _Counter = {"found": 0, "migrated": 0, "skipped": 0, "errors": 0}

    col_list = ", ".join(columns)
    rows = session.execute(text(f"SELECT {id_col}, {col_list} FROM {table}")).fetchall()  # nosec B608
    counts["found"] = len(rows)

    for row in rows:
        row_id = row[0]
        updates: dict = {}

        for i, col in enumerate(columns):
            raw_val = row[i + 1]
            if raw_val is None:
                counts["skipped"] += 1
                continue

            # raw_val may be a dict (SQLAlchemy JSON) or a JSON string
            if isinstance(raw_val, str):
                try:
                    config = json.loads(raw_val)
                except (json.JSONDecodeError, ValueError):
                    counts["skipped"] += 1
                    continue
            else:
                config = raw_val

            new_config, m, s, e = _reencrypt_oauth_config(config, old_svc, new_svc)
            counts["migrated"] += m
            counts["skipped"] += s
            counts["errors"] += e

            if m > 0:
                updates[col] = json.dumps(new_config)

        if updates and not dry_run:
            set_clause = ", ".join(f"{c} = :{c}" for c in updates)
            params = {**updates, "_id": row_id}
            session.execute(text(f"UPDATE {table} SET {set_clause} WHERE {id_col} = :_id"), params)  # nosec B608

    return counts


# ---------------------------------------------------------------------------
# Main migration orchestrator
# ---------------------------------------------------------------------------


def run_migration(
    database_url: str,
    old_key: str,
    new_key: str,
    dry_run: bool = False,
    *,
    _engine=None,
    _force: bool = False,
) -> int:
    """Orchestrate the full re-encryption migration pass.

    Discovers every affected table/column, decrypts with *old_key*, and
    re-encrypts with *new_key*.  The entire migration is wrapped in a single
    database transaction that is rolled back on any error (unless ``dry_run``
    is True, in which case no writes happen at all).

    Args:
        database_url: SQLAlchemy-compatible database connection URL.
        old_key: The ``AUTH_ENCRYPTION_SECRET`` previously used to encrypt stored values.
        new_key: The new strong ``AUTH_ENCRYPTION_SECRET`` to use for re-encryption.
        dry_run: When True, reads and reports but does not write any changes.
        _engine: Optional pre-built SQLAlchemy engine (used in tests to share an
            in-memory SQLite instance across calls).
        _force: When True, ``new_key`` may be weak/short; a compliant placeholder is
            used for the Settings import so the validator does not reject the key.

    Returns:
        int: Exit code — ``0`` on success, ``1`` on any failure.
    """
    # Inject compliant values into os.environ before importing mcpgateway modules.
    # encryption_service.py imports mcpgateway.config.settings at module level, which
    # runs validate_security_combinations().  That validator enforces:
    #   - AUTH_ENCRYPTION_SECRET: non-empty, ≥ MIN_SECRET_LENGTH, not weak, entropy ≥ 3.5
    #   - JWT_SECRET_KEY: same
    #   - MIN_SECRET_LENGTH: ge=32 via Field — if operator has raised it, Settings still
    #     only checks against max(min_secret_length, _MIN_SECRET_LENGTH).
    # We pin MIN_SECRET_LENGTH=32 for the import so that an operator-raised floor
    # (e.g. MIN_SECRET_LENGTH=64) does not cause a false SecurityConfigurationError
    # when new_key is a valid 43-char token that satisfies the absolute minimum.
    #
    # When _force=True one of the two keys may be weak/short and would fail Settings
    # validation.  Pick whichever key satisfies the absolute minimum length as the
    # placeholder for the import; both keys are passed directly to
    # get_encryption_service() after the import, so Settings never sees the weak one.
    if _force:
        _import_enc_key = old_key if len(old_key) >= _MIN_SECRET_LENGTH else new_key  # nosec
    else:
        _import_enc_key = new_key  # nosec
    _prev_enc = os.environ.get("AUTH_ENCRYPTION_SECRET")
    _prev_jwt = os.environ.get("JWT_SECRET_KEY")
    _prev_min = os.environ.get("MIN_SECRET_LENGTH")
    os.environ["AUTH_ENCRYPTION_SECRET"] = _import_enc_key  # nosec
    os.environ["MIN_SECRET_LENGTH"] = str(_MIN_SECRET_LENGTH)  # pin to absolute floor for import
    if not _prev_jwt or len(_prev_jwt) < _MIN_SECRET_LENGTH:
        os.environ["JWT_SECRET_KEY"] = _import_enc_key  # nosec — migration tool only, not persisted
    try:
        # First-Party
        from mcpgateway.services.encryption_service import get_encryption_service  # pylint: disable=import-outside-toplevel
    finally:
        # Restore original environment regardless of import success
        if _prev_enc is not None:
            os.environ["AUTH_ENCRYPTION_SECRET"] = _prev_enc
        elif "AUTH_ENCRYPTION_SECRET" in os.environ:
            del os.environ["AUTH_ENCRYPTION_SECRET"]
        if _prev_jwt is not None:
            os.environ["JWT_SECRET_KEY"] = _prev_jwt
        elif "JWT_SECRET_KEY" in os.environ and not _prev_jwt:
            del os.environ["JWT_SECRET_KEY"]
        if _prev_min is not None:
            os.environ["MIN_SECRET_LENGTH"] = _prev_min
        elif "MIN_SECRET_LENGTH" in os.environ:
            del os.environ["MIN_SECRET_LENGTH"]

    old_svc = get_encryption_service(old_key)
    new_svc = get_encryption_service(new_key)

    engine = _engine if _engine is not None else _make_engine(database_url)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    total: _Counter = {"found": 0, "migrated": 0, "skipped": 0, "errors": 0}

    # Tables with plain-text encrypted columns (not JSON blobs) — EncryptionService path
    simple_targets = [
        # (table, id_col, [columns])
        ("oauth_tokens", "id", ["access_token", "refresh_token"]),
        ("registered_oauth_clients", "id", ["client_secret_encrypted", "registration_access_token_encrypted"]),
        ("sso_providers", "id", ["client_secret_encrypted"]),
        ("gateways", "id", ["client_key"]),
    ]

    # Tables whose oauth_config JSON contains recursively-encrypted sensitive keys — EncryptionService path
    json_targets = [
        # (table, id_col, [json_columns])
        ("gateways", "id", ["oauth_config"]),
        ("servers", "id", ["oauth_config"]),
        ("a2a_agents", "id", ["oauth_config"]),
        ("a2a_agent_auth", "id", ["oauth_config"]),
    ]

    # Tables with plain-text services_auth blobs (base64url AES-GCM nonce+ciphertext)
    sa_simple_targets = [
        # (table, id_col, [columns])
        # NOTE: all entries here must be mapped_column(Text), not JSON.
        # JSON-typed columns that hold a services_auth blob scalar belong in
        # sa_json_scalar_targets below so the JSON codec round-trip is applied.
        ("tools", "id", ["auth_value"]),
        ("a2a_agents", "id", ["auth_value"]),
        ("a2a_agent_auth", "id", ["auth_value"]),
        ("a2a_push_notification_configs", "id", ["auth_token"]),
        ("llm_providers", "id", ["api_key"]),
    ]

    # Tables where a services_auth blob is stored as a JSON-quoted scalar
    # (mapped_column(JSON) holding a plain str at runtime).
    # The helper json.loads() on read and json.dumps() on write to preserve
    # the JSON encoding that SQLAlchemy expects for the column type.
    sa_json_scalar_targets = [
        # (table, id_col, [columns])
        ("gateways", "id", ["auth_value"]),
    ]

    # Tables with JSON dicts whose values are services_auth blobs (auth_query_params)
    sa_json_targets = [
        # (table, id_col, [json_columns])
        ("gateways", "id", ["auth_query_params"]),
        ("a2a_agents", "id", ["auth_query_params"]),
        ("a2a_agent_auth", "id", ["auth_query_params"]),
    ]

    # Tables with nested sentinel-envelope JSON columns (services_auth blobs wrapped in
    # {sentinel_key: "<blob>"} dicts).  Each entry adds a (table, id_col, [columns], sentinel_key).
    tool_header_sentinel = "_mcpgateway_encrypted_header_value_v1"
    provider_config_sentinel = "_mcpgateway_encrypted_value_v1"
    sa_sentinel_targets = [
        # (table, id_col, [columns], sentinel_key)
        ("tools", "id", ["headers"], tool_header_sentinel),
        ("llm_providers", "id", ["config"], provider_config_sentinel),
    ]

    session = session_factory()
    try:
        # ------------------------------------------------------------------
        # Check which tables actually exist in this database so the script
        # does not crash on minimal deployments missing optional tables.
        # ------------------------------------------------------------------
        from sqlalchemy import inspect as sa_inspect  # pylint: disable=import-outside-toplevel

        inspector = sa_inspect(engine)
        existing_tables = set(inspector.get_table_names())

        if dry_run:
            logger.info("DRY RUN — no database writes will be performed.")

        for table, id_col, columns in simple_targets:
            if table not in existing_tables:
                logger.info("  %s: table not found — skipping", table)
                continue
            # Only include columns that exist
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            cols = [c for c in columns if c in existing_cols]
            if not cols:
                continue

            logger.info("  Migrating %s [%s] ...", table, ", ".join(cols))
            counts = _migrate_simple_columns(session, table, id_col, cols, old_svc, new_svc, dry_run)
            _accumulate(total, counts)
            logger.info("    → found=%d  migrated=%d  skipped=%d  errors=%d", counts["found"], counts["migrated"], counts["skipped"], counts["errors"])

        for table, id_col, columns in json_targets:
            if table not in existing_tables:
                logger.info("  %s: table not found — skipping", table)
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            cols = [c for c in columns if c in existing_cols]
            if not cols:
                continue

            logger.info("  Migrating %s JSON [%s] ...", table, ", ".join(cols))
            counts = _migrate_json_columns(session, table, id_col, cols, old_svc, new_svc, dry_run)
            _accumulate(total, counts)
            logger.info("    → found=%d  migrated=%d  skipped=%d  errors=%d", counts["found"], counts["migrated"], counts["skipped"], counts["errors"])

        # ------------------------------------------------------------------
        # services_auth path (base64url AES-GCM blobs)
        # ------------------------------------------------------------------
        for table, id_col, columns in sa_simple_targets:
            if table not in existing_tables:
                logger.info("  %s: table not found — skipping", table)
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            cols = [c for c in columns if c in existing_cols]
            if not cols:
                continue

            logger.info("  Migrating %s (services_auth) [%s] ...", table, ", ".join(cols))
            counts = _migrate_services_auth_simple_columns(session, table, id_col, cols, old_key, new_key, dry_run)
            _accumulate(total, counts)
            logger.info("    → found=%d  migrated=%d  skipped=%d  errors=%d", counts["found"], counts["migrated"], counts["skipped"], counts["errors"])

        for table, id_col, columns in sa_json_scalar_targets:
            if table not in existing_tables:
                logger.info("  %s: table not found — skipping", table)
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            cols = [c for c in columns if c in existing_cols]
            if not cols:
                continue

            logger.info("  Migrating %s (services_auth JSON scalar) [%s] ...", table, ", ".join(cols))
            counts = _migrate_services_auth_json_scalar_columns(session, table, id_col, cols, old_key, new_key, dry_run)
            _accumulate(total, counts)
            logger.info("    → found=%d  migrated=%d  skipped=%d  errors=%d", counts["found"], counts["migrated"], counts["skipped"], counts["errors"])

        for table, id_col, columns in sa_json_targets:
            if table not in existing_tables:
                logger.info("  %s: table not found — skipping", table)
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            cols = [c for c in columns if c in existing_cols]
            if not cols:
                continue

            logger.info("  Migrating %s auth_query_params (services_auth) [%s] ...", table, ", ".join(cols))
            counts = _migrate_services_auth_json_columns(session, table, id_col, cols, old_key, new_key, dry_run)
            _accumulate(total, counts)
            logger.info("    → found=%d  migrated=%d  skipped=%d  errors=%d", counts["found"], counts["migrated"], counts["skipped"], counts["errors"])

        for table, id_col, columns, sentinel_key in sa_sentinel_targets:
            if table not in existing_tables:
                logger.info("  %s: table not found — skipping", table)
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            cols = [c for c in columns if c in existing_cols]
            if not cols:
                continue

            logger.info("  Migrating %s sentinel-envelope (services_auth) [%s] ...", table, ", ".join(cols))
            counts = _migrate_services_auth_sentinel_json_columns(session, table, id_col, cols, sentinel_key, old_key, new_key, dry_run)
            _accumulate(total, counts)
            logger.info("    → found=%d  migrated=%d  skipped=%d  errors=%d", counts["found"], counts["migrated"], counts["skipped"], counts["errors"])

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        print()
        print("=" * 60)
        if dry_run:
            print("DRY RUN SUMMARY (no changes written):")
        else:
            print("MIGRATION SUMMARY:")
        print(f"  Rows scanned  : {total['found']}")
        print(f"  Values migrated: {total['migrated']}")
        print(f"  Values skipped : {total['skipped']}")
        print(f"  Errors         : {total['errors']}")
        print("=" * 60)

        if total["errors"] > 0:
            print(f"\n❌  Migration completed with {total['errors']} error(s). Check logs above.", file=sys.stderr)
            session.rollback()
            return 1

        if not dry_run:
            session.commit()
            if total["migrated"] == 0:
                print("\nℹ️   Nothing to migrate — all values are already up to date.")
            else:
                print(f"\n✅  Migration complete — {total['migrated']} value(s) re-encrypted successfully.")
        else:
            session.rollback()
            if total["migrated"] == 0:
                print("\nℹ️   Dry run: nothing would be migrated — all values are already up to date.")
            else:
                print(f"\nℹ️   Dry run: {total['migrated']} value(s) would be re-encrypted.")

        return 0

    except Exception as exc:  # pylint: disable=broad-except
        session.rollback()
        logger.exception("Fatal error during migration: %s", exc)
        print(f"\n❌  Fatal error: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()
        # Only dispose the engine if we created it ourselves; caller-supplied
        # engines (_engine parameter) are managed by the caller.
        if _engine is None:
            engine.dispose()


def _accumulate(total: _Counter, counts: _Counter) -> None:
    """Add per-table counts into the running total.

    Args:
        total: Accumulated counter dict (modified in-place).
        counts: Per-table counter dict to add.
    """
    for key in counts:
        total[key] = total.get(key, 0) + counts[key]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for the encryption-key migration script.

    Parses arguments, validates inputs, and invokes :func:`run_migration`.
    Falls back to ``OLD_AUTH_ENCRYPTION_SECRET`` / ``NEW_AUTH_ENCRYPTION_SECRET``
    environment variables when ``--old-key`` / ``--new-key`` are not supplied.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s  %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(
        description=("Re-encrypt stored credentials from an old AUTH_ENCRYPTION_SECRET to a new one.\n\nRequired for the 1.0.7 → 1.0.8 upgrade when AUTH_ENCRYPTION_SECRET was weak in 1.0.7."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Upgrade sequence:\n"
            "  1. Generate a strong new key:\n"
            "       make init-secrets-patch-env\n"
            "  2. Run this script BEFORE starting the gateway:\n"
            "       python -m mcpgateway.scripts.migrate_enc_secret \\\n"
            "           --old-key <old_weak_key> --new-key <new_strong_key>\n"
            "  3. Start the gateway normally.\n\n"
            "Environment variable fallback:\n"
            "  OLD_AUTH_ENCRYPTION_SECRET=<old> NEW_AUTH_ENCRYPTION_SECRET=<new>\n"
            "  python -m mcpgateway.scripts.migrate_enc_secret\n"
        ),
    )
    parser.add_argument(
        "--old-key",
        type=str,
        default=None,
        help="Old AUTH_ENCRYPTION_SECRET (falls back to OLD_AUTH_ENCRYPTION_SECRET env var)",
    )
    parser.add_argument(
        "--new-key",
        type=str,
        default=None,
        help="New AUTH_ENCRYPTION_SECRET (falls back to NEW_AUTH_ENCRYPTION_SECRET env var)",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Database URL (falls back to DATABASE_URL env var, then sqlite:///./mcp.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Read-only mode: report what would be migrated without writing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help=(
            "Skip strength validation on --new-key. "
            "Use only when intentionally re-encrypting to a weaker key "
            "(e.g. rolling back to a previous key or decrypting to a known-weak value). "
            "⚠️  The resulting database will not start with a gateway that enforces strong secrets."
        ),
    )
    args = parser.parse_args()

    old_key = args.old_key or os.environ.get("OLD_AUTH_ENCRYPTION_SECRET", "")  # pragma: allowlist secret
    new_key = args.new_key or os.environ.get("NEW_AUTH_ENCRYPTION_SECRET", "")  # pragma: allowlist secret

    if not old_key:
        print(
            "❌  --old-key is required (or set OLD_AUTH_ENCRYPTION_SECRET env var).",
            file=sys.stderr,
        )
        parser.print_help(sys.stderr)
        sys.exit(1)

    if not new_key:
        print(
            "❌  --new-key is required (or set NEW_AUTH_ENCRYPTION_SECRET env var).",
            file=sys.stderr,
        )
        parser.print_help(sys.stderr)
        sys.exit(1)

    if old_key == new_key:
        print(
            "❌  --old-key and --new-key are identical — nothing to migrate.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Validate new_key against the same predicate Settings enforces at startup.
    # Catching this before touching the database prevents a completed migration
    # followed by a gateway startup failure.
    # --force bypasses all three checks for deliberate rollback / weak-key scenarios.
    if not args.force:
        _weak_set = frozenset(v.lower() for v in _WEAK_VALUES)
        if len(new_key) < _MIN_SECRET_LENGTH:
            print(
                f"❌  --new-key is too short ({len(new_key)} chars, minimum {_MIN_SECRET_LENGTH}). Generate a strong key with: make init-secrets-patch-env  (or pass --force to skip this check)",
                file=sys.stderr,
            )
            sys.exit(1)
        if new_key.lower() in _weak_set or new_key.lower().startswith("__replace_me__"):
            print(
                "❌  --new-key is a known-weak value. Generate a strong key with: make init-secrets-patch-env  (or pass --force to skip this check)",
                file=sys.stderr,
            )
            sys.exit(1)
        if calculate_entropy(new_key) < _MIN_ENTROPY:
            print(
                f"❌  --new-key has low entropy (score {calculate_entropy(new_key):.2f} < {_MIN_ENTROPY}). "
                f"Generate a strong key with: make init-secrets-patch-env  "
                f"(or pass --force to skip this check)",
                file=sys.stderr,
            )
            sys.exit(1)

    database_url = args.database_url or os.environ.get("DATABASE_URL", "sqlite:///./mcp.db")

    print(f"ContextForge AUTH_ENCRYPTION_SECRET migration — database: {database_url}")
    print(f"  old key: {'*' * min(len(old_key), 8)}...  new key: {'*' * min(len(new_key), 8)}...")
    if args.dry_run:
        print("  mode: DRY RUN (no writes)")
    if args.force:
        print("  ⚠️   --force: new-key strength validation skipped", file=sys.stderr)
    print()

    rc = run_migration(database_url, old_key, new_key, dry_run=args.dry_run, _force=args.force)
    sys.exit(rc)


if __name__ == "__main__":
    main()
