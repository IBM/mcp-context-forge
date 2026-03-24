#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/output_schema_test_server/src/output_schema_test_server/server_fastmcp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Output Schema Test Server

MCP server for testing the outputSchema field support in tools.
Implements tools with explicit output schemas to verify the complete workflow.
"""

# Standard
import argparse
import logging
import sys
from typing import Any

# Third-Party
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# Configure logging to stderr to avoid MCP protocol interference
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# Create FastMCP server instance
mcp = FastMCP(name="output-schema-test-server", version="0.1.0")


# Pydantic models for structured outputs
class CalculationResult(BaseModel):
    """Result of a mathematical calculation."""

    result: float = Field(..., description="The calculated result")
    operation: str = Field(..., description="The operation performed")
    operands: list[float] = Field(..., description="The operands used")
    success: bool = Field(True, description="Whether the calculation succeeded")


class UserInfo(BaseModel):
    """User information structure."""

    name: str = Field(..., description="User's full name")
    email: str = Field(..., description="User's email address")
    age: int = Field(..., ge=0, le=150, description="User's age")
    roles: list[str] = Field(default_factory=list, description="User's roles")


class ValidationResult(BaseModel):
    """Result of input validation."""

    valid: bool = Field(..., description="Whether the input is valid")
    errors: list[str] = Field(default_factory=list, description="Validation errors if any")
    cleaned_value: str = Field(..., description="Cleaned/normalized value")


# Tools with output schemas
@mcp.tool(description="Add two numbers and return a structured result with output schema")
async def add_numbers(
    a: float = Field(..., description="First number"),
    b: float = Field(..., description="Second number"),
) -> CalculationResult:
    """Add two numbers and return a structured result.

    This tool demonstrates outputSchema support by returning a typed Pydantic model.
    The MCP framework should automatically generate the output schema.
    """
    logger.info(f"Adding {a} + {b}")
    return CalculationResult(result=a + b, operation="addition", operands=[a, b], success=True)


@mcp.tool(description="Multiply two numbers with structured output")
async def multiply_numbers(
    a: float = Field(..., description="First number"),
    b: float = Field(..., description="Second number"),
) -> CalculationResult:
    """Multiply two numbers and return a structured result."""
    logger.info(f"Multiplying {a} * {b}")
    return CalculationResult(result=a * b, operation="multiplication", operands=[a, b], success=True)


@mcp.tool(description="Divide two numbers with error handling in output")
async def divide_numbers(a: float = Field(..., description="Numerator"), b: float = Field(..., description="Denominator")) -> CalculationResult:
    """Divide two numbers with error handling."""
    logger.info(f"Dividing {a} / {b}")

    if b == 0:
        # Return structured error
        return CalculationResult(result=0.0, operation="division", operands=[a, b], success=False)

    return CalculationResult(result=a / b, operation="division", operands=[a, b], success=True)


@mcp.tool(description="Create a user profile with structured validation")
async def create_user(
    name: str = Field(..., min_length=1, max_length=100, description="User's full name"),
    email: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
        description="Valid email address",
    ),
    age: int = Field(..., ge=0, le=150, description="User's age"),
    roles: list[str] = Field(default_factory=list, description="User's roles"),
) -> UserInfo:
    """Create a user profile with validation.

    This tool demonstrates complex output schemas with nested fields and validation.
    """
    logger.info(f"Creating user: {name}")
    return UserInfo(name=name, email=email, age=age, roles=roles if roles else ["user"])


@mcp.tool(description="Validate email address format")
async def validate_email(
    email: str = Field(..., description="Email address to validate"),
) -> ValidationResult:
    """Validate an email address and return structured validation result."""
    # Standard
    import re

    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    errors = []

    if not email:
        errors.append("Email cannot be empty")
    elif not re.match(email_pattern, email):
        errors.append("Invalid email format")

    if "@" not in email:
        errors.append("Email must contain @ symbol")

    cleaned = email.strip().lower()

    return ValidationResult(valid=len(errors) == 0, errors=errors, cleaned_value=cleaned)


@mcp.tool(description="Perform calculation with multiple operations (testing complex output)")
async def calculate_stats(
    numbers: list[float] = Field(..., min_length=1, description="List of numbers to analyze"),
) -> dict[str, Any]:
    """Calculate statistics from a list of numbers.

    Returns a dictionary with statistical measures.
    This tests dict-based output schemas.
    """
    if not numbers:
        return {"error": "Empty list provided", "success": False}

    result = {
        "count": len(numbers),
        "sum": sum(numbers),
        "mean": sum(numbers) / len(numbers),
        "min": min(numbers),
        "max": max(numbers),
        "range": max(numbers) - min(numbers),
        "success": True,
    }

    # Calculate median
    sorted_numbers = sorted(numbers)
    n = len(sorted_numbers)
    if n % 2 == 0:
        result["median"] = (sorted_numbers[n // 2 - 1] + sorted_numbers[n // 2]) / 2
    else:
        result["median"] = sorted_numbers[n // 2]

    return result


@mcp.tool(description="Echo a list of strings (testing list input/output schema)")
async def echo_list(
    items: list[str] = Field(..., description="List of strings to echo back"),
) -> list[str]:
    """Echo back a list of strings.

    This tool demonstrates list-based input and output schema support.
    Accepts a list of strings and returns the same list.
    """
    logger.info(f"Echoing list with {len(items)} items")
    return items


@mcp.tool(description="Echo a dictionary of strings (testing dict input/output schema)")
async def echo_dict(
    data: dict[str, str] = Field(..., description="Dictionary with string keys and values to echo back"),
) -> dict[str, str]:
    """Echo back a dictionary of strings.

    This tool demonstrates dictionary-based input and output schema support.
    Accepts a dict with string keys and values, returns the same dict.
    """
    logger.info(f"Echoing dict with {len(data)} keys")
    return data


@mcp.tool(description="Simple echo tool without output schema (for comparison)")
async def echo(message: str = Field(..., description="Message to echo back")) -> str:
    """Echo a message back - simple string return without schema."""
    logger.info(f"Echoing: {message}")
    return f"Echo: {message}"


@mcp.tool(description="Inspectable echo tool")
async def echo_back(message: str) -> str:
    """Echo a message back as-is for inspection."""
    return f"{message}"


class NestedData(BaseModel):
    """Example of nested data with lists and dictionaries."""

    message: str = Field(..., description="A simple string message")
    num: str = Field(..., description="A large number as string")
    nested_list: list[Any] = Field(..., description="A nested list, can contain strings or lists")
    nested_dict: dict[str, Any] = Field(..., description="A nested dictionary, can contain strings, lists, or dicts")


@mcp.tool(description="Echo nested list and dictionary structure")
async def echo_nested(data: NestedData) -> NestedData:
    """
    Accepts a nested structure and returns it as-is.
    Demonstrates nested list and dict support in MCP output schema.
    """
    return data


@mcp.tool(description="Get server information and capabilities")
async def get_server_info() -> dict[str, Any]:
    """Get information about this MCP server and its output schema capabilities."""
    return {
        "server_name": "output-schema-test-server",
        "version": "0.1.0",
        "supports_output_schema": True,
        "tools_with_schemas": [
            "add_numbers",
            "multiply_numbers",
            "divide_numbers",
            "create_user",
            "validate_email",
            "calculate_stats",
            "echo_list",
            "echo_dict",
        ],
        "tools_without_schemas": ["echo", "echo_back"],
        "description": "Test server demonstrating MCP outputSchema field support",
        "schema_types": {
            "pydantic_models": ["CalculationResult", "UserInfo", "ValidationResult"],
            "dict_returns": ["calculate_stats", "get_server_info", "echo_dict"],
            "list_returns": ["echo_list"],
            "simple_returns": ["echo", "echo_back"],
        },
    }


def main() -> None:
    """Main server entry point with transport selection."""
    parser = argparse.ArgumentParser(description="Output Schema Test MCP Server - Tests outputSchema field support")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (stdio or http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host (only for http transport)")
    parser.add_argument("--port", type=int, default=9100, help="HTTP port (only for http transport)")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info(f"Starting Output Schema Test Server on HTTP at {args.host}:{args.port}")
        logger.info(f"HTTP endpoint: http://{args.host}:{args.port}/mcp/")
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting Output Schema Test Server on stdio")
        mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
