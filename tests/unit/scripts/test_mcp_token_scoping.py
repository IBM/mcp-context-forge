# -*- coding: utf-8 -*-
"""Location: ./tests/unit/scripts/test_mcp_token_scoping.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for the MCP token-scoping smoke script.
"""

import importlib.util
from pathlib import Path

import aiohttp
import jwt
import pytest


_SCRIPT = Path(__file__).parents[3] / "scripts" / "test_mcp_token_scoping.py"
_SPEC = importlib.util.spec_from_file_location("test_mcp_token_scoping_script", _SCRIPT)
assert _SPEC and _SPEC.loader
_SCRIPT_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCRIPT_MODULE)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.request_url = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get(self, url, **_kwargs):
        self.request_url = url
        return _Response(self.payload)


@pytest.mark.asyncio
async def test_discover_tool_counts_reads_rest_visibility(monkeypatch):
    session = _Session(
        [
            {"name": "public-tool", "visibility": "public"},
            {"name": "team-tool", "visibility": "team"},
            {"name": "team-tool-2", "visibility": "team"},
        ]
    )
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: session)

    counts = await _SCRIPT_MODULE.discover_tool_counts("http://gateway", "token")

    assert counts == (1, 2)
    assert session.request_url == "http://gateway/tools?limit=0"


def test_generate_token_includes_jti():
    token = _SCRIPT_MODULE.generate_token("admin@example.com", is_admin=True, secret="test-secret-that-is-long-enough-32")

    payload = jwt.decode(token, options={"verify_signature": False})

    assert payload["jti"]
