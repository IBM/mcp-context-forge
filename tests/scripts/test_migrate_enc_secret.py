# -*- coding: utf-8 -*-
"""Location: ./tests/scripts/test_migrate_enc_secret.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for mcpgateway.scripts.migrate_enc_secret.

Covers:
- Successful re-encryption of plain text columns
- Idempotency: running twice does not double-encrypt
- Wrong-old-key detection: values encrypted with a different key are reported as errors
- Partial failure handling: errors are counted and non-zero exit returned
- dry-run mode: no writes performed, counts still reported
- JSON (oauth_config) recursive re-encryption
- NULL / plaintext values are skipped harmlessly
- CLI arg validation (missing keys, same keys)
"""

# Standard
import json
import os
import tempfile
from unittest.mock import patch

# Set compliant env vars BEFORE any mcpgateway import so that
# mcpgateway.config.settings does not raise SecurityConfigurationError.
# The test keys themselves are set to compliant NEW_KEY below.
os.environ.setdefault("JWT_SECRET_KEY", "new-strong-key-that-is-long-enough-xxxxx")  # nosec # pragma: allowlist secret
os.environ.setdefault("AUTH_ENCRYPTION_SECRET", "new-strong-key-that-is-long-enough-xxxxx")  # nosec # pragma: allowlist secret

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# First-Party
from mcpgateway.scripts.migrate_enc_secret import (  # noqa: E402
    _accumulate,
    _is_services_auth_blob,
    _reencrypt_oauth_config,
    _reencrypt_services_auth_value,
    _reencrypt_value,
    run_migration,
    main,
)
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.utils.services_auth import decode_auth, encode_auth

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

OLD_KEY = "old-key-that-was-weak-but-long-enough-xx"  # nosec B105  # pragma: allowlist secret
NEW_KEY = "new-strong-key-that-is-long-enough-xxxxx"  # nosec B105  # pragma: allowlist secret
OTHER_KEY = "completely-different-key-for-testing-xxx"  # nosec B105  # pragma: allowlist secret


@pytest.fixture()
def old_svc():
    """EncryptionService for the old key."""
    return get_encryption_service(OLD_KEY)


@pytest.fixture()
def new_svc():
    """EncryptionService for the new key."""
    return get_encryption_service(NEW_KEY)


@pytest.fixture()
def other_svc():
    """EncryptionService for an unrelated key (simulates wrong-key scenario)."""
    return get_encryption_service(OTHER_KEY)


# ---------------------------------------------------------------------------
# Minimal in-memory SQLite database with the expected tables
# ---------------------------------------------------------------------------

def _setup_db(db_path: str | None = None):
    """Create minimal tables needed for migration tests.

    Uses a file-based SQLite database so that run_migration (which creates its
    own engine/sessions internally) can share the same persistent state as the
    test's verification session.

    Args:
        db_path: Optional path for the SQLite file. When None, a temp file is created.

    Returns:
        tuple: (engine, SessionLocal, db_url)
    """
    if db_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        tmp.close()
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False}, echo=False)
    with engine.connect() as conn:
        # oauth_tokens
        conn.execute(
            __import__("sqlalchemy").text(
                """
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    id TEXT PRIMARY KEY,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT
                )
                """
            )
        )
        # sso_providers
        conn.execute(
            __import__("sqlalchemy").text(
                """
                CREATE TABLE IF NOT EXISTS sso_providers (
                    id TEXT PRIMARY KEY,
                    client_secret_encrypted TEXT NOT NULL
                )
                """
            )
        )
        # gateways with oauth_config JSON
        conn.execute(
            __import__("sqlalchemy").text(
                """
                CREATE TABLE IF NOT EXISTS gateways (
                    id TEXT PRIMARY KEY,
                    oauth_config TEXT
                )
                """
            )
        )
        conn.commit()
    return engine, sessionmaker(bind=engine, autocommit=False, autoflush=False), db_url


