# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_runtime_settings.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for runtime environment settings.
"""

import pytest
from pydantic import ValidationError

from mcpgateway.config import Settings
from mcpgateway.config_sections import SSLCacheSettings


def test_sqlalchemy_echo_empty_disables_logging(monkeypatch):
    monkeypatch.setenv("SQLALCHEMY_ECHO", "")
    assert Settings(_env_file=None).sqlalchemy_echo is False


@pytest.mark.parametrize("value", ["", "0", "-1"])
def test_gateway_replicas_reject_invalid_values(monkeypatch, value):
    monkeypatch.setenv("GATEWAY_REPLICAS", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("value", ["", "0", "-1"])
def test_ssl_cache_max_size_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("SSL_CONTEXT_CACHE_MAX_SIZE", value)
    with pytest.raises(ValidationError):
        SSLCacheSettings(_env_file=None)


def test_sqlalchemy_echo_rejects_invalid_value(monkeypatch):
    monkeypatch.setenv("SQLALCHEMY_ECHO", "invalid")
    with pytest.raises(ValidationError, match="sqlalchemy_echo"):
        Settings(_env_file=None)


def test_loopback_key_requires_certificate(monkeypatch):
    monkeypatch.delenv("LOOPBACK_CLIENT_CERT", raising=False)
    monkeypatch.setenv("LOOPBACK_CLIENT_KEY", "/tmp/client.key")
    with pytest.raises(ValidationError, match="LOOPBACK_CLIENT_CERT and LOOPBACK_CLIENT_KEY"):
        Settings(_env_file=None)


@pytest.mark.parametrize("value, expected", [("", None), ("   ", None), ("60", 60)])
def test_ssl_cache_ttl_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("SSL_CONTEXT_CACHE_TTL", value)
    assert SSLCacheSettings(_env_file=None).ssl_context_cache_ttl == expected


@pytest.mark.parametrize("value", ["invalid", "0", "-1"])
def test_ssl_cache_ttl_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("SSL_CONTEXT_CACHE_TTL", value)
    with pytest.raises(ValidationError, match="ssl_context_cache_ttl"):
        SSLCacheSettings(_env_file=None)
