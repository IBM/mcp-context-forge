#!/usr/bin/env python3
"""Validate that legacy routes are disabled when LEGACY_API_ENABLED=false.

This script validates deployment configuration by checking that:
1. Legacy routes (unversioned) return 404 when LEGACY_API_ENABLED=false
2. Versioned routes (/v1/*) remain accessible

Usage:
    python scripts/validate_legacy_disabled.py [BASE_URL]

Example:
    python scripts/validate_legacy_disabled.py http://localhost:4444
    python scripts/validate_legacy_disabled.py https://api.example.com

Exit codes:
    0 - All validations passed
    1 - Validation failed
    2 - Connection error or invalid URL
"""

import sys
from typing import List, Tuple

try:
    import requests
except ImportError:
    print("ERROR: requests library not installed. Install with: pip install requests")
    sys.exit(2)


def validate_legacy_disabled(base_url: str) -> bool:
    """Check that legacy routes return 404 when disabled.

    Args:
        base_url: Base URL of the API (e.g., http://localhost:4444)

    Returns:
        True if all validations pass, False otherwise.
    """
    # Legacy paths that should return 404 when disabled
    legacy_paths = [
        "/tools",
        "/servers",
        "/prompts",
        "/resources",
        "/gateways",
    ]

    # Versioned paths that should still work
    v1_paths = [
        "/v1/tools",
        "/v1/servers",
        "/v1/prompts",
        "/v1/resources",
        "/v1/gateways",
    ]

    all_passed = True

    print(f"Validating legacy routes disabled at: {base_url}")
    print("=" * 60)

    # Check legacy routes return 404
    print("\n1. Checking legacy routes return 404...")
    for path in legacy_paths:
        try:
            resp = requests.get(f"{base_url}{path}", timeout=5, allow_redirects=False)
            if resp.status_code == 404:
                print(f"  ✓ {path} → 404 (correct)")
            else:
                print(f"  ✗ {path} → {resp.status_code} (expected 404)")
                all_passed = False
        except requests.RequestException as e:
            print(f"  ✗ {path} → ERROR: {e}")
            all_passed = False

    # Check v1 routes are accessible (not 404)
    print("\n2. Checking /v1/* routes are accessible...")
    for path in v1_paths:
        try:
            resp = requests.get(f"{base_url}{path}", timeout=5, allow_redirects=False)
            if resp.status_code == 404:
                print(f"  ✗ {path} → 404 (should be accessible)")
                all_passed = False
            else:
                # Any non-404 is acceptable (401/403 due to auth is fine)
                print(f"  ✓ {path} → {resp.status_code} (accessible)")
        except requests.RequestException as e:
            print(f"  ✗ {path} → ERROR: {e}")
            all_passed = False

    print("\n" + "=" * 60)
    return all_passed


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        base_url = sys.argv[1].rstrip("/")
    else:
        base_url = "http://localhost:4444"

    # Validate URL format
    if not base_url.startswith(("http://", "https://")):
        print(f"ERROR: Invalid URL format: {base_url}")
        print("URL must start with http:// or https://")
        sys.exit(2)

    try:
        if validate_legacy_disabled(base_url):
            print("\n✓ All validations passed - legacy routes correctly disabled")
            sys.exit(0)
        else:
            print("\n✗ Validation failed - see errors above")
            sys.exit(1)
    except requests.ConnectionError:
        print(f"\nERROR: Could not connect to {base_url}")
        print("Ensure the server is running and accessible")
        sys.exit(2)
    except Exception as e:
        print(f"\nERROR: Unexpected error: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
