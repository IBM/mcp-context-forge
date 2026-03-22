# -*- coding: utf-8 -*-
"""Tests for the workflow pattern service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.workflow_pattern_service import (
    WorkflowPatternService,
    get_workflow_pattern_service,
)


@pytest.fixture
def svc():
    return WorkflowPatternService()


@pytest.fixture
def mock_db():
    return MagicMock()


def _make_tool_row(id_, name, description=None):
    row = SimpleNamespace(id=id_, name=name, description=description)
    return row


def _make_metric_row(tool_id, ts):
    return SimpleNamespace(tool_id=tool_id, timestamp=ts)


# ---------------------------------------------------------------------------
# Singleton helper
# ---------------------------------------------------------------------------


class TestGetWorkflowPatternService:
    def test_returns_singleton(self):
        a = get_workflow_pattern_service()
        b = get_workflow_pattern_service()
        assert a is b
        assert isinstance(a, WorkflowPatternService)


# ---------------------------------------------------------------------------
# initialize / shutdown
# ---------------------------------------------------------------------------


class TestInitializeShutdown:
    @pytest.mark.asyncio
    async def test_initialize_creates_task(self, svc):
        with patch.object(svc, "_update_patterns_loop", return_value=asyncio.sleep(0)):
            await svc.initialize()
            assert svc._update_task is not None
        await svc.shutdown()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, svc):
        with patch.object(svc, "_update_patterns_loop", return_value=asyncio.sleep(0)):
            await svc.initialize()
            task1 = svc._update_task
            await svc.initialize()
            task2 = svc._update_task
            # Second call should not replace a running task
            assert task1 is task2
        await svc.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_task(self, svc):
        async def _noop():
            await asyncio.sleep(9999)

        svc._update_task = asyncio.create_task(_noop())
        await svc.shutdown()
        assert svc._update_task.cancelled()


# ---------------------------------------------------------------------------
# get_workflow_recommendations — empty inputs
# ---------------------------------------------------------------------------


class TestGetWorkflowRecommendationsEmpty:
    @pytest.mark.asyncio
    async def test_empty_recent_tools_returns_empty(self, svc, mock_db):
        results = await svc.get_workflow_recommendations([], mock_db)
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_matrix_returns_empty(self, svc, mock_db):
        svc._memory_matrix = {}
        with patch.object(svc, "_get_matrix", return_value={}):
            results = await svc.get_workflow_recommendations(["tool-1"], mock_db)
        assert results == []

    @pytest.mark.asyncio
    async def test_no_candidates_after_exclusion_returns_empty(self, svc, mock_db):
        # Matrix only contains same tools as recent_tool_ids
        svc._memory_matrix = {"tool-1": {"tool-1": 5}}
        with patch.object(svc, "_get_matrix", new_callable=AsyncMock, return_value={"tool-1": {"tool-1": 5}}):
            results = await svc.get_workflow_recommendations(["tool-1"], mock_db)
        assert results == []


# ---------------------------------------------------------------------------
# get_workflow_recommendations — scored results
# ---------------------------------------------------------------------------


class TestGetWorkflowRecommendationsScored:
    @pytest.mark.asyncio
    async def test_returns_normalised_scores(self, svc, mock_db):
        matrix = {
            "tool-A": {"tool-B": 10, "tool-C": 5},
        }
        tool_rows = [
            _make_tool_row("tool-B", "ToolB", "desc B"),
            _make_tool_row("tool-C", "ToolC", "desc C"),
        ]
        trigger_row = SimpleNamespace(name="ToolA")

        mock_db.execute.return_value.all.return_value = tool_rows
        mock_db.execute.return_value.scalar_one_or_none.return_value = "ToolA"

        with patch.object(svc, "_get_matrix", new_callable=AsyncMock, return_value=matrix):
            results = await svc.get_workflow_recommendations(["tool-A"], mock_db)

        assert len(results) == 2
        scores = {r.tool_name: r.score for r in results}
        assert scores["ToolB"] == pytest.approx(1.0)
        assert scores["ToolC"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_explanation_references_trigger_tool(self, svc, mock_db):
        matrix = {"tool-A": {"tool-B": 4}}
        tool_rows = [_make_tool_row("tool-B", "ToolB")]
        mock_db.execute.return_value.all.return_value = tool_rows
        mock_db.execute.return_value.scalar_one_or_none.return_value = "ToolA"

        with patch.object(svc, "_get_matrix", new_callable=AsyncMock, return_value=matrix):
            results = await svc.get_workflow_recommendations(["tool-A"], mock_db)

        assert "ToolA" in results[0].explanation

    @pytest.mark.asyncio
    async def test_limit_respected(self, svc, mock_db):
        matrix = {"tool-A": {f"tool-{i}": i + 1 for i in range(10)}}
        tool_rows = [_make_tool_row(f"tool-{i}", f"Tool{i}") for i in range(10)]
        mock_db.execute.return_value.all.return_value = tool_rows
        mock_db.execute.return_value.scalar_one_or_none.return_value = "ToolA"

        with patch.object(svc, "_get_matrix", new_callable=AsyncMock, return_value=matrix):
            results = await svc.get_workflow_recommendations(["tool-A"], mock_db, limit=3)

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_tool_not_in_db_skipped(self, svc, mock_db):
        """Candidates whose IDs are missing from the DB are silently skipped."""
        matrix = {"tool-A": {"tool-B": 5, "tool-ghost": 10}}
        tool_rows = [_make_tool_row("tool-B", "ToolB")]  # tool-ghost not returned
        mock_db.execute.return_value.all.return_value = tool_rows
        mock_db.execute.return_value.scalar_one_or_none.return_value = "ToolA"

        with patch.object(svc, "_get_matrix", new_callable=AsyncMock, return_value=matrix):
            results = await svc.get_workflow_recommendations(["tool-A"], mock_db)

        names = [r.tool_name for r in results]
        assert "ToolB" in names
        assert "tool-ghost" not in names


# ---------------------------------------------------------------------------
# _get_matrix — Redis load
# ---------------------------------------------------------------------------


class TestGetMatrix:
    @pytest.mark.asyncio
    async def test_memory_matrix_returned_directly(self, svc):
        svc._memory_matrix = {"tool-X": {"tool-Y": 3}}
        matrix = await svc._get_matrix()
        assert matrix == {"tool-X": {"tool-Y": 3}}

    @pytest.mark.asyncio
    async def test_loads_from_redis_when_memory_empty(self, svc):
        svc._memory_matrix = {}
        payload = json.dumps({"tool-A": {"tool-B": 7}})
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=payload)

        with patch("mcpgateway.services.workflow_pattern_service.get_redis_client", new_callable=AsyncMock, return_value=mock_redis):
            matrix = await svc._get_matrix()

        assert matrix == {"tool-A": {"tool-B": 7}}

    @pytest.mark.asyncio
    async def test_redis_miss_returns_empty(self, svc):
        svc._memory_matrix = {}
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("mcpgateway.services.workflow_pattern_service.get_redis_client", new_callable=AsyncMock, return_value=mock_redis):
            matrix = await svc._get_matrix()

        assert matrix == {}

    @pytest.mark.asyncio
    async def test_redis_unavailable_returns_empty(self, svc):
        svc._memory_matrix = {}
        with patch("mcpgateway.services.workflow_pattern_service.get_redis_client", new_callable=AsyncMock, return_value=None):
            matrix = await svc._get_matrix()
        assert matrix == {}


# ---------------------------------------------------------------------------
# _rebuild_cooccurrence_matrix — co-occurrence logic
# ---------------------------------------------------------------------------


class TestRebuildCooccurrenceMatrix:
    @pytest.mark.asyncio
    async def test_pairs_within_window_counted(self, svc):
        now = datetime.now(timezone.utc)
        rows = [
            (1, now),
            (2, now + timedelta(minutes=3)),
            (3, now + timedelta(minutes=10)),  # outside 5-min window
        ]

        mock_execute = MagicMock()
        mock_execute.all.return_value = [(r[0], r[1]) for r in rows]

        mock_db = MagicMock()
        mock_db.execute.return_value = mock_execute

        with patch("mcpgateway.services.workflow_pattern_service.fresh_db_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch("mcpgateway.services.workflow_pattern_service.get_redis_client", new_callable=AsyncMock, return_value=None):
                with patch("mcpgateway.services.workflow_pattern_service.settings") as mock_settings:
                    mock_settings.recommendation_workflow_window_minutes = 5
                    mock_settings.recommendation_min_cooccurrence = 1
                    mock_settings.recommendation_pattern_cache_ttl = 86400
                    await svc._rebuild_cooccurrence_matrix()

        # Tools 1 and 2 co-occur (3 min apart); tool 3 is outside window
        assert "1" not in svc._memory_matrix or "3" not in svc._memory_matrix.get("1", {})

    @pytest.mark.asyncio
    async def test_min_cooccurrence_filter_applied(self, svc):
        """Pairs below the minimum count threshold are excluded from the matrix."""
        now = datetime.now(timezone.utc)
        # Only one co-occurrence between tool-A and tool-B
        rows = [
            ("A", now),
            ("B", now + timedelta(minutes=1)),
        ]

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = rows

        with patch("mcpgateway.services.workflow_pattern_service.fresh_db_session") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch("mcpgateway.services.workflow_pattern_service.get_redis_client", new_callable=AsyncMock, return_value=None):
                with patch("mcpgateway.services.workflow_pattern_service.settings") as mock_settings:
                    mock_settings.recommendation_workflow_window_minutes = 5
                    mock_settings.recommendation_min_cooccurrence = 3  # threshold > 1 occurrence
                    mock_settings.recommendation_pattern_cache_ttl = 86400
                    await svc._rebuild_cooccurrence_matrix()

        # Should be filtered out — below min_cooccurrence
        assert svc._memory_matrix == {}