def _make_sa_db(db_path: str | None = None):
    """Create minimal tables needed for services_auth migration tests.

    Args:
        db_path: Optional path for the SQLite file.

    Returns:
        tuple: (engine, SessionLocal, db_url)
    """
    if db_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        tmp.close()
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False}, echo=False)
    with engine.connect() as conn:
        conn.execute(
            __import__("sqlalchemy").text(
                """
                CREATE TABLE IF NOT EXISTS tools (
                    id TEXT PRIMARY KEY,
                    auth_type TEXT,
                    auth_value TEXT
                )
                """
            )
        )
        conn.execute(
            __import__("sqlalchemy").text(
                """
                CREATE TABLE IF NOT EXISTS a2a_agents (
                    id TEXT PRIMARY KEY,
                    auth_type TEXT,
                    auth_value TEXT,
                    auth_query_params TEXT
                )
                """
            )
        )
        conn.execute(
            __import__("sqlalchemy").text(
                """
                CREATE TABLE IF NOT EXISTS a2a_agent_auth (
                    id TEXT PRIMARY KEY,
                    a2a_agent_id TEXT,
                    auth_type TEXT,
                    auth_value TEXT,
                    auth_query_params TEXT
                )
                """
            )
        )
        conn.execute(
            __import__("sqlalchemy").text(
                """
                CREATE TABLE IF NOT EXISTS gateways (
                    id TEXT PRIMARY KEY,
                    oauth_config TEXT,
                    auth_query_params TEXT
                )
                """
            )
        )
        conn.execute(
            __import__("sqlalchemy").text(
                """
                CREATE TABLE IF NOT EXISTS llm_providers (
                    id TEXT PRIMARY KEY,
                    api_key TEXT
                )
                """
            )
        )
        conn.commit()
    return engine, sessionmaker(bind=engine, autocommit=False, autoflush=False), db_url


# ---------------------------------------------------------------------------
# _reencrypt_value unit tests
# ---------------------------------------------------------------------------


class TestReencryptValue:
    """Unit tests for _reencrypt_value()."""

    def test_migrates_value_encrypted_under_old_key(self, old_svc, new_svc):
        """A value encrypted under old_key is decrypted and re-encrypted under new_key."""
        plaintext = "super-secret-token-value"  # nosec B105  # pragma: allowlist secret
        old_cipher = old_svc.encrypt_secret(plaintext)

        new_val, status = _reencrypt_value(old_cipher, old_svc, new_svc)

        assert status == "migrated"
        assert new_svc.is_encrypted(new_val)
        assert new_svc.decrypt_secret(new_val) == plaintext

    def test_skips_null(self, old_svc, new_svc):
        """NULL values are skipped without error."""
        new_val, status = _reencrypt_value(None, old_svc, new_svc)
        assert status == "skipped_null"
        assert new_val is None

    def test_skips_empty_string(self, old_svc, new_svc):
        """Empty-string values are skipped without error."""
        new_val, status = _reencrypt_value("", old_svc, new_svc)
        assert status == "skipped_null"

    def test_skips_plaintext(self, old_svc, new_svc):
        """Plaintext values that are not encrypted are skipped."""
        new_val, status = _reencrypt_value("plaintext-value", old_svc, new_svc)
        assert status == "skipped_plaintext"
        assert new_val == "plaintext-value"

    def test_idempotent_already_new_key(self, old_svc, new_svc):
        """A value already encrypted under new_key is skipped (idempotent)."""
        plaintext = "already-migrated-value"  # nosec B105  # pragma: allowlist secret
        new_cipher = new_svc.encrypt_secret(plaintext)

        new_val, status = _reencrypt_value(new_cipher, old_svc, new_svc)

        assert status == "skipped_already_new"
        assert new_val == new_cipher  # unchanged

    def test_wrong_old_key_returns_error(self, other_svc, new_svc):
        """A value encrypted with a different (unrelated) key returns an error status."""
        plaintext = "encrypted-with-wrong-key"  # nosec B105  # pragma: allowlist secret
        wrong_cipher = other_svc.encrypt_secret(plaintext)

        # old_svc uses OLD_KEY which is different from other_svc (OTHER_KEY)
        old_svc = get_encryption_service(OLD_KEY)
        _new_val, status = _reencrypt_value(wrong_cipher, old_svc, new_svc)

        assert status.startswith("error:")


