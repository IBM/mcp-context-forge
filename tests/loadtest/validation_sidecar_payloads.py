# -*- coding: utf-8 -*-
"""Shared payload builders for the focused validation sidecar loadtest."""

# Standard
from __future__ import annotations

from typing import Any
import uuid


def _large_capabilities_blob() -> dict[str, Any]:
    """Build a nested but protocol-valid capabilities structure."""
    features = [f"feature-{index:03d}" for index in range(180)]
    return {
        "tools": {
            "listChanged": True,
            "metadata": {
                "groups": [
                    {
                        "name": f"group-{bucket}",
                        "features": features[bucket * 18 : (bucket + 1) * 18],
                        "notes": "validation-load" * 12,
                    }
                    for bucket in range(10)
                ]
            },
        },
        "resources": {
            "subscribe": True,
            "listChanged": True,
            "templates": [{"name": f"template-{index}", "description": "resource-template" * 8} for index in range(24)],
        },
        "prompts": {
            "listChanged": True,
            "catalog": [{"name": f"prompt-{index}", "description": "prompt-catalog" * 8} for index in range(24)],
        },
    }


def build_safe_initialize_payload() -> dict[str, Any]:
    """Return a large but accepted `/protocol/initialize` request body."""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": _large_capabilities_blob(),
        "clientInfo": {
            "name": f"validation-loadtest-{uuid.uuid4().hex}",
            "version": "1.0.0",
            "description": "safe-client-description-" * 64,
        },
    }


def build_rejected_initialize_payload() -> dict[str, Any]:
    """Return a large `/protocol/initialize` request body that should fail validation."""
    payload = build_safe_initialize_payload()
    payload["clientInfo"]["name"] = "<script>alert(1)</script>"
    return payload
