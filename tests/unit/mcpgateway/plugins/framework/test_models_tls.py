# -*- coding: utf-8 -*-
"""Tests for TLS configuration on external MCP plugins."""

# Standard
from pathlib import Path

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.models import MCPClientTLSConfig, PluginConfig


def _write_pem(path: Path) -> str:
    path.write_text(
        "-----BEGIN CERTIFICATE-----\nMIIBszCCAVmgAwIBAgIJALICEFAKE000MA0GCSqGSIb3DQEBCwUAMBQxEjAQBgNV\nBAMMCXRlc3QtY2EwHhcNMjUwMTAxMDAwMDAwWhcNMjYwMTAxMDAwMDAwWjAUMRIw\nEAYDVQQDDAl0ZXN0LWNsaTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEB\nALzM8FSo48ByKC16ecEsPpRghr7kDDLOZWisS+8mHb4RLzdrg5e8tRgFuBlbslUT\n8VE+j54v+J2mOv5u18CVeq4xjp1IqP/PpeL9Z8sY2XohGKVCUj8lMiMM6trXwPh3\n4nDXwG8hxhTZWOeAZv93FqMgBANpUAOC0yM5Ar+uSoC2Tbf3juDEnHiVNWdP6hJg\n38zrla9Yh+SPYj9m6z6wG6jZc37SaJnKI/v4ycq31wkK7S226gRA7i72H+eEt1Kp\nI5rkJ+6kkfgeJc8FvbB6c88T9EycneEW7Pm2Xp6gJdxeN1g2jeDJPnWc5Cj9VPYU\nCJPwy6DnKSmGA4MZij19+cUCAwEAAaNQME4wHQYDVR0OBBYEFL0CyJXw5CtP6Ls9\nVgn8BxwysA2fMB8GA1UdIwQYMBaAFL0CyJXw5CtP6Ls9Vgn8BxwysA2fMAwGA1Ud\nEwQFMAMBAf8wDQYJKoZIhvcNAQELBQADggEBAIgUjACmJS4cGL7yp0T1vpuZi856\nG7k18Om8Ze9fJbVI1MBBxDWS5F9bNOn5z1ytgCMs9VXg7QibQPXlqprcM2aYJWaV\ndHZ92ohqzJ0EB1G2r8x5Fkw3O0mEWcJvl10FgUVHVGzi552MZGFMZ7DAMA4EAq/u\nsOUgWup8uLSyvvl7dao3rJ8k+YkBWkDu6eCKwQn3nNKFB5Bg9P6IKkmDdLhYodl/\nW1q/qmHZapCp8XDsrmS8skWsmcFJFU6f4VDOwdJaNiMgRGQpWlwO4dRw9xvyhsHc\nsOf0HWNvw60sX6Zav8HC0FzDGhGJkpyyU10BzpQLVEf5AEE7MkK5eeqi2+0=\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
    return str(path)


@pytest.mark.parametrize(
    "verify",
    [True, False],
)
def test_plugin_config_supports_tls_block(tmp_path, verify):
    ca_path = Path(tmp_path) / "ca.crt"
    client_bundle = Path(tmp_path) / "client.pem"
    _write_pem(ca_path)
    _write_pem(client_bundle)

    config = PluginConfig(
        name="ExternalTLSPlugin",
        kind="external",
        hooks=["prompt_pre_fetch"],
        mcp={
            "proto": "STREAMABLEHTTP",
            "url": "https://plugins.internal.example.com/mcp",
            "tls": {
                "ca_bundle": str(ca_path),
                "certfile": str(client_bundle),
                "verify": verify,
            },
        },
    )

    assert config.mcp is not None
    assert config.mcp.tls is not None
    assert config.mcp.tls.certfile == str(client_bundle)
    assert config.mcp.tls.verify == verify


def test_plugin_config_tls_missing_cert_raises(tmp_path):
    ca_path = Path(tmp_path) / "ca.crt"
    _write_pem(ca_path)

    with pytest.raises(ValueError):
        PluginConfig(
            name="ExternalTLSPlugin",
            kind="external",
            hooks=["prompt_pre_fetch"],
            mcp={
                "proto": "STREAMABLEHTTP",
                "url": "https://plugins.internal.example.com/mcp",
                "tls": {
                    "keyfile": str(ca_path),
                },
            },
        )


def test_plugin_config_tls_missing_file(tmp_path):
    missing_path = Path(tmp_path) / "missing.crt"

    with pytest.raises(ValueError):
        PluginConfig(
            name="ExternalTLSPlugin",
            kind="external",
            hooks=["prompt_pre_fetch"],
            mcp={
                "proto": "STREAMABLEHTTP",
                "url": "https://plugins.internal.example.com/mcp",
                "tls": {
                    "ca_bundle": str(missing_path),
                },
            },
        )


def test_tls_config_from_env_defaults(monkeypatch, tmp_path):
    ca_path = Path(tmp_path) / "ca.crt"
    client_cert = Path(tmp_path) / "client.pem"
    _write_pem(ca_path)
    _write_pem(client_cert)

    monkeypatch.setenv("PLUGINS_CLIENT_MTLS_CA_BUNDLE", str(ca_path))
    monkeypatch.setenv("PLUGINS_CLIENT_MTLS_CERTFILE", str(client_cert))
    monkeypatch.setenv("PLUGINS_CLIENT_MTLS_VERIFY", "true")
    monkeypatch.setenv("PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME", "true")

    tls_config = MCPClientTLSConfig.from_env()

    assert tls_config is not None
    assert tls_config.ca_bundle == str(ca_path)
    assert tls_config.certfile == str(client_cert)
    assert tls_config.verify is True
    assert tls_config.check_hostname is True


def test_tls_config_from_env_returns_none(monkeypatch):
    monkeypatch.delenv("PLUGINS_MTLS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("PLUGINS_MTLS_CLIENT_CERT", raising=False)
    monkeypatch.delenv("PLUGINS_MTLS_CLIENT_KEY", raising=False)
    monkeypatch.delenv("PLUGINS_MTLS_CLIENT_KEY_PASSWORD", raising=False)
    monkeypatch.delenv("PLUGINS_MTLS_VERIFY", raising=False)
    monkeypatch.delenv("PLUGINS_MTLS_CHECK_HOSTNAME", raising=False)

    assert MCPClientTLSConfig.from_env() is None
