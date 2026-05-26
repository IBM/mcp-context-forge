# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_tool_lifecycle_validation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for tool lifecycle management validation (sunset_date field).

Tests cover:
- ToolCreate schema validation
- ToolUpdate schema validation
- sunsetDate required when deprecated=True
- sunsetDate must be future date
- sunsetDate can be cleared when deprecated=False
- Timezone-aware datetime handling
"""

# Standard
from datetime import datetime, timedelta, timezone

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.schemas import ToolCreate, ToolUpdate


class TestToolCreateSunsetValidation:
    """Test suite for ToolCreate schema sunset_date validation."""

    def test_create_active_tool_without_sunset_date(self):
        """Test creating an active tool without sunset_date succeeds."""
        tool_data = {
            "name": "test_tool",
            "description": "Test tool",
            "inputSchema": {"type": "object", "properties": {}},
            "deprecated": False,
        }
        tool = ToolCreate(**tool_data)
        assert tool.deprecated is False
        assert tool.sunsetDate is None

    def test_create_deprecated_tool_without_sunset_date_fails(self):
        """Test creating deprecated tool without sunset_date raises ValidationError."""
        tool_data = {
            "name": "test_tool",
            "description": "Test tool",
            "inputSchema": {"type": "object", "properties": {}},
            "deprecated": True,
            # Missing sunsetDate
        }
        with pytest.raises(ValidationError) as exc_info:
            ToolCreate(**tool_data)

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert "sunsetDate is required when deprecated=True" in str(errors[0]["msg"])

    def test_create_deprecated_tool_with_future_sunset_date_succeeds(self):
        """Test creating deprecated tool with future sunset_date succeeds."""
        future_date = datetime.now(timezone.utc) + timedelta(days=30)
        tool_data = {
            "name": "test_tool",
            "description": "Test tool",
            "inputSchema": {"type": "object", "properties": {}},
            "deprecated": True,
            "sunsetDate": future_date,
        }
        tool = ToolCreate(**tool_data)
        assert tool.deprecated is True
        assert tool.sunsetDate == future_date
        assert tool.sunsetDate.tzinfo is not None  # Timezone-aware

    def test_create_deprecated_tool_with_past_sunset_date_fails(self):
        """Test creating deprecated tool with past sunset_date raises ValidationError."""
        past_date = datetime.now(timezone.utc) - timedelta(days=1)
        tool_data = {
            "name": "test_tool",
            "description": "Test tool",
            "inputSchema": {"type": "object", "properties": {}},
            "deprecated": True,
            "sunsetDate": past_date,
        }
        with pytest.raises(ValidationError) as exc_info:
            ToolCreate(**tool_data)

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert "sunsetDate must be in the future" in str(errors[0]["msg"])

    def test_create_deprecated_tool_with_current_time_fails(self):
        """Test creating deprecated tool with current time as sunset_date fails."""
        now = datetime.now(timezone.utc)
        tool_data = {
            "name": "test_tool",
            "description": "Test tool",
            "inputSchema": {"type": "object", "properties": {}},
            "deprecated": True,
            "sunsetDate": now,
        }
        with pytest.raises(ValidationError) as exc_info:
            ToolCreate(**tool_data)

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert "sunsetDate must be in the future" in str(errors[0]["msg"])

    def test_create_tool_with_naive_datetime_converts_to_utc(self):
        """Test creating tool with timezone-naive datetime auto-converts to UTC."""
        # Create naive datetime (no timezone)
        naive_date = datetime.now() + timedelta(days=30)
        tool_data = {
            "name": "test_tool",
            "description": "Test tool",
            "inputSchema": {"type": "object", "properties": {}},
            "deprecated": True,
            "sunsetDate": naive_date,
        }
        # Should not raise - naive datetime is auto-converted to UTC
        tool = ToolCreate(**tool_data)

        # Verify sunsetDate has timezone info (UTC)
        assert tool.sunsetDate is not None
        assert tool.sunsetDate.tzinfo is not None
        assert tool.sunsetDate.tzinfo == timezone.utc

    def test_create_active_tool_with_sunset_date_succeeds(self):
        """Test creating active tool with sunset_date succeeds (for pre-planning)."""
        future_date = datetime.now(timezone.utc) + timedelta(days=30)
        tool_data = {
            "name": "test_tool",
            "description": "Test tool",
            "inputSchema": {"type": "object", "properties": {}},
            "deprecated": False,
            "sunsetDate": future_date,
        }
        tool = ToolCreate(**tool_data)
        assert tool.deprecated is False
        assert tool.sunsetDate == future_date


class TestToolUpdateSunsetValidation:
    """Test suite for ToolUpdate schema sunset_date validation."""

    def test_update_to_deprecated_without_sunset_date_fails(self):
        """Test updating tool to deprecated without sunset_date raises ValidationError."""
        update_data = {
            "deprecated": True,
            # Missing sunsetDate
        }
        with pytest.raises(ValidationError) as exc_info:
            ToolUpdate(**update_data)

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert "sunsetDate is required when setting deprecated=True" in str(errors[0]["msg"])

    def test_update_to_deprecated_with_future_sunset_date_succeeds(self):
        """Test updating tool to deprecated with future sunset_date succeeds."""
        future_date = datetime.now(timezone.utc) + timedelta(days=30)
        update_data = {
            "deprecated": True,
            "sunsetDate": future_date,
        }
        tool = ToolUpdate(**update_data)
        assert tool.deprecated is True
        assert tool.sunsetDate == future_date

    def test_update_to_deprecated_with_past_sunset_date_fails(self):
        """Test updating tool to deprecated with past sunset_date raises ValidationError."""
        past_date = datetime.now(timezone.utc) - timedelta(days=1)
        update_data = {
            "deprecated": True,
            "sunsetDate": past_date,
        }
        with pytest.raises(ValidationError) as exc_info:
            ToolUpdate(**update_data)

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert "sunsetDate must be in the future" in str(errors[0]["msg"])

    def test_update_to_active_clears_sunset_date(self):
        """Test updating tool to active (deprecated=False) allows clearing sunset_date."""
        update_data = {
            "deprecated": False,
            "sunsetDate": None,
        }
        tool = ToolUpdate(**update_data)
        assert tool.deprecated is False
        assert tool.sunsetDate is None

    def test_update_to_active_with_sunset_date_succeeds(self):
        """Test updating to active while keeping sunset_date succeeds (for pre-planning)."""
        future_date = datetime.now(timezone.utc) + timedelta(days=30)
        update_data = {
            "deprecated": False,
            "sunsetDate": future_date,
        }
        tool = ToolUpdate(**update_data)
        assert tool.deprecated is False
        assert tool.sunsetDate == future_date

    def test_update_only_sunset_date_without_deprecated_succeeds(self):
        """Test updating only sunset_date without changing deprecated status succeeds."""
        future_date = datetime.now(timezone.utc) + timedelta(days=60)
        update_data = {
            "sunsetDate": future_date,
        }
        tool = ToolUpdate(**update_data)
        assert tool.deprecated is None  # Not being updated
        assert tool.sunsetDate == future_date

    def test_update_with_naive_datetime_converts_to_utc(self):
        """Test updating with timezone-naive datetime auto-converts to UTC."""
        naive_date = datetime.now() + timedelta(days=30)
        update_data = {
            "deprecated": True,
            "sunsetDate": naive_date,
        }
        # Should not raise - naive datetime is auto-converted to UTC
        tool_update = ToolUpdate(**update_data)

        # Verify sunsetDate has timezone info (UTC)
        assert tool_update.sunsetDate is not None
        assert tool_update.sunsetDate.tzinfo is not None
        assert tool_update.sunsetDate.tzinfo == timezone.utc

    def test_update_deprecated_false_with_null_sunset_date_succeeds(self):
        """Test explicitly setting deprecated=False and sunsetDate=None succeeds."""
        update_data = {
            "deprecated": False,
            "sunsetDate": None,
        }
        tool = ToolUpdate(**update_data)
        assert tool.deprecated is False
        assert tool.sunsetDate is None


class TestToolLifecycleEdgeCases:
    """Test suite for edge cases in tool lifecycle validation."""

    def test_sunset_date_exactly_one_second_in_future_succeeds(self):
        """Test sunset_date exactly 1 second in future succeeds."""
        future_date = datetime.now(timezone.utc) + timedelta(seconds=1)
        tool_data = {
            "name": "test_tool",
            "description": "Test tool",
            "inputSchema": {"type": "object", "properties": {}},
            "deprecated": True,
            "sunsetDate": future_date,
        }
        tool = ToolCreate(**tool_data)
        assert tool.sunsetDate == future_date

    def test_sunset_date_far_future_succeeds(self):
        """Test sunset_date far in future (1 year) succeeds."""
        future_date = datetime.now(timezone.utc) + timedelta(days=365)
        tool_data = {
            "name": "test_tool",
            "description": "Test tool",
            "inputSchema": {"type": "object", "properties": {}},
            "deprecated": True,
            "sunsetDate": future_date,
        }
        tool = ToolCreate(**tool_data)
        assert tool.sunsetDate == future_date

    def test_different_timezone_future_date_succeeds(self):
        """Test sunset_date with different timezone (but still future) succeeds."""
        # Create a future date in a different timezone
        from datetime import timezone as tz
        future_date = datetime.now(tz(timedelta(hours=5))) + timedelta(days=30)
        tool_data = {
            "name": "test_tool",
            "description": "Test tool",
            "inputSchema": {"type": "object", "properties": {}},
            "deprecated": True,
            "sunsetDate": future_date,
        }
        tool = ToolCreate(**tool_data)
        assert tool.sunsetDate.tzinfo is not None

    def test_update_only_deprecated_to_true_without_existing_sunset_fails(self):
        """Test updating only deprecated to True (without sunset_date) fails."""
        update_data = {
            "deprecated": True,
        }
        with pytest.raises(ValidationError) as exc_info:
            ToolUpdate(**update_data)

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert "sunsetDate is required when setting deprecated=True" in str(errors[0]["msg"])

    def test_create_with_both_deprecated_false_and_sunset_date_succeeds(self):
        """Test creating tool with deprecated=False but with sunset_date succeeds."""
        future_date = datetime.now(timezone.utc) + timedelta(days=30)
        tool_data = {
            "name": "test_tool",
            "description": "Test tool",
            "inputSchema": {"type": "object", "properties": {}},
            "deprecated": False,
            "sunsetDate": future_date,
        }
        tool = ToolCreate(**tool_data)
        assert tool.deprecated is False
        assert tool.sunsetDate == future_date
