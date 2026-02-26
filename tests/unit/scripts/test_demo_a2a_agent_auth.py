# Copyright (c) 2025 ContextForge Contributors. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for host header validation in demo_a2a_agent_auth.py.

The demo script cannot be imported directly due to side effects,
so we test the host header validation regex logic in isolation.
"""

import re

import pytest

# Exact regex used in scripts/demo_a2a_agent_auth.py get_agent_card()
HOST_HEADER_PATTERN = re.compile(r"^[a-zA-Z0-9._\-:\[\]]+$")


def _sanitize_host(raw: str) -> str:
    """Mirror the host validation logic from get_agent_card()."""
    if not HOST_HEADER_PATTERN.match(raw):
        return "localhost"
    return raw


@pytest.mark.parametrize(
    "raw_host,expected",
    [
        ("localhost", "localhost"),
        ("example.com", "example.com"),
        ("example.com:8080", "example.com:8080"),
        ("192.168.1.1", "192.168.1.1"),
        ("192.168.1.1:443", "192.168.1.1:443"),
        ("[::1]", "[::1]"),
        ("my-host.internal", "my-host.internal"),
        ("sub.domain.example.com", "sub.domain.example.com"),
    ],
)
def test_valid_host_headers_pass(raw_host, expected):
    """Valid host headers are returned as-is."""
    assert _sanitize_host(raw_host) == expected


@pytest.mark.parametrize(
    "raw_host",
    [
        'evil.com"><script>alert(1)</script>',
        "evil.com/path",
        "evil.com?q=1",
        "host with spaces",
        "host\nnewline",
        "host\rcarriage",
        "",
    ],
)
def test_malicious_host_headers_rejected(raw_host):
    """Malicious or malformed host headers fall back to localhost."""
    assert _sanitize_host(raw_host) == "localhost"
