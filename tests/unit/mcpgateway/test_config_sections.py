# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_config_sections.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for shared environment configuration and standalone consumers.
"""

# Standard
import importlib
import json
import os
from pathlib import Path
import runpy
import secrets
import sys

# Third-Party
from pydantic import SecretStr, ValidationError
import pytest

# First-Party
from mcpgateway import cli
from mcpgateway.config import Settings
from mcpgateway.config_sections import (
    BuilderSettings,
    ClientAuthSettings,
    DatabaseSettings,
    ListenerHostSettings,
    ListenerSettings,
    RedisReadinessSettings,
    ReverseProxySettings,
    SSLCacheSettings,
    ToolOpsSettings,
)
from mcpgateway.services.support_bundle_service import SupportBundleService


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Isolate process and file configuration for source precedence tests."""
    monkeypatch.chdir(tmp_path)
    for name in ("HOST", "PORT", "MCG_HOST", "MCG_PORT", "LOG_LEVEL", "MCPGATEWAY_BEARER_TOKEN", "OPENAI_API_KEY", "REVERSE_PROXY_TOKEN", "DEFAULT_PASSTHROUGH_HEADERS", "ALLOWED_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


@pytest.mark.parametrize(
    ("file_values", "env_values", "expected"),
    [
        ("", {}, 4444),
        ("PORT=5001\n", {}, 5001),
        ("MCG_PORT=5002\n", {}, 5002),
        ("PORT=5001\nMCG_PORT=5002\n", {}, 5001),
        ("PORT=5001\n", {"MCG_PORT": "5002"}, 5002),
        ("MCG_PORT=5002\n", {"PORT": "5003"}, 5003),
        ("PORT=5001\n", {"PORT": "5003", "MCG_PORT": "5002"}, 5003),
    ],
)
def test_listener_alias_source_precedence(isolated_config, monkeypatch, file_values, env_values, expected):
    """Process source priority applies before canonical alias priority."""
    (isolated_config / ".env").write_text(file_values)
    for name, value in env_values.items():
        monkeypatch.setenv(name, value)
    assert ListenerSettings().port == expected
    assert Settings().port == expected
    argv = cli._insert_defaults([])
    assert argv[argv.index("--port") + 1] == str(expected)


def test_explicit_listener_options_override_invalid_environment(isolated_config, monkeypatch):
    """Explicit CLI values override invalid environment values, including equals syntax."""
    monkeypatch.setenv("PORT", "invalid")
    args = ["--host=127.0.0.2", "--port=8765"]
    assert cli._insert_defaults(args) == [cli.DEFAULT_APP, *args]


@pytest.mark.parametrize("name", ["HOST", "MCG_HOST"])
@pytest.mark.parametrize("source", ["process", "file"])
def test_empty_host_is_rejected_across_settings_models(isolated_config, monkeypatch, name, source):
    """Empty configured hosts fail validation instead of selecting wildcard listeners."""
    if source == "process":
        (isolated_config / ".env").write_text("HOST=127.0.0.2\n")
        monkeypatch.setenv(name, "")
    else:
        (isolated_config / ".env").write_text(f"{name}=\n")
    for model in (ListenerHostSettings, ListenerSettings, Settings):
        with pytest.raises(ValidationError) as exc:
            model()
        assert any(error["loc"] == ("host",) and error["type"] == "string_too_short" for error in exc.value.errors())


@pytest.mark.parametrize("source", ["process", "file"])
def test_empty_canonical_host_does_not_fall_back_to_legacy_alias(isolated_config, monkeypatch, source):
    """Invalid canonical hosts remain authoritative over valid legacy aliases."""
    if source == "process":
        monkeypatch.setenv("HOST", "")
        monkeypatch.setenv("MCG_HOST", "127.0.0.2")
    else:
        (isolated_config / ".env").write_text("HOST=\nMCG_HOST=127.0.0.2\n")
    with pytest.raises(ValidationError, match="host"):
        ListenerHostSettings()


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0", "::"])
def test_nonempty_listener_hosts_remain_supported(isolated_config, monkeypatch, host):
    """Configured loopback and wildcard addresses retain explicit support."""
    monkeypatch.setenv("HOST", host)
    for model in (ListenerHostSettings, ListenerSettings, Settings):
        assert model().host == host


def test_unset_listener_host_defaults_to_loopback(isolated_config):
    """Missing host configuration preserves the loopback default across consumers."""
    for model in (ListenerHostSettings, ListenerSettings, Settings):
        assert model().host == "127.0.0.1"
    argv = cli._insert_defaults([])
    assert argv[argv.index("--host") + 1] == "127.0.0.1"


def test_listener_schema_preserves_existing_property_names():
    """Environment aliases retain the existing lowercase JSON schema properties."""
    for model in (ListenerSettings, Settings):
        properties = model.model_json_schema()["properties"]
        assert properties["host"]["default"] == "127.0.0.1"
        assert properties["host"]["minLength"] == 1
        assert properties["port"]["default"] == 4444
        assert "MCG_HOST" not in properties
        assert "MCG_PORT" not in properties


@pytest.mark.parametrize("option", ["--uds=/tmp/gateway.sock", "--fd=3", "--help"])
def test_socket_options_do_not_initialize_listener_settings(isolated_config, monkeypatch, option):
    """Socket listeners and help do not require valid TCP configuration."""
    monkeypatch.setenv("PORT", "invalid")
    assert cli._insert_defaults([option]) == [cli.DEFAULT_APP, option]


@pytest.mark.parametrize("value", ["invalid", "0", "65536"])
def test_invalid_listener_port_is_rejected(isolated_config, monkeypatch, value):
    """All listener consumers use bounded port validation."""
    monkeypatch.setenv("PORT", value)
    with pytest.raises(ValidationError):
        ListenerSettings()


def test_logging_defaults_and_sources(isolated_config, monkeypatch):
    """Shared log validation retains explicit entry-point defaults."""
    assert DatabaseSettings().log_level == "ERROR"
    assert RedisReadinessSettings().log_level == "INFO"
    (isolated_config / ".env").write_text("LOG_LEVEL=warning\n")
    assert DatabaseSettings().log_level == RedisReadinessSettings().log_level == "WARNING"
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert DatabaseSettings().log_level == RedisReadinessSettings().log_level == "DEBUG"
    monkeypatch.setenv("LOG_LEVEL", "invalid")
    with pytest.raises(ValidationError):
        RedisReadinessSettings()


def test_readiness_without_gateway_secrets(isolated_config, monkeypatch):
    """Standalone readiness configuration does not validate unrelated gateway secrets."""
    monkeypatch.setenv("JWT_SECRET_KEY", "__REPLACE_ME__")
    monkeypatch.setenv("AUTH_ENCRYPTION_SECRET", "__REPLACE_ME__")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (isolated_config / ".env").write_text("DB_WAIT_MAX_TRIES=4\nDB_WAIT_INTERVAL=0.25\nREDIS_MAX_RETRIES=7\n")
    db_ready = importlib.import_module("mcpgateway.utils.db_isready")
    redis_ready = importlib.import_module("mcpgateway.utils.redis_isready")
    try:
        importlib.reload(db_ready)
        importlib.reload(redis_ready)
        assert db_ready.DEFAULT_MAX_TRIES == 4
        assert db_ready.DEFAULT_INTERVAL == 0.25
        assert redis_ready.REDIS_MAX_RETRIES == 7
    finally:
        monkeypatch.undo()
        importlib.reload(db_ready)
        importlib.reload(redis_ready)


def test_copied_database_probe_without_gateway_settings(isolated_config, monkeypatch):
    """SQLAlchemy-only probes retain their process configuration and INFO logging default."""
    monkeypatch.setitem(sys.modules, "mcpgateway.config_sections", None)
    monkeypatch.setenv("DB_WAIT_MAX_TRIES", "6")
    probe_path = Path(__file__).resolve().parents[3] / "mcpgateway" / "utils" / "db_isready.py"
    probe = runpy.run_path(str(probe_path))
    assert probe["DEFAULT_MAX_TRIES"] == 6
    assert probe["DEFAULT_LOG_LEVEL"] == "INFO"


def test_file_values_reach_oauth_and_metrics_configuration(isolated_config, monkeypatch):
    """Settings load OAuth and metrics values without exporting file values into the process."""
    (isolated_config / ".env").write_text("OAUTH_REQUEST_TIMEOUT=91\nOAUTH_MAX_RETRIES=5\nMETRICS_CUSTOM_LABELS=region=eu\n")
    cfg = Settings()
    assert (cfg.oauth_request_timeout, cfg.oauth_max_retries) == (91, 5)
    assert cfg.METRICS_CUSTOM_LABELS == "region=eu"
    for module_name, service_name in (("gateway_service", "GatewayService"), ("resource_service", "ResourceService")):
        module = importlib.import_module(f"mcpgateway.services.{module_name}")
        monkeypatch.setattr(module, "settings", cfg)
        service = getattr(module, service_name)()
        assert service.oauth_manager.request_timeout == 91
        assert service.oauth_manager.max_retries == 5


@pytest.mark.asyncio
async def test_cli_credential_file_and_environment_precedence(isolated_config, monkeypatch):
    """Bearer credentials load from files and override disabled Basic authentication."""
    from mcpgateway.cli_export_import import get_auth_token

    file_token = secrets.token_urlsafe(32)
    process_token = secrets.token_urlsafe(32)
    (isolated_config / ".env").write_text(f"MCPGATEWAY_BEARER_TOKEN={file_token}\n")
    assert await get_auth_token() == file_token
    monkeypatch.setenv("MCPGATEWAY_BEARER_TOKEN", process_token)
    assert await get_auth_token() == process_token
    assert isinstance(ClientAuthSettings().mcpgateway_bearer_token, SecretStr)


def test_migrated_secrets_are_absent_from_support_bundle(isolated_config, monkeypatch):
    """Typed credentials stay masked in serialization and excluded from diagnostic settings."""
    sentinel = secrets.token_urlsafe(48)
    for name in ("MCPGATEWAY_BEARER_TOKEN", "OPENAI_API_KEY", "AWS_SESSION_TOKEN", "REVERSE_PROXY_TOKEN"):
        monkeypatch.setenv(name, sentinel)
    cfg = Settings()
    for model in (cfg, ClientAuthSettings(), ReverseProxySettings(), ToolOpsSettings()):
        assert sentinel not in model.model_dump_json()
        assert sentinel not in repr(model)
    monkeypatch.setattr("mcpgateway.services.support_bundle_service.settings", cfg)
    service = SupportBundleService()  # type: ignore[no-untyped-call]
    exported = service._collect_settings()
    for name in ("mcpgateway_bearer_token", "openai_api_key", "aws_session_token", "reverse_proxy_token"):
        assert name not in exported
    assert sentinel not in json.dumps(exported, default=str)
    environment = service._collect_env_config()
    for name in ("MCPGATEWAY_BEARER_TOKEN", "OPENAI_API_KEY", "AWS_SESSION_TOKEN", "REVERSE_PROXY_TOKEN"):
        assert environment[name] == "*****"


def test_header_configuration_preserves_source_precedence(isolated_config, monkeypatch):
    """Header configuration respects constructor, environment, and file sources."""
    (isolated_config / ".env").write_text('DEFAULT_PASSTHROUGH_HEADERS=["X-File"]\n')
    assert Settings().default_passthrough_headers == ["X-File"]
    monkeypatch.setenv("DEFAULT_PASSTHROUGH_HEADERS", "X-Process, X-Second")
    assert Settings().default_passthrough_headers == ["X-Process", "X-Second"]
    assert Settings(default_passthrough_headers=["X-Explicit"]).default_passthrough_headers == ["X-Explicit"]


def test_explicit_file_origins_are_preserved(isolated_config):
    """Explicit file origins remain authoritative even when equal to built-in defaults."""
    (isolated_config / ".env").write_text('ALLOWED_ORIGINS=["http://localhost", "http://localhost:4444"]\n')
    assert Settings().allowed_origins == {"http://localhost", "http://localhost:4444"}


def test_cache_ttl_empty_and_invalid_values(isolated_config, monkeypatch):
    """Cache TTL parsing preserves empty and zero values while rejecting invalid numbers."""
    for raw, expected in (("", None), (" ", None), ("0", 0), ("42", 42)):
        monkeypatch.setenv("SSL_CONTEXT_CACHE_TTL", raw)
        assert SSLCacheSettings().ssl_context_cache_ttl == expected
    monkeypatch.setenv("SSL_CONTEXT_CACHE_TTL", "invalid")
    with pytest.raises(ValidationError):
        SSLCacheSettings()


def test_toolops_preserves_legacy_token_names(isolated_config, monkeypatch):
    """Legacy misspelled token variables retain their accepted names."""
    monkeypatch.setenv("OPENAI_MAX_TOEKNS", "123")
    monkeypatch.setenv("AZURE_OPENAI_MAX_TOEKNS", "234")
    cfg = ToolOpsSettings()
    assert cfg.openai_max_toekns == 123
    assert cfg.azure_openai_max_toekns == 234


@pytest.mark.parametrize("source", ["process", "file"])
@pytest.mark.parametrize("raw, expected", [("", False), ("invalid", False), ("on", False), ("true", True), ("TrUe", True), ("1", True), ("yes", True), ("false", False), ("0", False)])
def test_sql_echo_preserves_legacy_strings(isolated_config, monkeypatch, source, raw, expected):
    """Database settings preserve SQL echo parsing across process and file inputs."""
    monkeypatch.delenv("SQLALCHEMY_ECHO", raising=False)
    if source == "process":
        monkeypatch.setenv("SQLALCHEMY_ECHO", raw)
    else:
        (isolated_config / ".env").write_text(f"SQLALCHEMY_ECHO={raw}\n")
    assert DatabaseSettings().sqlalchemy_echo is expected
    assert Settings().sqlalchemy_echo is expected


def test_sql_echo_defaults_boolean_and_source_precedence(isolated_config, monkeypatch):
    """SQL echo retains false defaults, explicit booleans, and process priority."""
    monkeypatch.delenv("SQLALCHEMY_ECHO", raising=False)
    assert DatabaseSettings().sqlalchemy_echo is False
    (isolated_config / ".env").write_text("SQLALCHEMY_ECHO=true\n")
    monkeypatch.setenv("SQLALCHEMY_ECHO", "")
    assert DatabaseSettings().sqlalchemy_echo is False
    assert DatabaseSettings(sqlalchemy_echo=True).sqlalchemy_echo is True
    assert DatabaseSettings(sqlalchemy_echo=False).sqlalchemy_echo is False


@pytest.mark.parametrize("source", ["process", "file"])
def test_disabled_toolops_does_not_validate_provider_settings(isolated_config, monkeypatch, source):
    """Unused provider and utility configuration does not block gateway settings."""
    values = {"TOOLOPS_ENABLED": "false", "OPENAI_MAX_RETRIES": "invalid", "SSL_CONTEXT_CACHE_TTL": "invalid"}
    for name in values:
        monkeypatch.delenv(name, raising=False)
    if source == "process":
        for name, value in values.items():
            monkeypatch.setenv(name, value)
    else:
        (isolated_config / ".env").write_text("\n".join(f"{name}={value}" for name, value in values.items()))
    assert Settings().toolops_enabled is False
    with pytest.raises(ValidationError, match="openai_max_retries"):
        ToolOpsSettings()
    with pytest.raises(ValidationError, match="ssl_context_cache_ttl"):
        SSLCacheSettings()


def test_gateway_schema_excludes_standalone_sections():
    """Gateway settings expose only configuration owned by gateway consumers."""
    fields = Settings.model_fields
    for model in (BuilderSettings, ClientAuthSettings, ReverseProxySettings, SSLCacheSettings, ToolOpsSettings):
        assert not fields.keys() & model.model_fields.keys()


def test_builder_reads_file_without_exporting_values(isolated_config, monkeypatch):
    """Builder settings read file values without changing the process environment."""
    from mcpgateway.tools.builder.common import get_deploy_dir

    monkeypatch.delenv("MCP_DEPLOY_DIR", raising=False)
    monkeypatch.delenv("MCP_DEBUG", raising=False)
    target = isolated_config / "artifacts"
    (isolated_config / ".env").write_text(f"MCP_DEPLOY_DIR={target}\nMCP_DEBUG=1\n")
    assert get_deploy_dir() == target
    assert BuilderSettings().mcp_debug == "1"
    assert "MCP_DEPLOY_DIR" not in os.environ
    assert "MCP_DEBUG" not in os.environ
