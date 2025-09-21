# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/python_sandbox_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Python Sandbox MCP Server (FastMCP).
"""

import pytest


@pytest.mark.asyncio
async def test_execute_code_simple():
    """Test executing simple Python code."""
    from python_sandbox_server.server_fastmcp import execute_code

    result = await execute_code(code="print('Hello')")

    assert result["success"] is True
    assert "Hello" in result.get("stdout", "")


@pytest.mark.asyncio
async def test_execute_code_with_result():
    """Test executing code that returns a result."""
    from python_sandbox_server.server_fastmcp import execute_code

    result = await execute_code(code="2 + 2")

    assert result["success"] is True
    assert result["result"] == 4


@pytest.mark.asyncio
async def test_execute_code_with_error():
    """Test executing code that causes an error."""
    from python_sandbox_server.server_fastmcp import execute_code

    result = await execute_code(code="1 / 0")

    assert result["success"] is False
    assert "ZeroDivisionError" in result.get("error", "")


@pytest.mark.asyncio
async def test_restricted_code():
    """Test that restricted operations are blocked."""
    from python_sandbox_server.server_fastmcp import execute_code

    # Try to import os (should be restricted)
    result = await execute_code(code="import os")

    assert result["success"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_validate_code():
    """Test code validation."""
    from python_sandbox_server.server_fastmcp import validate_code

    # Valid code
    result = await validate_code(code="x = 1 + 1")
    assert result["valid"] is True

    # Invalid syntax
    result = await validate_code(code="x = = 1")
    assert result["valid"] is False


@pytest.mark.asyncio
async def test_get_capabilities():
    """Test getting sandbox capabilities."""
    from python_sandbox_server.server_fastmcp import get_capabilities

    result = await get_capabilities()

    assert "allowed_builtins" in result
    assert "print" in result["allowed_builtins"]
    assert "len" in result["allowed_builtins"]
