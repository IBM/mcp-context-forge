# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_sunset_scheduler_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for SunsetSchedulerService.

This test suite covers the automated tool lifecycle management service,
including scheduler lifecycle, error handling, concurrent execution protection,
and integration with observability/audit systems.
"""

# Standard
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.sunset_scheduler_service import (
    SunsetSchedulerService,
    get_sunset_scheduler_service,
)


class TestSunsetSchedulerServiceLifecycle:
    """Test scheduler service lifecycle management."""

    @pytest.mark.asyncio
    async def test_start_already_running(self):
        """Test that starting an already running scheduler logs warning."""
        scheduler = SunsetSchedulerService()

        # Start scheduler
        await scheduler.start()
        assert scheduler._running is True

        # Try to start again - should log warning
        with patch("mcpgateway.services.sunset_scheduler_service.logger") as mock_logger:
            await scheduler.start()
            mock_logger.warning.assert_called_once_with("SunsetSchedulerService already running")

        # Cleanup
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        """Test that stopping a non-running scheduler returns early."""
        scheduler = SunsetSchedulerService()

        # Stop without starting - should return early
        assert scheduler._running is False
        await scheduler.stop()  # Should not raise
        assert scheduler._running is False

    @pytest.mark.asyncio
    async def test_concurrent_execution_protection(self):
        """Test that scheduler skips run if already processing (lines 86-88)."""
        scheduler = SunsetSchedulerService()

        # Set very short interval to make test fast
        scheduler._interval_minutes = 0.001  # 0.06 seconds

        # Directly call _run_scheduler while _processing is True to trigger lines 86-88
        scheduler._running = True
        scheduler._processing = True  # Simulate ongoing processing

        with patch("mcpgateway.services.sunset_scheduler_service.logger") as mock_logger:
            with patch.object(scheduler, '_process_sunset_tools', new=AsyncMock()) as mock_process:
                # Create a task that will run one iteration of the scheduler loop
                task = asyncio.create_task(scheduler._run_scheduler())

                # Give the task time to:
                # 1. Check the _processing flag (line 85)
                # 2. Log warning (line 86)
                # 3. Sleep (line 87)
                # 4. Continue (line 88)
                await asyncio.sleep(0.15)

                # Stop the scheduler to exit the loop
                scheduler._running = False

                # Wait for task to complete
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except asyncio.TimeoutError:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                # Verify warning was logged about skipping run (line 86)
                warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
                assert any("already processing" in call.lower() for call in warning_calls), \
                    f"Expected concurrent execution warning, got: {warning_calls}"

                # Verify _process_sunset_tools was NOT called because _processing was True
                # This confirms the continue statement (line 88) worked
                mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """Test that stop() properly cancels the background task."""
        scheduler = SunsetSchedulerService()
        scheduler._interval_minutes = 0.01  # Very short interval for testing

        # Start scheduler
        await scheduler.start()
        assert scheduler._running is True
        assert scheduler._task is not None

        # Give task a moment to start
        await asyncio.sleep(0.01)

        # Stop scheduler
        with patch("mcpgateway.services.sunset_scheduler_service.logger") as mock_logger:
            await scheduler.stop()
            mock_logger.info.assert_called_with("SunsetSchedulerService stopped")

        assert scheduler._running is False
        assert scheduler._task.cancelled() or scheduler._task.done()

    @pytest.mark.asyncio
    async def test_scheduler_exception_handling(self):
        """Test that scheduler handles exceptions in _process_sunset_tools."""
        scheduler = SunsetSchedulerService()
        scheduler._interval_minutes = 0.01

        # Mock _process_sunset_tools to raise exception
        test_error = RuntimeError("Test error in processing")

        # Mock fresh_db_session to avoid database access
        with patch("mcpgateway.services.sunset_scheduler_service.fresh_db_session") as mock_db_ctx:
            mock_db = MagicMock()
            mock_db.execute.side_effect = test_error
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db_ctx.return_value = mock_db

            with patch("mcpgateway.services.sunset_scheduler_service.logger") as mock_logger:
                with patch("mcpgateway.services.sunset_scheduler_service.structured_logger") as mock_struct_logger:
                    # Start scheduler
                    await scheduler.start()

                    # Wait for exception to be caught
                    await asyncio.sleep(0.05)

                    # Verify exception was logged
                    mock_logger.exception.assert_called()
                    assert "Error in sunset scheduler" in str(mock_logger.exception.call_args)

                    # Verify structured logging
                    mock_struct_logger.log.assert_called_once()
                    call_kwargs = mock_struct_logger.log.call_args[1]
                    assert call_kwargs["level"] == "ERROR"
                    assert call_kwargs["custom_fields"]["error"] == "Test error in processing"
                    assert call_kwargs["custom_fields"]["error_type"] == "RuntimeError"

                    # Verify _processing flag was reset
                    assert scheduler._processing is False

                    await scheduler.stop()


class TestSunsetSchedulerProcessing:
    """Test sunset tool processing logic."""

    @pytest.mark.asyncio
    async def test_no_tools_to_sunset(self):
        """Test processing when no tools need to be sunset."""
        scheduler = SunsetSchedulerService()

        # Mock fresh_db_session to return empty result
        with patch("mcpgateway.services.sunset_scheduler_service.fresh_db_session") as mock_db_ctx:
            mock_db = MagicMock()
            mock_result = MagicMock()
            mock_result.scalars().all.return_value = []
            mock_db.execute.return_value = mock_result
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db_ctx.return_value = mock_db

            with patch("mcpgateway.services.sunset_scheduler_service.logger") as mock_logger:
                await scheduler._process_sunset_tools()

                # Verify debug log for no tools
                mock_logger.debug.assert_called_with("No tools to sunset at this time")

    @pytest.mark.asyncio
    async def test_partial_update_concurrent_execution(self, test_db):
        """Test handling when some tools are already sunset by another instance (lines 172, 174-175)."""
        # Create two tools with past sunset dates
        past_date = datetime.now(timezone.utc) - timedelta(hours=1)

        tool1 = DbTool(
            original_name="tool1",
            custom_name="tool1",
            custom_name_slug="tool-1",
            display_name="Tool 1",
            url="http://example.com/tool1",
            description="Tool 1",
            input_schema={"type": "object"},
            deprecated=True,
            sunset_date=past_date,
            enabled=True,
        )
        tool2 = DbTool(
            original_name="tool2",
            custom_name="tool2",
            custom_name_slug="tool-2",
            display_name="Tool 2",
            url="http://example.com/tool2",
            description="Tool 2",
            input_schema={"type": "object"},
            deprecated=True,
            sunset_date=past_date,
            enabled=True,
        )

        test_db.add_all([tool1, tool2])
        test_db.commit()
        test_db.refresh(tool1)
        test_db.refresh(tool2)

        scheduler = SunsetSchedulerService()

        # Mock fresh_db_session to use test_db
        with patch("mcpgateway.services.sunset_scheduler_service.fresh_db_session") as mock_db_ctx:
            # Create a custom mock that returns fewer rows updated than expected
            def mock_db_context():
                class MockDB:
                    def __enter__(self):
                        return test_db
                    def __exit__(self, *args):
                        return False
                return MockDB()

            mock_db_ctx.side_effect = mock_db_context

            # Mock the execute method to return a result with rowcount=1 instead of 2
            original_execute = test_db.execute

            def mock_execute(stmt, *args, **kwargs):
                result = original_execute(stmt, *args, **kwargs)
                # Check if this is the UPDATE statement
                stmt_str = str(stmt.compile(compile_kwargs={"literal_binds": True}))
                if "UPDATE" in stmt_str and "enabled" in stmt_str:
                    # Create a mock result with rowcount=1 to simulate partial update
                    mock_result = MagicMock()
                    mock_result.rowcount = 1  # Only 1 updated instead of 2
                    return mock_result
                return result

            with patch.object(test_db, 'execute', side_effect=mock_execute):
                with patch("mcpgateway.services.sunset_scheduler_service.logger") as mock_logger:
                    # Mock other services to avoid side effects
                    with patch("mcpgateway.services.sunset_scheduler_service.get_registry_cache"):
                        with patch("mcpgateway.services.sunset_scheduler_service.get_audit_trail_service"):
                            with patch("mcpgateway.services.sunset_scheduler_service.ObservabilityService"):
                                await scheduler._process_sunset_tools()

                    # Verify warning about partial update (line 172)
                    warning_calls = [call[0][0] for call in mock_logger.warning.call_args_list]
                    assert any("Only 1 of 2 tools were sunset" in str(call) for call in warning_calls), \
                        f"Expected partial update warning, got: {warning_calls}"

    @pytest.mark.asyncio
    async def test_cache_invalidation_error_handling(self, test_db):
        """Test that cache invalidation errors are handled gracefully."""
        past_date = datetime.now(timezone.utc) - timedelta(hours=1)

        tool = DbTool(
            original_name="cache_test",
            custom_name="cache_test",
            custom_name_slug="cache-test",
            display_name="Cache Test",
            url="http://example.com/tool",
            description="Tool for cache error test",
            input_schema={"type": "object"},
            deprecated=True,
            sunset_date=past_date,
            enabled=True,
        )

        test_db.add(tool)
        test_db.commit()

        scheduler = SunsetSchedulerService()

        # Mock fresh_db_session to use test_db
        with patch("mcpgateway.services.sunset_scheduler_service.fresh_db_session") as mock_db_ctx:
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=test_db)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            # Mock cache to raise exception
            with patch("mcpgateway.services.sunset_scheduler_service.get_registry_cache") as mock_cache:
                mock_registry = AsyncMock()
                mock_registry.invalidate_tools.side_effect = RuntimeError("Cache error")
                mock_cache.return_value = mock_registry

                with patch("mcpgateway.services.sunset_scheduler_service.logger") as mock_logger:
                    await scheduler._process_sunset_tools()

                    # Verify error was logged but processing continued
                    error_calls = [str(call) for call in mock_logger.error.call_args_list]
                    assert any("Failed to invalidate tools cache" in call for call in error_calls)

    @pytest.mark.asyncio
    async def test_audit_trail_error_handling(self, test_db):
        """Test that audit trail errors are handled gracefully."""
        past_date = datetime.now(timezone.utc) - timedelta(hours=1)

        tool = DbTool(
            original_name="audit_test",
            custom_name="audit_test",
            custom_name_slug="audit-test",
            display_name="Audit Test",
            url="http://example.com/tool",
            description="Tool for audit error test",
            input_schema={"type": "object"},
            deprecated=True,
            sunset_date=past_date,
            enabled=True,
            team_id="test-team",
        )

        test_db.add(tool)
        test_db.commit()

        scheduler = SunsetSchedulerService()

        # Mock fresh_db_session to use test_db
        with patch("mcpgateway.services.sunset_scheduler_service.fresh_db_session") as mock_db_ctx:
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=test_db)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            # Mock audit service to raise exception
            with patch("mcpgateway.services.sunset_scheduler_service.get_audit_trail_service") as mock_audit:
                mock_service = MagicMock()
                mock_service.log_action.side_effect = RuntimeError("Audit error")
                mock_audit.return_value = mock_service

                with patch("mcpgateway.services.sunset_scheduler_service.logger") as mock_logger:
                    await scheduler._process_sunset_tools()

                    # Verify error was logged but processing continued
                    error_calls = [str(call) for call in mock_logger.error.call_args_list]
                    assert any("Failed to log audit trail" in call for call in error_calls)

    @pytest.mark.asyncio
    async def test_audit_trail_logging_details(self, test_db):
        """Test that audit trail is logged with correct details."""
        past_date = datetime.now(timezone.utc) - timedelta(hours=1)

        tool = DbTool(
            original_name="audit_detail_test",
            custom_name="audit_detail_test",
            custom_name_slug="audit-detail-test",
            display_name="Audit Detail Test",
            url="http://example.com/tool",
            description="Tool for audit detail test",
            input_schema={"type": "object"},
            deprecated=True,
            sunset_date=past_date,
            enabled=True,
            team_id="test-team-123",
        )

        test_db.add(tool)
        test_db.commit()
        test_db.refresh(tool)

        scheduler = SunsetSchedulerService()

        # Mock fresh_db_session to use test_db
        with patch("mcpgateway.services.sunset_scheduler_service.fresh_db_session") as mock_db_ctx:
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=test_db)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            # Mock audit service to capture calls
            with patch("mcpgateway.services.sunset_scheduler_service.get_audit_trail_service") as mock_audit:
                mock_service = MagicMock()
                mock_audit.return_value = mock_service

                await scheduler._process_sunset_tools()

                # Verify audit trail was logged with correct details
                mock_service.log_action.assert_called_once()
                call_kwargs = mock_service.log_action.call_args[1]

                assert call_kwargs["user_id"] == "sunset_scheduler"
                assert call_kwargs["action"] == "tool_sunset"
                assert call_kwargs["resource_type"] == "tool"
                assert call_kwargs["resource_id"] == str(tool.id)
                assert call_kwargs["resource_name"] == "audit-detail-test"  # Uses slug
                assert call_kwargs["user_email"] is None
                assert call_kwargs["team_id"] == "test-team-123"
                assert call_kwargs["details"]["automated"] is True
                assert "sunset_date" in call_kwargs["details"]
                assert "timestamp" in call_kwargs["details"]

    @pytest.mark.asyncio
    async def test_metrics_recording_error_handling(self, test_db):
        """Test that metrics recording errors are handled gracefully."""
        past_date = datetime.now(timezone.utc) - timedelta(hours=1)

        tool = DbTool(
            original_name="metrics_test",
            custom_name="metrics_test",
            custom_name_slug="metrics-test",
            display_name="Metrics Test",
            url="http://example.com/tool",
            description="Tool for metrics error test",
            input_schema={"type": "object"},
            deprecated=True,
            sunset_date=past_date,
            enabled=True,
        )

        test_db.add(tool)
        test_db.commit()

        scheduler = SunsetSchedulerService()

        # Mock fresh_db_session to use test_db
        with patch("mcpgateway.services.sunset_scheduler_service.fresh_db_session") as mock_db_ctx:
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=test_db)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            # Mock ObservabilityService to raise exception
            with patch("mcpgateway.services.sunset_scheduler_service.ObservabilityService") as mock_obs:
                mock_service = MagicMock()
                mock_service.record_metric.side_effect = RuntimeError("Metrics error")
                mock_obs.return_value = mock_service

                with patch("mcpgateway.services.sunset_scheduler_service.logger") as mock_logger:
                    await scheduler._process_sunset_tools()

                    # Verify error was logged but processing continued
                    error_calls = [str(call) for call in mock_logger.error.call_args_list]
                    assert any("Failed to record sunset metrics" in call for call in error_calls)

    @pytest.mark.asyncio
    async def test_metrics_recording_details(self, test_db):
        """Test that metrics are recorded with correct details."""
        past_date = datetime.now(timezone.utc) - timedelta(hours=1)

        tool1 = DbTool(
            original_name="metrics_tool1",
            custom_name="metrics_tool1",
            custom_name_slug="metrics-tool1",
            display_name="Metrics Tool 1",
            url="http://example.com/tool1",
            description="Tool 1",
            input_schema={"type": "object"},
            deprecated=True,
            sunset_date=past_date,
            enabled=True,
        )
        tool2 = DbTool(
            original_name="metrics_tool2",
            custom_name="metrics_tool2",
            custom_name_slug="metrics-tool2",
            display_name="Metrics Tool 2",
            url="http://example.com/tool2",
            description="Tool 2",
            input_schema={"type": "object"},
            deprecated=True,
            sunset_date=past_date,
            enabled=True,
        )

        test_db.add_all([tool1, tool2])
        test_db.commit()
        test_db.refresh(tool1)
        test_db.refresh(tool2)

        scheduler = SunsetSchedulerService()

        # Mock fresh_db_session to use test_db
        with patch("mcpgateway.services.sunset_scheduler_service.fresh_db_session") as mock_db_ctx:
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=test_db)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            # Mock ObservabilityService to capture calls
            with patch("mcpgateway.services.sunset_scheduler_service.ObservabilityService") as mock_obs:
                mock_service = MagicMock()
                mock_obs.return_value = mock_service

                await scheduler._process_sunset_tools()

                # Verify batch count metric
                calls = mock_service.record_metric.call_args_list
                assert len(calls) == 3  # 1 batch + 2 individual events

                # First call should be batch count
                batch_call = calls[0]
                assert batch_call[1]["name"] == "tool.lifecycle.sunset.count"
                assert batch_call[1]["value"] == 2
                assert batch_call[1]["unit"] == "count"
                assert "batch_timestamp" in batch_call[1]["attributes"]

                # Next calls should be individual events
                event_call1 = calls[1]
                assert event_call1[1]["name"] == "tool.lifecycle.sunset.event"
                assert event_call1[1]["value"] == 1
                assert "tool_id" in event_call1[1]["attributes"]
                assert "tool_name" in event_call1[1]["attributes"]
                assert "sunset_date" in event_call1[1]["attributes"]

    @pytest.mark.asyncio
    async def test_structured_logging(self, test_db):
        """Test that structured logging is performed correctly."""
        past_date = datetime.now(timezone.utc) - timedelta(hours=1)

        tool = DbTool(
            original_name="logging_test",
            custom_name="logging_test",
            custom_name_slug="logging-test",
            display_name="Logging Test",
            url="http://example.com/tool",
            description="Tool for logging test",
            input_schema={"type": "object"},
            deprecated=True,
            sunset_date=past_date,
            enabled=True,
        )

        test_db.add(tool)
        test_db.commit()

        scheduler = SunsetSchedulerService()

        # Mock fresh_db_session to use test_db
        with patch("mcpgateway.services.sunset_scheduler_service.fresh_db_session") as mock_db_ctx:
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=test_db)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            # Mock structured logger to capture calls
            with patch("mcpgateway.services.sunset_scheduler_service.structured_logger") as mock_logger:
                await scheduler._process_sunset_tools()

                # Verify structured log was called
                mock_logger.log.assert_called_once()
                call_kwargs = mock_logger.log.call_args[1]

                assert call_kwargs["level"] == "INFO"
                assert call_kwargs["message"] == "Tools sunset batch completed"
                assert call_kwargs["event_type"] == "tools_sunset_batch"
                assert call_kwargs["component"] == "sunset_scheduler"
                assert call_kwargs["custom_fields"]["tool_count"] == 1
                assert "logging-test" in call_kwargs["custom_fields"]["tool_names"]  # Uses slug
                assert "timestamp" in call_kwargs["custom_fields"]

    @pytest.mark.asyncio
    async def test_success_logging(self, test_db):
        """Test that success is logged with correct count."""
        past_date = datetime.now(timezone.utc) - timedelta(hours=1)

        tools = [
            DbTool(
                original_name=f"success_tool{i}",
                custom_name=f"success_tool{i}",
                custom_name_slug=f"success-tool{i}",
                display_name=f"Success Tool {i}",
                url=f"http://example.com/tool{i}",
                description=f"Tool {i}",
                input_schema={"type": "object"},
                deprecated=True,
                sunset_date=past_date,
                enabled=True,
            )
            for i in range(3)
        ]

        test_db.add_all(tools)
        test_db.commit()

        scheduler = SunsetSchedulerService()

        # Mock fresh_db_session to use test_db
        with patch("mcpgateway.services.sunset_scheduler_service.fresh_db_session") as mock_db_ctx:
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=test_db)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("mcpgateway.services.sunset_scheduler_service.logger") as mock_logger:
                await scheduler._process_sunset_tools()

                # Verify success log
                info_calls = [str(call) for call in mock_logger.info.call_args_list]
                assert any("Successfully sunset 3 tools" in call for call in info_calls)


class TestSunsetSchedulerSingleton:
    """Test singleton pattern for scheduler service."""

    def test_get_sunset_scheduler_service_singleton(self):
        """Test that get_sunset_scheduler_service returns singleton."""
        service1 = get_sunset_scheduler_service()
        service2 = get_sunset_scheduler_service()

        assert service1 is service2
        assert isinstance(service1, SunsetSchedulerService)

    def test_scheduler_initialization_with_custom_interval(self):
        """Test scheduler initialization with custom interval from settings."""
        with patch("mcpgateway.services.sunset_scheduler_service.settings") as mock_settings:
            mock_settings.sunset_scheduler_interval_minutes = 120

            scheduler = SunsetSchedulerService()

            assert scheduler._interval_minutes == 120

    def test_scheduler_initialization_default_interval(self):
        """Test scheduler initialization with default interval."""
        with patch("mcpgateway.services.sunset_scheduler_service.settings") as mock_settings:
            mock_settings.sunset_scheduler_interval_minutes = 60

            scheduler = SunsetSchedulerService()

            assert scheduler._interval_minutes == 60  # Default value
