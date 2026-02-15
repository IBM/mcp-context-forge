# -*- coding: utf-8 -*-
"""Tests for mcpgateway.plugins.framework.models."""

# Standard
import os
from pathlib import Path

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import TransportType
from mcpgateway.plugins.framework.constants import EXTERNAL_PLUGIN_TYPE
from mcpgateway.plugins.framework.models import (
    MCPClientConfig,
    MCPClientTLSConfig,
    MCPServerConfig,
    MCPServerTLSConfig,
    PluginConfig,
)


def _write_file(tmp_path: Path, name: str) -> str:
    file_path = tmp_path / name
    file_path.write_text("data")
    return str(file_path)


def test_bool_parsing_via_settings(monkeypatch):
    """Bool fields on PluginsSettings handle true/false strings correctly."""
    # First-Party
    from mcpgateway.plugins.framework.settings import PluginsSettings

    monkeypatch.setenv("PLUGINS_CLIENT_MTLS_VERIFY", "true")
    assert PluginsSettings().client_mtls_verify is True

    monkeypatch.setenv("PLUGINS_CLIENT_MTLS_VERIFY", "0")
    assert PluginsSettings().client_mtls_verify is False


def test_client_tls_from_env(monkeypatch, tmp_path):
    cert = _write_file(tmp_path, "client-cert.pem")
    key = _write_file(tmp_path, "client-key.pem")
    ca = _write_file(tmp_path, "client-ca.pem")

    monkeypatch.setenv("PLUGINS_CLIENT_MTLS_CERTFILE", cert)
    monkeypatch.setenv("PLUGINS_CLIENT_MTLS_KEYFILE", key)
    monkeypatch.setenv("PLUGINS_CLIENT_MTLS_CA_BUNDLE", ca)
    monkeypatch.setenv("PLUGINS_CLIENT_MTLS_KEYFILE_PASSWORD", "pw")
    monkeypatch.setenv("PLUGINS_CLIENT_MTLS_VERIFY", "false")
    monkeypatch.setenv("PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME", "0")

    config = MCPClientTLSConfig.from_env()
    assert config is not None
    assert config.certfile == os.path.expanduser(cert)
    assert config.keyfile == os.path.expanduser(key)
    assert config.ca_bundle == os.path.expanduser(ca)
    assert config.verify is False
    assert config.check_hostname is False


def test_server_tls_from_env_invalid_cert_reqs(monkeypatch):
    monkeypatch.setenv("PLUGINS_SERVER_SSL_CERT_REQS", "not-an-int")
    with pytest.raises((ValueError, Exception)):
        MCPServerTLSConfig.from_env()


@pytest.mark.parametrize("uds_value", [""])
def test_server_config_uds_validation_errors(uds_value):
    with pytest.raises(ValueError):
        MCPServerConfig(uds=uds_value)


def test_server_config_uds_missing_parent(tmp_path):
    missing = tmp_path / "missing" / "sock"
    with pytest.raises(ValueError):
        MCPServerConfig(uds=str(missing))


def test_server_config_uds_valid(tmp_path):
    uds_path = tmp_path / "socket.sock"
    config = MCPServerConfig(uds=str(uds_path))
    assert config.uds == str(uds_path.resolve())


def test_server_config_tls_with_uds_raises(tmp_path):
    uds_path = tmp_path / "socket.sock"
    tls = MCPServerTLSConfig()
    with pytest.raises(ValueError):
        MCPServerConfig(uds=str(uds_path), tls=tls)


def test_server_config_from_env_invalid_port(monkeypatch):
    monkeypatch.setenv("PLUGINS_SERVER_PORT", "bad")
    with pytest.raises((ValueError, Exception)):
        MCPServerConfig.from_env()


