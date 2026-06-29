# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/tests/test_mcp_reverse_proxy_cli.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the reverse proxy multi-transport CLI module.
"""

# Future
from __future__ import annotations

# Standard
from pathlib import Path
from unittest.mock import AsyncMock

# Third-Party
import pytest

# First-Party
import mcp_reverse_proxy.cli as cli


def test_create_mcp_transport_requires_exactly_one_transport() -> None:
    """No local transport should raise a validation error."""
    with pytest.raises(ValueError, match="Must specify one MCP server transport"):
        cli.create_mcp_transport()


def test_create_mcp_transport_rejects_multiple_transports() -> None:
    """Multiple local transports should raise a validation error."""
    with pytest.raises(ValueError, match="Can only specify one MCP server transport"):
        cli.create_mcp_transport(local_stdio="cmd", local_sse="https://example.com/sse")


def test_create_mcp_transport_stdio(monkeypatch) -> None:
    """Stdio transport should instantiate the stdio adapter."""
    captured = {}

    def _fake_stdio_adapter(command: str):
        captured["command"] = command
        return "stdio-transport"

    monkeypatch.setattr(cli, "StdioAdapter", _fake_stdio_adapter)

    result = cli.create_mcp_transport(local_stdio="python -m server")

    assert result == "stdio-transport"
    assert captured["command"] == "python -m server"


def test_create_mcp_transport_streamable_http(monkeypatch) -> None:
    """Streamable HTTP transport should pass URL and cert to adapter."""
    captured = {}

    def _fake_streamable_http_adapter(url: str, cert: str | None = None):
        captured["url"] = url
        captured["cert"] = cert
        return "streamable-http-transport"

    monkeypatch.setattr(cli, "StreamableHttpAdapter", _fake_streamable_http_adapter)

    result = cli.create_mcp_transport(local_streamable_http="https://example.com/mcp", cert="/tmp/ca.pem")

    assert result == "streamable-http-transport"
    assert captured == {"url": "https://example.com/mcp", "cert": "/tmp/ca.pem"}


def test_create_mcp_transport_sse(monkeypatch) -> None:
    """SSE transport should pass URL and cert to adapter."""
    captured = {}

    def _fake_sse_adapter(url: str, cert: str | None = None):
        captured["url"] = url
        captured["cert"] = cert
        return "sse-transport"

    monkeypatch.setattr(cli, "SseAdapter", _fake_sse_adapter)

    result = cli.create_mcp_transport(local_sse="https://example.com/sse", cert="/tmp/ca.pem")

    assert result == "sse-transport"
    assert captured == {"url": "https://example.com/sse", "cert": "/tmp/ca.pem"}


def test_create_gateway_transport_uses_websocket_adapter(monkeypatch) -> None:
    """Gateway transport factory should build the WebSocket adapter."""
    captured = {}

    def _fake_websocket_adapter(gateway_url: str, session_id: str, token: str | None = None, cert: str | None = None):
        captured["gateway_url"] = gateway_url
        captured["session_id"] = session_id
        captured["token"] = token
        captured["cert"] = cert
        return "gateway-transport"

    monkeypatch.setattr(cli, "WebSocketAdapter", _fake_websocket_adapter)

    result = cli.create_gateway_transport("wss://gateway.example/ws", "session-123", token="secret", cert="/tmp/ca.pem")

    assert result == "gateway-transport"
    assert captured == {
        "gateway_url": "wss://gateway.example/ws",
        "session_id": "session-123",
        "token": "secret",
        "cert": "/tmp/ca.pem",
    }


def test_parse_args_reads_gateway_and_token_from_environment(monkeypatch) -> None:
    """Environment variables should supply missing gateway and token values."""
    monkeypatch.setenv(cli.ENV_GATEWAY, "wss://gateway.example/ws")
    monkeypatch.setenv(cli.ENV_TOKEN, "env-token")
    monkeypatch.setattr("uuid.uuid4", lambda: "generated-uuid")

    args = cli.parse_args(["--local-stdio", "python -m server"])

    assert args.gateway == "wss://gateway.example/ws"
    assert args.token == "env-token"
    assert args.server_id == "generated-uuid"


def test_parse_args_verbose_sets_debug_log_level(monkeypatch) -> None:
    """Verbose flag should override the configured log level."""
    monkeypatch.setenv(cli.ENV_GATEWAY, "wss://gateway.example/ws")
    monkeypatch.delenv(cli.ENV_TOKEN, raising=False)
    monkeypatch.setattr("uuid.uuid4", lambda: "generated-uuid")

    args = cli.parse_args(["--local-stdio", "python -m server", "--log-level", "ERROR", "--verbose"])

    assert args.log_level == "DEBUG"


def test_parse_args_json_config_merges_missing_values_only(tmp_path: Path, monkeypatch) -> None:
    """JSON config should fill missing args but not override explicit CLI values."""
    config_file = tmp_path / "config.json"
    config_file.write_text(
        """
{
  "gateway": "wss://config.example/ws",
  "token": "config-token",
  "server-name": "config-server",
  "reconnect-delay": 5.5
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.delenv(cli.ENV_GATEWAY, raising=False)
    monkeypatch.delenv(cli.ENV_TOKEN, raising=False)
    monkeypatch.setattr("uuid.uuid4", lambda: "generated-uuid")

    args = cli.parse_args(
        [
            "--config",
            str(config_file),
            "--local-stdio",
            "python -m server",
            "--gateway",
            "wss://cli.example/ws",
        ]
    )

    assert args.gateway == "wss://cli.example/ws"
    assert args.token == "config-token"
    assert args.server_name == "config-server"
    assert args.reconnect_delay == cli.DEFAULT_RECONNECT_DELAY
    assert args.server_id == "generated-uuid"


def test_parse_args_yaml_config_requires_yaml_support(tmp_path: Path, monkeypatch) -> None:
    """YAML config should fail clearly when PyYAML is unavailable."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("gateway: wss://config.example/ws\n", encoding="utf-8")
    monkeypatch.setattr(cli, "yaml", None)

    with pytest.raises(SystemExit):
        cli.parse_args(["--config", str(config_file), "--local-stdio", "python -m server"])


def test_parse_args_rejects_non_mapping_config(tmp_path: Path, monkeypatch) -> None:
    """Top-level config must be an object/mapping."""
    config_file = tmp_path / "config.json"
    config_file.write_text('["not", "an", "object"]', encoding="utf-8")
    monkeypatch.delenv(cli.ENV_GATEWAY, raising=False)
    monkeypatch.delenv(cli.ENV_TOKEN, raising=False)

    with pytest.raises(SystemExit):
        cli.parse_args(["--config", str(config_file), "--local-stdio", "python -m server"])


def test_parse_args_requires_gateway_when_not_in_args_or_environment(monkeypatch) -> None:
    """Gateway is mandatory unless provided by CLI or environment."""
    monkeypatch.delenv(cli.ENV_GATEWAY, raising=False)
    monkeypatch.delenv(cli.ENV_TOKEN, raising=False)

    with pytest.raises(SystemExit):
        cli.parse_args(["--local-stdio", "python -m server"])


@pytest.mark.asyncio
async def test_main_creates_client_and_disconnects_on_shutdown(monkeypatch) -> None:
    """Main should build transports/client and disconnect during cleanup."""
    args = cli.argparse.Namespace(
        local_stdio="python -m server",
        local_streamable_http=None,
        local_sse=None,
        cert="/tmp/ca.pem",
        gateway="wss://gateway.example/ws",
        server_id="server-123",
        token="token-123",
        server_name="Server Name",
        server_description="Server Description",
        reconnect_delay=2.5,
        max_retries=3,
        keepalive=7,
        mcp_health_check_timeout=11.0,
        mcp_health_check_retry_interval=1.5,
        log_level="INFO",
    )
    monkeypatch.setattr(cli, "parse_args", lambda argv=None: args)

    created: dict[str, object] = {}
    disconnect_mock = AsyncMock()

    def _fake_create_mcp_transport(**kwargs):
        created["mcp_transport_kwargs"] = kwargs
        return "mcp-transport"

    def _fake_create_gateway_transport(**kwargs):
        created["gateway_transport_kwargs"] = kwargs
        return "gateway-transport"

    class _FakeClient:
        def __init__(self, **kwargs):
            created["client_kwargs"] = kwargs
            self.disconnect = disconnect_mock

        async def run_with_reconnect(self):
            return None

    monkeypatch.setattr(cli, "create_mcp_transport", _fake_create_mcp_transport)
    monkeypatch.setattr(cli, "create_gateway_transport", _fake_create_gateway_transport)
    monkeypatch.setattr(cli, "ReverseProxyClient", _FakeClient)

    await cli.main([])

    assert created["mcp_transport_kwargs"] == {
        "local_stdio": "python -m server",
        "local_streamable_http": None,
        "local_sse": None,
        "cert": "/tmp/ca.pem",
        "mcp_cert": None,
        "cert_from_cli": False,
    }
    assert created["gateway_transport_kwargs"] == {
        "gateway_url": "wss://gateway.example/ws",
        "session_id": "server-123",
        "token": "token-123",
        "cert": "/tmp/ca.pem",
        "gateway_cert": None,
        "cert_from_cli": False,
    }
    assert created["client_kwargs"] == {
        "mcp_transport": "mcp-transport",
        "gateway_transport": "gateway-transport",
        "session_id": "server-123",
        "server_name": "Server Name",
        "server_description": "Server Description",
        "reconnect_delay": 2.5,
        "max_retries": 3,
        "keepalive_interval": 7,
        "mcp_health_check_timeout": 11.0,
        "mcp_health_check_retry_interval": 1.5,
    }
    disconnect_mock.assert_awaited_once()


def test_run_exits_zero_on_keyboard_interrupt(monkeypatch) -> None:
    """KeyboardInterrupt should produce a clean zero exit code."""

    def _raise_keyboard_interrupt(_coro) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli.asyncio, "run", _raise_keyboard_interrupt)

    with pytest.raises(SystemExit) as exc_info:
        cli.run()

    assert exc_info.value.code == 0


def test_run_exits_one_on_stdio_subprocess_terminated(monkeypatch) -> None:
    """Stdio subprocess termination should exit non-zero for supervisor restart."""

    def _raise_stdio_terminated(_coro) -> None:
        raise cli.StdioSubprocessTerminated("subprocess died")

    monkeypatch.setattr(cli.asyncio, "run", _raise_stdio_terminated)

    with pytest.raises(SystemExit) as exc_info:
        cli.run()

    assert exc_info.value.code == 1


def test_run_exits_one_on_unexpected_exception(monkeypatch) -> None:
    """Unexpected exceptions should exit with status 1."""

    def _raise_runtime_error(_coro) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli.asyncio, "run", _raise_runtime_error)

    with pytest.raises(SystemExit) as exc_info:
        cli.run()

    assert exc_info.value.code == 1