# ---------------------------------------------------------------------------
# _reencrypt_oauth_config unit tests
# ---------------------------------------------------------------------------


class TestReencryptOauthConfig:
    """Unit tests for _reencrypt_oauth_config()."""

    def test_migrates_sensitive_keys(self, old_svc, new_svc):
        """Sensitive keys in oauth_config are re-encrypted."""
        secret = "oauth-client-secret-value"  # nosec B105  # pragma: allowlist secret
        config = {
            "grant_type": "client_credentials",
            "client_id": "my-client",
            "client_secret": old_svc.encrypt_secret(secret),
        }

        new_config, migrated, skipped, errors = _reencrypt_oauth_config(config, old_svc, new_svc)

        assert migrated == 1
        assert errors == 0
        assert new_svc.is_encrypted(new_config["client_secret"])
        assert new_svc.decrypt_secret(new_config["client_secret"]) == secret
        # Non-sensitive keys are unchanged
        assert new_config["client_id"] == "my-client"
        assert new_config["grant_type"] == "client_credentials"

    def test_skips_non_sensitive_keys(self, old_svc, new_svc):
        """Non-sensitive keys are left untouched."""
        config = {"client_id": "abc", "token_url": "https://example.com/token"}

        new_config, migrated, skipped, errors = _reencrypt_oauth_config(config, old_svc, new_svc)

        assert migrated == 0
        assert errors == 0
        assert new_config == config

    def test_nested_dict(self, old_svc, new_svc):
        """Sensitive keys nested inside dicts are also re-encrypted."""
        secret = "nested-secret"  # nosec B105  # pragma: allowlist secret
        config = {
            "credentials": {
                "client_secret": old_svc.encrypt_secret(secret),
            }
        }

        new_config, migrated, skipped, errors = _reencrypt_oauth_config(config, old_svc, new_svc)

        assert migrated == 1
        assert new_svc.decrypt_secret(new_config["credentials"]["client_secret"]) == secret

    def test_list_of_configs(self, old_svc, new_svc):
        """Lists are traversed recursively."""
        secret = "list-secret"  # nosec B105  # pragma: allowlist secret
        config = [{"client_secret": old_svc.encrypt_secret(secret)}]

        new_config, migrated, _s, errors = _reencrypt_oauth_config(config, old_svc, new_svc)

        assert migrated == 1
        assert isinstance(new_config, list)
        assert new_svc.decrypt_secret(new_config[0]["client_secret"]) == secret

    def test_none_config(self, old_svc, new_svc):
        """None config is returned unchanged with zero counts."""
        new_config, migrated, skipped, errors = _reencrypt_oauth_config(None, old_svc, new_svc)
        assert new_config is None
        assert migrated == skipped == errors == 0

    def test_scalar_config(self, old_svc, new_svc):
        """Scalar (non-dict, non-list) configs are returned unchanged."""
        new_config, migrated, skipped, errors = _reencrypt_oauth_config("just-a-string", old_svc, new_svc)
        assert new_config == "just-a-string"
        assert migrated == skipped == errors == 0


# ---------------------------------------------------------------------------
# run_migration integration tests (in-memory SQLite)
# ---------------------------------------------------------------------------


