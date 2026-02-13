#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify SRI hashes match current CDN content.

This script fetches external CDN resources and verifies that their SHA-384 hashes
match the values stored in mcpgateway/sri_hashes.json. This ensures that:
1. CDN content hasn't changed unexpectedly
2. SRI hashes in the repository are up-to-date
3. No version drift has occurred

Usage:
    python scripts/verify-sri-hashes.py
    make sri-verify
"""
import hashlib
import base64
import json
import sys
import urllib.request
from pathlib import Path
from typing import Dict, Tuple

# CDN resources requiring SRI hashes (must match generate-sri-hashes.py)
CDN_RESOURCES = {
    # HTMX
    "htmx": "https://unpkg.com/htmx.org@1.9.10/dist/htmx.min.js",

    # Alpine.js
    "alpinejs": "https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js",

    # Chart.js
    "chartjs": "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js",

    # Marked (Markdown parser)
    "marked": "https://cdn.jsdelivr.net/npm/marked@11.1.1/marked.min.js",

    # DOMPurify (XSS sanitizer)
    "dompurify": "https://cdn.jsdelivr.net/npm/dompurify@3.0.6/dist/purify.min.js",

    # CodeMirror (code editor)
    "codemirror_js": "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/codemirror.min.js",
    "codemirror_addon_simple": "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/addon/mode/simple.min.js",
    "codemirror_mode_javascript": "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/mode/javascript/javascript.min.js",
    "codemirror_mode_python": "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/mode/python/python.min.js",
    "codemirror_mode_shell": "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/mode/shell/shell.min.js",
    "codemirror_mode_go": "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/mode/go/go.min.js",
    "codemirror_mode_rust": "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/mode/rust/rust.min.js",
    "codemirror_css": "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/codemirror.min.css",
    "codemirror_theme_monokai": "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/theme/monokai.min.css",

    # Font Awesome
    "fontawesome": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css",
}


def calculate_sri_hash(url: str, algorithm: str = "sha384") -> str:
    """Calculate SRI hash for a URL.

    Args:
        url: The URL to fetch and hash
        algorithm: Hash algorithm (default: sha384, recommended by W3C)

    Returns:
        SRI hash string in format "algorithm-base64hash"

    Raises:
        urllib.error.URLError: If URL cannot be fetched
    """
    with urllib.request.urlopen(url, timeout=30) as response:
        content = response.read()

    hasher = hashlib.new(algorithm)
    hasher.update(content)
    digest = hasher.digest()
    hash_b64 = base64.b64encode(digest).decode("ascii")

    return f"{algorithm}-{hash_b64}"


def load_stored_hashes() -> Dict[str, str]:
    """Load SRI hashes from sri_hashes.json.

    Returns:
        Dict[str, str]: Dictionary mapping resource names to SRI hash strings

    Raises:
        FileNotFoundError: If sri_hashes.json doesn't exist
        json.JSONDecodeError: If sri_hashes.json is invalid
    """
    sri_file = Path(__file__).parent.parent / "mcpgateway" / "sri_hashes.json"
    
    if not sri_file.exists():
        raise FileNotFoundError(
            f"SRI hashes file not found: {sri_file}\n"
            "Run 'make sri-generate' to generate hashes"
        )
    
    with sri_file.open("r") as f:
        return json.load(f)


def verify_hash(name: str, url: str, stored_hash: str) -> Tuple[bool, str, str]:
    """Verify a single resource hash.

    Args:
        name: Resource name
        url: CDN URL
        stored_hash: Expected SRI hash from sri_hashes.json

    Returns:
        Tuple of (success, actual_hash, error_message)
    """
    try:
        actual_hash = calculate_sri_hash(url)
        
        if actual_hash == stored_hash:
            return True, actual_hash, ""
        else:
            return False, actual_hash, f"Hash mismatch!\n    Expected: {stored_hash}\n    Actual:   {actual_hash}"
    
    except Exception as e:
        return False, "", f"Failed to fetch: {e}"


def main() -> int:
    """Verify all SRI hashes match current CDN content."""
    print("🔐 Verifying SRI hashes against CDN content...")
    print()

    # Load stored hashes
    try:
        stored_hashes = load_stored_hashes()
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return 1
    except json.JSONDecodeError as e:
        print(f"❌ Invalid sri_hashes.json: {e}")
        return 1

    # Verify each resource
    results = []
    failed = []
    
    for name, url in CDN_RESOURCES.items():
        if name not in stored_hashes:
            print(f"  ⚠️  {name}: Missing from sri_hashes.json")
            failed.append(name)
            continue
        
        print(f"  Verifying {name}...", end=" ", flush=True)
        success, actual_hash, error = verify_hash(name, url, stored_hashes[name])
        
        if success:
            print("✓")
            results.append((name, True, ""))
        else:
            print(f"✗")
            print(f"    {error}")
            results.append((name, False, error))
            failed.append(name)

    # Check for extra hashes in file
    extra_hashes = set(stored_hashes.keys()) - set(CDN_RESOURCES.keys())
    if extra_hashes:
        print()
        print(f"  ⚠️  Extra hashes in sri_hashes.json (not in CDN_RESOURCES):")
        for name in extra_hashes:
            print(f"    - {name}")

    # Summary
    print()
    if failed:
        print(f"❌ Verification failed for {len(failed)} resource(s):")
        for name in failed:
            print(f"  - {name}")
        print()
        print("💡 To update hashes, run: make sri-generate")
        return 1
    else:
        print(f"✅ All {len(CDN_RESOURCES)} SRI hashes verified successfully!")
        return 0


if __name__ == "__main__":
    sys.exit(main())