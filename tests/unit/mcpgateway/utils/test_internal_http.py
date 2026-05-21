# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_internal_http.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for internal loopback HTTP helpers.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.internal_http import _is_ssl_enabled, internal_loopback_base_url, internal_loopback_verify


class TestIsSSLEnabled:
    """Tests for _is_ssl_enabled() edge cases."""

    def test_ssl_true(self, monkeypatch):
        monkeypatch.setenv("SSL", "true")
        assert _is_ssl_enabled() is True

    def test_ssl_false(self, monkeypatch):
        monkeypatch.setenv("SSL", "false")
        assert _is_ssl_enabled() is False

    def test_ssl_unset(self, monkeypatch):
        monkeypatch.delenv("SSL", raising=False)
        assert _is_ssl_enabled() is False

    def test_ssl_empty_string(self, monkeypatch):
        monkeypatch.setenv("SSL", "")
        assert _is_ssl_enabled() is False

    def test_ssl_uppercase_not_truthy(self, monkeypatch):
        """Shell launchers use exact [[ "${SSL}" == "true" ]], so uppercase is not truthy."""
        monkeypatch.setenv("SSL", "TRUE")
        assert _is_ssl_enabled() is False

    def test_ssl_mixed_case_not_truthy(self, monkeypatch):
        """Only exact lowercase 'true' enables SSL, matching run-gunicorn.sh / run-granian.sh."""
        monkeypatch.setenv("SSL", "True")
        assert _is_ssl_enabled() is False

    def test_ssl_with_whitespace_not_truthy(self, monkeypatch):
        """Whitespace-padded values are not truthy, matching gunicorn.config.py and shell launchers."""
        monkeypatch.setenv("SSL", " true ")
        assert _is_ssl_enabled() is False

    def test_ssl_one_is_not_truthy(self, monkeypatch):
        """Only 'true' is accepted — '1' is not, matching gunicorn.config.py."""
        monkeypatch.setenv("SSL", "1")
        assert _is_ssl_enabled() is False

    def test_ssl_yes_is_not_truthy(self, monkeypatch):
        monkeypatch.setenv("SSL", "yes")
        assert _is_ssl_enabled() is False


class TestInternalLoopbackBaseUrl:
    """Tests for internal_loopback_base_url()."""

    def test_https_when_ssl_enabled(self, monkeypatch):
        monkeypatch.setenv("SSL", "true")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_base_url() == "https://127.0.0.1:4444"

    def test_http_when_ssl_disabled(self, monkeypatch):
        monkeypatch.setenv("SSL", "false")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 8000)
        assert internal_loopback_base_url() == "http://127.0.0.1:8000"

    def test_http_when_ssl_unset(self, monkeypatch):
        monkeypatch.delenv("SSL", raising=False)
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_base_url() == "http://127.0.0.1:4444"

    def test_uses_configured_port(self, monkeypatch):
        monkeypatch.setenv("SSL", "false")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 9999)
        assert internal_loopback_base_url() == "http://127.0.0.1:9999"


class TestInternalLoopbackVerify:
    """Tests for internal_loopback_verify()."""

    def test_verify_disabled_when_ssl_enabled(self, monkeypatch):
        monkeypatch.setenv("SSL", "true")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_verify() is False

    def test_verify_enabled_when_ssl_disabled(self, monkeypatch):
        monkeypatch.setenv("SSL", "false")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_verify() is True

    def test_verify_enabled_when_ssl_unset(self, monkeypatch):
        monkeypatch.delenv("SSL", raising=False)
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_verify() is True
