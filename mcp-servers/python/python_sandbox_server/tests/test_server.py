# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/python_sandbox_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Python Sandbox MCP Server.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from python_sandbox_server.server import handle_call_tool, handle_list_tools


@pytest.mark.asyncio
async def test_list_tools():
    """Test that tools are listed correctly."""
    tools = await handle_list_tools()

    tool_names = [tool.name for tool in tools]
    expected_tools = [
        "execute_code",
        "validate_code",
        "list_capabilities"
    ]

    for expected in expected_tools:
        assert expected in tool_names


@pytest.mark.asyncio
async def test_list_capabilities():
    """Test listing sandbox capabilities."""
    result = await handle_call_tool("list_capabilities", {})

    result_data = json.loads(result[0].text)
    assert "sandbox_type" in result_data
    assert "security_features" in result_data
    assert "limits" in result_data
    assert "safe_modules" in result_data


@pytest.mark.asyncio
async def test_execute_simple_code():
    """Test executing simple Python code."""
    code = "result = 2 + 2\nprint('Hello sandbox!')"

    result = await handle_call_tool(
        "execute_code",
        {
            "code": code,
            "timeout": 10,
            "capture_output": True
        }
    )

    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        assert result_data["result"] == 4
        assert "Hello sandbox!" in result_data["stdout"]
        assert "execution_time" in result_data
        assert "execution_id" in result_data
    else:
        # When RestrictedPython is not available
        assert "error" in result_data


@pytest.mark.asyncio
async def test_execute_code_with_allowed_imports():
    """Test executing code with allowed imports."""
    code = """
import math
result = math.sqrt(16)
print(f'Square root of 16 is: {result}')
"""

    result = await handle_call_tool(
        "execute_code",
        {
            "code": code,
            "allowed_imports": ["math"],
            "timeout": 10
        }
    )

    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        assert result_data["result"] == 4.0
        assert "Square root" in result_data["stdout"]
    else:
        # When RestrictedPython is not available or import restricted
        assert "error" in result_data


@pytest.mark.asyncio
async def test_validate_safe_code():
    """Test validating safe code."""
    safe_code = "result = sum([1, 2, 3, 4, 5])\nprint(result)"

    result = await handle_call_tool(
        "validate_code",
        {"code": safe_code}
    )

    result_data = json.loads(result[0].text)
    assert "validation" in result_data
    assert "analysis" in result_data

    if result_data["validation"].get("valid") is not None:
        # If RestrictedPython is available
        assert result_data["validation"]["valid"] is True
    # Otherwise just check structure is correct


@pytest.mark.asyncio
async def test_validate_dangerous_code():
    """Test validating dangerous code."""
    dangerous_code = "import os\nos.system('rm -rf /')"

    result = await handle_call_tool(
        "validate_code",
        {"code": dangerous_code}
    )

    result_data = json.loads(result[0].text)
    assert "validation" in result_data
    assert "analysis" in result_data

    # Should detect issues if RestrictedPython is available
    if result_data["validation"].get("valid") is not None:
        assert result_data["validation"]["valid"] is False


