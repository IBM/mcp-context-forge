# -*- coding: utf-8 -*-
"""Tests for sandboxed jq filter execution."""

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.jq_runner import JqFilterError, run_jq_filter


def test_jq_filter_settings_defaults():
    """The sandbox is on by default with a short wall-clock limit."""
    assert settings.jq_filter_execution == "subprocess"
    assert settings.jq_filter_timeout_seconds == 2.0
    assert settings.jq_filter_workers == 2


def test_inprocess_mode_applies_filter(monkeypatch):
    """In-process mode still evaluates ordinary filters correctly."""
    monkeypatch.setattr(settings, "jq_filter_execution", "inprocess")
    assert run_jq_filter(".a", {"a": 42}) == [42]


def test_inprocess_mode_reports_compile_errors(monkeypatch):
    """A malformed filter surfaces as JqFilterError, not a raw jq exception."""
    monkeypatch.setattr(settings, "jq_filter_execution", "inprocess")
    with pytest.raises(JqFilterError):
        run_jq_filter("this is not jq |||", {"a": 1})


def test_compiled_programs_are_cached():
    """Compilation is cached so repeated invocations stay cheap."""
    # First-Party
    from mcpgateway.utils.jq_runner import _compile_jq_filter

    _compile_jq_filter.cache_clear()
    _compile_jq_filter(".a")
    _compile_jq_filter(".a")
    assert _compile_jq_filter.cache_info().hits == 1
