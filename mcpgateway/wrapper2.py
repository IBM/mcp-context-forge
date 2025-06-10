# -*- coding: utf-8 -*-
"""
MCP Gateway Wrapper server.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan, Mihai Criveti, Madhav Kandukuri

This module implements a wrapper bridge that facilitates
interaction between the MCP client and the MCP gateway.
It provides several functionalities, including listing tools,
invoking tools, managing resources, retrieving prompts,
and handling tool calls via the MCP gateway.

A **stdio** bridge that exposes a remote MCP Gateway
(HTTP-/JSON-RPC APIs) as a local MCP server. All JSON-RPC
traffic is written to **stdout**; every log or trace message
is emitted on **stderr** so that protocol messages and
diagnostics never mix.

Environment variables:
- MCP_SERVER_CATALOG_URLS: Comma-separated list of gateway catalog URLs (required)
- MCP_AUTH_TOKEN: Bearer token for the gateway (optional)
- MCP_TOOL_CALL_TIMEOUT: Seconds to wait for a gateway RPC call (default 90)
- MCP_WRAPPER_LOG_LEVEL: Python log level name or OFF/NONE to disable logging (default INFO)

Example:
    $ export MCP_SERVER_CATALOG_URLS='https://api.example.com/catalog'
    $ export MCP_AUTH_TOKEN='my-secret-token'
    $ python mcpgateway.wrapper
"""

import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import httpx
import mcp.server.stdio
from mcp import types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from pydantic import AnyUrl

from mcpgateway import __version__

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
ENV_SERVER_CATALOGS = "MCP_SERVER_CATALOG_URLS"
ENV_AUTH_TOKEN = "MCP_AUTH_TOKEN"  # nosec B105 – this is an *environment variable name*, not a secret
ENV_TIMEOUT = "MCP_TOOL_CALL_TIMEOUT"
ENV_LOG_LEVEL = "MCP_WRAPPER_LOG_LEVEL"

RAW_CATALOGS: str = os.getenv(ENV_SERVER_CATALOGS, "")
SERVER_CATALOG_URLS: List[str] = [u.strip() for u in RAW_CATALOGS.split(",") if u.strip()]

AUTH_TOKEN: str = os.getenv(ENV_AUTH_TOKEN, "")
TOOL_CALL_TIMEOUT: int = int(os.getenv(ENV_TIMEOUT, "90"))

# Validate required configuration
if not SERVER_CATALOG_URLS:
    print(f"Error: {ENV_SERVER_CATALOGS} environment variable is required", file=sys.stderr)
    sys.exit(1)


