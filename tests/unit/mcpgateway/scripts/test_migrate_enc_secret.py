# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/scripts/test_migrate_enc_secret.py
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
import base64
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
    _reencrypt_sentinel_json,
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
                    auth_value TEXT,
                    headers TEXT
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
                    auth_query_params TEXT,
                    oauth_config TEXT
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
                    client_key TEXT,
                    oauth_config TEXT,
                    auth_value JSON,
                    auth_query_params TEXT
                )
                """
            )
        )
        conn.execute(
            __import__("sqlalchemy").text(
                """
                CREATE TABLE IF NOT EXISTS servers (
                    id TEXT PRIMARY KEY,
                    oauth_config TEXT
                )
                """
            )
        )
        conn.execute(
            __import__("sqlalchemy").text(
                """
                CREATE TABLE IF NOT EXISTS a2a_push_notification_configs (
                    id TEXT PRIMARY KEY,
                    auth_token TEXT
                )
                """
            )
        )
        conn.execute(
            __import__("sqlalchemy").text(
                """
                CREATE TABLE IF NOT EXISTS llm_providers (
                    id TEXT PRIMARY KEY,
                    api_key TEXT,
                    config TEXT
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
        import io
        import contextlib  # pylint: disable=import-outside-toplevel
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
        """Empty string is not a blob."""
        assert _is_services_auth_blob("") is False

    def test_none_like_rejected(self):
        """None is not a blob."""
        assert _is_services_auth_blob(None) is False  # type: ignore[arg-type]

    def test_v2_enc_service_prefix_rejected(self):
        """EncryptionService 'v2:{...}' tokens contain '{' and are not base64url-clean."""
        assert _is_services_auth_blob("v2:{nonce:aabbcc,ciphertext:ddeeff}") is False

    def test_plaintext_word_rejected(self):
        """Space is not a base64url character."""
        assert _is_services_auth_blob("Bearer token123") is False


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
        """None is skipped."""
        _, status = _reencrypt_services_auth_value(None, OLD_KEY, NEW_KEY)
        assert status == "skipped_null"

    def test_skips_empty_string(self):
        """Empty string is skipped."""
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


# ---------------------------------------------------------------------------
# _reencrypt_sentinel_json unit tests (covers list path, error/skip branches)
# ---------------------------------------------------------------------------


class TestReencryptSentinelJson:
    """Unit tests for _reencrypt_sentinel_json()."""

    SENTINEL = "_mcpgateway_encrypted_header_value_v1"

    def test_migrates_sentinel_envelope(self):
        """A sentinel envelope containing an old-key blob is re-encrypted."""
        payload = {"data": "secret-header-value"}
        old_blob = encode_auth(payload, secret=OLD_KEY)
        node = {self.SENTINEL: old_blob}

        new_node, m, s, e = _reencrypt_sentinel_json(node, self.SENTINEL, OLD_KEY, NEW_KEY)

        assert m == 1 and s == 0 and e == 0
        assert decode_auth(new_node[self.SENTINEL], secret=NEW_KEY) == payload

    def test_error_branch_on_wrong_key(self):
        """A blob encrypted with an unrelated key returns errors=1 and leaves node unchanged."""
        blob = encode_auth({"data": "x"}, secret=OTHER_KEY)
        node = {self.SENTINEL: blob}

        new_node, m, s, e = _reencrypt_sentinel_json(node, self.SENTINEL, OLD_KEY, NEW_KEY)

        assert e == 1 and m == 0
        assert new_node == node  # unchanged

    def test_skip_branch_already_new_key(self):
        """A blob already under the new key is skipped (idempotent)."""
        blob = encode_auth({"data": "x"}, secret=NEW_KEY)
        node = {self.SENTINEL: blob}

        new_node, m, s, e = _reencrypt_sentinel_json(node, self.SENTINEL, OLD_KEY, NEW_KEY)

        assert s == 1 and m == 0 and e == 0
        assert new_node == node

    def test_list_of_envelopes(self):
        """A list containing sentinel envelope dicts is traversed and re-encrypted."""
        payload = {"data": "list-item-secret"}
        old_blob = encode_auth(payload, secret=OLD_KEY)
        node = [{self.SENTINEL: old_blob}, "plain-string"]

        new_node, m, s, e = _reencrypt_sentinel_json(node, self.SENTINEL, OLD_KEY, NEW_KEY)

        assert m == 1 and e == 0
        assert isinstance(new_node, list)
        assert decode_auth(new_node[0][self.SENTINEL], secret=NEW_KEY) == payload
        assert new_node[1] == "plain-string"  # scalar left untouched

    def test_non_sentinel_dict_recurses(self):
        """A regular dict without the sentinel key is recursed into."""
        payload = {"data": "nested"}
        old_blob = encode_auth(payload, secret=OLD_KEY)
        node = {"outer_key": {self.SENTINEL: old_blob}, "other": 42}

        new_node, m, s, e = _reencrypt_sentinel_json(node, self.SENTINEL, OLD_KEY, NEW_KEY)

        assert m == 1 and e == 0
        assert decode_auth(new_node["outer_key"][self.SENTINEL], secret=NEW_KEY) == payload
        assert new_node["other"] == 42

    def test_scalar_node_returned_unchanged(self):
        """A scalar value (not dict or list) is returned as-is with zero counts."""
        new_node, m, s, e = _reencrypt_sentinel_json("just-a-string", self.SENTINEL, OLD_KEY, NEW_KEY)
        assert new_node == "just-a-string"
        assert m == s == e == 0


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

    def test_migrates_gateways_auth_value(self, tmp_path):
        """gateways.auth_value blob (bearer token, JSON column) is re-encrypted.

        The fixture uses a real JSON column type so SQLite stores the blob
        JSON-quoted on disk ('"<blob>"') — the shape production always produces.
        The test asserts both that the new key decrypts correctly AND that the
        old key no longer works, confirming re-encryption actually occurred.
        """
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        payload = {"Authorization": "Bearer gateway-bearer-tok"}
        old_blob = encode_auth(payload, secret=OLD_KEY)

        # Insert via json.dumps() to match what SQLAlchemy's JSON column does on write.
        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(
                text("INSERT INTO gateways (id, auth_value) VALUES ('gw-bearer', :v)"),
                {"v": json.dumps(old_blob)},
            )
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT auth_value FROM gateways WHERE id = 'gw-bearer'")).fetchone()
            # raw_val is JSON-quoted; unwrap before decoding
            raw = row[0]
            inner = json.loads(raw) if isinstance(raw, str) and raw.startswith('"') else raw
            assert decode_auth(inner, secret=NEW_KEY) == payload
            # Old key must no longer work — confirms actual re-encryption
            with pytest.raises(Exception):
                decode_auth(inner, secret=OLD_KEY)

    def test_migrates_gateways_auth_value_idempotent(self, tmp_path):
        """Running migration twice on gateways.auth_value produces no errors."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        payload = {"Authorization": "Bearer gateway-idem-tok"}
        old_blob = encode_auth(payload, secret=OLD_KEY)

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(
                text("INSERT INTO gateways (id, auth_value) VALUES ('gw-idem', :v)"),
                {"v": json.dumps(old_blob)},
            )
            session.commit()

        assert run_migration(db_url, OLD_KEY, NEW_KEY) == 0
        assert run_migration(db_url, OLD_KEY, NEW_KEY) == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT auth_value FROM gateways WHERE id = 'gw-idem'")).fetchone()
            raw = row[0]
            inner = json.loads(raw) if isinstance(raw, str) and raw.startswith('"') else raw
            assert decode_auth(inner, secret=NEW_KEY) == payload

    def test_migrates_servers_oauth_config(self, tmp_path):
        """servers.oauth_config sensitive keys are re-encrypted (EncryptionService path)."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        new_svc = get_encryption_service(NEW_KEY)
        old_svc_local = get_encryption_service(OLD_KEY)
        secret = "srv-oauth-client-secret"  # nosec B105  # pragma: allowlist secret
        config = json.dumps({"client_id": "cid", "client_secret": old_svc_local.encrypt_secret(secret)})

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO servers (id, oauth_config) VALUES ('srv1', :cfg)"), {"cfg": config})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT oauth_config FROM servers WHERE id = 'srv1'")).fetchone()
            stored = json.loads(row[0])
            assert new_svc.decrypt_secret(stored["client_secret"]) == secret
            # Old key must no longer work
            with pytest.raises(Exception):
                old_svc_local.decrypt_secret(stored["client_secret"])

    def test_migrates_gateways_client_key(self, tmp_path):
        """gateways.client_key is re-encrypted (EncryptionService path, plain Text column)."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        old_svc_local = get_encryption_service(OLD_KEY)
        new_svc = get_encryption_service(NEW_KEY)
        client_key_plaintext = "client-private-key-plaintext-value"  # nosec B105  # pragma: allowlist secret
        encrypted = old_svc_local.encrypt_secret(client_key_plaintext)

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO gateways (id, client_key) VALUES ('gw-ck', :v)"), {"v": encrypted})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT client_key FROM gateways WHERE id = 'gw-ck'")).fetchone()
            assert new_svc.decrypt_secret(row[0]) == client_key_plaintext
            with pytest.raises(Exception):
                old_svc_local.decrypt_secret(row[0])

    def test_migrates_a2a_push_notification_configs_auth_token(self, tmp_path):
        """a2a_push_notification_configs.auth_token blob is re-encrypted."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        payload = {"token": "webhook-bearer-secret"}  # nosec B105  # pragma: allowlist secret
        old_blob = encode_auth(payload, secret=OLD_KEY)

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(
                text("INSERT INTO a2a_push_notification_configs (id, auth_token) VALUES ('pn1', :v)"),
                {"v": old_blob},
            )
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT auth_token FROM a2a_push_notification_configs WHERE id = 'pn1'")).fetchone()
            assert decode_auth(row[0], secret=NEW_KEY) == payload
            # Old key must no longer work
            with pytest.raises(Exception):
                decode_auth(row[0], secret=OLD_KEY)

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

    def test_migrates_a2a_agents_oauth_config(self, tmp_path):
        """a2a_agents.oauth_config sensitive keys are re-encrypted (EncryptionService path)."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        old_svc_local = get_encryption_service(OLD_KEY)
        new_svc = get_encryption_service(NEW_KEY)
        secret = "a2a-agent-oauth-secret"  # nosec B105  # pragma: allowlist secret
        config = json.dumps({"client_id": "cid", "client_secret": old_svc_local.encrypt_secret(secret)})

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO a2a_agents (id, auth_type, oauth_config) VALUES ('ag1', 'oauth', :cfg)"), {"cfg": config})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT oauth_config FROM a2a_agents WHERE id = 'ag1'")).fetchone()
            stored = json.loads(row[0])
            assert new_svc.decrypt_secret(stored["client_secret"]) == secret
            with pytest.raises(Exception):
                old_svc_local.decrypt_secret(stored["client_secret"])

    def test_migrates_tools_headers(self, tmp_path):
        """tools.headers sentinel-envelope blobs are re-encrypted."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        payload = {"data": "Authorization: Bearer secret-hdr"}
        old_blob = encode_auth(payload, secret=OLD_KEY)
        sentinel = "_mcpgateway_encrypted_header_value_v1"
        headers = json.dumps({"Authorization": {sentinel: old_blob}, "Content-Type": "application/json"})

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO tools (id, auth_type, headers) VALUES ('th1', 'bearer', :h)"), {"h": headers})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT headers FROM tools WHERE id = 'th1'")).fetchone()
            stored = json.loads(row[0])
            # Sentinel envelope re-encrypted under new key
            new_blob = stored["Authorization"][sentinel]
            assert decode_auth(new_blob, secret=NEW_KEY) == payload
            with pytest.raises(Exception):
                decode_auth(new_blob, secret=OLD_KEY)
            # Non-sensitive header left untouched
            assert stored["Content-Type"] == "application/json"

    def test_migrates_llm_providers_config(self, tmp_path):
        """llm_providers.config sentinel-envelope blobs are re-encrypted."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        payload = {"data": "sk-supersecret-api-key"}  # pragma: allowlist secret
        old_blob = encode_auth(payload, secret=OLD_KEY)
        sentinel = "_mcpgateway_encrypted_value_v1"
        config = json.dumps({"model": "gpt-4", "api_key": {sentinel: old_blob}})

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO llm_providers (id, config) VALUES ('lp3', :cfg)"), {"cfg": config})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT config FROM llm_providers WHERE id = 'lp3'")).fetchone()
            stored = json.loads(row[0])
            new_blob = stored["api_key"][sentinel]
            assert decode_auth(new_blob, secret=NEW_KEY) == payload
            with pytest.raises(Exception):
                decode_auth(new_blob, secret=OLD_KEY)
            # Non-sensitive key untouched
            assert stored["model"] == "gpt-4"

    def test_gateways_auth_value_json_scalar_bare_string_path(self, tmp_path):
        """gateways.auth_value: bare string in JSON column (PostgreSQL read path) is handled.

        Inserts a bare blob without json.dumps() so the raw SELECT returns the
        bare string directly (no surrounding JSON quotes), exercising the
        json.loads-fails-fallthrough branch (lines 399-400).
        """
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        payload = {"Authorization": "Bearer bare-path-tok"}
        old_blob = encode_auth(payload, secret=OLD_KEY)

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            # Insert bare blob — simulates PostgreSQL/psycopg deserialized read path.
            session.execute(text("INSERT INTO gateways (id, auth_value) VALUES ('gw-bare', :v)"), {"v": old_blob})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT auth_value FROM gateways WHERE id = 'gw-bare'")).fetchone()
            raw = row[0]
            inner = json.loads(raw) if isinstance(raw, str) and raw.startswith('"') else raw
            assert decode_auth(inner, secret=NEW_KEY) == payload

    def test_gateways_auth_value_json_scalar_non_string_inner_skipped(self, tmp_path):
        """gateways.auth_value: non-string inner value (e.g. JSON number) is skipped.

        Exercises line 402 (raw_val not str) and lines 405-406 (inner not str).
        """
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            # Insert a JSON number — inner will be int, not str → skipped.
            session.execute(text("INSERT INTO gateways (id, auth_value) VALUES ('gw-num', :v)"), {"v": json.dumps(42)})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0  # skipped cleanly, no error

    def test_gateways_auth_value_json_scalar_error_path(self, tmp_path):
        """gateways.auth_value: wrong-key blob triggers error path (lines 415-417)."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        # Encrypt with a third key — neither OLD nor NEW can decrypt it.
        wrong_blob = encode_auth({"x": "y"}, secret=OTHER_KEY)

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO gateways (id, auth_value) VALUES ('gw-err', :v)"), {"v": json.dumps(wrong_blob)})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 1  # error exit — transaction rolled back

    def test_sentinel_json_columns_invalid_json_string_skipped(self, tmp_path):
        """_migrate_services_auth_sentinel_json_columns: invalid JSON string is skipped (lines 628-630)."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            # Insert a raw non-JSON string into tools.headers — json.loads will fail.
            session.execute(text("INSERT INTO tools (id, headers) VALUES ('th-bad', 'not-valid-json{{{')"))
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0  # skipped cleanly

    def test_sentinel_json_columns_dict_raw_val_path(self, tmp_path):
        """_migrate_services_auth_sentinel_json_columns: dict raw_val (PostgreSQL path) is handled (line 632)."""
        _, SessionLocal, db_url = _make_sa_db(str(tmp_path / "sa.db"))
        payload = {"data": "pg-sentinel-tok"}
        old_blob = encode_auth(payload, secret=OLD_KEY)
        sentinel = "_mcpgateway_encrypted_header_value_v1"
        # Insert as a Python dict — SQLAlchemy JSON column returns dict on PostgreSQL.
        # Simulate by inserting JSON-serialised and reading back via SQLAlchemy ORM.
        headers_json = json.dumps({"Authorization": {sentinel: old_blob}})

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            session.execute(text("INSERT INTO tools (id, headers) VALUES ('th-pg', :v)"), {"v": headers_json})
            session.commit()

        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0

        with SessionLocal() as session:
            from sqlalchemy import text  # pylint: disable=import-outside-toplevel

            row = session.execute(text("SELECT headers FROM tools WHERE id = 'th-pg'")).fetchone()
            stored = json.loads(row[0])
            new_blob = stored["Authorization"][sentinel]
            assert decode_auth(new_blob, secret=NEW_KEY) == payload

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

    def test_force_bypasses_short_key_check(self, tmp_path, capsys):
        """--force allows a short --new-key that would otherwise be rejected."""
        short_key = "tooshort"  # nosec B105  # pragma: allowlist secret
        db_url = f"sqlite:///{tmp_path / 'force_short.db'}"
        with patch.dict("os.environ", {"DATABASE_URL": db_url}, clear=False):
            with pytest.raises(SystemExit) as exc_info:
                with patch("sys.argv", ["migrate_enc_secret", "--old-key", OLD_KEY, "--new-key", short_key, "--force"]):
                    main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "too short" not in captured.err

    def test_force_bypasses_weak_key_check(self, tmp_path, capsys):
        """--force allows a known-weak --new-key that would otherwise be rejected."""
        weak_key = "my-test-key-but-now-longer-than-32-bytes"  # nosec B105  # pragma: allowlist secret
        db_url = f"sqlite:///{tmp_path / 'force_weak.db'}"
        with patch.dict("os.environ", {"DATABASE_URL": db_url}, clear=False):
            with pytest.raises(SystemExit) as exc_info:
                with patch("sys.argv", ["migrate_enc_secret", "--old-key", OLD_KEY, "--new-key", weak_key, "--force"]):
                    main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "known-weak" not in captured.err

    def test_force_bypasses_low_entropy_check(self, tmp_path, capsys):
        """--force allows a low-entropy --new-key that would otherwise be rejected."""
        low_entropy_key = "a" * 40  # nosec B105  # pragma: allowlist secret
        db_url = f"sqlite:///{tmp_path / 'force_entropy.db'}"
        with patch.dict("os.environ", {"DATABASE_URL": db_url}, clear=False):
            with pytest.raises(SystemExit) as exc_info:
                with patch("sys.argv", ["migrate_enc_secret", "--old-key", OLD_KEY, "--new-key", low_entropy_key, "--force"]):
                    main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "low entropy" not in captured.err

    def test_force_prints_warning(self, tmp_path, capsys):
        """--force prints a warning to stderr so operators know validation was skipped."""
        short_key = "tooshort"  # nosec B105  # pragma: allowlist secret
        db_url = f"sqlite:///{tmp_path / 'force_warn.db'}"
        with patch.dict("os.environ", {"DATABASE_URL": db_url}, clear=False):
            with pytest.raises(SystemExit):
                with patch("sys.argv", ["migrate_enc_secret", "--old-key", OLD_KEY, "--new-key", short_key, "--force"]):
                    main()
        captured = capsys.readouterr()
        assert "--force" in captured.err

    def test_force_actually_migrates_with_short_key(self, tmp_path):
        """--force + short new key performs a real re-encryption."""
        from mcpgateway.utils.services_auth import encode_auth, decode_auth  # pylint: disable=import-outside-toplevel
        from sqlalchemy import create_engine, text as sa_text  # pylint: disable=import-outside-toplevel
        from sqlalchemy.orm import sessionmaker as sm  # pylint: disable=import-outside-toplevel

        short_key = "tooshort"  # nosec B105  # pragma: allowlist secret
        db_url = f"sqlite:///{tmp_path / 'force_migrate.db'}"

        # Seed a tools row encrypted under OLD_KEY
        engine = create_engine(db_url, connect_args={"check_same_thread": False})
        with engine.connect() as conn:
            conn.execute(sa_text("CREATE TABLE tools (id TEXT PRIMARY KEY, auth_value TEXT)"))
            conn.commit()

        payload = {"Authorization": "Bearer rollback-tok"}
        old_blob = encode_auth(payload, secret=OLD_KEY)
        SessionLocal = sm(bind=engine, autocommit=False, autoflush=False)
        with SessionLocal() as session:
            session.execute(sa_text("INSERT INTO tools (id, auth_value) VALUES ('t1', :v)"), {"v": old_blob})
            session.commit()

        with patch.dict("os.environ", {"DATABASE_URL": db_url}, clear=False):
            with pytest.raises(SystemExit) as exc_info:
                with patch("sys.argv", ["migrate_enc_secret", "--old-key", OLD_KEY, "--new-key", short_key, "--force"]):
                    main()
        assert exc_info.value.code == 0

        # Row should now decrypt under the short key
        with SessionLocal() as session:
            row = session.execute(sa_text("SELECT auth_value FROM tools WHERE id = 't1'")).fetchone()
            assert decode_auth(row[0], secret=short_key) == payload


# ---------------------------------------------------------------------------
# calculate_entropy edge-case (line 119 — empty string early-return)
# ---------------------------------------------------------------------------


def test_calculate_entropy_empty_string():
    """calculate_entropy returns 0.0 for an empty string."""
    from mcpgateway.scripts.migrate_enc_secret import calculate_entropy  # pylint: disable=import-outside-toplevel

    assert calculate_entropy("") == 0.0


# ---------------------------------------------------------------------------
# _try_decode_services_auth — blob too-short decoded branch (line 167)
# ---------------------------------------------------------------------------


def test_try_decode_services_auth_too_short():
    """Blobs that decode to fewer than 13 bytes return None (too-short branch)."""
    from mcpgateway.scripts.migrate_enc_secret import _make_services_auth_aesgcm, _try_decode_services_auth  # pylint: disable=import-outside-toplevel

    aesgcm = _make_services_auth_aesgcm(OLD_KEY)
    # Encode 12 bytes (exactly the nonce size, zero ciphertext bytes) → len < 13
    short_blob = base64.urlsafe_b64encode(b"\x00" * 12).rstrip(b"=").decode()
    assert _try_decode_services_auth(short_blob, aesgcm) is None


# ---------------------------------------------------------------------------
# _is_services_auth_blob — base64 decode exception path (lines 200-201)
# ---------------------------------------------------------------------------


def test_is_services_auth_blob_decode_exception():
    """A string of valid base64url chars that raises on decode returns False."""
    from mcpgateway.scripts.migrate_enc_secret import _is_services_auth_blob  # pylint: disable=import-outside-toplevel
    from unittest.mock import patch as _patch  # pylint: disable=import-outside-toplevel

    # Construct a string that passes the charset check but simulate a decode error
    valid_looking = "A" * 20  # passes length and charset checks
    with _patch("base64.urlsafe_b64decode", side_effect=Exception("forced")):
        assert _is_services_auth_blob(valid_looking) is False


# ---------------------------------------------------------------------------
# _reencrypt_services_auth_value — encrypt failure path (lines 259-260)
# ---------------------------------------------------------------------------


def test_reencrypt_services_auth_encrypt_failure():
    """When re-encryption raises an exception, status starts with 'error:encrypt_failed:'."""
    from unittest.mock import patch as _patch, MagicMock  # pylint: disable=import-outside-toplevel
    from mcpgateway.scripts.migrate_enc_secret import (  # pylint: disable=import-outside-toplevel
        _reencrypt_services_auth_value,
        _make_services_auth_aesgcm,
    )
    from mcpgateway.utils.services_auth import encode_auth  # pylint: disable=import-outside-toplevel

    old_blob = encode_auth({"k": "v"}, secret=OLD_KEY)

    real_old_aesgcm = _make_services_auth_aesgcm(OLD_KEY)
    boom_aesgcm = MagicMock()
    boom_aesgcm.encrypt.side_effect = RuntimeError("forced encrypt failure")

    with _patch(
        "mcpgateway.scripts.migrate_enc_secret._make_services_auth_aesgcm",
        side_effect=[real_old_aesgcm, boom_aesgcm],
    ):
        _result, status = _reencrypt_services_auth_value(old_blob, OLD_KEY, NEW_KEY)

    assert status.startswith("error:encrypt_failed:")


# ---------------------------------------------------------------------------
# _reencrypt_value — encrypt failure path (lines 467-468)
# ---------------------------------------------------------------------------


def test_reencrypt_value_encrypt_failure(old_svc, new_svc):
    """When new_svc.encrypt_secret raises, status starts with 'error:encrypt_failed:'."""
    from unittest.mock import MagicMock  # pylint: disable=import-outside-toplevel
    from mcpgateway.scripts.migrate_enc_secret import _reencrypt_value  # pylint: disable=import-outside-toplevel

    plaintext = "encrypt-fail-test"  # nosec B105  # pragma: allowlist secret
    old_cipher = old_svc.encrypt_secret(plaintext)

    broken_new_svc = MagicMock()
    broken_new_svc.is_encrypted.side_effect = new_svc.is_encrypted
    broken_new_svc.decrypt_secret.side_effect = new_svc.decrypt_secret
    broken_new_svc.encrypt_secret.side_effect = RuntimeError("forced encrypt error")

    _result, status = _reencrypt_value(old_cipher, old_svc, broken_new_svc)
    assert status.startswith("error:encrypt_failed:")


# ---------------------------------------------------------------------------
# _reencrypt_oauth_config — error and skipped branches (lines 496-500)
# ---------------------------------------------------------------------------


def test_reencrypt_oauth_config_sensitive_key_error(old_svc, new_svc):
    """A sensitive key that fails decryption is counted as an error."""
    from mcpgateway.scripts.migrate_enc_secret import _reencrypt_oauth_config  # pylint: disable=import-outside-toplevel

    other_svc = get_encryption_service(OTHER_KEY)
    # Encrypt with OTHER_KEY; old_svc cannot decrypt it → error
    bad_cipher = other_svc.encrypt_secret("bad")
    config = {"client_secret": bad_cipher}

    _new_config, migrated, skipped, errors = _reencrypt_oauth_config(config, old_svc, new_svc)
    assert errors == 1
    assert migrated == 0


def test_reencrypt_oauth_config_sensitive_key_plaintext_skipped(old_svc, new_svc):
    """A sensitive key whose value is plaintext (not encrypted) is counted as skipped."""
    from mcpgateway.scripts.migrate_enc_secret import _reencrypt_oauth_config  # pylint: disable=import-outside-toplevel

    config = {"client_secret": "not-encrypted-value"}
    _new_config, migrated, _skipped, errors = _reencrypt_oauth_config(config, old_svc, new_svc)
    assert errors == 0
    assert migrated == 0


# ---------------------------------------------------------------------------
# _migrate_services_auth_simple_columns — error row (lines 304-306)
# ---------------------------------------------------------------------------


def test_migrate_services_auth_simple_columns_error_row(tmp_path):
    """A row with an undecryptable blob is counted as an error."""
    from sqlalchemy import create_engine, text as sa_text  # pylint: disable=import-outside-toplevel
    from sqlalchemy.orm import sessionmaker as sm  # pylint: disable=import-outside-toplevel
    from mcpgateway.scripts.migrate_enc_secret import _migrate_services_auth_simple_columns  # pylint: disable=import-outside-toplevel
    from mcpgateway.utils.services_auth import encode_auth  # pylint: disable=import-outside-toplevel

    db_url = f"sqlite:///{tmp_path / 'err.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        conn.execute(sa_text("CREATE TABLE tools (id TEXT PRIMARY KEY, auth_value TEXT)"))
        conn.commit()

    # Encrypt with OTHER_KEY — neither OLD_KEY nor NEW_KEY can decrypt it
    bad_blob = encode_auth({"k": "v"}, secret=OTHER_KEY)
    SessionLocal = sm(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as session:
        session.execute(sa_text("INSERT INTO tools (id, auth_value) VALUES ('t1', :v)"), {"v": bad_blob})
        session.commit()

    with SessionLocal() as session:
        counts = _migrate_services_auth_simple_columns(session, "tools", "id", ["auth_value"], OLD_KEY, NEW_KEY, dry_run=False)

    assert counts["errors"] == 1
    assert counts["migrated"] == 0


# ---------------------------------------------------------------------------
# _migrate_services_auth_json_columns — various skip branches
# ---------------------------------------------------------------------------


def test_migrate_services_auth_json_columns_invalid_json(tmp_path):
    """A column containing invalid JSON is skipped."""
    from sqlalchemy import create_engine, text as sa_text  # pylint: disable=import-outside-toplevel
    from sqlalchemy.orm import sessionmaker as sm  # pylint: disable=import-outside-toplevel
    from mcpgateway.scripts.migrate_enc_secret import _migrate_services_auth_json_columns  # pylint: disable=import-outside-toplevel

    db_url = f"sqlite:///{tmp_path / 'jskip.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        conn.execute(sa_text("CREATE TABLE gateways (id TEXT PRIMARY KEY, auth_query_params TEXT)"))
        conn.commit()

    SessionLocal = sm(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as session:
        session.execute(sa_text("INSERT INTO gateways (id, auth_query_params) VALUES ('g1', 'not-json')"))
        session.commit()

    with SessionLocal() as session:
        counts = _migrate_services_auth_json_columns(session, "gateways", "id", ["auth_query_params"], OLD_KEY, NEW_KEY, dry_run=False)

    assert counts["errors"] == 0
    assert counts["skipped"] >= 1


def test_migrate_services_auth_json_columns_non_dict_json(tmp_path):
    """A column containing valid JSON but not a dict is skipped."""
    from sqlalchemy import create_engine, text as sa_text  # pylint: disable=import-outside-toplevel
    from sqlalchemy.orm import sessionmaker as sm  # pylint: disable=import-outside-toplevel
    from mcpgateway.scripts.migrate_enc_secret import _migrate_services_auth_json_columns  # pylint: disable=import-outside-toplevel

    db_url = f"sqlite:///{tmp_path / 'ndskip.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        conn.execute(sa_text("CREATE TABLE gateways (id TEXT PRIMARY KEY, auth_query_params TEXT)"))
        conn.commit()

    SessionLocal = sm(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as session:
        # A JSON array instead of a dict
        session.execute(sa_text("INSERT INTO gateways (id, auth_query_params) VALUES ('g2', :v)"), {"v": json.dumps([1, 2, 3])})
        session.commit()

    with SessionLocal() as session:
        counts = _migrate_services_auth_json_columns(session, "gateways", "id", ["auth_query_params"], OLD_KEY, NEW_KEY, dry_run=False)

    assert counts["errors"] == 0
    assert counts["skipped"] >= 1


def test_migrate_services_auth_json_columns_non_str_blob_value(tmp_path):
    """A JSON dict whose value is not a string is skipped."""
    from sqlalchemy import create_engine, text as sa_text  # pylint: disable=import-outside-toplevel
    from sqlalchemy.orm import sessionmaker as sm  # pylint: disable=import-outside-toplevel
    from mcpgateway.scripts.migrate_enc_secret import _migrate_services_auth_json_columns  # pylint: disable=import-outside-toplevel

    db_url = f"sqlite:///{tmp_path / 'nsblob.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        conn.execute(sa_text("CREATE TABLE gateways (id TEXT PRIMARY KEY, auth_query_params TEXT)"))
        conn.commit()

    SessionLocal = sm(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as session:
        # Value is an integer, not a string blob
        session.execute(sa_text("INSERT INTO gateways (id, auth_query_params) VALUES ('g3', :v)"), {"v": json.dumps({"key": 42})})
        session.commit()

    with SessionLocal() as session:
        counts = _migrate_services_auth_json_columns(session, "gateways", "id", ["auth_query_params"], OLD_KEY, NEW_KEY, dry_run=False)

    assert counts["errors"] == 0
    assert counts["skipped"] >= 1


def test_migrate_services_auth_json_columns_error_in_blob(tmp_path):
    """A JSON dict whose blob fails decryption is counted as an error."""
    from sqlalchemy import create_engine, text as sa_text  # pylint: disable=import-outside-toplevel
    from sqlalchemy.orm import sessionmaker as sm  # pylint: disable=import-outside-toplevel
    from mcpgateway.scripts.migrate_enc_secret import _migrate_services_auth_json_columns  # pylint: disable=import-outside-toplevel
    from mcpgateway.utils.services_auth import encode_auth  # pylint: disable=import-outside-toplevel

    db_url = f"sqlite:///{tmp_path / 'errblob.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        conn.execute(sa_text("CREATE TABLE gateways (id TEXT PRIMARY KEY, auth_query_params TEXT)"))
        conn.commit()

    bad_blob = encode_auth({"k": "v"}, secret=OTHER_KEY)  # undecryptable with OLD_KEY
    SessionLocal = sm(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as session:
        session.execute(sa_text("INSERT INTO gateways (id, auth_query_params) VALUES ('g4', :v)"), {"v": json.dumps({"tok": bad_blob})})
        session.commit()

    with SessionLocal() as session:
        counts = _migrate_services_auth_json_columns(session, "gateways", "id", ["auth_query_params"], OLD_KEY, NEW_KEY, dry_run=False)

    assert counts["errors"] == 1


# ---------------------------------------------------------------------------
# _migrate_json_columns (EncryptionService path) — JSON decode error and
# non-str raw_val branches
# ---------------------------------------------------------------------------


def test_migrate_json_columns_invalid_json(tmp_path):
    """oauth_config column with invalid JSON is silently skipped."""
    from sqlalchemy import create_engine, text as sa_text  # pylint: disable=import-outside-toplevel
    from sqlalchemy.orm import sessionmaker as sm  # pylint: disable=import-outside-toplevel
    from mcpgateway.scripts.migrate_enc_secret import _migrate_json_columns  # pylint: disable=import-outside-toplevel

    db_url = f"sqlite:///{tmp_path / 'jsonbad.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        conn.execute(sa_text("CREATE TABLE gateways (id TEXT PRIMARY KEY, oauth_config TEXT)"))
        conn.commit()

    old_svc = get_encryption_service(OLD_KEY)
    new_svc = get_encryption_service(NEW_KEY)
    SessionLocal = sm(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as session:
        session.execute(sa_text("INSERT INTO gateways (id, oauth_config) VALUES ('g1', 'not-json-at-all')"))
        session.commit()

    with SessionLocal() as session:
        counts = _migrate_json_columns(session, "gateways", "id", ["oauth_config"], old_svc, new_svc, dry_run=False)

    assert counts["errors"] == 0
    assert counts["skipped"] >= 1


def test_migrate_json_columns_non_str_raw_val(tmp_path):
    """oauth_config returned as a dict directly (SQLAlchemy JSON type) is handled."""
    from sqlalchemy import create_engine, Column, String, JSON  # pylint: disable=import-outside-toplevel
    from sqlalchemy.orm import sessionmaker as sm, DeclarativeBase  # pylint: disable=import-outside-toplevel
    from mcpgateway.scripts.migrate_enc_secret import _migrate_json_columns  # pylint: disable=import-outside-toplevel

    db_url = f"sqlite:///{tmp_path / 'jsondict.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    class Base(DeclarativeBase):
        """Declarative base for test model."""

    class GW(Base):
        """Minimal gateway model with JSON oauth_config."""

        __tablename__ = "gateways"
        id = Column(String, primary_key=True)
        oauth_config = Column(JSON)

    Base.metadata.create_all(engine)

    old_svc = get_encryption_service(OLD_KEY)
    new_svc = get_encryption_service(NEW_KEY)
    SessionLocal = sm(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as session:
        secret = "gw-secret"  # nosec B105  # pragma: allowlist secret
        session.add(GW(id="g1", oauth_config={"client_id": "cid", "client_secret": old_svc.encrypt_secret(secret)}))
        session.commit()

    with SessionLocal() as session:
        counts = _migrate_json_columns(session, "gateways", "id", ["oauth_config"], old_svc, new_svc, dry_run=False)

    assert counts["migrated"] >= 1


# ---------------------------------------------------------------------------
# run_migration — env-restore branches when vars are absent
# ---------------------------------------------------------------------------


def test_run_migration_env_restore_absent_vars(tmp_path):
    """run_migration cleans up injected env vars when they were absent before the call."""
    db_url = f"sqlite:///{tmp_path / 'envrestore.db'}"
    # Strip the three vars we care about so the restore branches (del) are exercised
    env_without = {k: v for k, v in os.environ.items() if k not in ("AUTH_ENCRYPTION_SECRET", "JWT_SECRET_KEY", "MIN_SECRET_LENGTH")}

    def _sniff_env(*_args, **_kwargs):
        """Record env state immediately after run_migration sets the vars."""
        raise SystemExit(0)

    with patch.dict(os.environ, env_without, clear=True):
        with patch("mcpgateway.scripts.migrate_enc_secret.sessionmaker", side_effect=_sniff_env):
            try:
                run_migration(db_url, OLD_KEY, NEW_KEY)
            except SystemExit:
                pass
        # After run_migration returns, the vars it injected must be gone
        assert "AUTH_ENCRYPTION_SECRET" not in os.environ
        assert "MIN_SECRET_LENGTH" not in os.environ


def test_run_migration_jwt_too_short_uses_new_key(tmp_path):
    """When JWT_SECRET_KEY is shorter than _MIN_SECRET_LENGTH the migration still
    succeeds — the short value is temporarily replaced then restored."""
    db_url = f"sqlite:///{tmp_path / 'jwtshort.db'}"
    with patch.dict(os.environ, {"JWT_SECRET_KEY": "short"}, clear=False):
        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
        assert rc == 0
        # Inside patch.dict scope the key should be back to "short"
        assert os.environ.get("JWT_SECRET_KEY") == "short"


# ---------------------------------------------------------------------------
# run_migration — fatal exception path
# ---------------------------------------------------------------------------


def test_run_migration_fatal_exception(tmp_path):
    """A fatal exception during migration returns exit code 1."""
    from unittest.mock import patch as _patch  # pylint: disable=import-outside-toplevel

    db_url = f"sqlite:///{tmp_path / 'fatal.db'}"
    with _patch("sqlalchemy.inspect", side_effect=RuntimeError("boom")):
        rc = run_migration(db_url, OLD_KEY, NEW_KEY)
    assert rc == 1


# ---------------------------------------------------------------------------
# run_migration — dry-run zero-migrated message
# ---------------------------------------------------------------------------


def test_run_migration_dry_run_nothing_to_migrate(tmp_path):
    """Dry-run with an empty DB prints the 'nothing would be migrated' message."""
    import io
    import contextlib  # pylint: disable=import-outside-toplevel

    db_url = f"sqlite:///{tmp_path / 'drynoop.db'}"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run_migration(db_url, OLD_KEY, NEW_KEY, dry_run=True)
    assert rc == 0
    assert "nothing would be migrated" in buf.getvalue()


# ---------------------------------------------------------------------------
# run_migration — cols empty after column-existence filtering
# ---------------------------------------------------------------------------


def test_run_migration_skips_missing_columns(tmp_path):
    """Tables that exist but are missing all expected columns are silently skipped."""
    from sqlalchemy import create_engine, text as sa_text  # pylint: disable=import-outside-toplevel

    db_url = f"sqlite:///{tmp_path / 'nocols.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        # Create the tables but without ANY of the expected encrypted columns
        conn.execute(sa_text("CREATE TABLE oauth_tokens (id TEXT PRIMARY KEY, unrelated TEXT)"))
        conn.execute(sa_text("CREATE TABLE tools (id TEXT PRIMARY KEY, unrelated TEXT)"))
        conn.commit()

    rc = run_migration(db_url, OLD_KEY, NEW_KEY)
    assert rc == 0


# ---------------------------------------------------------------------------
# main() — --dry-run print path
# ---------------------------------------------------------------------------


def test_main_dry_run_flag_output(tmp_path, capsys):
    """Passing --dry-run to main() prints 'DRY RUN' before calling run_migration."""
    db_url = f"sqlite:///{tmp_path / 'maindry.db'}"
    env = {"DATABASE_URL": db_url}
    with patch.dict(os.environ, env, clear=False):
        with patch("sys.argv", ["migrate_enc_secret", "--old-key", OLD_KEY, "--new-key", NEW_KEY, "--dry-run"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "DRY RUN" in captured.out