class TestRunMigration:
    """Integration tests for run_migration() against in-memory SQLite."""

    def _seed_oauth_tokens(self, session: Session, old_svc, rows: list[tuple]):
        """Insert rows into oauth_tokens.

        Args:
            session: Active SQLAlchemy session.
            old_svc: Encryption service to encrypt tokens.
            rows: List of (id, access_token_plaintext, refresh_token_plaintext_or_none).
        """
        from sqlalchemy import text  # pylint: disable=import-outside-toplevel

        for row_id, at, rt in rows:
            enc_at = old_svc.encrypt_secret(at)
            enc_rt = old_svc.encrypt_secret(rt) if rt else None
            session.execute(
                text("INSERT INTO oauth_tokens (id, access_token, refresh_token) VALUES (:id, :at, :rt)"),
                {"id": row_id, "at": enc_at, "rt": enc_rt},
            )
        session.commit()

    def test_successful_migration(self, tmp_path):
        """Happy path: rows are re-encrypted and commit succeeds."""
        _engine, SessionLocal, db_url = _setup_db(str(tmp_path / "test.db"))
        old_svc = get_encryption_service(OLD_KEY)

        with SessionLocal() as session:
            self._seed_oauth_tokens(session, old_svc, [("1", "access-tok-1", "refresh-tok-1"), ("2", "access-tok-2", None)])

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)

        assert rc == 0

        # Verify rows are now under new key
        new_svc = get_encryption_service(NEW_KEY)
        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            rows = session.execute(text("SELECT id, access_token, refresh_token FROM oauth_tokens ORDER BY id")).fetchall()
            assert len(rows) == 2
            assert new_svc.decrypt_secret(rows[0][1]) == "access-tok-1"
            assert new_svc.decrypt_secret(rows[0][2]) == "refresh-tok-1"
            assert new_svc.decrypt_secret(rows[1][1]) == "access-tok-2"
            assert rows[1][2] is None  # NULL stays NULL

    def test_idempotent_second_run(self, tmp_path):
        """Running migration twice produces no errors and no double-encryption."""
        _engine, SessionLocal, db_url = _setup_db(str(tmp_path / "test.db"))
        old_svc = get_encryption_service(OLD_KEY)

        with SessionLocal() as session:
            self._seed_oauth_tokens(session, old_svc, [("1", "idempotent-tok", None)])

        # First run
        rc1 = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc1 == 0

        # Second run — should be a no-op
        rc2 = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc2 == 0

        # Value is still readable and second run was truly a no-op
        new_svc = get_encryption_service(NEW_KEY)
        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT access_token FROM oauth_tokens WHERE id = '1'")).fetchone()
            assert new_svc.decrypt_secret(row[0]) == "idempotent-tok"

    def test_dry_run_makes_no_changes(self, tmp_path):
        """Dry-run mode reports counts but writes nothing."""
        _engine, SessionLocal, db_url = _setup_db(str(tmp_path / "test.db"))
        old_svc = get_encryption_service(OLD_KEY)

        with SessionLocal() as session:
            self._seed_oauth_tokens(session, old_svc, [("1", "dry-run-tok", None)])

        rc = run_migration(db_url, OLD_KEY, NEW_KEY, dry_run=True)
        assert rc == 0

        # Value is still under OLD key, not migrated
        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT access_token FROM oauth_tokens WHERE id = '1'")).fetchone()
            # Should still be encrypted under old key (dry run → not re-encrypted)
            assert old_svc.is_encrypted(row[0])
            assert old_svc.decrypt_secret(row[0]) == "dry-run-tok"

    def test_empty_database_succeeds(self, tmp_path):
        """Empty tables return rc=0 with zero migrated."""
        _engine, _SessionLocal, db_url = _setup_db(str(tmp_path / "test.db"))
        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

    def test_missing_tables_are_skipped(self, tmp_path):
        """Tables that don't exist (e.g. optional features) are silently skipped."""
        # Empty file-based DB with no tables
        db_url = f"sqlite:///{tmp_path / 'empty.db'}"
        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

    def test_json_oauth_config_migrated(self, tmp_path):
        """oauth_config JSON with sensitive keys is re-encrypted."""
        _engine, SessionLocal, db_url = _setup_db(str(tmp_path / "test.db"))
        old_svc = get_encryption_service(OLD_KEY)
        new_svc = get_encryption_service(NEW_KEY)

        secret = "gateway-client-secret"  # nosec B105  # pragma: allowlist secret
        config = json.dumps({"client_id": "cid", "client_secret": old_svc.encrypt_secret(secret)})

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO gateways (id, oauth_config) VALUES (:id, :cfg)"), {"id": "gw1", "cfg": config})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT oauth_config FROM gateways WHERE id = 'gw1'")).fetchone()
            stored = json.loads(row[0])
            assert new_svc.decrypt_secret(stored["client_secret"]) == secret


    def test_partial_failure_rolls_back_all_changes(self, tmp_path):
        """If any row errors, the entire transaction is rolled back — no partial state."""
        _engine, SessionLocal, db_url = _setup_db(str(tmp_path / "test.db"))
        old_svc = get_encryption_service(OLD_KEY)
        other_svc = get_encryption_service(OTHER_KEY)

        # Row 1: properly encrypted under OLD_KEY — would migrate fine on its own
        # Row 2: encrypted under OTHER_KEY (not OLD_KEY) — will cause a decrypt error
        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            enc_good = old_svc.encrypt_secret("good-token")
            enc_bad = other_svc.encrypt_secret("bad-token")  # wrong key
            session.execute(text("INSERT INTO oauth_tokens (id, access_token, refresh_token) VALUES ('good', :v, NULL)"), {"v": enc_good})
            session.execute(text("INSERT INTO oauth_tokens (id, access_token, refresh_token) VALUES ('bad', :v, NULL)"), {"v": enc_bad})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)

        # Must return error exit code
        assert rc == 1

        # Both rows must still be in their original state — no partial migration
        new_svc = get_encryption_service(NEW_KEY)
        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row_good = session.execute(text("SELECT access_token FROM oauth_tokens WHERE id = 'good'")).fetchone()
            row_bad = session.execute(text("SELECT access_token FROM oauth_tokens WHERE id = 'bad'")).fetchone()

            # 'good' row must NOT have been migrated (rolled back)
            assert old_svc.decrypt_secret(row_good[0]) == "good-token", "good row was committed despite rollback"
            with pytest.raises(Exception):
                new_svc.decrypt_secret(row_good[0])  # must not decrypt under new key

            # 'bad' row is still under the wrong key (unchanged)
            assert other_svc.decrypt_secret(row_bad[0]) == "bad-token"

    def test_idempotent_second_run_migrates_zero(self, tmp_path):
        """Second run reports migrated=0 — nothing is re-encrypted again."""
        _engine, SessionLocal, db_url = _setup_db(str(tmp_path / "test.db"))
        old_svc = get_encryption_service(OLD_KEY)

        with SessionLocal() as session:
            self._seed_oauth_tokens(session, old_svc, [("1", "idem-check-tok", None)])

        # First run — should migrate 1 value
        rc1 = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc1 == 0

        # Capture the second run's output to confirm migrated=0
        import io, contextlib  # pylint: disable=import-outside-toplevel,multiple-imports
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc2 = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc2 == 0
        output = buf.getvalue()
        assert "Values migrated: 0" in output, f"Expected 0 migrated on second run, got:\n{output}"
        assert "Nothing to migrate" in output or "0" in output

        # Value still readable under new key
        new_svc = get_encryption_service(NEW_KEY)
        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT access_token FROM oauth_tokens WHERE id = '1'")).fetchone()
            assert new_svc.decrypt_secret(row[0]) == "idem-check-tok"


