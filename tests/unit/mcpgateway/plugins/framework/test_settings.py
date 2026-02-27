# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_settings.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Tests for the plugin framework settings module.
Verifies default values, environment variable overrides, and settings isolation
from mcpgateway.config.
"""

# Standard
import os

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.settings import PluginsSettings


class TestPluginsSettingsDefaults:
    """Test that PluginsSettings has correct defaults."""

    @pytest.fixture(autouse=True)
    def _clean_plugins_env(self, monkeypatch):
        """Remove PLUGINS_ env vars and .env file so tests verify true defaults."""
        for key in list(os.environ):
            if key.startswith("PLUGINS_") or key == "UNIX_SOCKET_PATH":
                monkeypatch.delenv(key, raising=False)
        # Prevent values from .env file leaking into tests
        monkeypatch.setattr(PluginsSettings, "model_config", {**PluginsSettings.model_config, "env_file": None})

    def test_default_enabled(self):
        s = PluginsSettings()
        assert s.enabled is False

    def test_default_config_file(self):
        s = PluginsSettings()
        assert s.config_file == "plugins/config.yaml"

    def test_default_plugin_timeout(self):
        s = PluginsSettings()
        assert s.plugin_timeout == 30

    def test_default_log_level(self):
        s = PluginsSettings()
        assert s.log_level == "INFO"

    def test_default_skip_ssl_verify(self):
        s = PluginsSettings()
        assert s.skip_ssl_verify is False

    def test_default_httpx_max_connections(self):
        s = PluginsSettings()
        assert s.httpx_max_connections == 200

    def test_default_httpx_max_keepalive_connections(self):
        s = PluginsSettings()
        assert s.httpx_max_keepalive_connections == 100

    def test_default_httpx_keepalive_expiry(self):
        s = PluginsSettings()
        assert s.httpx_keepalive_expiry == 30.0

    def test_default_httpx_connect_timeout(self):
        s = PluginsSettings()
        assert s.httpx_connect_timeout == 5.0

    def test_default_httpx_read_timeout(self):
        s = PluginsSettings()
        assert s.httpx_read_timeout == 120.0

    def test_default_httpx_write_timeout(self):
        s = PluginsSettings()
        assert s.httpx_write_timeout == 30.0

    def test_default_httpx_pool_timeout(self):
        s = PluginsSettings()
        assert s.httpx_pool_timeout == 10.0

    def test_default_cli_completion(self):
        s = PluginsSettings()
        assert s.cli_completion is False

    def test_default_cli_markup_mode(self):
        s = PluginsSettings()
        assert s.cli_markup_mode is None

    # --- New transport/TLS/runtime fields default to None ---

    def test_default_client_mtls_fields(self):
        s = PluginsSettings()
        assert s.client_mtls_certfile is None
        assert s.client_mtls_keyfile is None
        assert s.client_mtls_ca_bundle is None
        assert s.client_mtls_keyfile_password is None
        assert s.client_mtls_verify is None
        assert s.client_mtls_check_hostname is None

    def test_default_server_ssl_fields(self):
        s = PluginsSettings()
        assert s.server_ssl_keyfile is None
        assert s.server_ssl_certfile is None
        assert s.server_ssl_ca_certs is None
        assert s.server_ssl_keyfile_password is None
        assert s.server_ssl_cert_reqs is None

    def test_default_server_fields(self):
        s = PluginsSettings()
        assert s.server_host is None
        assert s.server_port is None
        assert s.server_uds is None
        assert s.server_ssl_enabled is None

    def test_default_grpc_client_mtls_fields(self):
        s = PluginsSettings()
        assert s.grpc_client_mtls_certfile is None
        assert s.grpc_client_mtls_keyfile is None
        assert s.grpc_client_mtls_ca_bundle is None
        assert s.grpc_client_mtls_keyfile_password is None
        assert s.grpc_client_mtls_verify is None

    def test_default_grpc_server_ssl_fields(self):
        s = PluginsSettings()
        assert s.grpc_server_ssl_keyfile is None
        assert s.grpc_server_ssl_certfile is None
        assert s.grpc_server_ssl_ca_certs is None
        assert s.grpc_server_ssl_keyfile_password is None
        assert s.grpc_server_ssl_client_auth is None

    def test_default_grpc_server_fields(self):
        s = PluginsSettings()
        assert s.grpc_server_host is None
        assert s.grpc_server_port is None
        assert s.grpc_server_uds is None
        assert s.grpc_server_ssl_enabled is None

    def test_default_unix_socket_path(self):
        s = PluginsSettings()
        assert s.unix_socket_path is None

    def test_default_runtime_fields(self):
        s = PluginsSettings()
        assert s.config_path is None
        assert s.transport is None


class TestPluginsSettingsEnvOverrides:
    """Test that PLUGINS_ prefixed env vars override defaults."""

    def test_enabled_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_ENABLED", "true")
        s = PluginsSettings()
        assert s.enabled is True

    def test_plugin_timeout_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_PLUGIN_TIMEOUT", "60")
        s = PluginsSettings()
        assert s.plugin_timeout == 60

    def test_skip_ssl_verify_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SKIP_SSL_VERIFY", "true")
        s = PluginsSettings()
        assert s.skip_ssl_verify is True

    def test_httpx_connect_timeout_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_HTTPX_CONNECT_TIMEOUT", "15.0")
        s = PluginsSettings()
        assert s.httpx_connect_timeout == 15.0

    def test_httpx_read_timeout_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_HTTPX_READ_TIMEOUT", "300.0")
        s = PluginsSettings()
        assert s.httpx_read_timeout == 300.0

    def test_config_file_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_CONFIG_FILE", "/custom/path.yaml")
        s = PluginsSettings()
        assert s.config_file == "/custom/path.yaml"

    def test_cli_markup_mode_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_CLI_MARKUP_MODE", "markdown")
        s = PluginsSettings()
        assert s.cli_markup_mode == "markdown"

    # --- New transport/TLS/runtime field overrides ---

    def test_client_mtls_verify_bool_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_CLIENT_MTLS_VERIFY", "true")
        s = PluginsSettings()
        assert s.client_mtls_verify is True

    def test_server_port_int_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SERVER_PORT", "9000")
        s = PluginsSettings()
        assert s.server_port == 9000

    def test_server_host_str_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SERVER_HOST", "0.0.0.0")
        s = PluginsSettings()
        assert s.server_host == "0.0.0.0"

    def test_grpc_server_ssl_enabled_bool_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_SSL_ENABLED", "false")
        s = PluginsSettings()
        assert s.grpc_server_ssl_enabled is False

    def test_unix_socket_path_alias_override(self, monkeypatch):
        """UNIX_SOCKET_PATH (no PLUGINS_ prefix) is accepted via AliasChoices."""
        monkeypatch.setenv("UNIX_SOCKET_PATH", "/tmp/test.sock")
        s = PluginsSettings()
        assert s.unix_socket_path == "/tmp/test.sock"

    def test_unix_socket_path_prefixed_override(self, monkeypatch):
        """PLUGINS_UNIX_SOCKET_PATH is also accepted."""
        monkeypatch.setenv("PLUGINS_UNIX_SOCKET_PATH", "/tmp/prefixed.sock")
        s = PluginsSettings()
        assert s.unix_socket_path == "/tmp/prefixed.sock"

    def test_config_path_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_CONFIG_PATH", "/custom/config.yaml")
        s = PluginsSettings()
        assert s.config_path == "/custom/config.yaml"

    def test_transport_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_TRANSPORT", "stdio")
        s = PluginsSettings()
        assert s.transport == "stdio"

    def test_server_ssl_cert_reqs_int_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SERVER_SSL_CERT_REQS", "1")
        s = PluginsSettings()
        assert s.server_ssl_cert_reqs == 1

    def test_grpc_server_port_int_override(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_PORT", "50052")
        s = PluginsSettings()
        assert s.grpc_server_port == 50052

    def test_empty_optional_values_are_treated_as_none(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SERVER_SSL_CERT_REQS", "")
        monkeypatch.setenv("PLUGINS_SERVER_PORT", "")
        monkeypatch.setenv("PLUGINS_SERVER_SSL_ENABLED", "")
        monkeypatch.setenv("PLUGINS_CLIENT_MTLS_VERIFY", "")
        monkeypatch.setenv("PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME", "")
        monkeypatch.setenv("PLUGINS_GRPC_CLIENT_MTLS_VERIFY", "")
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_PORT", "")
        monkeypatch.setenv("PLUGINS_GRPC_SERVER_SSL_ENABLED", "")
        s = PluginsSettings()
        assert s.server_ssl_cert_reqs is None
        assert s.server_port is None
        assert s.server_ssl_enabled is None
        assert s.client_mtls_verify is None
        assert s.client_mtls_check_hostname is None
        assert s.grpc_client_mtls_verify is None
        assert s.grpc_server_port is None
        assert s.grpc_server_ssl_enabled is None


class TestPluginsSettingsModuleSingleton:
    """Test the module-level settings singleton."""

    def test_module_settings_instance_exists(self):
        from mcpgateway.plugins.framework.settings import settings

        assert settings


class TestPluginsSettingsStartupIsolation:
    """Startup fields must not fail due to unrelated malformed plugin env vars."""

    def test_config_file_survives_malformed_server_port(self, monkeypatch):
        """config_file must be readable even with PLUGINS_SERVER_PORT=abc."""
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_SERVER_PORT", "not_a_number")
        settings.cache_clear()
        try:
            assert settings.config_file == "plugins/config.yaml"
        finally:
            settings.cache_clear()

    def test_plugin_timeout_survives_malformed_server_port(self, monkeypatch):
        """plugin_timeout must be readable even with PLUGINS_SERVER_PORT=abc."""
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_SERVER_PORT", "not_a_number")
        settings.cache_clear()
        try:
            assert settings.plugin_timeout == 30
        finally:
            settings.cache_clear()

    def test_config_file_env_override(self, monkeypatch):
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_CONFIG_FILE", "/custom/plugins.yaml")
        settings.cache_clear()
        try:
            assert settings.config_file == "/custom/plugins.yaml"
        finally:
            settings.cache_clear()

    def test_plugin_timeout_env_override(self, monkeypatch):
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_PLUGIN_TIMEOUT", "60")
        settings.cache_clear()
        try:
            assert settings.plugin_timeout == 60
        finally:
            settings.cache_clear()



class TestPluginsSettingsEnabledFlag:
    """Test lazy enabled flag resolution behavior."""

    def test_enabled_reads_from_env_file_without_parsing_full_settings(self, monkeypatch, tmp_path):
        from mcpgateway.plugins.framework.settings import settings

        env_file = tmp_path / ".env"
        env_file.write_text("PLUGINS_ENABLED=true\nPLUGINS_SERVER_PORT=abc\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
        settings.cache_clear()

        assert settings.enabled is True

    def test_enabled_reads_inline_comment_value(self, monkeypatch, tmp_path):
        from mcpgateway.plugins.framework.settings import settings

        env_file = tmp_path / ".env"
        env_file.write_text("PLUGINS_ENABLED=true # enable plugin framework\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
        settings.cache_clear()

        assert settings.enabled is True


class TestPluginsHttpClientSettings:
    """Test the lightweight PluginsHttpClientSettings model."""

    def test_defaults(self):
        from mcpgateway.plugins.framework.settings import PluginsHttpClientSettings

        s = PluginsHttpClientSettings()
        assert s.skip_ssl_verify is False
        assert s.httpx_max_connections == 200
        assert s.httpx_max_keepalive_connections == 100
        assert s.httpx_keepalive_expiry == 30.0
        assert s.httpx_connect_timeout == 5.0
        assert s.httpx_read_timeout == 120.0
        assert s.httpx_write_timeout == 30.0
        assert s.httpx_pool_timeout == 10.0

    def test_env_override(self, monkeypatch):
        from mcpgateway.plugins.framework.settings import PluginsHttpClientSettings

        monkeypatch.setenv("PLUGINS_HTTPX_CONNECT_TIMEOUT", "15.0")
        monkeypatch.setenv("PLUGINS_SKIP_SSL_VERIFY", "true")
        s = PluginsHttpClientSettings()
        assert s.httpx_connect_timeout == 15.0
        assert s.skip_ssl_verify is True

    def test_get_http_client_settings_cached(self):
        from mcpgateway.plugins.framework.settings import get_http_client_settings

        s1 = get_http_client_settings()
        s2 = get_http_client_settings()
        assert s1 is s2


class TestPluginsCliSettings:
    """Test the lightweight PluginsCliSettings model."""

    @pytest.fixture(autouse=True)
    def _clean_cli_env(self, monkeypatch):
        """Remove PLUGINS_CLI_ env vars and .env file so tests verify true defaults."""
        for key in list(os.environ):
            if key.startswith("PLUGINS_CLI_"):
                monkeypatch.delenv(key, raising=False)
        from mcpgateway.plugins.framework.settings import PluginsCliSettings

        monkeypatch.setattr(PluginsCliSettings, "model_config", {**PluginsCliSettings.model_config, "env_file": None})

    def test_defaults(self):
        from mcpgateway.plugins.framework.settings import PluginsCliSettings

        s = PluginsCliSettings()
        assert s.cli_completion is False
        assert s.cli_markup_mode is None

    def test_env_override(self, monkeypatch):
        from mcpgateway.plugins.framework.settings import PluginsCliSettings

        monkeypatch.setenv("PLUGINS_CLI_COMPLETION", "true")
        monkeypatch.setenv("PLUGINS_CLI_MARKUP_MODE", "markdown")
        s = PluginsCliSettings()
        assert s.cli_completion is True
        assert s.cli_markup_mode == "markdown"

    def test_get_cli_settings_cached(self):
        from mcpgateway.plugins.framework.settings import get_cli_settings

        s1 = get_cli_settings()
        s2 = get_cli_settings()
        assert s1 is s2


class TestLazySettingsWrapperProperties:
    """Test LazySettingsWrapper @property methods bypass __getattr__."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for key in list(os.environ):
            if key.startswith("PLUGINS_") or key == "UNIX_SOCKET_PATH":
                monkeypatch.delenv(key, raising=False)

    def test_ssrf_protection_enabled_property(self, monkeypatch):
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_SSRF_PROTECTION_ENABLED", "false")
        settings.cache_clear()
        assert settings.ssrf_protection_enabled is False
        settings.cache_clear()

    def test_transport_property(self, monkeypatch):
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_TRANSPORT", "stdio")
        settings.cache_clear()
        assert settings.transport == "stdio"
        settings.cache_clear()

    def test_unix_socket_path_property(self, monkeypatch):
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_UNIX_SOCKET_PATH", "/tmp/test.sock")
        settings.cache_clear()
        assert settings.unix_socket_path == "/tmp/test.sock"
        settings.cache_clear()

    def test_default_hook_policy_property(self, monkeypatch):
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_DEFAULT_HOOK_POLICY", "deny")
        settings.cache_clear()
        assert settings.default_hook_policy == "deny"
        settings.cache_clear()

    def test_config_path_property(self, monkeypatch):
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_CONFIG_PATH", "/custom/path.yaml")
        settings.cache_clear()
        assert settings.config_path == "/custom/path.yaml"
        settings.cache_clear()

    def test_cli_completion_property(self, monkeypatch):
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_CLI_COMPLETION", "true")
        settings.cache_clear()
        assert settings.cli_completion is True
        settings.cache_clear()

    def test_cli_markup_mode_property(self, monkeypatch):
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_CLI_MARKUP_MODE", "markdown")
        settings.cache_clear()
        assert settings.cli_markup_mode == "markdown"
        settings.cache_clear()

    def test_cli_properties_survive_unrelated_malformed_env(self, monkeypatch):
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_SERVER_PORT", "not_a_number")
        monkeypatch.setenv("PLUGINS_CLI_MARKUP_MODE", "rich")
        settings.cache_clear()
        assert settings.cli_markup_mode == "rich"
        settings.cache_clear()

    def test_getattr_fallback_to_full_settings(self):
        """Accessing a field without a @property falls back to __getattr__."""
        from mcpgateway.plugins.framework.settings import settings

        settings.cache_clear()
        assert settings.plugin_timeout == 30
        settings.cache_clear()
