# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/toolops/testing/mcp-server-setup/example_mcp_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Jay Bandlamudi

MCP Gateway - Script to set up test MCP server with tools

This module creates test MCP server for toolops testing purpose.
"""
import json
from typing import Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI()

# Define token-to-role mapping
TOKEN_ROLES = {"super-secret-123": "admin", "developer-token-456": "developer", "readonly-token-789": "viewer"}


# Define role-based tool access
ROLE_TOOLS = {"admin": ["add_numbers", "reverse_string", "multiply_numbers", "concat_strings"], "developer": ["add_numbers", "reverse_string"], "viewer": ["reverse_string"]}


# Enhanced authentication that returns the role
def verify_bearer_token(authorization: Optional[str] = Header(None)) -> str:
    """
    Verify bearer token and return the associated role

    Args:
        authorization: Authorization header

    Returns:
        str: Authorization role

    Raises:
        HTTPException: If there's an error parsing or executing the JSONPath expressions.

    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    token = authorization.replace("Bearer ", "")

    # Check if token exists and get role
    role = TOKEN_ROLES.get(token)
    if not role:
        raise HTTPException(status_code=401, detail="Invalid bearer token")

    return role


# Tool implementations
def add_numbers(a: float, b: float) -> float:
    """
    Add two numbers together

    Args:
        a: float number
        b: float number

    Returns:
        sum of two numbers
    """
    return a + b


def multiply_numbers(a: float, b: float) -> float:
    """
    Multiply two numbers together

    Args:
        a: float number
        b: float number

    Returns:
        product of two numbers
    """
    return a * b


def reverse_string(text: str) -> str:
    """
    Reverse a string

    Args:
        text: input string

    Returns:
        Reversed input text

    """
    return text[::-1]


def concat_strings(str1: str, str2: str) -> str:
    """
    Concatenate two strings

    Args:
        str1: first string
        str2: second string

    Returns:
        concatenated string

    """
    return str1 + str2


# Define all available tools with their schemas
ALL_TOOLS = {
    "add_numbers": {
        "name": "add_numbers",
        "description": "Add two numbers together",
        "inputSchema": {"type": "object", "properties": {"a": {"type": "number", "description": "First number"}, "b": {"type": "number", "description": "Second number"}}, "required": ["a", "b"]},
    },
    "multiply_numbers": {
        "name": "multiply_numbers",
        "description": "Multiply two numbers together",
        "inputSchema": {"type": "object", "properties": {"a": {"type": "number", "description": "First number"}, "b": {"type": "number", "description": "Second number"}}, "required": ["a", "b"]},
    },
    "reverse_string": {
        "name": "reverse_string",
        "description": "Reverse a string",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string", "description": "Text to reverse"}}, "required": ["text"]},
    },
    "concat_strings": {
        "name": "concat_strings",
        "description": "Concatenate two strings",
        "inputSchema": {
            "type": "object",
            "properties": {"str1": {"type": "string", "description": "First string"}, "str2": {"type": "string", "description": "Second string"}},
            "required": ["str1", "str2"],
        },
    },
}


# Tool execution mapping
TOOL_FUNCTIONS = {"add_numbers": add_numbers, "multiply_numbers": multiply_numbers, "reverse_string": reverse_string, "concat_strings": concat_strings}


def get_tools_for_role(role: str) -> List[Dict]:
    """
    Get available tools based on user role

    Args:
        role: Authorisation role

    Returns:
        List of tools based on role

    """
    allowed_tools = ROLE_TOOLS.get(role, [])
    return [ALL_TOOLS[tool_name] for tool_name in allowed_tools if tool_name in ALL_TOOLS]


def can_access_tool(role: str, tool_name: str) -> bool:
    """
    Check if role has access to specific tool

    Args:
        role: Authorization role
        tool_name: tool name

    Returns:
        Boolean if tool is accesible for the role

    """
    return tool_name in ROLE_TOOLS.get(role, [])


@app.post("/mcp")
async def mcp_handler(request: Request, authorization: Optional[str] = Header(None)):
    """
    MCP server handler

    Args:
        request: incoming request
        authorization: Authorization header

    Returns:
        Json response for the MCP server configuration

    Raises:
        HTTPException: If the request body contains invalid JSON, a 400 Bad Request error is raised.
        ValueError: unknown tool or tool not found

    """
    print("authorization", authorization)
    # Verify authentication and get role
    role = verify_bearer_token(authorization)

    # Read and parse request
    body_bytes = await request.body()
    print(f"🔹 Incoming request from role: {role}")
    print("🔹 Raw request body:", body_bytes.decode("utf-8"))

    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    method = payload.get("method")
    params = payload.get("params", {})
    request_id = payload.get("id")

    # Handle initialize request
    if method == "initialize":
        response = {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "example-server", "version": "1.0.0"}}}
        return JSONResponse(response, headers={"Mcp-Session-Id": f"session-{role}-{request_id}"})

    # Handle tools/list request - return tools based on role
    if method == "tools/list":
        tools = get_tools_for_role(role)
        print(f"🔹 Returning {len(tools)} tools for role '{role}'")

        response = {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}
        return JSONResponse(response)

    # Handle tools/call request - validate access before execution
    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})

        # Check if role has access to this tool
        if not can_access_tool(role, tool_name):
            error_response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": f"Access denied: Role '{role}' cannot access tool '{tool_name}'"}}
            print(f"❌ Access denied: {role} tried to access {tool_name}")
            return JSONResponse(error_response, status_code=403)

        try:
            # Execute the tool
            tool_func = TOOL_FUNCTIONS.get(tool_name)
            if not tool_func:
                raise ValueError(f"Unknown tool: {tool_name}")

            result = tool_func(**tool_args)

            tool_result = {"content": [{"type": "text", "text": f"Result: {result}"}]}

            response = {"jsonrpc": "2.0", "id": request_id, "result": tool_result}
            print(f"✅ Successfully executed {tool_name} for role {role}")
            return JSONResponse(response)

        except Exception as e:
            error_response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(e)}}
            return JSONResponse(error_response, status_code=400)

    # Unknown method
    if method not in ["tools/list", "tools/call", "initialize"]:
        error_response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        print("Unknown method requested:", method)
        # return JSONResponse(error_response, status_code=400)


@app.get("/mcp")
async def mcp_sse_handler(authorization: Optional[str] = Header(None)):
    """
    MCP server sse handler

    Args:
        authorization: Authorization header

    Raises:
        HTTPException: If there's an error parsing or executing the JSONPath expressions.

    """
    verify_bearer_token(authorization)
    raise HTTPException(status_code=405, detail="Method not allowed")


@app.get("/health")
async def health_check():
    """
    Health check of API

    Returns:
        Status of health check

    """
    return {"status": "healthy"}


if __name__ == "__main__":
    print("#" * 50)
    print("-" * 50)
    print("Started MCP server with example tools use /mcp , stremable_http for the MCP server")
    print("Tools - ", list(ALL_TOOLS.keys()))
    print("Tools use bearer auth for authorisation and admin bearer token is : ", list(TOKEN_ROLES.keys())[0])
    print("Example auth header : {'Authorization': 'Bearer super-secret-123'}")
    print("NOTE - After the MCP server is started you need to configure/add server in MCP-CF UI")
    print("-" * 50)
    print("#" * 50)
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=9009)