# ---------------------------------------------------------------------------
# services_auth helpers unit tests
# ---------------------------------------------------------------------------


class TestIsServicesAuthBlob:
    """Unit tests for _is_services_auth_blob()."""

    def test_valid_blob_detected(self):
        """A value produced by encode_auth must be detected as a services_auth blob."""
        blob = encode_auth({"Authorization": "Bearer tok123"})
        assert _is_services_auth_blob(blob) is True

    def test_short_string_rejected(self):
        """Strings below the minimum length threshold are not blobs."""
        assert _is_services_auth_blob("short") is False

    def test_non_base64url_chars_rejected(self):
        """Strings containing '+', '/' or '=' (standard base64) are not blobs."""
        assert _is_services_auth_blob("abc+def/ghi=") is False

    def test_empty_string_rejected(self):
        assert _is_services_auth_blob("") is False

    def test_none_like_rejected(self):
        assert _is_services_auth_blob(None) is False  # type: ignore[arg-type]

    def test_v2_enc_service_prefix_rejected(self):
        """EncryptionService 'v2:{...}' tokens contain '{' and are not base64url-clean."""
        assert _is_services_auth_blob("v2:{nonce:aabbcc,ciphertext:ddeeff}") is False

    def test_plaintext_word_rejected(self):
        assert _is_services_auth_blob("Bearer token123") is False  # space is not base64url


