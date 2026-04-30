# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_server_classification_no_regression.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

No-regression tests for ServerClassificationService post-#4205.

With the upstream-session pool gone, ``_perform_classification`` can no
longer produce a hot/cold split from per-URL pool usage. The service now
purges Redis classification state each cycle so ``should_poll_server``
falls through to "poll now" — same behaviour as disabling the feature
flag. These tests pin that invariant and catch future edits that would
accidentally publish an "everything cold" result (which would regress
auto-refresh cadence for previously-hot gateways).
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services.server_classification_service import ServerClassificationService


@pytest.mark.asyncio
async def test_perform_classification_purges_redis_keys_and_publishes_nothing():
    """Cycle must DELETE classification keys and never set them (#4205 regression)."""
    redis = AsyncMock()
    redis.delete = AsyncMock()
    redis.sadd = AsyncMock()
    redis.set = AsyncMock()
    redis.expire = AsyncMock()
    redis.pipeline = MagicMock()  # should never be used

    svc = ServerClassificationService(redis_client=redis)
    await svc._perform_classification()  # pylint: disable=protected-access

    redis.delete.assert_awaited_once_with(
        ServerClassificationService.CLASSIFICATION_HOT_KEY,
        ServerClassificationService.CLASSIFICATION_COLD_KEY,
        ServerClassificationService.CLASSIFICATION_METADATA_KEY,
        ServerClassificationService.CLASSIFICATION_TIMESTAMP_KEY,
    )
    redis.sadd.assert_not_called()
    redis.set.assert_not_called()
    redis.expire.assert_not_called()
    redis.pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_perform_classification_tolerates_redis_errors_silently():
    """A Redis failure during the purge is logged at debug, not raised."""
    redis = AsyncMock()
    redis.delete = AsyncMock(side_effect=RuntimeError("redis unreachable"))

    svc = ServerClassificationService(redis_client=redis)
    await svc._perform_classification()  # pylint: disable=protected-access

    redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_perform_classification_is_a_noop_without_redis():
    """Without Redis the purge is skipped entirely (nothing to purge)."""
    svc = ServerClassificationService(redis_client=None)
    # Must not raise
    await svc._perform_classification()  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_should_poll_server_returns_true_when_classification_keys_absent(monkeypatch):
    """With no classification stored, should_poll_server short-circuits to True.

    This is the behaviour that makes the purged state equivalent to
    "feature flag off" — no regression in auto-refresh cadence.
    """
    redis = AsyncMock()
    redis.sismember = AsyncMock(return_value=False)  # not in hot or cold

    svc = ServerClassificationService(redis_client=redis)
    # settings.hot_cold_classification_enabled=True is the risky path.
    monkeypatch.setattr(
        "mcpgateway.services.server_classification_service.settings.hot_cold_classification_enabled",
        True,
    )

    assert await svc.should_poll_server("http://gw.test", "tool_discovery") is True
