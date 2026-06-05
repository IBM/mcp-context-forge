
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_observability_session_reuse.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for observability session reuse optimization (Issue #5072).

Tests verify that ObservabilityService methods accept and reuse database sessions
to reduce connection pool pressure from 4-6 sessions per traced request to 1 session.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.observability_service import ObservabilityService


class TestObservabilitySessionReuse:
    """Test session reuse optimization for observability operations."""

    @pytest.fixture
    def service(self):
        """Create ObservabilityService instance."""
        return ObservabilityService()

    @pytest.fixture
    def mock_session(self):
        """Create mock database session."""
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None
        return session

    def test_start_trace_with_session_reuse(self, service, mock_session):
        """Test start_trace accepts obs_db parameter for session reuse."""
        # When obs_db is provided, should not create new session
        with patch("mcpgateway.services.observability_service._get_or_create_observability_session") as mock_get:
            trace_id = service.start_trace(
                name="test_trace",
                commit=False,
                obs_db=mock_session,
            )

            # Should not create new session when obs_db provided
            mock_get.assert_not_called()
            # Should use provided session
            mock_session.add.assert_called_once()
            # Should not commit when commit=False
            mock_session.commit.assert_not_called()
            # Should not close session (caller owns it)
            mock_session.close.assert_not_called()
            assert trace_id is not None

    def test_start_trace_without_session_creates_own(self, service):
        """Test start_trace creates own session when obs_db not provided."""
        with patch("mcpgateway.services.observability_service._get_or_create_observability_session") as mock_get:
            mock_session = MagicMock()
            mock_get.return_value = (mock_session, True)

            trace_id = service.start_trace(name="test_trace")

            # Should create new session when obs_db not provided
            mock_get.assert_called_once()
            # Should commit by default
            mock_session.commit.assert_called_once()
            # Should close session (owns it)
            mock_session.close.assert_called_once()
            assert trace_id is not None

    def test_end_trace_with_session_reuse(self, service, mock_session):
        """Test end_trace accepts obs_db parameter for session reuse."""
        # Setup mock trace with proper datetime
        from datetime import datetime, timezone
        mock_trace = MagicMock()
        mock_trace.start_time = datetime.now(timezone.utc)
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_trace

        with patch("mcpgateway.services.observability_service._get_or_create_observability_session") as mock_get:
            service.end_trace(
                trace_id="test-trace-id",
                status="ok",
                commit=False,
                obs_db=mock_session,
            )

            # Should not create new session when obs_db provided
            mock_get.assert_not_called()
            # Should not commit when commit=False
            mock_session.commit.assert_not_called()
            # Should not close session (caller owns it)
            mock_session.close.assert_not_called()

    def test_end_trace_without_session_creates_own(self, service):
        """Test end_trace creates own session when obs_db not provided."""
        from datetime import datetime, timezone
        with patch("mcpgateway.services.observability_service._get_or_create_observability_session") as mock_get:
            mock_session = MagicMock()
            mock_trace = MagicMock()
            mock_trace.start_time = datetime.now(timezone.utc)
            mock_session.query.return_value.filter_by.return_value.first.return_value = mock_trace
            mock_get.return_value = (mock_session, True)

            service.end_trace(trace_id="test-trace-id", status="ok")

            # Should create new session when obs_db not provided
            mock_get.assert_called_once()
            # Should commit by default
            mock_session.commit.assert_called_once()
            # Should close session (owns it)
            mock_session.close.assert_called_once()

    def test_start_span_with_session_reuse(self, service, mock_session):
        """Test start_span accepts obs_db parameter for session reuse."""
        with patch("mcpgateway.services.observability_service._get_or_create_observability_session") as mock_get:
            span_id = service.start_span(
                trace_id="test-trace-id",
                name="test_span",
                commit=False,
                obs_db=mock_session,
            )

            # Should not create new session when obs_db provided
            mock_get.assert_not_called()
            # Should use provided session
            mock_session.add.assert_called_once()
            # Should not commit when commit=False
            mock_session.commit.assert_not_called()
            # Should not close session (caller owns it)
            mock_session.close.assert_not_called()
            assert span_id is not None

    def test_end_span_with_session_reuse(self, service, mock_session):
        """Test end_span accepts obs_db parameter for session reuse."""
        # Setup mock span with proper datetime
        from datetime import datetime, timezone
        mock_span = MagicMock()
        mock_span.start_time = datetime.now(timezone.utc)
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_span

        with patch("mcpgateway.services.observability_service._get_or_create_observability_session") as mock_get:
            service.end_span(
                span_id="test-span-id",
                status="ok",
                commit=False,
                obs_db=mock_session,
            )

            # Should not create new session when obs_db provided
            mock_get.assert_not_called()
            # Should not commit when commit=False
            mock_session.commit.assert_not_called()
            # Should not close session (caller owns it)
            mock_session.close.assert_not_called()

    def test_full_trace_lifecycle_with_single_session(self, service, mock_session):
        """Test complete trace lifecycle reuses single session."""
        # Setup mocks with proper datetime
        from datetime import datetime, timezone
        mock_trace = MagicMock()
        mock_trace.start_time = datetime.now(timezone.utc)
        mock_span = MagicMock()
        mock_span.start_time = datetime.now(timezone.utc)

        def query_side_effect(*args):
            mock_query = MagicMock()
            if "ObservabilityTrace" in str(args):
                mock_query.filter_by.return_value.first.return_value = mock_trace
            else:
                mock_query.filter_by.return_value.first.return_value = mock_span
            return mock_query

        mock_session.query.side_effect = query_side_effect

        with patch("mcpgateway.services.observability_service._get_or_create_observability_session") as mock_get:
            # Simulate middleware pattern: create session once
            # Start trace (no commit)
            trace_id = service.start_trace(
                name="test_trace",
                commit=False,
                obs_db=mock_session,
            )

            # Start span (no commit)
            span_id = service.start_span(
                trace_id=trace_id,
                name="test_span",
                commit=False,
                obs_db=mock_session,
            )

            # End span (no commit)
            service.end_span(
                span_id=span_id,
                status="ok",
                commit=False,
                obs_db=mock_session,
            )

            # End trace (final commit)
            service.end_trace(
                trace_id=trace_id,
                status="ok",
                commit=True,
                obs_db=mock_session,
            )

            # Verify no new sessions created (all operations reused provided session)
            mock_get.assert_not_called()

            # Verify session was used for all operations
            assert mock_session.add.call_count == 2  # trace + span
            # Only final commit should happen
            assert mock_session.commit.call_count == 1
            # Session should not be closed (caller owns it)
            mock_session.close.assert_not_called()

    def test_add_event_with_session_reuse(self, service, mock_session):
        """Test add_event accepts obs_db parameter for session reuse."""
        # Mock commit to return False (simulating failure)
        mock_session.commit.return_value = None

        with patch("mcpgateway.services.observability_service._get_or_create_observability_session") as mock_get:
            with patch.object(service, '_safe_commit', return_value=False):
                event_id = service.add_event(
                    span_id="test-span-id",
                    name="test_event",
                    severity="info",
                    message="Test message",
                    obs_db=mock_session,
                )

                # Should not create new session when obs_db provided
                mock_get.assert_not_called()
                # Should use provided session
                mock_session.add.assert_called_once()
                # Should not close session (caller owns it)
                mock_session.close.assert_not_called()
                assert event_id == 0  # Returns 0 when commit fails