class TestReencryptServicesAuthValue:
    """Unit tests for _reencrypt_services_auth_value()."""

    def test_migrates_value_encrypted_under_old_secret(self):
        """A blob encrypted with the old secret is re-encrypted under the new one."""
        payload = {"Authorization": "Bearer super-secret-token"}
        old_blob = encode_auth(payload, secret=OLD_KEY)

        new_blob, status = _reencrypt_services_auth_value(old_blob, OLD_KEY, NEW_KEY)

        assert status == "migrated"
        assert _is_services_auth_blob(new_blob)
        # Must be decodable with the new key and contain the original payload
        assert decode_auth(new_blob, secret=NEW_KEY) == payload

    def test_idempotent_already_new_key(self):
        """A blob already encrypted under the new key is skipped."""
        payload = {"X-API-Key": "already-rotated"}
        new_blob = encode_auth(payload, secret=NEW_KEY)

        result, status = _reencrypt_services_auth_value(new_blob, OLD_KEY, NEW_KEY)

        assert status == "skipped_already_new"
        assert result == new_blob  # unchanged

    def test_skips_null(self):
        _, status = _reencrypt_services_auth_value(None, OLD_KEY, NEW_KEY)
        assert status == "skipped_null"

    def test_skips_empty_string(self):
        _, status = _reencrypt_services_auth_value("", OLD_KEY, NEW_KEY)
        assert status == "skipped_null"

    def test_skips_plaintext(self):
        """A plain string that is not a base64url blob is skipped."""
        val, status = _reencrypt_services_auth_value("Bearer plaintext", OLD_KEY, NEW_KEY)
        assert status == "skipped_plaintext"
        assert val == "Bearer plaintext"

    def test_wrong_old_key_returns_error(self):
        """A blob encrypted with a third key returns an error status."""
        payload = {"key": "value"}
        blob = encode_auth(payload, secret=OTHER_KEY)

        _, status = _reencrypt_services_auth_value(blob, OLD_KEY, NEW_KEY)

        assert status.startswith("error:")

    def test_old_and_new_keys_produce_independent_blobs(self):
        """The migrated blob is NOT identical to the original (random nonce)."""
        payload = {"X-Token": "abc123"}
        old_blob = encode_auth(payload, secret=OLD_KEY)

        new_blob, status = _reencrypt_services_auth_value(old_blob, OLD_KEY, NEW_KEY)

        assert status == "migrated"
        assert new_blob != old_blob


# ---------------------------------------------------------------------------
# services_auth run_migration integration tests
# ---------------------------------------------------------------------------


