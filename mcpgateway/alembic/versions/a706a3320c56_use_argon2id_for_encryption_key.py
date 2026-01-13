# -*- coding: utf-8 -*-
"""Use Argon2id for encryption key

Revision ID: a706a3320c56
Revises: h2b3c4d5e6f7
Create Date: 2025-10-30 15:31:25.115536

"""

# Standard
import base64
import logging
import os
from typing import Optional, Sequence, Union

# Third-Party
from alembic import op
from argon2.low_level import hash_secret_raw, Type
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import orjson
import sqlalchemy as sa
from sqlalchemy import text

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = "a706a3320c56"
down_revision: Union[str, Sequence[str], None] = "h2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def reencrypt_with_argon2id(encrypted_text: str) -> str:
    """Re-encrypts an existing encrypted text using Argon2id KDF.

    Args:
        encrypted_text: The original encrypted text using PBKDF2HMAC.

    Returns:
        A JSON string containing the Argon2id re-encrypted token and parameters.
    """
    encryption_secret = settings.auth_encryption_secret.get_secret_value().encode()
    original_kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"mcp_gateway_oauth",  # Fixed salt for consistency
        iterations=100000,
    )
    original_key = base64.urlsafe_b64encode(original_kdf.derive(encryption_secret))
    original_fernet = Fernet(original_key)
    original_encrypted_bytes = base64.urlsafe_b64decode(encrypted_text.encode())
    original_decrypted_bytes = original_fernet.decrypt(original_encrypted_bytes)

    time_cost = getattr(settings, "argon2id_time_cost", 3)
    memory_cost = getattr(settings, "argon2id_memory_cost", 65536)
    parallelism = getattr(settings, "argon2id_parallelism", 1)
    hash_len = 32

    salt = os.urandom(16)
    argon2id_raw = hash_secret_raw(
        secret=encryption_secret,
        salt=salt,
        time_cost=time_cost,
        memory_cost=memory_cost,  # KiB
        parallelism=parallelism,
        hash_len=hash_len,
        type=Type.ID,
    )
    argon2id_key = base64.urlsafe_b64encode(argon2id_raw)
    argon2id_fernet = Fernet(argon2id_key)
    argon2id_encrypted_bytes = argon2id_fernet.encrypt(original_decrypted_bytes)
    return orjson.dumps(
        {
            "kdf": "argon2id",
            "t": time_cost,
            "m": memory_cost,
            "p": parallelism,
            "salt": base64.b64encode(salt).decode(),
            "token": argon2id_encrypted_bytes.decode(),
        }
    ).decode()


def reencrypt_with_pbkdf2hmac(argon2id_bundle: str) -> Optional[str]:
    """Re-encrypts an Argon2id encrypted bundle back to PBKDF2HMAC.

    Args:
        argon2id_bundle: The JSON string containing Argon2id encrypted data.

    Returns:
        A PBKDF2HMAC re-encrypted token.

    Raises:
        ValueError: If the input is not a valid Argon2id bundle.
    """
    try:
        argon2id_data = orjson.loads(argon2id_bundle)
        if argon2id_data.get("kdf") != "argon2id":
            raise ValueError("Not an Argon2id bundle")

        encryption_secret = settings.auth_encryption_secret.get_secret_value().encode()
        salt = base64.b64decode(argon2id_data["salt"])
        time_cost = argon2id_data["t"]
        memory_cost = argon2id_data["m"]
        parallelism = argon2id_data["p"]
        argon2id_raw = hash_secret_raw(
            secret=encryption_secret,
            salt=salt,
            time_cost=time_cost,
            memory_cost=memory_cost,  # KiB
            parallelism=parallelism,
            hash_len=32,
            type=Type.ID,
        )
        argon2id_key = base64.urlsafe_b64encode(argon2id_raw)
        argon2id_fernet = Fernet(argon2id_key)
        argon2id_encrypted_bytes = argon2id_data["token"].encode()
        decrypted_bytes = argon2id_fernet.decrypt(argon2id_encrypted_bytes)

        original_kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"mcp_gateway_oauth",  # Fixed salt for consistency
            iterations=100000,
        )
        original_key = base64.urlsafe_b64encode(original_kdf.derive(encryption_secret))
        original_fernet = Fernet(original_key)
        original_encrypted_bytes = original_fernet.encrypt(decrypted_bytes)
        return base64.urlsafe_b64encode(original_encrypted_bytes).decode()
    except Exception as e:
        raise ValueError("Invalid Argon2id bundle") from e


