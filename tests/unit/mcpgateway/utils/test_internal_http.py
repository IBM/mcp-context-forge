"""Unit tests for internal loopback HTTP helpers."""

import pytest
from mcpgateway.utils.internal_http import internal_loopback_base_url, internal_loopback_verify


@pytest.mark.parametrize("ssl_value", ["true"])
def test_internal_loopback_helpers_ssl_enabled(monkeypatch, ssl_value):
    """SSL truthy values should produce HTTPS base URL and disabled verification."""
    monkeypatch.setenv("SSL", ssl_value)
    monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)

    assert internal_loopback_base_url() == "https://127.0.0.1:4444"
    assert internal_loopback_verify() is False


@pytest.mark.parametrize("ssl_value", ["false"])
def test_internal_loopback_helpers_ssl_disabled(monkeypatch, ssl_value):
    """Non-truthy SSL values should produce HTTP base URL and enabled verification."""
    monkeypatch.setenv("SSL", ssl_value)
    monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 8000)

    assert internal_loopback_base_url() == "http://127.0.0.1:8000"
    assert internal_loopback_verify() is True
