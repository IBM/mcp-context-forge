# -*- coding: utf-8 -*-
"""MCP Gateway Wrapper server.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan, Mihai Criveti, Madhav Kandukuri

This module implements a wrapper bridge that facilitates 
interaction between the MCP client and the MCP gateway. 
It provides several functionalities, including listing tools, invoking tools, managing resources , 
retrieving prompts, and handling tool calls via the MCP gateway.
"""

import asyncio
import os
from typing import List, Dict, Any, Optional, Union
from urllib.parse import urlparse


import httpx
from pydantic import AnyUrl

from mcp import types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
import mcp.server.stdio


def extract_base_url(url: str) -> str:
    """
    Extracts the base URL (scheme + netloc) from a given URL string.

    Args:
        url (str): The full URL string to be parsed.

    Returns:
        str: The base URL, including the scheme (http, https) and the netloc (domain).

    Example:
        >>> extract_base_url("https://www.example.com/path/to/resource")
        'https://www.example.com'
    """
    parsed_url = urlparse(url)
    return f"{parsed_url.scheme}://{parsed_url.netloc}"


# Default Values

mcp_servers_raw = os.getenv("MCP_SERVER_CATALOG_URLS", "")
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")

mcp_servers_urls = mcp_servers_raw.split(",") if "," in mcp_servers_raw else [mcp_servers_raw]
BASE_URL = extract_base_url(mcp_servers_urls[0])
TOOL_CALL_TIMEOUT = 90