def _reflect(conn):
    """Reflect relevant tables.

    Args:
        conn: The database connection.

    Returns:
        A dict of reflected tables.
    """
    md = sa.MetaData()
    gateways = sa.Table("gateways", md, autoload_with=conn)
    a2a_agents = sa.Table("a2a_agents", md, autoload_with=conn)
    return {"gateways": gateways, "a2a_agents": a2a_agents}


def _is_json(col):
    """Check if a column is of JSON type.

    Args:
        col: The column to check.

    Returns:
        True if the column is of JSON type.
    """
    return isinstance(col.type, sa.JSON)


def _looks_argon2_bundle(val: Optional[str]) -> bool:
    """Heuristic for Argon2id bundle format (JSON with kdf=argon2id).

    Args:
        val: The encrypted value.

    Returns:
        True if it looks like an Argon2id encrypted token.
    """
    if not val:
        return False
    # Fast path: Fernet tokens usually start with 'gAAAAA'; Argon2 bundle is JSON
    if val and val[:1] in ("{", "["):
        try:
            obj = orjson.loads(val)
            return isinstance(obj, dict) and obj.get("kdf") == "argon2id"
        except Exception:
            return False
    return False


def _looks_legacy_pbkdf2_token(val: Optional[str]) -> bool:
    """Heuristic for legacy PBKDF2 format (base64-wrapped Fernet token string, not JSON).

    Args:
        val: The encrypted value.

    Returns:
        True if it looks like a legacy PBKDF2 encrypted token.
    """
    if not val or not isinstance(val, str):
        return False
    # Legacy column stored base64(urlsafe) of the Fernet token (which is itself base64 bytes),
    # so it's NOT JSON and usually not starting with '{'
    return not val.startswith("{")


def _upgrade_value(old: Optional[str]) -> Optional[str]:
    """PBKDF2 -> Argon2id bundle, when needed.

    Args:
        old: The existing encrypted value.

    Returns:
        The re-encrypted value using Argon2id, or None if no change is needed.
    """
    if not old:
        return None
    if _looks_argon2_bundle(old):
        return None  # already migrated
    if not _looks_legacy_pbkdf2_token(old):
        return None  # unknown format; skip
    try:
        return reencrypt_with_argon2id(old)
    except Exception as e:
        logger.warning("Upgrade skip (cannot re-encrypt PBKDF2 value): %s", e)
        return None


def _downgrade_value(old: Optional[str]) -> Optional[str]:
    """Argon2id bundle -> PBKDF2 legacy, when needed.

    Args:
        old: The existing encrypted value.

    Returns:
        The re-encrypted value using PBKDF2HMAC, or None if no change is needed.
    """
    if not old:
        return None
    if not _looks_argon2_bundle(old):
        return None  # not an Argon2 bundle
    try:
        return reencrypt_with_pbkdf2hmac(old)
    except Exception as e:
        logger.warning("Downgrade skip (cannot re-encrypt Argon2 bundle): %s", e)
        return None


