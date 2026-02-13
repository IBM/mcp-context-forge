#!/usr/bin/env python3
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

# CDN resources requiring SRI hashes
# Format: "key": "url"
CDN_RESOURCES = {
    # Tailwind CSS (JIT - special handling, no SRI for dynamic content)
    # "tailwindcss": "https://cdn.tailwindcss.com",  # Excluded: JIT compiler
    
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

# Made with Bob
