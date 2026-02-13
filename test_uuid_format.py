#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quick test of UUID format changes."""

from mcpgateway.common.validators import SecurityValidator

# Test 1: Hyphenated UUID input
result1 = SecurityValidator.validate_uuid('550e8400-e29b-41d4-a716-446655440000')
print("Test 1: Hyphenated UUID")
print(f"  Input:  550e8400-e29b-41d4-a716-446655440000")
print(f"  Output: {result1}")
print(f"  Length: {len(result1)}")
print(f"  Has dashes: {'-' in result1}")
print()

# Test 2: Hex UUID input (no dashes)
result2 = SecurityValidator.validate_uuid('550e8400e29b41d4a716446655440000')
print("Test 2: Hex UUID (no dashes)")
print(f"  Input:  550e8400e29b41d4a716446655440000")
print(f"  Output: {result2}")
print(f"  Length: {len(result2)}")
print(f"  Has dashes: {'-' in result2}")
print()

# Test 3: Uppercase UUID
result3 = SecurityValidator.validate_uuid('550E8400-E29B-41D4-A716-446655440000')
print("Test 3: Uppercase UUID")
print(f"  Input:  550E8400-E29B-41D4-A716-446655440000")
print(f"  Output: {result3}")
print(f"  Length: {len(result3)}")
print(f"  Has dashes: {'-' in result3}")
print(f"  Is lowercase: {result3.islower() or all(c.isdigit() or c == '-' for c in result3)}")
