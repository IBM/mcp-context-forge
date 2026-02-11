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
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.settings import PluginsSettings


class TestPluginsSettingsDefaults:
    """Test that PluginsSettings has correct defaults."""

    @pytest.fixture(autouse=True)
    def _clean_plugins_env(self, monkeypatch):
        """Remove PLUGINS_ env vars so tests verify true defaults."""
        for key in list(os.environ):
            if key.startswith("PLUGINS_") or key in ("PLUGIN_CONFIG_FILE", "UNIX_SOCKET_PATH"):
                monkeypatch.delenv(key, raising=False)

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

    def test_enabled_override(self):
        with patch.dict(os.environ, {"PLUGINS_ENABLED": "true"}):
            s = PluginsSettings()
            assert s.enabled is True

    def test_plugin_timeout_override(self):
        with patch.dict(os.environ, {"PLUGINS_PLUGIN_TIMEOUT": "60"}):
            s = PluginsSettings()
            assert s.plugin_timeout == 60

    def test_skip_ssl_verify_override(self):
        with patch.dict(os.environ, {"PLUGINS_SKIP_SSL_VERIFY": "true"}):
            s = PluginsSettings()
            assert s.skip_ssl_verify is True

    def test_httpx_connect_timeout_override(self):
        with patch.dict(os.environ, {"PLUGINS_HTTPX_CONNECT_TIMEOUT": "15.0"}):
            s = PluginsSettings()
            assert s.httpx_connect_timeout == 15.0

    def test_httpx_read_timeout_override(self):
        with patch.dict(os.environ, {"PLUGINS_HTTPX_READ_TIMEOUT": "300.0"}):
            s = PluginsSettings()
            assert s.httpx_read_timeout == 300.0

    def test_config_file_override(self):
        with patch.dict(os.environ, {"PLUGINS_CONFIG_FILE": "/custom/path.yaml"}):
            s = PluginsSettings()
            assert s.config_file == "/custom/path.yaml"

    def test_config_file_legacy_alias_override(self):
        """PLUGIN_CONFIG_FILE (without PLUGINS_ prefix) is supported for backwards compatibility."""
        with patch.dict(os.environ, {"PLUGIN_CONFIG_FILE": "/legacy/path.yaml"}):
            s = PluginsSettings()
            assert s.config_file == "/legacy/path.yaml"

    def test_cli_markup_mode_override(self):
        with patch.dict(os.environ, {"PLUGINS_CLI_MARKUP_MODE": "markdown"}):
            s = PluginsSettings()
            assert s.cli_markup_mode == "markdown"

    # --- New transport/TLS/runtime field overrides ---

    def test_client_mtls_verify_bool_override(self):
        with patch.dict(os.environ, {"PLUGINS_CLIENT_MTLS_VERIFY": "true"}):
            s = PluginsSettings()
            assert s.client_mtls_verify is True

    def test_server_port_int_override(self):
        with patch.dict(os.environ, {"PLUGINS_SERVER_PORT": "9000"}):
            s = PluginsSettings()
            assert s.server_port == 9000

    def test_server_host_str_override(self):
        with patch.dict(os.environ, {"PLUGINS_SERVER_HOST": "0.0.0.0"}):
            s = PluginsSettings()
            assert s.server_host == "0.0.0.0"

    def test_grpc_server_ssl_enabled_bool_override(self):
        with patch.dict(os.environ, {"PLUGINS_GRPC_SERVER_SSL_ENABLED": "false"}):
            s = PluginsSettings()
            assert s.grpc_server_ssl_enabled is False

    def test_unix_socket_path_alias_override(self):
        """UNIX_SOCKET_PATH (no PLUGINS_ prefix) is accepted via AliasChoices."""
        with patch.dict(os.environ, {"UNIX_SOCKET_PATH": "/tmp/test.sock"}):
            s = PluginsSettings()
            assert s.unix_socket_path == "/tmp/test.sock"

    def test_unix_socket_path_prefixed_override(self):
        """PLUGINS_UNIX_SOCKET_PATH is also accepted."""
        with patch.dict(os.environ, {"PLUGINS_UNIX_SOCKET_PATH": "/tmp/prefixed.sock"}):
            s = PluginsSettings()
            assert s.unix_socket_path == "/tmp/prefixed.sock"

    def test_config_path_override(self):
        with patch.dict(os.environ, {"PLUGINS_CONFIG_PATH": "/custom/config.yaml"}):
            s = PluginsSettings()
            assert s.config_path == "/custom/config.yaml"

    def test_transport_override(self):
        with patch.dict(os.environ, {"PLUGINS_TRANSPORT": "stdio"}):
            s = PluginsSettings()
            assert s.transport == "stdio"

    def test_server_ssl_cert_reqs_int_override(self):
        with patch.dict(os.environ, {"PLUGINS_SERVER_SSL_CERT_REQS": "1"}):
            s = PluginsSettings()
            assert s.server_ssl_cert_reqs == 1

    def test_grpc_server_port_int_override(self):
        with patch.dict(os.environ, {"PLUGINS_GRPC_SERVER_PORT": "50052"}):
            s = PluginsSettings()
            assert s.grpc_server_port == 50052


class TestPluginsSettingsModuleSingleton:
    """Test the module-level settings singleton."""

    def test_module_settings_instance_exists(self):
        from mcpgateway.plugins.framework.settings import settings
        assert isinstance(settings, PluginsSettings)

    def test_module_settings_is_stable_reference(self):
        from mcpgateway.plugins.framework.settings import settings as s1
        from mcpgateway.plugins.framework.settings import settings as s2
        assert s1 is s2
