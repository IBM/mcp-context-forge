#!/usr/bin/env python3
"""Validate that legacy routes are disabled when LEGACY_API_ENABLED=false.

This script validates deployment configuration by checking that:
1. Legacy routes (unversioned) return 404 when LEGACY_API_ENABLED=false
2. Versioned routes (/v1/*) remain accessible

Auth-protected routes return 401 without credentials, which is ambiguous — a 401
could mean the route exists (legacy enabled) or that auth middleware intercepted
before the routing layer could return 404. Pass --token to authenticate requests
and get an unambiguous result.

Usage:
    python scripts/validate_legacy_disabled.py [BASE_URL] [--token BEARER_TOKEN]

Example:
    python scripts/validate_legacy_disabled.py http://localhost:4444
    python scripts/validate_legacy_disabled.py https://api.example.com --token eyJ...

Exit codes:
    0 - All validations passed
    1 - Validation failed
    2 - Connection error or invalid URL
"""

import argparse
import sys
from typing import List, Optional, Tuple

try:
    import requests
except ImportError:
    print("ERROR: requests library not installed. Install with: pip install requests")
    sys.exit(2)


def validate_legacy_disabled(base_url: str, token: Optional[str] = None) -> bool:
    """Check that legacy routes return 404 when disabled.

    Args:
        base_url: Base URL of the API (e.g., http://localhost:4444)
        token: Optional bearer token for authenticated requests.

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

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    auth_note = " (authenticated)" if token else " (unauthenticated — pass --token for unambiguous results)"

    all_passed = True

    print(f"Validating legacy routes disabled at: {base_url}{auth_note}")
    print("=" * 60)

    # Check legacy routes return 404
    print("\n1. Checking legacy routes return 404...")
    for path in legacy_paths:
        try:
            resp = requests.get(f"{base_url}{path}", headers=headers, timeout=5, allow_redirects=False)
            if resp.status_code == 404:
                print(f"  ✓ {path} → 404 (correct)")
            elif resp.status_code == 401 and not token:
                print(f"  ? {path} → 401 (ambiguous without token — pass --token to verify)")
                all_passed = False
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
            resp = requests.get(f"{base_url}{path}", headers=headers, timeout=5, allow_redirects=False)
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
    parser = argparse.ArgumentParser(description="Validate legacy routes are disabled.")
    parser.add_argument("base_url", nargs="?", default="http://localhost:4444", help="Base URL of the API")
    parser.add_argument("--token", default=None, help="Bearer token for authenticated requests")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")

    # Validate URL format
    if not base_url.startswith(("http://", "https://")):
        print(f"ERROR: Invalid URL format: {base_url}")
        print("URL must start with http:// or https://")
        sys.exit(2)

    try:
        if validate_legacy_disabled(base_url, token=args.token):
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