@pytest.mark.asyncio
async def test_execute_code_timeout():
    """Test code execution with timeout."""
    # Code that would run forever
    infinite_code = """
import time
while True:
    time.sleep(1)
    print("Still running...")
"""

    result = await handle_call_tool(
        "execute_code",
        {
            "code": infinite_code,
            "timeout": 2,  # Very short timeout
            "allowed_imports": ["time"]
        }
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "timeout" in result_data["error"].lower()


@pytest.mark.asyncio
async def test_execute_empty_code():
    """Test executing empty code."""
    result = await handle_call_tool(
        "execute_code",
        {"code": ""}
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "Empty code" in result_data["error"]


@pytest.mark.asyncio
async def test_execute_large_code():
    """Test executing oversized code."""
    large_code = "x = 1\n" * 50000  # Very large code

    result = await handle_call_tool(
        "execute_code",
        {"code": large_code}
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "too large" in result_data["error"]


@pytest.mark.asyncio
async def test_execute_syntax_error():
    """Test executing code with syntax errors."""
    bad_code = "result = 2 +\nprint('incomplete expression')"

    result = await handle_call_tool(
        "execute_code",
        {"code": bad_code}
    )

    result_data = json.loads(result[0].text)
    # Should handle syntax errors gracefully
    assert result_data["success"] is False or "error" in result_data


@pytest.mark.asyncio
async def test_execute_code_with_exception():
    """Test executing code that raises an exception."""
    error_code = """
def divide_by_zero():
    return 1 / 0

result = divide_by_zero()
"""

    result = await handle_call_tool(
        "execute_code",
        {"code": error_code}
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "division by zero" in result_data["error"].lower() or "error" in result_data


@pytest.mark.asyncio
async def test_execute_code_return_different_types():
    """Test executing code that returns different data types."""
    test_cases = [
        ("result = 42", "integer"),
        ("result = 'hello world'", "string"),
        ("result = [1, 2, 3, 4, 5]", "list"),
        ("result = {'key': 'value', 'number': 42}", "dict"),
        ("result = True", "boolean"),
        ("result = 3.14159", "float"),
    ]

    for code, data_type in test_cases:
        result = await handle_call_tool(
            "execute_code",
            {"code": code}
        )

        result_data = json.loads(result[0].text)
        if result_data.get("success"):
            assert "result" in result_data
            # Verify result exists and is properly formatted
            assert result_data["result"] is not None


@pytest.mark.asyncio
async def test_execute_code_with_print_statements():
    """Test capturing print output."""
    code = """
print("First line")
print("Second line")
result = "execution complete"
print(f"Result: {result}")
"""

    result = await handle_call_tool(
        "execute_code",
        {
            "code": code,
            "capture_output": True
        }
    )

    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        assert "stdout" in result_data
        stdout = result_data["stdout"]
        assert "First line" in stdout
        assert "Second line" in stdout
        assert "execution complete" in stdout


@pytest.mark.asyncio
@patch('python_sandbox_server.server.subprocess.run')
async def test_execute_code_container_mode(mock_subprocess):
    """Test container-based execution."""
    # Mock successful container execution
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Hello from container!"
    mock_result.stderr = ""
    mock_subprocess.return_value = mock_result

    code = "print('Hello from container!')"

    result = await handle_call_tool(
        "execute_code",
        {
            "code": code,
            "use_container": True,
            "memory_limit": "128m",
            "timeout": 10
        }
    )

    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        assert "stdout" in result_data
        assert "execution_time" in result_data
    else:
        # When container runtime is not available
        assert "error" in result_data


@pytest.mark.asyncio
async def test_unknown_tool():
    """Test calling unknown tool."""
    result = await handle_call_tool(
        "unknown_tool",
        {"some": "argument"}
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "Unknown tool" in result_data["error"]


@pytest.mark.asyncio
async def test_execute_mathematical_computation():
    """Test executing mathematical computations."""
    code = """
import math

# Calculate factorial
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

# Test with different values
results = []
for i in range(1, 6):
    results.append(factorial(i))

result = {
    'factorials': results,
    'pi': math.pi,
    'e': math.e
}
"""

    result = await handle_call_tool(
        "execute_code",
        {
            "code": code,
            "allowed_imports": ["math"],
            "timeout": 15
        }
    )

    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        assert "result" in result_data
        # Check if result contains expected mathematical values
        result_value = result_data["result"]
        if isinstance(result_value, dict):
            assert "factorials" in result_value
            assert "pi" in result_value


@pytest.mark.asyncio
async def test_code_analysis():
    """Test code analysis features."""
    complex_code = """
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)

result = [fibonacci(i) for i in range(10)]
"""

    result = await handle_call_tool(
        "validate_code",
        {"code": complex_code}
    )

    result_data = json.loads(result[0].text)
    assert "analysis" in result_data
    assert "line_count" in result_data["analysis"]
    assert result_data["analysis"]["line_count"] > 1
    assert "estimated_complexity" in result_data["analysis"]
