# -*- coding: utf-8 -*-
"""Tests for mcpgateway.cache.metrics_cache."""

# Standard
import builtins

# Third-Party
import pytest

# First-Party
from mcpgateway.cache import metrics_cache as metrics_cache_module


def test_create_metrics_cache_import_error_falls_back_to_default_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002 - match __import__ signature
        if name == "mcpgateway.config":
            raise ImportError("boom")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    cache = metrics_cache_module._create_metrics_cache()
    assert cache._ttl_seconds == 10


def test_is_cache_enabled_import_error_defaults_to_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002 - match __import__ signature
        if name == "mcpgateway.config":
            raise ImportError("boom")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    assert metrics_cache_module.is_cache_enabled() is True
