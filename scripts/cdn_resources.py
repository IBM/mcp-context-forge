#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared CDN resource definitions for SRI hash generation and verification.

This module provides a single source of truth for all CDN resources that require
Subresource Integrity (SRI) protection. Both generate-sri-hashes.py and
verify-sri-hashes.py import from this module to prevent configuration drift.
"""

# CDN resources requiring SRI hashes
# Format: "key": "url"
# IMPORTANT: URLs must be canonical (not redirect URLs) for reliable SRI verification
CDN_RESOURCES = {
    # Tailwind CSS (JIT - special handling, no SRI for dynamic content)
    # "tailwindcss": "https://cdn.tailwindcss.com",  # Excluded: JIT compiler

    # HTMX - Use canonical /dist/ path, not redirect URL
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