def _upgrade_json_client_secret(conn, table):
    """Upgrade JSON client_secret fields in the given table.

    Args:
        conn: The database connection.
        table: The table to upgrade.
    """
    t = table
    sel = sa.select(t.c.id, t.c.oauth_config).where(t.c.oauth_config.isnot(None))
    for row in conn.execute(sel).mappings():
        rid = row["id"]
        cfg = row["oauth_config"]
        if isinstance(cfg, str):
            try:
                cfg = orjson.loads(cfg)
            except orjson.JSONDecodeError as e:
                logger.warning("Skipping %s.id=%s: invalid JSON (%s)", table, rid, e)
                continue
        if not isinstance(cfg, dict):
            continue

        old = cfg.get("client_secret")
        new = _upgrade_value(old)  # your helper
        if not new:
            continue

        cfg["client_secret"] = new
        value = cfg if _is_json(t.c.oauth_config) else orjson.dumps(cfg).decode()
        upd = sa.update(t).where(t.c.id == rid).values(oauth_config=value)
        conn.execute(upd)


def _downgrade_json_client_secret(conn, table):
    """Downgrade JSON client_secret fields in the given table.

    Args:
        conn: The database connection.
        table: The table to downgrade.
    """
    t = table
    sel = sa.select(t.c.id, t.c.oauth_config).where(t.c.oauth_config.isnot(None))
    for row in conn.execute(sel).mappings():
        rid = row["id"]
        cfg = row["oauth_config"]
        if isinstance(cfg, str):
            try:
                cfg = orjson.loads(cfg)
            except orjson.JSONDecodeError as e:
                logger.warning("Skipping %s.id=%s: invalid JSON (%s)", table, rid, e)
                continue
        if not isinstance(cfg, dict):
            continue

        old = cfg.get("client_secret")
        new = _downgrade_value(old)  # your helper
        if not new:
            continue

        cfg["client_secret"] = new
        value = cfg if _is_json(t.c.oauth_config) else orjson.dumps(cfg).decode()
        upd = sa.update(t).where(t.c.id == rid).values(oauth_config=value)
        conn.execute(upd)


def upgrade() -> None:
    """Use Argon2id KDF for encryption key re-encryption."""
    bind = op.get_bind()

    conn = op.get_bind()
    t = _reflect(conn)

    # JSON: gateways.oauth_config.client_secret
    _upgrade_json_client_secret(conn, t["gateways"])

    # JSON: a2a_agents.oauth_config.client_secret
    _upgrade_json_client_secret(conn, t["a2a_agents"])

    # oauth_tokens: access_token, refresh_token
    rows = (
        bind.execute(
            text(
                """
        SELECT id, access_token, refresh_token
        FROM oauth_tokens
        WHERE (access_token IS NOT NULL OR refresh_token IS NOT NULL)
    """
            )
        )
        .mappings()
        .all()
    )

    for r in rows:
        tid = r["id"]
        at = r["access_token"]
        rt = r["refresh_token"]
        nat = _upgrade_value(at)
        nrt = _upgrade_value(rt)
        if nat or nrt:
            bind.execute(
                text(
                    """
                    UPDATE oauth_tokens
                    SET access_token  = COALESCE(:nat, access_token),
                        refresh_token = COALESCE(:nrt, refresh_token)
                    WHERE id = :id
                """
                ),
                {"nat": nat, "nrt": nrt, "id": tid},
            )

    # registered_oauth_clients: client_secret_encrypted, registration_access_token_encrypted
    rows = (
        bind.execute(
            text(
                """
        SELECT id, client_secret_encrypted, registration_access_token_encrypted
        FROM registered_oauth_clients
        WHERE client_secret_encrypted IS NOT NULL
           OR registration_access_token_encrypted IS NOT NULL
    """
            )
        )
        .mappings()
        .all()
    )

    for r in rows:
        rid = r["id"]
        cs = r["client_secret_encrypted"]
        rat = r["registration_access_token_encrypted"]
        ncs = _upgrade_value(cs)
        nrat = _upgrade_value(rat)
        if ncs or nrat:
            bind.execute(
                text(
                    """
                    UPDATE registered_oauth_clients
                    SET client_secret_encrypted = COALESCE(:ncs, client_secret_encrypted),
                        registration_access_token_encrypted = COALESCE(:nrat, registration_access_token_encrypted)
                    WHERE id = :id
                """
                ),
                {"ncs": ncs, "nrat": nrat, "id": rid},
            )

    # sso_providers: client_secret_encrypted
    rows = (
        bind.execute(
            text(
                """
        SELECT id, client_secret_encrypted
        FROM sso_providers
        WHERE client_secret_encrypted IS NOT NULL
    """
            )
        )
        .mappings()
        .all()
    )

    for r in rows:
        sid = r["id"]
        cs = r["client_secret_encrypted"]
        ncs = _upgrade_value(cs)
        if ncs:
            bind.execute(
                text(
                    """
                    UPDATE sso_providers
                    SET client_secret_encrypted = :ncs
                    WHERE id = :id
                """
                ),
                {"ncs": ncs, "id": sid},
            )

    logger.info("Upgrade complete: PBKDF2 -> Argon2id bundle re-encryption.")


