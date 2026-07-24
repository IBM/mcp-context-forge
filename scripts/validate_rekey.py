#!/usr/bin/env python3
"""Post-rotation validation for AUTH_ENCRYPTION_SECRET.

Run this script after every key rotation, before restarting the routercore container.
All checks must pass. Any failure means the rekey migration is incomplete or incorrect.

Usage:
    python3 scripts/validate_rekey.py OLD_SECRET NEW_SECRET DATABASE_URL

    OLD_SECRET  The previous AUTH_ENCRYPTION_SECRET value (what was in the container before rotation)
    NEW_SECRET  The new AUTH_ENCRYPTION_SECRET value (what will be in the container after restart)
    DATABASE_URL postgresql+psycopg://user:pass@host:port/dbname

Exit codes:
    0  All checks passed — safe to restart
    1  One or more checks failed — do not restart until repaired

Background:
    ContextForge stores encrypted auth credentials in two distinct schemes that must
    never be conflated during a rekey:

    A. services_auth  (gateway/tool auth_value columns)
       key    = SHA256(AUTH_ENCRYPTION_SECRET.encode())
       format = base64url(nonce[12] + aesgcm_ciphertext)
       used   = mcpgateway/utils/services_auth.py decode_auth / encode_auth

    B. encryption_service  (other encrypted fields, e.g. oauth_config secrets)
       key    = Argon2id(AUTH_ENCRYPTION_SECRET)
       format = "v2:{...json...}"
       used   = mcpgateway/services/encryption_service.py

    Mixing these layers (e.g. passing an AES-GCM blob through encrypt_secret) produces
    double-wrapped values that look valid in the DB but raise InvalidTag at runtime.
    See the 2026-06-26 incident postmortem in the session audit log for details.
"""
import sys
import re
import base64
import hashlib
import json as json_mod

FAIL = "\033[31mFAIL\033[0m"
OK   = "\033[32m OK \033[0m"


def die(msg: str) -> None:
    print(f"\n{FAIL}  {msg}", file=sys.stderr)
    sys.exit(1)


if len(sys.argv) != 4:
    print(__doc__)
    sys.exit(2)

OLD_SECRET, NEW_SECRET, DATABASE_URL = sys.argv[1], sys.argv[2], sys.argv[3]

if OLD_SECRET == NEW_SECRET:
    die("OLD_SECRET and NEW_SECRET are identical — rotation did not change the key")

# Parse DSN
dsn = re.sub(r"postgresql\+psycopg://([^:]+):([^@]+)@([^/]+)/(.+)", r"host=\3 dbname=\4 user=\1 password=\2", DATABASE_URL)
dsn = re.sub(r"host=([^:]+):(\d+)", r"host=\1 port=\2", dsn)

sys.path.insert(0, "/app")
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.utils.services_auth import decode_auth, encode_auth
import psycopg

old_fernet = get_encryption_service(OLD_SECRET)
new_fernet = get_encryption_service(NEW_SECRET)

# Tables using AES-GCM (services_auth) for their auth columns
AESGCM_COLS = [
    ("gateways",  "id", "name", ["auth_value", "oauth_config", "auth_query_params"]),
    ("tools",     "id", "name", ["auth_value"]),
    ("servers",   "id", "name", ["oauth_config"]),
    ("a2a_agents","id", "name", ["auth_value", "oauth_config"]),
]

failures = 0
warnings = 0


def check(label: str, passed: bool, detail: str = "") -> None:
    global failures
    tag = OK if passed else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{tag}] {label}{suffix}")
    if not passed:
        failures += 1


def is_v2_fernet(val: str) -> bool:
    return isinstance(val, str) and val.startswith("v2:")


def is_json_quoted(val: str) -> bool:
    """Detect accidentally JSON-encoded strings: '"v2:{...}"' or '"base64..."'."""
    return isinstance(val, str) and val.startswith('"') and val.endswith('"')


def is_encrypted_auth_blob(val) -> bool:
    """Return True only if val looks like an actual AES-GCM auth blob.

    JSON columns can legitimately hold {} (no OAuth), json null (→ Python None),
    or other non-encrypted values. Only base64url strings of sufficient length
    are candidate encrypted blobs.
    """
    if not isinstance(val, str):
        return False
    if not val or val in ("{}", "null", "[]"):
        return False
    # AES-GCM blobs are base64url: alphabet A-Z a-z 0-9 - _ (no spaces, no colons)
    # v2: Fernet blobs start with "v2:" and are detected separately
    if val.startswith("v2:") or val.startswith('"'):
        return False  # Fernet or JSON-quoted — not a raw AES-GCM blob
    return len(val) >= 20  # minimum: 12-byte nonce + 1 byte data + 16-byte tag → 29 bytes → ~39 base64 chars


def probe_aesgcm(val, secret: str) -> bool:
    if not is_encrypted_auth_blob(val):
        return False
    try:
        result = decode_auth(val, secret=secret)
        return isinstance(result, dict) and bool(result)
    except Exception:
        return False


