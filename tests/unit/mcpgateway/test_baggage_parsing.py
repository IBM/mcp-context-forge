# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_baggage_parsing.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for baggage.py parsing edge cases.

This module targets specific uncovered lines in baggage parsing logic.
"""

# Standard
from unittest.mock import patch


class TestBaggageParsing:
    """Tests for baggage.py parsing edge cases."""

    def test_parse_w3c_baggage_invalid_member_no_equals_line_366(self):
        """Test parsing baggage member without '=' separator (line 366)."""
        # First-Party
        from mcpgateway.baggage import parse_w3c_baggage_header

        # Baggage header with invalid member (no '=')
        baggage_header = "valid-key=valid-value,invalid-member-no-equals,another-key=another-value"

        with patch("mcpgateway.baggage.logger") as mock_logger:
            result = parse_w3c_baggage_header(baggage_header)

            # Should skip invalid member and parse valid ones
            assert "valid-key" in result
            assert "another-key" in result
            assert "invalid-member-no-equals" not in result

            # Should have logged the skip (line 366)
            debug_calls = [call for call in mock_logger.debug.call_args_list if len(call[0]) > 0 and "Skipping invalid baggage member" in call[0][0]]
            assert len(debug_calls) == 1

    def test_filter_incoming_baggage_size_limit_line_437(self):
        """Test filtering baggage when size limit is reached (line 437)."""
        # First-Party
        from mcpgateway.baggage import BaggageConfig, filter_incoming_baggage, HeaderMapping

        # Create config with mappings to allow keys and small size limit
        config = BaggageConfig(
            enabled=True,
            mappings=[
                HeaderMapping("X-Key1", "key1"),
                HeaderMapping("X-Key2", "key2"),
                HeaderMapping("X-Key3", "key3"),
                HeaderMapping("X-Key4", "key4"),
                HeaderMapping("X-Key5", "key5"),
            ],
            propagate_to_external=False,
            max_items=10,
            max_size_bytes=30,  # Very small limit - only 2 keys will fit
            log_rejected=True,
            log_sanitization=False,
        )

        # Create baggage that will definitely exceed size limit
        # Each entry: len(key) + len(value) + 2
        # "key1" (4) + "value1" (6) + 2 = 12 bytes
        # "key2" (4) + "value2" (6) + 2 = 12 bytes (total 24)
        # "key3" (4) + "value3" (6) + 2 = 12 bytes (total 36, exceeds 30)
        baggage = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
            "key4": "value4",
            "key5": "value5",
        }

        with patch("mcpgateway.baggage.logger") as mock_logger:
            result = filter_incoming_baggage(baggage, config)

            # Should have dropped keys due to size limit
            assert len(result) < len(baggage), f"Expected fewer keys, got {len(result)} out of {len(baggage)}"

            # Should have logged the rejection (line 437)
            warning_calls = [call for call in mock_logger.warning.call_args_list if len(call[0]) > 0 and "size limit reached" in call[0][0]]
            assert len(warning_calls) >= 1, f"Expected size limit warning, got warnings: {mock_logger.warning.call_args_list}"