def downgrade() -> None:
    """Revert to PBKDF2HMAC KDF for encryption key re-encryption."""
    bind = op.get_bind()

    # JSON: gateways.oauth_config.client_secret
    _downgrade_json_client_secret(bind, "gateways")

    # JSON: a2a_agents.oauth_config.client_secret
    _downgrade_json_client_secret(bind, "a2a_agents")

    # oauth_tokens: access_token, refresh_token
    rows = (
        bind.execute(
            text(
                """
        SELECT id, access_token, refresh_token
        FROM oauth_tokens
        WHERE (access_token IS NOT NULL OR refresh_token IS NOT NULL)
    """
            )
        )
        .mappings()
        .all()
    )

    for r in rows:
        tid = r["id"]
        at = r["access_token"]
        rt = r["refresh_token"]
        nat = _downgrade_value(at)
        nrt = _downgrade_value(rt)
        if nat or nrt:
            bind.execute(
                text(
                    """
                    UPDATE oauth_tokens
                    SET access_token  = COALESCE(:nat, access_token),
                        refresh_token = COALESCE(:nrt, refresh_token)
                    WHERE id = :id
                """
                ),
                {"nat": nat, "nrt": nrt, "id": tid},
            )

    # registered_oauth_clients: client_secret_encrypted, registration_access_token_encrypted
    rows = (
        bind.execute(
            text(
                """
        SELECT id, client_secret_encrypted, registration_access_token_encrypted
        FROM registered_oauth_clients
        WHERE client_secret_encrypted IS NOT NULL
           OR registration_access_token_encrypted IS NOT NULL
    """
            )
        )
        .mappings()
        .all()
    )

    for r in rows:
        rid = r["id"]
        cs = r["client_secret_encrypted"]
        rat = r["registration_access_token_encrypted"]
        ncs = _downgrade_value(cs)
        nrat = _downgrade_value(rat)
        if ncs or nrat:
            bind.execute(
                text(
                    """
                    UPDATE registered_oauth_clients
                    SET client_secret_encrypted = COALESCE(:ncs, client_secret_encrypted),
                        registration_access_token_encrypted = COALESCE(:nrat, registration_access_token_encrypted)
                    WHERE id = :id
                """
                ),
                {"ncs": ncs, "nrat": nrat, "id": rid},
            )

    # sso_providers: client_secret_encrypted
    rows = (
        bind.execute(
            text(
                """
        SELECT id, client_secret_encrypted
        FROM sso_providers
        WHERE client_secret_encrypted IS NOT NULL
    """
            )
        )
        .mappings()
        .all()
    )

    for r in rows:
        sid = r["id"]
        cs = r["client_secret_encrypted"]
        ncs = _downgrade_value(cs)
        if ncs:
            bind.execute(
                text(
                    """
                    UPDATE sso_providers
                    SET client_secret_encrypted = :ncs
                    WHERE id = :id
                """
                ),
                {"ncs": ncs, "id": sid},
            )

    logger.info("Downgrade complete: Argon2id bundle -> PBKDF2 legacy re-encryption.")