def test_server_config_from_env_with_tls(monkeypatch, tmp_path):
    cert = _write_file(tmp_path, "server-cert.pem")
    key = _write_file(tmp_path, "server-key.pem")
    monkeypatch.setenv("PLUGINS_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("PLUGINS_SERVER_PORT", "9000")
    monkeypatch.setenv("PLUGINS_SERVER_SSL_ENABLED", "true")
    monkeypatch.setenv("PLUGINS_SERVER_SSL_CERTFILE", cert)
    monkeypatch.setenv("PLUGINS_SERVER_SSL_KEYFILE", key)

    config = MCPServerConfig.from_env()
    assert config is not None
    assert config.host == "0.0.0.0"
    assert config.port == 9000
    assert config.tls is not None


def test_client_config_script_requires_executable(tmp_path):
    script = tmp_path / "script.txt"
    script.write_text("data")
    with pytest.raises(ValueError):
        MCPClientConfig(proto=TransportType.STDIO, script=str(script))


@pytest.mark.parametrize("cmd_value", [[], [""], [" ", "x"]])
def test_client_config_cmd_validation(cmd_value):
    with pytest.raises(ValueError):
        MCPClientConfig(proto=TransportType.STDIO, cmd=cmd_value)


@pytest.mark.parametrize("env_value", [{}, {"KEY": 1}])
def test_client_config_env_validation(env_value):
    with pytest.raises(ValueError):
        MCPClientConfig(proto=TransportType.STDIO, cmd=["python"], env=env_value)


def test_client_config_cwd_validation(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(ValueError):
        MCPClientConfig(proto=TransportType.STDIO, cmd=["python"], cwd=str(missing))


@pytest.mark.parametrize("uds_value", [""])
def test_client_config_uds_validation_errors(uds_value):
    with pytest.raises(ValueError):
        MCPClientConfig(proto=TransportType.STREAMABLEHTTP, uds=uds_value)


def test_client_config_uds_missing_parent(tmp_path):
    missing = tmp_path / "missing" / "sock"
    with pytest.raises(ValueError):
        MCPClientConfig(proto=TransportType.STREAMABLEHTTP, uds=str(missing))


def test_client_config_tls_usage_errors(tmp_path):
    tls = MCPClientTLSConfig()
    with pytest.raises(ValueError):
        MCPClientConfig(proto=TransportType.STDIO, cmd=["python"], tls=tls)

    uds_path = tmp_path / "socket.sock"
    with pytest.raises(ValueError):
        MCPClientConfig(proto=TransportType.STREAMABLEHTTP, uds=str(uds_path), tls=tls)


def test_client_config_transport_field_errors():
    with pytest.raises(ValueError):
        MCPClientConfig(proto=TransportType.STDIO, url="https://example.com", cmd=["python"])

    with pytest.raises(ValueError):
        MCPClientConfig(proto=TransportType.SSE, script="script.py")

    with pytest.raises(ValueError):
        MCPClientConfig(proto=TransportType.SSE, uds="/tmp/socket.sock")


def test_plugin_config_stdio_requires_script_or_cmd():
    mcp = MCPClientConfig(proto=TransportType.STDIO, cmd=None)
    with pytest.raises(ValueError):
        PluginConfig(name="plug", kind="internal", mcp=mcp)


def test_plugin_config_stdio_script_and_cmd_conflict():
    mcp = MCPClientConfig(proto=TransportType.STDIO, script="script.py", cmd=["python"])
    with pytest.raises(ValueError):
        PluginConfig(name="plug", kind="internal", mcp=mcp)


def test_plugin_config_http_requires_url():
    mcp = MCPClientConfig(proto=TransportType.SSE)
    with pytest.raises(ValueError):
        PluginConfig(name="plug", kind="internal", mcp=mcp)


def test_plugin_config_external_requires_mcp():
    with pytest.raises(ValueError):
        PluginConfig(name="external", kind=EXTERNAL_PLUGIN_TYPE)


def test_plugin_config_external_config_disallowed():
    mcp = MCPClientConfig(proto=TransportType.SSE, url="https://example.com")
    with pytest.raises(ValueError):
        PluginConfig(name="external", kind=EXTERNAL_PLUGIN_TYPE, config={"x": 1}, mcp=mcp)


def test_transport_type_enum_parity():
    """Ensure framework and common TransportType enums stay in sync."""
    # First-Party
    from mcpgateway.plugins.framework.models import TransportType as FrameworkTransportType

    common_members = {m.name: m.value for m in TransportType}
    framework_members = {m.name: m.value for m in FrameworkTransportType}
    assert framework_members == common_members, (
        f"TransportType enums diverged. " f"Common-only: {set(common_members) - set(framework_members)}, " f"Framework-only: {set(framework_members) - set(common_members)}"
    )
