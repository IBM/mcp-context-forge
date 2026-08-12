# -*- coding: utf-8 -*-
"""Tests for sandboxed jq filter execution."""

# First-Party
from mcpgateway.config import settings


def test_jq_filter_settings_defaults():
    """The sandbox is on by default with a short wall-clock limit."""
    assert settings.jq_filter_execution == "subprocess"
    assert settings.jq_filter_timeout_seconds == 2.0
    assert settings.jq_filter_workers == 2
