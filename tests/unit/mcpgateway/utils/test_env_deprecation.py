# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_env_deprecation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for environment variable deprecation warnings.
"""

import logging

from mcpgateway.utils import env_deprecation


def test_removed_variables_warn_for_case_insensitive_glob_matches(caplog):
    with caplog.at_level(logging.WARNING, logger=env_deprecation.__name__):
        env_deprecation.warn_deprecated_envs({"mcp_session_pool_size": "5", "MCP_SESSION_POOL_TTL": "10", "OTHER": "1"})

    assert len(caplog.records) == 1
    assert "mcp_session_pool_size" in caplog.text
    assert "MCP_SESSION_POOL_TTL" in caplog.text
    assert "OTHER" not in caplog.text
    assert "removed" in caplog.text
    assert "UpstreamSessionRegistry" in caplog.text
    assert "mcpgateway/services/upstream_session_registry.py" in caplog.text


def test_deprecated_variable_warns_from_custom_mapping(monkeypatch, caplog):
    monkeypatch.setattr(env_deprecation, "DEPRECATED_ENVS", [("OLD_SETTING", "Use NEW_SETTING.")])
    monkeypatch.setenv("MCP_SESSION_POOL_SIZE", "5")

    with caplog.at_level(logging.WARNING, logger=env_deprecation.__name__):
        env_deprecation.warn_deprecated_envs({"old_setting": "value"})

    assert len(caplog.records) == 1
    assert "old_setting" in caplog.text
    assert "NEW_SETTING" in caplog.text
    assert "MCP_SESSION_POOL_SIZE" not in caplog.text


def test_default_environment_and_empty_mapping(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("MCP_SESSION_POOL_SIZE", "5")
    monkeypatch.chdir(tmp_path)
    with caplog.at_level(logging.WARNING, logger=env_deprecation.__name__):
        env_deprecation.warn_deprecated_envs({})
        assert not caplog.records
        env_deprecation.warn_deprecated_envs()

    assert len(caplog.records) == 1
    assert "MCP_SESSION_POOL_SIZE" in caplog.text


def test_warns_for_dotenv_and_false_deprecated_value(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("MCP_SESSION_POOL_SIZE", raising=False)
    monkeypatch.delenv("EXPOSE_ERROR_DETAILS", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("MCP_SESSION_POOL_SIZE=5\nEXPOSE_ERROR_DETAILS=false\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.WARNING, logger=env_deprecation.__name__):
        env_deprecation.warn_deprecated_envs()

    assert "mcp_session_pool_size" in caplog.text.lower()
    assert "expose_error_details" in caplog.text.lower()


def test_warns_for_removed_process_environment(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("MCP_SESSION_POOL_SIZE", "5")
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.WARNING, logger=env_deprecation.__name__):
        env_deprecation.warn_deprecated_envs()

    assert "MCP_SESSION_POOL_SIZE" in caplog.text
