# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_support_bundle_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for support bundle service.
Tests bundle generation, sanitization, and file operations.
"""

# Standard
import builtins
from pathlib import Path
import tempfile
from typing import Dict, get_args
import zipfile

# Third-Party
from pydantic import BaseModel, Field, SecretStr
import pytest

# First-Party
from mcpgateway.services.support_bundle_service import (
    SupportBundleConfig,
    SupportBundleService,
    create_support_bundle,
)


class TestSupportBundleService:
    """Test support bundle service functionality."""

    def test_service_initialization(self):
        """Test service initializes with hostname and timestamp."""
        service = SupportBundleService()
        assert service.hostname
        assert service.timestamp
        assert len(service.hostname) > 0

    def test_is_secret_detection(self):
        """Test secret detection in environment variable names."""
        service = SupportBundleService()

        # Test secret detection
        assert service._is_secret("PASSWORD")
        assert service._is_secret("API_KEY")
        assert service._is_secret("SECRET_TOKEN")
        assert service._is_secret("JWT_SECRET_KEY")
        assert service._is_secret("DATABASE_PASSWORD")
        assert service._is_secret("BASIC_AUTH_USER")
        assert service._is_secret("DATABASE_URL")
        assert service._is_secret("REDIS_URL")
        assert service._is_secret("AUTH_ENCRYPTION_SECRET")

        # Test non-secrets
        assert not service._is_secret("DEBUG")
        assert not service._is_secret("PORT")
        assert not service._is_secret("HOSTNAME")
        assert not service._is_secret("LOG_LEVEL")

    def test_is_secret_detection_url_suffix(self):
        """Any *_URL environment variable is masked, not just the two named exact matches.

        database_url / redis_url are also *_URL names and are already covered by the
        SECRET/TOKEN/PASS/KEY substring check or the exact-match list; this test targets
        URL settings that were previously missed entirely, such as ratelimiter_redis_url
        and elasticsearch_url, both of which routinely carry inline credentials.
        """
        service = SupportBundleService()

        assert service._is_secret("RATELIMITER_REDIS_URL")
        assert service._is_secret("ELASTICSEARCH_URL")
        assert service._is_secret("MEMCACHED_URL")

        # Existing exact-match entries must still be caught (not narrowed).
        assert service._is_secret("DATABASE_URL")
        assert service._is_secret("REDIS_URL")

        # Benign, non-URL names must not be swept up by the new suffix rule.
        assert not service._is_secret("LOG_LEVEL")
        assert not service._is_secret("HOSTNAME")
        assert not service._is_secret("URL_PREFIX")

    def test_sanitize_url(self):
        """Test URL sanitization removes passwords."""
        service = SupportBundleService()

        # Test PostgreSQL URL
        url = "postgresql://user:password@localhost:5432/db"  # pragma: allowlist secret
        sanitized = service._sanitize_url(url)
        assert "password" not in sanitized
        assert "*****" in sanitized
        assert "user" in sanitized

        # Test Redis URL
        url = "redis://admin:secret123@redis.example.com:6379/0"  # pragma: allowlist secret
        sanitized = service._sanitize_url(url)
        assert "secret123" not in sanitized
        assert "*****" in sanitized

        # Test driver-qualified PostgreSQL URL
        url = "postgresql+psycopg://user:password@localhost:5432/db"  # pragma: allowlist secret
        sanitized = service._sanitize_url(url)
        assert "password" not in sanitized
        assert "*****" in sanitized

        # Test legacy/stale MySQL URL (credentials must still be redacted)
        url = "mysql+pymysql://admin:secret@db.host:3306/mydb"  # pragma: allowlist secret
        sanitized = service._sanitize_url(url)
        assert "secret" not in sanitized
        assert "*****" in sanitized

        # Test URL without credentials
        url = "http://example.com/path"
        sanitized = service._sanitize_url(url)
        assert sanitized == url

        # Test None
        assert service._sanitize_url(None) is None

    def test_sanitize_line(self):
        """Test line sanitization removes sensitive data."""
        service = SupportBundleService()

        # Test password redaction
        line = 'password: "secret123"'  # pragma: allowlist secret
        sanitized = service._sanitize_line(line)
        assert "secret123" not in sanitized
        assert "*****" in sanitized

        # Test token redaction
        line = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"  # pragma: allowlist secret
        sanitized = service._sanitize_line(line)
        assert "eyJhbGci" not in sanitized or "*****" in sanitized

        # Test API key redaction
        line = "api_key: abc123xyz"
        sanitized = service._sanitize_line(line)
        assert "*****" in sanitized

        # Test non-sensitive line
        line = "debug: true"
        sanitized = service._sanitize_line(line)
        assert sanitized == line

    def test_collect_version_info(self):
        """Test version information collection."""
        service = SupportBundleService()
        info = service._collect_version_info()

        assert "app_name" in info
        assert "app_version" in info
        assert "python_version" in info
        assert "platform" in info
        assert "hostname" in info
        assert "timestamp" in info

    def test_collect_system_info(self):
        """Test system information collection."""
        service = SupportBundleService()
        info = service._collect_system_info()

        assert "platform" in info
        assert "python" in info
        assert "database" in info
        assert info["platform"]["system"]
        assert info["python"]["version"]

    def test_collect_system_info_without_psutil(self, monkeypatch: pytest.MonkeyPatch):
        """Test system info collection falls back when psutil isn't installed."""
        service = SupportBundleService()

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
            if name == "psutil":
                raise ImportError("psutil missing")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        info = service._collect_system_info()
        assert info["system"]["note"].startswith("psutil not installed")

    def test_collect_env_config(self):
        """Test environment configuration collection with sanitization."""
        service = SupportBundleService()
        env = service._collect_env_config()

        assert isinstance(env, dict)
        # All secrets should be redacted
        for key, value in env.items():
            if service._is_secret(key):
                assert value == "*****"

    def test_collect_settings(self):
        """Test application settings collection."""
        service = SupportBundleService()
        config = service._collect_settings()

        assert isinstance(config, dict)
        assert "host" in config

        # Check sensitive fields are not included
        assert "basic_auth_password" not in config
        assert "jwt_secret_key" not in config
        assert "auth_encryption_secret" not in config
        assert "platform_admin_password" not in config
        assert "sso_github_client_secret" not in config
        assert "sso_google_client_secret" not in config
        assert "sso_ibm_verify_client_secret" not in config
        assert "sso_okta_client_secret" not in config
        assert "sso_keycloak_client_secret" not in config
        assert "sso_entra_client_secret" not in config
        assert "sso_generic_client_secret" not in config

    def test_collect_settings_sanitizes_only_database_url(self, monkeypatch: pytest.MonkeyPatch):
        """Cover database_url present / redis_url absent branches."""
        service = SupportBundleService()

        def fake_dump(*, exclude=None):  # noqa: ARG001
            return {"database_url": "postgresql://user:password@localhost:5432/db"}  # pragma: allowlist secret

        monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings.model_dump", fake_dump)

        config = service._collect_settings()
        assert "database_url" in config
        assert "password" not in config["database_url"]
        assert "redis_url" not in config

    def test_collect_settings_sanitizes_only_redis_url(self, monkeypatch: pytest.MonkeyPatch):
        """Cover redis_url present / database_url absent branches."""
        service = SupportBundleService()

        def fake_dump(*, exclude=None):  # noqa: ARG001
            return {"redis_url": "redis://admin:secret123@redis.example.com:6379/0"}  # pragma: allowlist secret

        monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings.model_dump", fake_dump)

        config = service._collect_settings()
        assert "redis_url" in config
        assert "secret123" not in config["redis_url"]
        assert "database_url" not in config

    def test_collect_settings_sanitizes_other_url_settings(self, monkeypatch: pytest.MonkeyPatch):
        """Credentials are redacted from any setting value, whatever the field is called.

        Sanitization keys off the *content* of a value rather than the field name:
        a name says nothing about the shape of what it holds, so ratelimiter_redis_url,
        elasticsearch_url, and a URL-shaped value under a name with no url suffix are
        all covered by the same pass.
        """
        service = SupportBundleService()

        def fake_dump(*, exclude=None):  # noqa: ARG001
            return {
                "ratelimiter_redis_url": "redis://ratelimiter:hunter2@ratelimiter.example.com:6379/0",  # pragma: allowlist secret
                "elasticsearch_url": "https://elastic:hunter2@es.example.com:9200",  # pragma: allowlist secret
                "not_a_url_setting": "https://user:hunter2@example.com",  # pragma: allowlist secret
                "harmless_setting": "X-CSRF-Token",
            }

        monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings.model_dump", fake_dump)

        config = service._collect_settings()
        for key in ("ratelimiter_redis_url", "elasticsearch_url", "not_a_url_setting"):
            assert "hunter2" not in config[key]
            assert "*****" in config[key]
        # Content-based sanitization must not chew through ordinary values.
        assert config["harmless_setting"] == "X-CSRF-Token"

    def test_sanitize_url_redacts_empty_username_credentials(self):
        """A DSN with no username still has its password redacted.

        Several clients accept scheme://:password@host. The userinfo pattern must
        allow a zero-length username, or this common Redis form ships verbatim.
        """
        service = SupportBundleService()

        sanitized = service._sanitize_url("redis://:hunter2@cache.example.com:6379/0")  # pragma: allowlist secret
        assert "hunter2" not in sanitized
        assert sanitized == "redis://:*****@cache.example.com:6379/0"

        # A URL with no credentials at all is returned unchanged.
        assert service._sanitize_url("redis://cache.example.com:6379/0") == "redis://cache.example.com:6379/0"

    def test_sanitize_config_value_walks_collections(self):
        """Collection-typed settings are sanitized element-wise, at any depth."""
        service = SupportBundleService()

        # List of strings: each element is sanitized on its content.
        assert service._sanitize_config_value(["redis://:hunter2@h:6379", "10.0.0.0/8"]) == ["redis://:*****@h:6379", "10.0.0.0/8"]  # pragma: allowlist secret

        # List of dicts: a secret-looking key has its value replaced outright,
        # since the value itself carries no pattern to match on.
        destinations = [{"endpoint": "https://siem.example.com", "token": "hunter2", "name": "prod"}]  # pragma: allowlist secret
        assert service._sanitize_config_value(destinations) == [{"endpoint": "https://siem.example.com", "token": "*****", "name": "prod"}]

        # Nested dicts are walked; benign mappings survive intact.
        assert service._sanitize_config_value({"role_map": {"admin": "platform_admin"}}) == {"role_map": {"admin": "platform_admin"}}

        # Non-string scalars pass through untouched.
        assert service._sanitize_config_value(3600) == 3600
        assert service._sanitize_config_value(None) is None
        # An empty string stays empty rather than becoming None: "set but blank"
        # and "unset" are different facts to whoever reads the bundle.
        assert service._sanitize_config_value("") == ""

    def test_sanitize_config_value_redacts_bearer_token_in_header_blob(self):
        """A header blob carrying a bearer token is redacted.

        otel_exporter_otlp_headers is a comma-separated key=value string that
        conventionally holds an Authorization header. Its field name matches no
        secret-name rule, so only content-based sanitization catches it.
        """
        service = SupportBundleService()

        sanitized = service._sanitize_config_value("Authorization=Bearer eyJhbGci.eyJzdWIi.abc123,X-Env=prod")  # pragma: allowlist secret
        assert "eyJhbGci" not in sanitized
        assert "*****" in sanitized
        assert "X-Env=prod" in sanitized

    def test_collect_logs_file_not_found(self):
        """Test log collection when file doesn't exist."""
        service = SupportBundleService()
        config = SupportBundleConfig(log_tail_lines=100)

        # Create a custom config with non-existent log path
        with tempfile.TemporaryDirectory() as tmpdir:
            # Temporarily override settings
            logs = service._collect_logs(config)
            # Should return a message about missing file
            for log_content in logs.values():
                assert "[Log file not found]" in log_content or "[Showing last" in log_content or isinstance(log_content, str)

    def test_collect_logs_file_too_large(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Cover log collection branch for log files exceeding max_log_size_mb."""
        service = SupportBundleService()

        log_file = "mcpgateway.log"
        (tmp_path / log_file).write_text("x" * 256, encoding="utf-8")  # ~0.0002 MB

        monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings.log_folder", str(tmp_path))
        monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings.log_file", log_file)

        config = SupportBundleConfig(log_tail_lines=100, max_log_size_mb=0.00001)
        logs = service._collect_logs(config)
        assert "too large" in logs[log_file]

    def test_collect_logs_tails_and_sanitizes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Cover tailing and sanitization when log file exists and is within size limit."""
        service = SupportBundleService()

        log_file = "mcpgateway.log"
        log_path = tmp_path / log_file
        log_path.write_text(
            'line0\nline1\nline2\npassword: "secret123"\n',  # pragma: allowlist secret
            encoding="utf-8",
        )

        monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings.log_folder", str(tmp_path))
        monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings.log_file", log_file)

        config = SupportBundleConfig(log_tail_lines=2, max_log_size_mb=10.0)
        logs = service._collect_logs(config)

        content = logs[log_file]
        assert "[Showing last 2 lines]" in content
        assert "secret123" not in content
        assert "*****" in content

    def test_collect_logs_read_error_is_reported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Cover exception path when reading an existing log file fails."""
        service = SupportBundleService()

        log_file = "mcpgateway.log"
        (tmp_path / log_file).write_text("ok\n", encoding="utf-8")

        monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings.log_folder", str(tmp_path))
        monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings.log_file", log_file)

        def bad_open(*args, **kwargs):  # noqa: ARG001
            raise OSError("read failed")

        monkeypatch.setattr(builtins, "open", bad_open)

        config = SupportBundleConfig(log_tail_lines=100, max_log_size_mb=10.0)
        logs = service._collect_logs(config)
        assert "Error reading log file" in logs[log_file]

    def test_collect_logs_does_not_tail_when_few_lines(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Cover branch where log file is shorter than log_tail_lines (no tailing)."""
        service = SupportBundleService()

        log_file = "mcpgateway.log"
        (tmp_path / log_file).write_text("password: secret123\nline1\n", encoding="utf-8")

        monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings.log_folder", str(tmp_path))
        monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings.log_file", log_file)

        config = SupportBundleConfig(log_tail_lines=100, max_log_size_mb=10.0)
        logs = service._collect_logs(config)

        content = logs[log_file]
        assert "[Showing last" not in content
        assert "secret123" not in content
        assert "*****" in content

    def test_create_manifest(self):
        """Test manifest creation."""
        service = SupportBundleService()
        config = SupportBundleConfig(log_tail_lines=500)
        manifest = service._create_manifest(config)

        assert "bundle_version" in manifest
        assert "generated_at" in manifest
        assert "hostname" in manifest
        assert "app_version" in manifest
        assert "configuration" in manifest
        assert "warning" in manifest
        assert manifest["configuration"]["log_tail_lines"] == 500

    def test_generate_bundle_creates_zip(self):
        """Test bundle generation creates a valid ZIP file."""
        service = SupportBundleService()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = SupportBundleConfig(output_dir=Path(tmpdir), log_tail_lines=100)
            bundle_path = service.generate_bundle(config)

            # Check file exists
            assert bundle_path.exists()
            assert bundle_path.suffix == ".zip"
            assert bundle_path.name.startswith("mcpgateway-support-")

            # Check ZIP is valid
            assert zipfile.is_zipfile(bundle_path)

            # Check ZIP contents
            with zipfile.ZipFile(bundle_path, "r") as zf:
                namelist = zf.namelist()
                assert "MANIFEST.json" in namelist
                assert "version.json" in namelist
                assert "system_info.json" in namelist
                assert "settings.json" in namelist
                assert "environment.json" in namelist
                assert "README.md" in namelist
                # Logs directory should exist
                assert any("logs/" in name for name in namelist)

    def test_generate_bundle_with_custom_config(self):
        """Test bundle generation with custom configuration."""
        service = SupportBundleService()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = SupportBundleConfig(
                output_dir=Path(tmpdir),
                log_tail_lines=50,
                include_logs=False,
                include_env=False,
                include_system_info=False,
            )
            bundle_path = service.generate_bundle(config)

            assert bundle_path.exists()

            with zipfile.ZipFile(bundle_path, "r") as zf:
                namelist = zf.namelist()
                # Required files should always be present
                assert "MANIFEST.json" in namelist
                assert "version.json" in namelist
                assert "README.md" in namelist

                # Optional files should be missing
                if not config.include_system_info:
                    assert "system_info.json" not in namelist
                if not config.include_env:
                    assert "settings.json" not in namelist
                    assert "environment.json" not in namelist

    def test_convenience_function(self):
        """Test create_support_bundle convenience function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SupportBundleConfig(output_dir=Path(tmpdir), log_tail_lines=100)
            bundle_path = create_support_bundle(config)

            assert bundle_path.exists()
            assert zipfile.is_zipfile(bundle_path)

    def test_bundle_contains_sanitized_data(self):
        """Test that generated bundle contains sanitized data."""
        service = SupportBundleService()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = SupportBundleConfig(output_dir=Path(tmpdir), log_tail_lines=100)
            bundle_path = service.generate_bundle(config)

            with zipfile.ZipFile(bundle_path, "r") as zf:
                # Check environment.json is sanitized
                env_data = zf.read("environment.json").decode("utf-8")
                # Should not contain actual password values
                assert "changeme" not in env_data or "*****" in env_data

                # Check settings.json doesn't have sensitive fields
                settings_data = zf.read("settings.json").decode("utf-8")
                assert "basic_auth_password" not in settings_data
                assert "jwt_secret_key" not in settings_data
                assert "platform_admin_password" not in settings_data
                assert "sso_github_client_secret" not in settings_data
                assert "sso_google_client_secret" not in settings_data
                assert "sso_ibm_verify_client_secret" not in settings_data
                assert "sso_okta_client_secret" not in settings_data
                assert "sso_keycloak_client_secret" not in settings_data
                assert "sso_entra_client_secret" not in settings_data
                assert "sso_generic_client_secret" not in settings_data

    def test_support_bundle_config_validation(self):
        """Test SupportBundleConfig validation."""
        # Valid config
        config = SupportBundleConfig(log_tail_lines=500, max_log_size_mb=5.0)
        assert config.log_tail_lines == 500
        assert config.max_log_size_mb == 5.0

        # Default config
        config = SupportBundleConfig()
        assert config.include_logs is True
        assert config.include_env is True
        assert config.include_system_info is True
        assert config.log_tail_lines == 1000

    def test_secret_field_names_includes_known_secretstr_settings(self):
        """The two settings that were previously plain-str secrets are detected.

        Both csrf_secret_key and identity_claims_secret are now SecretStr-typed (see
        test_secret_field_names_matches_secretstr_fields_exactly for the rule-2 backstop
        they used to exercise), but pinning them by name is still valuable: neither may
        slip out of the detected set, regardless of which rule catches it.
        """
        names = SupportBundleService._secret_field_names()

        # csrf_secret_key derives from the JWT signing secret when unset.
        assert "csrf_secret_key" in names
        # identity_claims_secret derives from it the same way.
        assert "identity_claims_secret" in names

    def test_secret_field_names_matches_secretstr_fields_exactly(self):
        """Every secret setting is SecretStr-typed; rule 2 currently adds nothing.

        This test fails the day a contributor adds a plain-string secret with a
        secret-ish name, forcing an explicit decision (retype it SecretStr, or
        add it to _SAFE_STRING_FIELDS) rather than silently relying on the net.
        """
        # First-Party
        from mcpgateway.config import Settings

        secretstr_fields = {name for name, field in Settings.model_fields.items() if field.annotation is SecretStr or SecretStr in get_args(field.annotation)}

        assert SupportBundleService._secret_field_names() == secretstr_fields

    def test_secret_field_names_rule_2_backstop_on_throwaway_model(self):
        """Rule 2 (name-regex fallback for plain strings) is directly exercised.

        Against the real Settings model, rule 2 currently selects nothing (every
        secret is SecretStr-typed), so this test builds a throwaway model to prove
        the fallback still works on its own terms: it must catch a plain-string
        secret-shaped name, ignore a benign string name, ignore a non-string
        container annotation even with a secret-shaped name, and ignore a
        non-string scalar annotation with a secret-shaped name.
        """

        class ThrowawayModel(BaseModel):
            """Throwaway model exercising _secret_field_names() rule 2 in isolation."""

            api_key: str = ""
            notes: str = ""
            mapping: Dict[str, str] = Field(default_factory=dict)
            token_expiry: int = 0

        names = SupportBundleService._secret_field_names(ThrowawayModel)

        assert "api_key" in names
        assert "notes" not in names
        assert "mapping" not in names
        assert "token_expiry" not in names

    def test_secret_field_names_includes_every_secretstr_field(self):
        """Every SecretStr-annotated setting is detected by type alone."""
        # First-Party
        from mcpgateway.config import Settings

        names = SupportBundleService._secret_field_names()
        for field_name, field in Settings.model_fields.items():
            annotation = field.annotation
            is_secret_type = annotation is SecretStr or SecretStr in get_args(annotation)
            if is_secret_type:
                assert field_name in names, f"SecretStr field {field_name} not detected as a secret"

    def test_secret_field_names_excludes_benign_settings(self):
        """Non-secret knobs whose names contain secret-ish words are kept."""
        names = SupportBundleService._secret_field_names()

        # int/bool knobs — redacting these would gut the bundle's usefulness
        for benign in (
            "token_expiry",
            "password_min_length",
            "password_policy_enabled",
            "min_secret_length",
            "require_strong_secrets",
            "csrf_token_name",
            "host",
            "port",
        ):
            assert benign not in names, f"{benign} must not be redacted"

        # A filesystem path, not a key
        assert "jwt_private_key_path" not in names

    def test_collect_settings_omits_csrf_secret_key(self):
        """Neither JWT-derived signing key may appear in the collected settings."""
        service = SupportBundleService()
        config = service._collect_settings()

        assert "csrf_secret_key" not in config
        assert "identity_claims_secret" not in config

    def test_collect_settings_keeps_benign_fields(self):
        """The bundle stays useful: non-secret settings keep their real values."""
        service = SupportBundleService()
        config = service._collect_settings()

        for benign in ("host", "port", "token_expiry", "password_min_length", "csrf_token_name"):
            assert benign in config, f"{benign} was over-redacted"

    def test_collect_settings_omits_every_detected_secret(self):
        """Meta-test: every field _secret_field_names() flags is really gone.

        A future secret setting that is neither SecretStr-typed nor name-matched
        is caught by test_no_secret_leaks_into_bundle below; one that is detected
        but somehow still emitted is caught here.
        """
        service = SupportBundleService()
        config = service._collect_settings()

        for name in SupportBundleService._secret_field_names():
            assert name not in config, f"secret field {name} leaked into settings.json"

    def test_no_secret_leaks_into_bundle(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """End-to-end: a sentinel JWT secret appears in no bundle member.

        Byte-level rather than key-level, so the check still fires when the value
        surfaces under some other key — a derived setting carrying a copy of the
        signing secret would not be caught by a key-name assertion.
        """
        # First-Party
        from mcpgateway.config import Settings

        sentinel = "sentinel-jwt-canary-DO-NOT-USE-IN-PRODUCTION-0123456789"  # pragma: allowlist secret
        sentinel_settings = Settings(
            jwt_secret_key=sentinel,
            database_url="sqlite:///:memory:",
            environment="development",
        )
        # Sanity: the fallback under test really did copy the JWT secret across.
        assert sentinel_settings.csrf_secret_key == sentinel or sentinel_settings.csrf_secret_key.get_secret_value() == sentinel

        monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings", sentinel_settings)

        service = SupportBundleService()
        bundle_path = service.generate_bundle(SupportBundleConfig(output_dir=tmp_path, include_logs=False))

        with zipfile.ZipFile(bundle_path) as zf:
            for member in zf.namelist():
                assert sentinel.encode() not in zf.read(member), f"JWT secret leaked into {member}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