class TestRunMigrationServicesAuth:
    """Integration tests for the services_auth path in run_migration()."""

    def test_migrates_tools_auth_value(self, tmp_path):
        """tools.auth_value blobs are re-encrypted under the new key."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        payload = {"Authorization": "Bearer secret-tool-token"}
        old_blob = encode_auth(payload, secret=OLD_KEY)

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO tools (id, auth_type, auth_value) VALUES ('t1', 'bearer', :v)"), {"v": old_blob})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT auth_value FROM tools WHERE id = 't1'")).fetchone()
            assert decode_auth(row[0], secret=NEW_KEY) == payload

    def test_migrates_a2a_agents_auth_value(self, tmp_path):
        """a2a_agents.auth_value blobs are re-encrypted."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        payload = {"X-API-Key": "agent-api-key"}  # pragma: allowlist secret
        old_blob = encode_auth(payload, secret=OLD_KEY)

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO a2a_agents (id, auth_type, auth_value) VALUES ('a1', 'api_key', :v)"), {"v": old_blob})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT auth_value FROM a2a_agents WHERE id = 'a1'")).fetchone()
            assert decode_auth(row[0], secret=NEW_KEY) == payload

    def test_migrates_a2a_agent_auth_auth_value(self, tmp_path):
        """a2a_agent_auth.auth_value blobs are re-encrypted."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        payload = {"Authorization": "Bearer agent-auth-tok"}
        old_blob = encode_auth(payload, secret=OLD_KEY)

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(
                text("INSERT INTO a2a_agent_auth (id, a2a_agent_id, auth_type, auth_value) VALUES ('aa1', 'a1', 'bearer', :v)"),
                {"v": old_blob},
            )
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT auth_value FROM a2a_agent_auth WHERE id = 'aa1'")).fetchone()
            assert decode_auth(row[0], secret=NEW_KEY) == payload

    def test_migrates_llm_providers_api_key(self, tmp_path):
        """llm_providers.api_key blobs are re-encrypted."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        payload = {"api_key": "sk-supersecret"}  # pragma: allowlist secret
        old_blob = encode_auth(payload, secret=OLD_KEY)

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO llm_providers (id, api_key) VALUES ('lp1', :v)"), {"v": old_blob})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT api_key FROM llm_providers WHERE id = 'lp1'")).fetchone()
            assert decode_auth(row[0], secret=NEW_KEY) == payload

    def test_migrates_gateways_auth_query_params(self, tmp_path):
        """gateways.auth_query_params JSON dict values are re-encrypted."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        param_payload = {"api_token": "qp-secret"}
        old_blob = encode_auth(param_payload, secret=OLD_KEY)
        qp_json = json.dumps({"api_token": old_blob})

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO gateways (id, auth_query_params) VALUES ('gw1', :v)"), {"v": qp_json})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT auth_query_params FROM gateways WHERE id = 'gw1'")).fetchone()
            stored = json.loads(row[0])
            assert decode_auth(stored["api_token"], secret=NEW_KEY) == param_payload

    def test_migrates_a2a_agents_auth_query_params(self, tmp_path):
        """a2a_agents.auth_query_params JSON dict values are re-encrypted."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        param_payload = {"token": "qp-agent-tok"}
        old_blob = encode_auth(param_payload, secret=OLD_KEY)
        qp_json = json.dumps({"token": old_blob})

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(
                text("INSERT INTO a2a_agents (id, auth_type, auth_query_params) VALUES ('a2', 'query_param', :v)"),
                {"v": qp_json},
            )
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT auth_query_params FROM a2a_agents WHERE id = 'a2'")).fetchone()
            stored = json.loads(row[0])
            assert decode_auth(stored["token"], secret=NEW_KEY) == param_payload

    def test_services_auth_idempotent_second_run(self, tmp_path):
        """Running migration twice on services_auth columns produces no errors."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        payload = {"Authorization": "Bearer idem-tok"}
        old_blob = encode_auth(payload, secret=OLD_KEY)

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO tools (id, auth_type, auth_value) VALUES ('t2', 'bearer', :v)"), {"v": old_blob})
            session.commit()

        assert run_migration(db_url, OLD_KEY, NEW_KEY) == 0
        assert run_migration(db_url, OLD_KEY, NEW_KEY) == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT auth_value FROM tools WHERE id = 't2'")).fetchone()
            assert decode_auth(row[0], secret=NEW_KEY) == payload

    def test_services_auth_dry_run_no_changes(self, tmp_path):
        """Dry-run does not modify services_auth columns."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        payload = {"Authorization": "Bearer dry-tok"}
        old_blob = encode_auth(payload, secret=OLD_KEY)

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO tools (id, auth_type, auth_value) VALUES ('t3', 'bearer', :v)"), {"v": old_blob})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY, dry_run=True)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT auth_value FROM tools WHERE id = 't3'")).fetchone()
            # Still encrypted under old key
            assert decode_auth(row[0], secret=OLD_KEY) == payload

    def test_null_services_auth_columns_skipped(self, tmp_path):
        """NULL auth_value / api_key is skipped without error."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO tools (id, auth_type, auth_value) VALUES ('t4', NULL, NULL)"))
            session.execute(text("INSERT INTO llm_providers (id, api_key) VALUES ('lp2', NULL)"))
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0


# ---------------------------------------------------------------------------
# _accumulate helper
# ---------------------------------------------------------------------------


def test_accumulate():
    """_accumulate adds sub-counters into the total."""
    total: dict = {}
    _accumulate(total, {"found": 5, "migrated": 3, "skipped": 1, "errors": 1})
    _accumulate(total, {"found": 2, "migrated": 2, "skipped": 0, "errors": 0})
    assert total == {"found": 7, "migrated": 5, "skipped": 1, "errors": 1}


# ---------------------------------------------------------------------------
# CLI argument validation via main()
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for the CLI entry-point argument validation."""

    def test_missing_old_key_exits_1(self, capsys):
        """Missing --old-key causes sys.exit(1)."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                with patch("sys.argv", ["migrate_enc_secret", "--new-key", NEW_KEY]):
                    main()
        assert exc_info.value.code == 1

    def test_missing_new_key_exits_1(self, capsys):
        """Missing --new-key causes sys.exit(1)."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                with patch("sys.argv", ["migrate_enc_secret", "--old-key", OLD_KEY]):
                    main()
        assert exc_info.value.code == 1

    def test_same_old_and_new_key_exits_1(self, capsys):
        """Identical --old-key and --new-key causes sys.exit(1)."""
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["migrate_enc_secret", "--old-key", OLD_KEY, "--new-key", OLD_KEY]):
                main()
        assert exc_info.value.code == 1

    def test_env_var_fallback(self, tmp_path):
        """OLD_AUTH_ENCRYPTION_SECRET / NEW_AUTH_ENCRYPTION_SECRET env vars used as fallback."""
        import os  # pylint: disable=import-outside-toplevel

        # Use a temp file DB so run_migration sees a persistent, empty database
        db_url = f"sqlite:///{tmp_path / 'env_fallback.db'}"
        env = {
            "OLD_AUTH_ENCRYPTION_SECRET": OLD_KEY,  # pragma: allowlist secret
            "NEW_AUTH_ENCRYPTION_SECRET": NEW_KEY,  # pragma: allowlist secret
            "DATABASE_URL": db_url,
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("sys.argv", ["migrate_enc_secret"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        # Should exit 0 (empty DB → nothing to migrate → success)
        assert exc_info.value.code == 0

    def test_new_key_too_short_exits_1(self, capsys):
        """--new-key shorter than MIN_SECRET_LENGTH rejects before touching the DB."""
        short_key = "tooshort"  # nosec B105  # pragma: allowlist secret
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["migrate_enc_secret", "--old-key", OLD_KEY, "--new-key", short_key]):
                main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "too short" in captured.err

    def test_new_key_weak_value_exits_1(self, capsys):
        """--new-key matching a known-weak value rejects before touching the DB."""
        # Must be ≥ 32 chars so the length check passes and the weak-value check fires.
        weak_key = "my-test-key-but-now-longer-than-32-bytes"  # nosec B105  # pragma: allowlist secret
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["migrate_enc_secret", "--old-key", OLD_KEY, "--new-key", weak_key]):
                main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "known-weak" in captured.err

    def test_new_key_low_entropy_exits_1(self, capsys):
        """--new-key with low entropy (all same char) rejects before touching the DB."""
        low_entropy_key = "a" * 40  # nosec B105  # pragma: allowlist secret
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["migrate_enc_secret", "--old-key", OLD_KEY, "--new-key", low_entropy_key]):
                main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "low entropy" in captured.err
