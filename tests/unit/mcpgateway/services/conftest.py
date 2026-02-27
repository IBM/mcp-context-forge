# -*- coding: utf-8 -*-
"""Conftest for services unit tests.

Ensures settings are in a known state for tests regardless of local .env overrides.
"""
# Third-Party
import pytest


@pytest.fixture(autouse=True)
def reset_metrics_settings():
    """Ensure metrics settings are True for tests that expect default behaviour."""
    from mcpgateway.config import settings
    original_recording = settings.db_metrics_recording_enabled
    original_rollup = settings.metrics_rollup_enabled
    settings.db_metrics_recording_enabled = True
    settings.metrics_rollup_enabled = True
    yield
    settings.db_metrics_recording_enabled = original_recording
    settings.metrics_rollup_enabled = original_rollup
