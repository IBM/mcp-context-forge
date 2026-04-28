# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_time_restrictions.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Sebastian Iozu

Unit tests for time restriction validation.

This module tests the time_restrictions validation function to ensure:
- Valid time windows and day restrictions allow access
- Invalid time windows and day restrictions deny access
- Midnight crossing time ranges work correctly
- Both HH:MM and HH:MM:SS formats are supported
- Invalid formats and day names are rejected (fail-closed)
- Empty/missing restrictions allow access
- Timezone handling works correctly
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.utils.time_restrictions import VALID_DAYS, validate_time_restrictions


class TestValidateTimeRestrictions:
    """Test time restriction validation."""

    def test_no_restrictions_passes(self):
        """Test that tokens without time_restrictions pass through."""
        payload = {"sub": "user@example.com", "scopes": {}}
        # Should not raise
        validate_time_restrictions(payload)

    def test_empty_time_restrictions_passes(self):
        """Test that empty time_restrictions dict passes through."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {}}}
        # Should not raise
        validate_time_restrictions(payload)

    def test_no_actual_restrictions_passes(self):
        """Test that time_restrictions with no actual constraints passes through."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": None, "end_time": None, "timezone": "UTC", "days": []}}}
        # Should not raise
        validate_time_restrictions(payload)

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_valid_time_window_passes(self, mock_datetime):
        """Test that access within allowed time window passes."""
        # Mock current time to Wednesday 2026-03-25 10:00:00 UTC
        mock_now = datetime(2026, 3, 25, 10, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime  # Keep original strptime

        payload = {
            "sub": "user@example.com",
            "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": "UTC", "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]}},
        }
        # Should not raise
        validate_time_restrictions(payload)

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_invalid_time_window_denies(self, mock_datetime):
        """Test that access outside allowed time window is denied."""
        # Mock current time to Wednesday 2026-03-25 18:00:00 UTC (after end_time)
        mock_now = datetime(2026, 3, 25, 18, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {
            "sub": "user@example.com",
            "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": "UTC", "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]}},
        }

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "outside allowed range" in exc_info.value.detail or "restricted to" in exc_info.value.detail

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_wrong_day_denies(self, mock_datetime):
        """Test that access on non-allowed day is denied."""
        # Mock current time to Saturday 2026-03-28 10:00:00 UTC
        mock_now = datetime(2026, 3, 28, 10, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {
            "sub": "user@example.com",
            "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": "UTC", "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]}},
        }

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "Saturday" in exc_info.value.detail
        assert "restricted to specific days" in exc_info.value.detail

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_midnight_crossing_before_midnight(self, mock_datetime):
        """Test midnight crossing time range (e.g., 22:00-06:00) before midnight."""
        # Mock current time to Wednesday 2026-03-25 23:00:00 UTC
        mock_now = datetime(2026, 3, 25, 23, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "22:00", "end_time": "06:00", "timezone": "UTC", "days": []}}}
        # Should not raise (23:00 is within 22:00-06:00 range)
        validate_time_restrictions(payload)

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_midnight_crossing_after_midnight(self, mock_datetime):
        """Test midnight crossing time range (e.g., 22:00-06:00) after midnight."""
        # Mock current time to Thursday 2026-03-26 02:00:00 UTC
        mock_now = datetime(2026, 3, 26, 2, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "22:00", "end_time": "06:00", "timezone": "UTC", "days": []}}}
        # Should not raise (02:00 is within 22:00-06:00 range)
        validate_time_restrictions(payload)

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_midnight_crossing_outside_range(self, mock_datetime):
        """Test midnight crossing rejects time outside range."""
        # Mock current time to Thursday 2026-03-26 10:00:00 UTC
        mock_now = datetime(2026, 3, 26, 10, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "22:00", "end_time": "06:00", "timezone": "UTC", "days": []}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_hhmm_format_supported(self, mock_datetime):
        """Test that HH:MM format is supported."""
        # Mock current time to Wednesday 2026-03-25 10:00:00 UTC
        mock_now = datetime(2026, 3, 25, 10, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": "UTC", "days": []}}}
        # Should not raise
        validate_time_restrictions(payload)

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_hhmmss_format_supported(self, mock_datetime):
        """Test that HH:MM:SS format is supported."""
        # Mock current time to Wednesday 2026-03-25 10:00:00 UTC
        mock_now = datetime(2026, 3, 25, 10, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00:00", "end_time": "17:00:00", "timezone": "UTC", "days": []}}}
        # Should not raise
        validate_time_restrictions(payload)

    def test_invalid_time_format_denies(self):
        """Test that invalid time format is rejected (fail-closed)."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "9am", "end_time": "5pm", "timezone": "UTC", "days": []}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "invalid time format" in exc_info.value.detail.lower()

    def test_invalid_end_time_format_denies(self):
        """Test that invalid end_time format is rejected when start_time is valid."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "5pm", "timezone": "UTC", "days": []}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "invalid time format" in exc_info.value.detail.lower()

    def test_invalid_day_names_denies(self):
        """Test that invalid day names are rejected."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": "UTC", "days": ["Monday", "Moonday", "Fireday"]}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "invalid day names" in exc_info.value.detail.lower()
        assert "Moonday" in exc_info.value.detail or "Fireday" in exc_info.value.detail

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_different_timezone(self, mock_datetime):
        """Test that timezone handling works correctly."""
        # Mock current time to Wednesday 2026-03-25 10:00:00 EST (15:00 UTC)
        est = ZoneInfo("America/New_York")
        mock_now = datetime(2026, 3, 25, 10, 0, 0, tzinfo=est)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": "America/New_York", "days": ["Wednesday"]}}}
        # Should not raise (10:00 EST is within 09:00-17:00 EST)
        validate_time_restrictions(payload)

    def test_invalid_timezone_denies(self):
        """Test that invalid timezone is rejected (fail-closed)."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": "Invalid/Timezone", "days": []}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "invalid timezone" in exc_info.value.detail.lower()

    def test_only_start_time_denies(self):
        """Test that only start_time without end_time is rejected (fail-closed)."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": None, "timezone": "UTC", "days": []}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "incomplete time restriction" in exc_info.value.detail.lower()

    def test_only_end_time_denies(self):
        """Test that only end_time without start_time is rejected (fail-closed)."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": None, "end_time": "17:00", "timezone": "UTC", "days": []}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "incomplete time restriction" in exc_info.value.detail.lower()

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_only_days_restriction(self, mock_datetime):
        """Test that day-only restriction works without time range."""
        # Mock current time to Wednesday 2026-03-25 10:00:00 UTC
        mock_now = datetime(2026, 3, 25, 10, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": None, "end_time": None, "timezone": "UTC", "days": ["Monday", "Wednesday", "Friday"]}}}
        # Should not raise (Wednesday is in allowed days)
        validate_time_restrictions(payload)

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_only_days_restriction_denies(self, mock_datetime):
        """Test that day-only restriction denies access on wrong day."""
        # Mock current time to Saturday 2026-03-28 10:00:00 UTC
        mock_now = datetime(2026, 3, 28, 10, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": None, "end_time": None, "timezone": "UTC", "days": ["Monday", "Wednesday", "Friday"]}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "Saturday" in exc_info.value.detail

    def test_scopes_not_dict_passes(self):
        """Test that non-dict scopes field passes through."""
        payload = {"sub": "user@example.com", "scopes": "invalid"}
        # Should not raise
        validate_time_restrictions(payload)

    def test_time_restrictions_not_dict_passes(self):
        """Test that non-dict time_restrictions passes through."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": "invalid"}}
        # Should not raise
        validate_time_restrictions(payload)

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_boundary_exact_start_time(self, mock_datetime):
        """Test that exact start_time boundary is allowed."""
        # Mock current time to Wednesday 2026-03-25 09:00:00 UTC
        mock_now = datetime(2026, 3, 25, 9, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": "UTC", "days": []}}}
        # Should not raise (09:00 is exactly at start_time)
        validate_time_restrictions(payload)

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_boundary_exact_end_time(self, mock_datetime):
        """Test that exact end_time boundary is allowed."""
        # Mock current time to Wednesday 2026-03-25 17:00:00 UTC
        mock_now = datetime(2026, 3, 25, 17, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": "UTC", "days": []}}}
        # Should not raise (17:00 is exactly at end_time)
        validate_time_restrictions(payload)

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_seconds_precision_within_range(self, mock_datetime):
        """Test that HH:MM:SS format with seconds precision works."""
        # Mock current time to Wednesday 2026-03-25 09:30:45 UTC
        mock_now = datetime(2026, 3, 25, 9, 30, 45, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00:00", "end_time": "17:00:00", "timezone": "UTC", "days": []}}}
        # Should not raise (09:30:45 is within 09:00:00-17:00:00)
        validate_time_restrictions(payload)

    def test_valid_days_constant(self):
        """Test that VALID_DAYS constant contains all 7 days."""
        assert len(VALID_DAYS) == 7
        assert "Monday" in VALID_DAYS
        assert "Tuesday" in VALID_DAYS
        assert "Wednesday" in VALID_DAYS
        assert "Thursday" in VALID_DAYS
        assert "Friday" in VALID_DAYS
        assert "Saturday" in VALID_DAYS
        assert "Sunday" in VALID_DAYS

    # --- Type guard tests (fail-closed on wrong inner types) ---

    def test_non_string_start_time_denies(self):
        """Test that non-string start_time is rejected."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": 123, "end_time": "17:00", "timezone": "UTC", "days": []}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "start_time and end_time must be strings" in exc_info.value.detail

    def test_non_string_end_time_denies(self):
        """Test that non-string end_time is rejected."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": 1700, "timezone": "UTC", "days": []}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "start_time and end_time must be strings" in exc_info.value.detail

    def test_non_string_timezone_denies(self):
        """Test that non-string timezone is rejected."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": 123, "days": []}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "timezone must be a string" in exc_info.value.detail

    def test_non_list_days_denies(self):
        """Test that non-list days is rejected (e.g. string iterates chars)."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": "UTC", "days": "Monday"}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "days must be a list of strings" in exc_info.value.detail

    def test_int_days_denies(self):
        """Test that integer days is rejected."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": "UTC", "days": 1}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "days must be a list of strings" in exc_info.value.detail

    def test_non_string_entries_in_days_denies(self):
        """Test that non-string entries inside days list are rejected (fail-closed)."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": "UTC", "days": [123, None]}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "days must be a list of strings" in exc_info.value.detail

    def test_mixed_valid_and_invalid_type_in_days_denies(self):
        """Test that a mix of strings and non-strings in days is rejected."""
        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "09:00", "end_time": "17:00", "timezone": "UTC", "days": ["Monday", 123]}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "days must be a list of strings" in exc_info.value.detail

    # --- Overnight window + days semantics ---

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_overnight_window_with_days_allows_same_calendar_day(self, mock_datetime):
        """Test that overnight window allows access on the starting calendar day.

        With days=["Monday"] and window 22:00-06:00, Monday 23:00 is allowed
        because the day check applies to the current calendar day.
        """
        # Monday 23:00 UTC
        mock_now = datetime(2026, 3, 23, 23, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "22:00", "end_time": "06:00", "timezone": "UTC", "days": ["Monday"]}}}
        # Should not raise (Monday is allowed, 23:00 is in 22:00-06:00 range)
        validate_time_restrictions(payload)

    @patch("mcpgateway.utils.time_restrictions.datetime")
    def test_overnight_window_with_days_denies_next_calendar_day(self, mock_datetime):
        """Test that overnight window denies access on the next calendar day.

        With days=["Monday"] and window 22:00-06:00, Tuesday 02:00 is denied
        because the day check applies to the current calendar day (Tuesday),
        which is not in the allowed list. To allow overnight continuation,
        include both Monday and Tuesday in the days list.
        """
        # Tuesday 02:00 UTC
        mock_now = datetime(2026, 3, 24, 2, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        payload = {"sub": "user@example.com", "scopes": {"time_restrictions": {"start_time": "22:00", "end_time": "06:00", "timezone": "UTC", "days": ["Monday"]}}}

        with pytest.raises(HTTPException) as exc_info:
            validate_time_restrictions(payload)

        assert exc_info.value.status_code == 403
        assert "Tuesday" in exc_info.value.detail
