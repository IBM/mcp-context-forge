# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone

# Third-Party
import pytest

# First-Party
from mcpgateway.services import metrics_query_service as mqs


def test_get_retention_cutoff_uses_hours(monkeypatch):
    monkeypatch.setattr(mqs.settings, "metrics_retention_days", 7)
    monkeypatch.setattr(mqs.settings, "metrics_delete_raw_after_rollup", True)
    monkeypatch.setattr(mqs.settings, "metrics_delete_raw_after_rollup_hours", 1)

    now = datetime.now(timezone.utc)
    cutoff = mqs.get_retention_cutoff()

    assert cutoff.minute == 0
    assert cutoff.second == 0
    assert cutoff.microsecond == 0

    delta = now - cutoff
    assert timedelta(hours=1) <= delta < timedelta(hours=2)
