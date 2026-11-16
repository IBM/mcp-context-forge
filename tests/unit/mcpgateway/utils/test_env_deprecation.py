# -*- coding: utf-8 -*-
"""Tests for environment variable deprecation warnings."""

import logging

from mcpgateway.config import EnvDeprecation
from mcpgateway.utils import env_deprecation


def test_removed_variables_warn_for_case_insensitive_glob_matches(caplog):
    with caplog.at_level(logging.WARNING, logger=env_deprecation.__name__):
        env_deprecation.warn_deprecated_envs({"mcp_session_pool_size": "5", "MCP_SESSION_POOL_TTL": "10", "OTHER": "1"})

    assert len(caplog.records) == 1
    assert "mcp_session_pool_size" in caplog.text
    assert "MCP_SESSION_POOL_TTL" in caplog.text
    assert "OTHER" not in caplog.text
    assert "removed" in caplog.text


def test_deprecated_variable_warns_from_custom_mapping(monkeypatch, caplog):
    monkeypatch.setattr(env_deprecation, "DEPRECATED_ENVS", (EnvDeprecation("OLD_SETTING", "Use NEW_SETTING."),))
    monkeypatch.setenv("MCP_SESSION_POOL_SIZE", "5")

    with caplog.at_level(logging.WARNING, logger=env_deprecation.__name__):
        env_deprecation.warn_deprecated_envs({"old_setting": "value"})

    assert len(caplog.records) == 1
    assert "old_setting" in caplog.text
    assert "NEW_SETTING" in caplog.text
    assert "MCP_SESSION_POOL_SIZE" not in caplog.text


def test_default_environment_and_empty_mapping(monkeypatch, caplog):
    monkeypatch.setenv("MCP_SESSION_POOL_SIZE", "5")
    with caplog.at_level(logging.WARNING, logger=env_deprecation.__name__):
        env_deprecation.warn_deprecated_envs({})
        assert not caplog.records
        env_deprecation.warn_deprecated_envs()

    assert len(caplog.records) == 1
    assert "MCP_SESSION_POOL_SIZE" in caplog.text