async def fetch_url(url: str) -> httpx.Response:
    """Fetch a URL asynchronously.

    Args:
        url (str): The URL to fetch.

    Returns:
        httpx.Response: The HTTP response.
    """
    headers = {"Authorization": f"Bearer {MCP_AUTH_TOKEN}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response


async def get_tools_from_mcp_server(catalog_urls: List[str]) -> List[str]:
    """Fetch associated tool IDs for the given server catalog URLs.

    Args:
        catalog_urls (List[str]): List of catalog URLs.

    Returns:
        List[str]: A list of tool IDs.
    """

    server_ids = [server.split("/")[-1] for server in catalog_urls]
    url = f"{BASE_URL}/servers/"
    response = await fetch_url(url)
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch server catalog: {response.status_code}")
    server_catalog = response.json()
    tool_ids = [tool for server in server_catalog if str(server["id"]) in server_ids for tool in server["associatedTools"]]
    return tool_ids


async def tools_metadata(tool_ids: List[str]) -> List[Dict[str, Any]]:
    """Fetch metadata for tools based on the given tool IDs.

    Args:
        tool_ids (List[str]): List of tool IDs.

    Returns:
        List[Dict[str, Any]]: A list of tool metadata.
    """
    if not tool_ids:
        return []
    url = f"{BASE_URL}/tools/"
    response = await fetch_url(url)
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch tools metadata: {response.status_code}")
    all_tools = response.json()
    if tool_ids == [0]:
        return all_tools
    tools = [tool for tool in all_tools if tool["id"] in tool_ids]
    return tools


async def get_prompts_from_mcp_server(catalog_urls: List[str]) -> List[str]:
    """Fetch associated prompt IDs for the given server catalog URLs.

    Args:
        catalog_urls (List[str]): List of catalog URLs.

    Returns:
        List[str]: A list of prompt IDs.
    """
    server_ids = [server.split("/")[-1] for server in catalog_urls]
    url = f"{BASE_URL}/servers/"
    response = await fetch_url(url)
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch server catalog: {response.status_code}")
    server_catalog = response.json()
    prompt_ids = [prompt for server in server_catalog if str(server["id"]) in server_ids for prompt in server.get("associatedPrompts", [])]
    return prompt_ids


async def prompts_metadata(prompt_ids: List[str]) -> List[Dict[str, Any]]:
    """Fetch metadata for prompts based on the given prompt IDs.

    Args:
        prompt_ids (List[str]): List of prompt IDs.

    Returns:
        List[Dict[str, Any]]: A list of prompt metadata.
    """
    if not prompt_ids:
        return []
    url = f"{BASE_URL}/prompts/"
    response = await fetch_url(url)
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch prompts metadata: {response.status_code}")
    all_prompts = response.json()
    if prompt_ids == [0]:
        return all_prompts
    prompts = [prompt for prompt in all_prompts if prompt["id"] in prompt_ids]
    return prompts


async def get_resources_from_mcp_server(catalog_urls: List[str]) -> List[str]:
    """Fetch associated resource IDs for the given server catalog URLs.

    Args:
        catalog_urls (List[str]): List of catalog URLs.

    Returns:
        List[str]: A list of resource IDs.
    """
    server_ids = [server.split("/")[-1] for server in catalog_urls]
    url = f"{BASE_URL}/servers/"
    response = await fetch_url(url)
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch server catalog: {response.status_code}")
    server_catalog = response.json()
    resource_ids = [resource for server in server_catalog if str(server["id"]) in server_ids for resource in server.get("associatedResources", [])]
    return resource_ids


async def resources_metadata(resource_ids: List[str]) -> List[Dict[str, Any]]:
    """Fetch metadata for resources based on the given resource IDs.

    Args:
        resource_ids (List[str]): List of resource IDs.

    Returns:
        List[Dict[str, Any]]: A list of resource metadata.
    """
    if not resource_ids:
        return []
    url = f"{BASE_URL}/resources/"
    response = await fetch_url(url)
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch resources metadata: {response.status_code}")
    all_resources = response.json()
    if resource_ids == [0]:
        return all_resources
    resources = [resource for resource in all_resources if resource["id"] in resource_ids]
    return resources


server = Server("mcpgateway-wrapper")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools from the MCP server.

    Returns:
        list[types.Tool]: List of available tools.
    """
    try:
        mcp_tools = []
        if BASE_URL == mcp_servers_urls[0]:
            tool_ids = [0]
        else:
            tool_ids = await get_tools_from_mcp_server(mcp_servers_urls)
        tools = await tools_metadata(tool_ids)
        for tool in tools:
            mcp_tools.append(
                types.Tool(
                    name=tool["name"],
                    description=tool["description"],
                    inputSchema=tool["inputSchema"],
                )
            )
        return mcp_tools
    except Exception as e:
        raise RuntimeError(f"Error listing tools: {e}")


@server.call_tool()
async def handle_call_tool(name: str, arguments: Optional[dict] = None) -> list[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]:
    """Handle tool execution requests.

    Args:
        name (str): Name of the tool.
        arguments (dict | None): Arguments for the tool.

    Returns:
        list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
            List of content responses from the tool.
    """
    if not arguments:
        raise ValueError("Missing arguments")
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": name,
        "params": arguments,
    }
    url = f"{BASE_URL}/rpc/"
    try:
        headers = {"Authorization": f"Bearer {MCP_AUTH_TOKEN}"}
        response = httpx.post(
            url=url,
            json=payload,
            headers=headers,
            timeout=TOOL_CALL_TIMEOUT,
        )
        response.raise_for_status()
        tool_response = response.json()
        return [
            types.TextContent(
                type="text",
                text=str(tool_response),
            )
        ]
    except httpx.RequestError as e:
        raise ConnectionError(f"An error occurred while calling tool {name}: {e}")
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Tool call failed with status code {e.response.status_code}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error calling tool: {e}")


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """List available resources fetched from the MCP server.

    Returns:
        list[types.Resource]: List of available resources.
    """
    try:
        if BASE_URL == mcp_servers_urls[0]:
            resource_ids = [0]
        else:
            resource_ids = await get_resources_from_mcp_server(mcp_servers_urls)
        resources = await resources_metadata(resource_ids)
        mcp_resources = []
        for resource in resources:
            mcp_resources.append(
                types.Resource(
                    uri=AnyUrl(resource["uri"]),
                    name=resource["name"],
                    description=resource.get("description", ""),
                    mimeType=resource.get("mimeType", "text/plain"),
                )
            )
        return mcp_resources
    except Exception as e:
        raise RuntimeError(f"Error listing resources: {e}")


@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    """Read the content of a resource identified by its URI.

    Args:
        uri (AnyUrl): The resource URI.

    Returns:
        str: The content of the resource.
    """
    response = await fetch_url(str(uri))
    if response.status_code != 200:
        raise ValueError(f"Failed to read resource at {uri}: {response.status_code}")
    return response.text


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    """List available prompts fetched from the MCP server.

    Returns:
        list[types.Prompt]: List of available prompts.
    """
    try:
        if BASE_URL == mcp_servers_urls[0]:
            prompt_ids = [0]
        else:
            prompt_ids = await get_prompts_from_mcp_server(mcp_servers_urls)
        prompts = await prompts_metadata(prompt_ids)
        mcp_prompts = []
        for prompt in prompts:
            mcp_prompts.append(
                types.Prompt(
                    name=prompt["name"],
                    description=prompt.get("description", ""),
                    template=prompt.get("template", ""),
                    arguments=prompt.get("arguments", []),
                )
            )
        return mcp_prompts
    except Exception as e:
        raise RuntimeError(f"Error listing prompts: {e}")


@server.get_prompt()
async def handle_get_prompt(name: str, arguments: Optional[dict[str, str]] = None) -> types.GetPromptResult:
    """Generate a prompt by combining the remote prompt template with provided arguments.

    Args:
        name (str): The prompt name.
        arguments (dict[str, str] | None): Optional arguments for the prompt.

    Returns:
        types.GetPromptResult: The generated prompt result.
    """
    url = f"{BASE_URL}/prompts/{name}"
    response = await fetch_url(url)
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch prompt {name}: {response.status_code}")
    prompt = response.json()
    try:
        formatted_text = prompt["template"].format(**(arguments or {}))
    except Exception as e:
        raise ValueError(f"Error formatting prompt template: {e}")
    return types.GetPromptResult(
        description=prompt.get("description", ""),
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(
                    type="text",
                    text=formatted_text,
                ),
            )
        ],
    )


async def main():
    """Main entry point to run the MCP stdio server."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="mcpgateway-wrapper",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