# -----------------------------------------------------------------------------
# Base URL Extraction
# -----------------------------------------------------------------------------
def _extract_base_url(url: str) -> str:
    """
    Extract the base URL (scheme and network location) from a full URL.

    Args:
        url (str): The full URL to parse, e.g., "https://example.com/path?query=1".

    Returns:
        str: The base URL, including scheme and netloc, e.g., "https://example.com".

    Raises:
        ValueError: If the URL does not contain a scheme or netloc.

    Example:
        >>> _extract_base_url("https://www.example.com/path/to/resource")
        'https://www.example.com'
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL provided: {url}")
    return f"{parsed.scheme}://{parsed.netloc}"


BASE_URL: str = _extract_base_url(SERVER_CATALOG_URLS[0]) if SERVER_CATALOG_URLS else ""

# -----------------------------------------------------------------------------
# Logging Setup
# -----------------------------------------------------------------------------
_log_level = os.getenv(ENV_LOG_LEVEL, "INFO").upper()
if _log_level in {"OFF", "NONE", "DISABLE", "FALSE", "0"}:
    logging.disable(logging.CRITICAL)
else:
    logging.basicConfig(
        level=getattr(logging, _log_level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
    )

logger = logging.getLogger("mcpgateway.wrapper")
logger.info(f"Starting MCP wrapper: base_url={BASE_URL}, timeout={TOOL_CALL_TIMEOUT}")


# -----------------------------------------------------------------------------
# HTTP Helpers
# -----------------------------------------------------------------------------
async def fetch_url(url: str) -> httpx.Response:
    """
    Perform an asynchronous HTTP GET request and return the response.

    Args:
        url: The target URL to fetch.

    Returns:
        The successful ``httpx.Response`` object.

    Raises:
        httpx.RequestError:    If a network problem occurs while making the request.
        httpx.HTTPStatusError: If the server returns a 4xx or 5xx response.
    """
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"} if AUTH_TOKEN else {}
    async with httpx.AsyncClient(timeout=TOOL_CALL_TIMEOUT) as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response
        except httpx.RequestError as err:
            logger.error(f"Network error while fetching {url}: {err}")
            raise
        except httpx.HTTPStatusError as err:
            logger.error(f"HTTP {err.response.status_code} returned for {url}: {err}")
            raise


# -----------------------------------------------------------------------------
# Metadata Helpers
# -----------------------------------------------------------------------------
async def get_tools_from_mcp_server(catalog_urls: List[str]) -> List[str]:
    """
    Retrieve associated tool IDs from the MCP gateway server catalogs.

    Args:
        catalog_urls (List[str]): List of catalog endpoint URLs.

    Returns:
        List[str]: A list of tool ID strings extracted from the server catalog.

    Raises:
        httpx.RequestError: If a network problem occurs.
        httpx.HTTPStatusError: If the server returns a 4xx or 5xx response.
    """
    server_ids = [url.split("/")[-1] for url in catalog_urls]
    url = f"{BASE_URL}/servers/"
    response = await fetch_url(url)
    catalog = response.json()
    tool_ids: List[str] = []
    for entry in catalog:
        if str(entry.get("id")) in server_ids:
            tool_ids.extend(entry.get("associatedTools", []))
    return tool_ids


async def tools_metadata(tool_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Fetch metadata for a list of MCP tools by their IDs.

    Args:
        tool_ids (List[str]): List of tool ID strings.

    Returns:
        List[Dict[str, Any]]: A list of metadata dictionaries for each tool.

    Raises:
        httpx.RequestError: If a network problem occurs.
        httpx.HTTPStatusError: If the server returns a 4xx or 5xx response.
    """
    if not tool_ids:
        return []
    url = f"{BASE_URL}/tools/"
    response = await fetch_url(url)
    data: List[Dict[str, Any]] = response.json()
    if tool_ids == ["0"]:
        return data

    return [tool for tool in data if tool["id"] in tool_ids]


async def get_prompts_from_mcp_server(catalog_urls: List[str]) -> List[str]:
    """
    Retrieve associated prompt IDs from the MCP gateway server catalogs.

    Args:
        catalog_urls (List[str]): List of catalog endpoint URLs.

    Returns:
        List[str]: A list of prompt ID strings.

    Raises:
        httpx.RequestError: If a network problem occurs.
        httpx.HTTPStatusError: If the server returns a 4xx or 5xx response.
    """
    server_ids = [url.split("/")[-1] for url in catalog_urls]
    url = f"{BASE_URL}/servers/"
    response = await fetch_url(url)
    catalog = response.json()
    prompt_ids: List[str] = []
    for entry in catalog:
        if str(entry.get("id")) in server_ids:
            prompt_ids.extend(entry.get("associatedPrompts", []))
    return prompt_ids