with psycopg.connect(dsn) as conn:
    print("\n=== 1. Invariant: no column contains a value decodable by the OLD secret ===")
    print("    (all AES-GCM auth columns must have been re-keyed away from OLD_SECRET)\n")

    for table, pk, name_col, columns in AESGCM_COLS:
        for col in columns:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {pk}, {name_col}, {col} FROM {table} WHERE {col} IS NOT NULL")
                rows = cur.fetchall()
            blobs = [(row[0], row[1], row[2]) for row in rows if is_encrypted_auth_blob(row[2])]
            if not blobs:
                print(f"  [ OK ] {table}.{col}: 0 encrypted rows — skip")
                continue
            bad = [(rid, name) for rid, name, val in blobs if probe_aesgcm(val, OLD_SECRET)]
            check(
                f"{table}.{col}: {len(blobs)} encrypted rows, none decodable with old secret",
                len(bad) == 0,
                f"still old-key: {[n for _,n in bad[:3]]}" if bad else "",
            )

    print("\n=== 2. Invariant: all encrypted AES-GCM rows decode with the NEW secret ===\n")

    for table, pk, name_col, columns in AESGCM_COLS:
        for col in columns:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {pk}, {name_col}, {col} FROM {table} WHERE {col} IS NOT NULL")
                rows = cur.fetchall()
            blobs = [(row[0], row[1], row[2]) for row in rows if is_encrypted_auth_blob(row[2])]
            if not blobs:
                print(f"  [ OK ] {table}.{col}: 0 encrypted rows — skip")
                continue
            bad = [(rid, name) for rid, name, val in blobs if not probe_aesgcm(val, NEW_SECRET)]
            check(
                f"{table}.{col}: {len(blobs)} encrypted rows, all decode with new secret",
                len(bad) == 0,
                f"undecryptable: {[n for _,n in bad[:3]]}" if bad else "",
            )

    print("\n=== 3. Invariant: AES-GCM columns are never Fernet-wrapped (v2: prefix) ===\n")

    for table, pk, name_col, columns in AESGCM_COLS:
        for col in columns:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {pk}, {name_col}, {col} FROM {table} WHERE {col} IS NOT NULL")
                rows = cur.fetchall()
            str_rows = [(row[0], row[1], row[2]) for row in rows if isinstance(row[2], str) and row[2]]
            if not str_rows:
                continue
            wrapped = [(rid, name) for rid, name, val in str_rows if is_v2_fernet(val)]
            check(
                f"{table}.{col}: no rows are Fernet-wrapped (v2: prefix)",
                len(wrapped) == 0,
                f"fernet-wrapped: {[n for _,n in wrapped[:3]]}" if wrapped else "",
            )

    print("\n=== 4. Invariant: VARCHAR auth columns are not accidentally JSON-quoted ===\n")
    print("    (first rekey incident wrote \"v2:{...}\" with outer quotes into VARCHAR columns)\n")

    for table, pk, name_col, columns in AESGCM_COLS:
        for col in columns:
            with conn.cursor() as cur:
                # Get column type
                cur.execute(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name=%s AND column_name=%s",
                    (table, col),
                )
                row = cur.fetchone()
                if not row or row[0].lower() not in ("character varying", "text"):
                    continue  # JSON columns handled differently
                cur.execute(f"SELECT {pk}, {name_col}, {col} FROM {table} WHERE {col} IS NOT NULL")
                rows = cur.fetchall()
            if not rows:
                continue
            quoted = [(row[0], row[1]) for row in rows if is_json_quoted(str(row[2]))]
            check(
                f"{table}.{col} (varchar): no rows have JSON-quoted outer wrapping",
                len(quoted) == 0,
                f"json-quoted: {[n for _,n in quoted[:3]]}" if quoted else "",
            )

    print("\n=== 5. Invariant: decode_auth result is a non-empty dict for all encrypted rows ===\n")

    for table, pk, name_col, columns in AESGCM_COLS:
        for col in columns:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {pk}, {name_col}, {col} FROM {table} WHERE {col} IS NOT NULL")
                rows = cur.fetchall()
            blobs = [(row[0], row[1], row[2]) for row in rows if is_encrypted_auth_blob(row[2])]
            if not blobs:
                continue
            non_dict = []
            for rid, name, val in blobs:
                try:
                    result = decode_auth(val, secret=NEW_SECRET)
                    if not isinstance(result, dict) or not result:
                        non_dict.append(name)
                except Exception:
                    pass  # already caught by check 2
            check(
                f"{table}.{col}: decode_auth returns non-empty dict for all encrypted rows",
                len(non_dict) == 0,
                f"non-dict/empty: {non_dict[:3]}" if non_dict else "",
            )


print(f"\n{'='*60}")
if failures == 0:
    print(f"  [{OK}] All checks passed. Safe to restart the container.")
    print(f"{'='*60}\n")
    sys.exit(0)
else:
    print(f"  [{FAIL}] {failures} check(s) failed. Repair before restarting.")
    print(f"{'='*60}\n")
    sys.exit(1)
