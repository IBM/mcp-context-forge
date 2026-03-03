#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate SRI hashes for CDN resources.

This script fetches external CDN resources and generates SHA-384 integrity hashes
for Subresource Integrity (SRI) verification. The hashes are written to
mcpgateway/sri_hashes.json for use in HTML templates.

Usage:
    python scripts/generate-sri-hashes.py
    make sri-generate
"""
import hashlib
import base64
import json
import sys
import urllib.request
from pathlib import Path
from typing import Dict

# Import shared CDN resource definitions
from cdn_resources import CDN_RESOURCES


def generate_sri_hash(url: str, algorithm: str = "sha384") -> str:
    """Generate SRI hash for a URL.

    Args:
        url: The URL to fetch and hash
        algorithm: Hash algorithm (default: sha384, recommended by W3C)

    Returns:
        SRI hash string in format "algorithm-base64hash"

    Raises:
        urllib.error.URLError: If URL cannot be fetched
    """
    print(f"  Fetching {url}...", end=" ", flush=True)

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            content = response.read()

        hasher = hashlib.new(algorithm)
        hasher.update(content)
        digest = hasher.digest()
        hash_b64 = base64.b64encode(digest).decode("ascii")

        sri_hash = f"{algorithm}-{hash_b64}"
        print(f"✓ ({len(content)} bytes)")
        return sri_hash

    except Exception as e:
        print(f"✗ Error: {e}")
        raise


def main() -> int:
    """Generate SRI hashes for all CDN resources."""
    print("🔐 Generating SRI hashes for CDN resources...")
    print()

    hashes: Dict[str, str] = {}
    failed = []

    for name, url in CDN_RESOURCES.items():
        try:
            hashes[name] = generate_sri_hash(url)
        except Exception as e:
            print(f"  ⚠️  Failed to generate hash for {name}: {e}")
            failed.append(name)

    if failed:
        print()
        print(f"⚠️  Failed to generate hashes for {len(failed)} resource(s):")
        for name in failed:
            print(f"  - {name}")
        return 1

    # Write hashes to JSON file
    output_path = Path(__file__).parent.parent / "mcpgateway" / "sri_hashes.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w") as f:
        json.dump(hashes, f, indent=2, sort_keys=True)
        f.write("\n")  # Add trailing newline

    print()
    print(f"✅ Successfully generated {len(hashes)} SRI hashes")
    print(f"📝 Wrote hashes to {output_path}")
    print()
    print("Next steps:")
    print("  1. Review the generated hashes in mcpgateway/sri_hashes.json")
    print("  2. Update templates to use integrity attributes")
    print("  3. Run 'make sri-verify' to verify hashes match CDN content")

    return 0


if __name__ == "__main__":
    sys.exit(main())
