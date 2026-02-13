#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Verify UUID format changes are working correctly."""

import sys
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.schemas import ServerCreate, ServerUpdate

print("=" * 70)
print("VERIFYING UUID FORMAT CHANGES")
print("=" * 70)
print()

# Test 1: SecurityValidator.validate_uuid with hyphenated input
print("Test 1: SecurityValidator.validate_uuid with hyphenated input")
result1 = SecurityValidator.validate_uuid('550e8400-e29b-41d4-a716-446655440000')
print(f"  Input:  550e8400-e29b-41d4-a716-446655440000")
print(f"  Output: {result1}")
print(f"  Expected: 550e8400-e29b-41d4-a716-446655440000")
print(f"  ✓ PASS" if result1 == '550e8400-e29b-41d4-a716-446655440000' else f"  ✗ FAIL")
print()

# Test 2: SecurityValidator.validate_uuid with hex input (no dashes)
print("Test 2: SecurityValidator.validate_uuid with hex input (normalizes to hyphenated)")
result2 = SecurityValidator.validate_uuid('550e8400e29b41d4a716446655440000')
print(f"  Input:  550e8400e29b41d4a716446655440000")
print(f"  Output: {result2}")
print(f"  Expected: 550e8400-e29b-41d4-a716-446655440000")
print(f"  ✓ PASS" if result2 == '550e8400-e29b-41d4-a716-446655440000' else f"  ✗ FAIL")
print()

# Test 3: ServerCreate with custom UUID
print("Test 3: ServerCreate schema with custom UUID")
try:
    server_create = ServerCreate(id="550e8400-e29b-41d4-a716-446655440000", name="Test Server")
    print(f"  Input:  550e8400-e29b-41d4-a716-446655440000")
    print(f"  Output: {server_create.id}")
    print(f"  Expected: 550e8400-e29b-41d4-a716-446655440000")
    print(f"  ✓ PASS" if server_create.id == '550e8400-e29b-41d4-a716-446655440000' else f"  ✗ FAIL")
except Exception as e:
    print(f"  ✗ FAIL: {e}")
print()

# Test 4: ServerUpdate with custom UUID
print("Test 4: ServerUpdate schema with custom UUID")
try:
    server_update = ServerUpdate(id="123e4567-e89b-12d3-a456-426614174000")
    print(f"  Input:  123e4567-e89b-12d3-a456-426614174000")
    print(f"  Output: {server_update.id}")
    print(f"  Expected: 123e4567-e89b-12d3-a456-426614174000")
    print(f"  ✓ PASS" if server_update.id == '123e4567-e89b-12d3-a456-426614174000' else f"  ✗ FAIL")
except Exception as e:
    print(f"  ✗ FAIL: {e}")
print()

# Test 5: UUID length verification
print("Test 5: UUID format length verification")
result5 = SecurityValidator.validate_uuid('550e8400-e29b-41d4-a716-446655440000')
print(f"  Length: {len(result5)}")
print(f"  Has dashes: {'-' in result5}")
print(f"  Expected length: 36")
print(f"  Expected dashes: True")
print(f"  ✓ PASS" if len(result5) == 36 and '-' in result5 else f"  ✗ FAIL")
print()

print("=" * 70)
print("VERIFICATION COMPLETE")
print("=" * 70)