async def prompts_metadata(prompt_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Fetch metadata for a list of MCP prompts by their IDs.

    Args:
        prompt_ids (List[str]): List of prompt ID strings.

    Returns:
        List[Dict[str, Any]]: A list of metadata dictionaries for each prompt.

    Raises:
        httpx.RequestError: If a network problem occurs.
        httpx.HTTPStatusError: If the server returns a 4xx or 5xx response.
    """
    if not prompt_ids:
        return []
    url = f"{BASE_URL}/prompts/"
    response = await fetch_url(url)
    data: List[Dict[str, Any]] = response.json()
    if prompt_ids == ["0"]:
        return data
    return [pr for pr in data if str(pr.get("id")) in prompt_ids]


async def get_resources_from_mcp_server(catalog_urls: List[str]) -> List[str]:
    """
    Retrieve associated resource IDs from the MCP gateway server catalogs.

    Args:
        catalog_urls (List[str]): List of catalog endpoint URLs.

    Returns:
        List[str]: A list of resource ID strings.

    Raises:
        httpx.RequestError: If a network problem occurs.
        httpx.HTTPStatusError: If the server returns a 4xx or 5xx response.
    """
    server_ids = [url.split("/")[-1] for url in catalog_urls]
    url = f"{BASE_URL}/servers/"
    response = await fetch_url(url)
    catalog = response.json()
    resource_ids: List[str] = []
    for entry in catalog:
        if str(entry.get("id")) in server_ids:
            resource_ids.extend(entry.get("associatedResources", []))
    return resource_ids


async def resources_metadata(resource_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Fetch metadata for a list of MCP resources by their IDs.

    Args:
        resource_ids (List[str]): List of resource ID strings.

    Returns:
        List[Dict[str, Any]]: A list of metadata dictionaries for each resource.

    Raises:
        httpx.RequestError: If a network problem occurs.
        httpx.HTTPStatusError: If the server returns a 4xx or 5xx response.
    """
    if not resource_ids:
        return []
    url = f"{BASE_URL}/resources/"
    response = await fetch_url(url)
    data: List[Dict[str, Any]] = response.json()
    if resource_ids == ["0"]:
        return data
    return [res for res in data if str(res.get("id")) in resource_ids]


# -----------------------------------------------------------------------------
# Server Handlers
# -----------------------------------------------------------------------------
server: Server = Server("mcpgateway-wrapper")


@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    """
    List all available MCP tools exposed by the gateway.

    Queries the configured server catalogs to retrieve tool IDs and then
    fetches metadata for each tool to construct a list of Tool objects.

    Returns:
        List[types.Tool]: A list of Tool instances including name, description, and input schema.

    Raises:
        RuntimeError: If an error occurs during fetching or processing.
    """
    try:
        tool_ids = ["0"] if SERVER_CATALOG_URLS[0] == BASE_URL else await get_tools_from_mcp_server(SERVER_CATALOG_URLS)
        metadata = await tools_metadata(tool_ids)
        tools = []
        for tool in metadata:
            tool_name = tool.get("name")
            if tool_name:  # Only include tools with valid names
                tools.append(
                    types.Tool(
                        name=str(tool_name),
                        description=tool.get("description", ""),
                        inputSchema=tool.get("inputSchema", {}),
                    )
                )
        return tools
    except Exception as exc:
        logger.exception("Error listing tools")
        raise RuntimeError(f"Error listing tools: {exc}")


@server.call_tool()
async def handle_call_tool(name: str, arguments: Optional[Dict[str, Any]] = None) -> List[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]:
    """
    Invoke a named MCP tool via the gateway's RPC endpoint.

    Args:
        name (str): The name of the tool to invoke.
        arguments (Optional[Dict[str, Any]]): The arguments to pass to the tool method.

    Returns:
        List[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]:
            A list of content objects returned by the tool.

    Raises:
        ValueError: If tool call fails.
        RuntimeError: If the HTTP request fails or returns an error.
    """
    if arguments is None:
        arguments = {}

    logger.info(f"Calling tool {name} with args {arguments}")
    payload = {"jsonrpc": "2.0", "id": 2, "method": name, "params": arguments}
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"} if AUTH_TOKEN else {}

    try:
        async with httpx.AsyncClient(timeout=TOOL_CALL_TIMEOUT) as client:
            resp = await client.post(f"{BASE_URL}/rpc/", json=payload, headers=headers)
            resp.raise_for_status()
            result = resp.json()

            if "error" in result:
                error_msg = result["error"].get("message", "Unknown error")
                raise ValueError(f"Tool call failed: {error_msg}")

            tool_result = result.get("result", result)
            return [types.TextContent(type="text", text=str(tool_result))]

    except httpx.TimeoutException as exc:
        logger.error(f"Timeout calling tool {name}: {exc}")
        raise RuntimeError(f"Tool call timeout: {exc}")
    except Exception as exc:
        logger.exception(f"Error calling tool {name}")
        raise RuntimeError(f"Error calling tool: {exc}")


@server.list_resources()
async def handle_list_resources() -> List[types.Resource]:
    """
    List all available MCP resources exposed by the gateway.

    Fetches resource IDs from the configured catalogs and retrieves
    metadata to construct Resource instances.

    Returns:
        List[types.Resource]: A list of Resource objects including URI, name, description, and MIME type.

    Raises:
        RuntimeError: If an error occurs during fetching or processing.
    """
    try:
        ids = ["0"] if SERVER_CATALOG_URLS[0] == BASE_URL else await get_resources_from_mcp_server(SERVER_CATALOG_URLS)
        meta = await resources_metadata(ids)
        resources = []
        for r in meta:
            uri = r.get("uri")
            if not uri:
                logger.warning(f"Resource missing URI, skipping: {r}")
                continue
            try:
                resources.append(
                    types.Resource(
                        uri=AnyUrl(uri),
                        name=r.get("name", ""),
                        description=r.get("description", ""),
                        mimeType=r.get("mimeType", "text/plain"),
                    )
                )
            except Exception as e:
                logger.warning(f"Invalid resource URI {uri}: {e}")
                continue
        return resources
    except Exception as exc:
        logger.exception("Error listing resources")
        raise RuntimeError(f"Error listing resources: {exc}")


@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    """
    Read and return the content of a resource by its URI.

    Args:
        uri (AnyUrl): The URI of the resource to read.

    Returns:
        str: The body text of the fetched resource.

    Raises:
        ValueError: If the resource cannot be fetched.
    """
    try:
        response = await fetch_url(str(uri))
        return response.text
    except Exception as exc:
        logger.exception(f"Error reading resource {uri}")
        raise ValueError(f"Failed to read resource at {uri}: {exc}")


@server.list_prompts()
async def handle_list_prompts() -> List[types.Prompt]:
    """
    List all available MCP prompts exposed by the gateway.

    Retrieves prompt IDs from the catalogs and fetches metadata
    to create Prompt instances.

    Returns:
        List[types.Prompt]: A list of Prompt objects including name, description, and arguments.

    Raises:
        RuntimeError: If an error occurs during fetching or processing.
    """
    try:
        ids = ["0"] if SERVER_CATALOG_URLS[0] == BASE_URL else await get_prompts_from_mcp_server(SERVER_CATALOG_URLS)
        meta = await prompts_metadata(ids)
        prompts = []
        for p in meta:
            prompt_name = p.get("name")
            if prompt_name:  # Only include prompts with valid names
                prompts.append(
                    types.Prompt(
                        name=str(prompt_name),
                        description=p.get("description", ""),
                        arguments=p.get("arguments", []),
                    )
                )
        return prompts
    except Exception as exc:
        logger.exception("Error listing prompts")
        raise RuntimeError(f"Error listing prompts: {exc}")


@server.get_prompt()
async def handle_get_prompt(name: str, arguments: Optional[Dict[str, str]] = None) -> types.GetPromptResult:
    """
    Retrieve and format a single prompt template with provided arguments.

    Args:
        name (str): The unique name of the prompt to fetch.
        arguments (Optional[Dict[str, str]]): A mapping of placeholder names to replacement values.

    Returns:
        types.GetPromptResult: Contains description and list of formatted PromptMessage instances.

    Raises:
        ValueError: If fetching or formatting fails.

    Example:
        >>> await handle_get_prompt("greet", {"username": "Alice"})
    """
    try:
        url = f"{BASE_URL}/prompts/{name}"
        response = await fetch_url(url)
        prompt_data = response.json()

        template = prompt_data.get("template", "")
        try:
            formatted = template.format(**(arguments or {}))
        except KeyError as exc:
            raise ValueError(f"Missing placeholder in arguments: {exc}")
        except Exception as exc:
            raise ValueError(f"Error formatting prompt: {exc}")

        return types.GetPromptResult(
            description=prompt_data.get("description", ""),
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=formatted),
                )
            ],
        )
    except ValueError:
        raise
    except Exception as exc:
        logger.exception(f"Error getting prompt {name}")
        raise ValueError(f"Failed to fetch prompt '{name}': {exc}")


async def main() -> None:
    """
    Main entry point to start the MCP stdio server.

    Initializes the server over standard IO, registers capabilities,
    and begins listening for JSON-RPC messages.

    This function should only be called in a script context.

    Raises:
        RuntimeError: If the server fails to start.

    Example:
        if __name__ == "__main__":
            asyncio.run(main())
    """
    try:
        async with mcp.server.stdio.stdio_server() as (reader, writer):
            await server.run(
                reader,
                writer,
                InitializationOptions(
                    server_name="mcpgateway-wrapper",
                    server_version=__version__,
                    capabilities=server.get_capabilities(notification_options=NotificationOptions(), experimental_capabilities={}),
                ),
            )
    except Exception as exc:
        logger.exception("Server failed to start")
        raise RuntimeError(f"Server startup failed: {exc}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception:
        logger.exception("Server failed")
        sys.exit(1)
    finally:
        logger.info("Wrapper shutdown complete")
