# -*- coding: utf-8 -*-
"""
Simple test script to directly test the metrics calculation functions in issue #699.
"""
import sys
import os

# Add the mcp-context-forge directory to the path so we can import from it
sys.path.append(os.path.join(os.path.dirname(__file__), "mcp-context-forge"))
try:
    from mcpgateway.utils.metrics_common import calculate_success_rate, format_response_time
except ImportError:
    print("❌ Could not import metrics functions. Make sure you're in the correct directory.")
    sys.exit(1)

def test_calculate_success_rate():
    """Test the calculate_success_rate function."""
    print("\n--- Testing calculate_success_rate function ---")

    test_cases = [
        # (successes, total, expected_result)
        (8, 10, 80.0),  # 80% success rate
        (5, 5, 100.0),  # 100% success rate
        (0, 3, 0.0),    # 0% success rate
        (0, 0, None),   # No data (should return None)
        (None, None, None),  # None inputs (should return None)
    ]

    for i, (successes, total, expected) in enumerate(test_cases):
        result = calculate_success_rate(successes, total)
        if result == expected:
            print(f"✅ Test case {i+1}: calculate_success_rate({successes}, {total}) = {result} (Expected: {expected})")
        else:
            print(f"❌ Test case {i+1}: calculate_success_rate({successes}, {total}) = {result} (Expected: {expected})")

def test_format_response_time():
    """Test the format_response_time function."""
    print("\n--- Testing format_response_time function ---")

    test_cases = [
        # (response_time, expected_result)
        (1.23456, "1.235"),  # Standard case, rounds to 3 decimal places
        (0.12, "0.120"),     # Adds trailing zeros if needed
        (1, "1.000"),        # Integer input
        (None, None),        # None input - returns None (admin.py converts to "N/A")
        (0, "0.000"),        # Zero input
    ]

    for i, (response_time, expected) in enumerate(test_cases):
        result = format_response_time(response_time)
        if result == expected:
            print(f"✅ Test case {i+1}: format_response_time({response_time}) = '{result}' (Expected: '{expected}')")
        else:
            print(f"❌ Test case {i+1}: format_response_time({response_time}) = '{result}' (Expected: '{expected}')")

def main():
    """Run all tests."""
    print("Starting tests for issue #699 metrics calculation functions...")

    # Test core metrics functions
    test_calculate_success_rate()
    test_format_response_time()

    print("\nAll tests completed!")

if __name__ == "__main__":
    main()
