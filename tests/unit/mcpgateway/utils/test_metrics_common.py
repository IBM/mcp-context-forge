# -*- coding: utf-8 -*-
"""
Unit tests for metrics_common.py utility functions.
"""

# Standard
import unittest
from unittest.mock import MagicMock

# Third-party
import pytest

# First-party
from mcpgateway.utils.metrics_common import build_top_performers, calculate_success_rate, format_response_time


class TestMetricsCommon(unittest.TestCase):
    """Test suite for metrics_common.py utility functions."""

    def test_calculate_success_rate_normal(self):
        """Test success rate calculation with normal inputs."""
        # Test with integer inputs
        self.assertEqual(calculate_success_rate(75, 100), 75.0)
        # Test with float inputs
        self.assertEqual(calculate_success_rate(7.5, 10), 75.0)
        # Test with 100% success rate
        self.assertEqual(calculate_success_rate(10, 10), 100.0)
        # Test with 0% success rate
        self.assertEqual(calculate_success_rate(0, 10), 0.0)

    def test_calculate_success_rate_edge_cases(self):
        """Test success rate calculation with edge cases."""
        # Test with zero total
        self.assertIsNone(calculate_success_rate(0, 0))
        # Test with negative total
        self.assertIsNone(calculate_success_rate(5, -10))
        # Test with None inputs
        self.assertIsNone(calculate_success_rate(None, 10))
        self.assertIsNone(calculate_success_rate(5, None))
        self.assertIsNone(calculate_success_rate(None, None))
        # Test with successful > total (should still calculate but might not make logical sense)
        self.assertEqual(calculate_success_rate(15, 10), 150.0)

    def test_format_response_time_normal(self):
        """Test response time formatting with normal inputs."""
        # Test with integer
        self.assertEqual(format_response_time(1), "1.000")
        # Test with float, no rounding
        self.assertEqual(format_response_time(1.234), "1.234")
        # Test with float, rounding up
        self.assertEqual(format_response_time(1.2345), "1.235")
        # Test with float, rounding down
        self.assertEqual(format_response_time(1.2344), "1.234")
        # Test with zero
        self.assertEqual(format_response_time(0), "0.000")

    def test_format_response_time_edge_cases(self):
        """Test response time formatting with edge cases."""
        # Test with None
        self.assertIsNone(format_response_time(None))
        # Test with negative value
        self.assertEqual(format_response_time(-1.234), "-1.234")
        # Test with string that can be converted to float
        self.assertEqual(format_response_time("1.234"), "1.234")
        # Test with string that cannot be converted to float
        with pytest.raises(ValueError):
            format_response_time("not a number")

    def test_build_top_performers(self):
        """Test building TopPerformer objects from database results."""
        # Create mock results
        result1 = MagicMock()
        result1.id = 1
        result1.name = "test1"
        result1.execution_count = 10
        result1.avg_response_time = 1.5
        result1.success_rate = 85.0
        result1.last_execution = None

        result2 = MagicMock()
        result2.id = 2
        result2.name = "test2"
        result2.execution_count = 20
        result2.avg_response_time = None
        result2.success_rate = None
        result2.last_execution = None

        # Test with a list of results
        performers = build_top_performers([result1, result2])

        # Verify the results
        self.assertEqual(len(performers), 2)
        self.assertEqual(performers[0].id, 1)
        self.assertEqual(performers[0].name, "test1")
        self.assertEqual(performers[0].execution_count, 10)
        self.assertEqual(performers[0].avg_response_time, 1.5)
        self.assertEqual(performers[0].success_rate, 85.0)
        self.assertIsNone(performers[0].last_execution)

        self.assertEqual(performers[1].id, 2)
        self.assertEqual(performers[1].name, "test2")
        self.assertEqual(performers[1].execution_count, 20)
        self.assertIsNone(performers[1].avg_response_time)
        self.assertIsNone(performers[1].success_rate)
        self.assertIsNone(performers[1].last_execution)

        # Test with empty list
        empty_performers = build_top_performers([])
        self.assertEqual(len(empty_performers), 0)


if __name__ == "__main__":
    unittest.main()
