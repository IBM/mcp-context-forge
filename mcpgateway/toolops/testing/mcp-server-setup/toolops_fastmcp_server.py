# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/toolops/testing/mcp-server-setup/toolops_fastmcp_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Jay Bandlamudi

MCP Gateway - Script to set up test MCP server from Open API specification

This module creates test MCP server for toolops testing purpose.
"""
# Standard
import json
import os

# Third-Party
from fastmcp import FastMCP
import httpx

def start_mcp_server_from_oapi(mcp_server_name,server_url,server_auth_headers,open_api_spec):
    '''
    Method to create the MCP server using Open API specification
    Args:
        mcp_server_name: Name of the MCP server given by user.
        server_url: External application server url used in the open api specification
        server_auth_headers: headers with authorisation details such as bearer token
        open_api_spec: Open API specification in json format

    Returns:
        This method starts the MCP server and return nothing.
    '''
    client = httpx.AsyncClient(base_url=server_url, headers=server_auth_headers)
    mcp = FastMCP.from_openapi(openapi_spec=open_api_spec, client=client, name=mcp_server_name)
    mcp.run()

if __name__ == "__main__":
    SALESLOFT_BEARER_TOKEN = os.environ.get("SALESLOFT_BEARER_TOKEN", "")
    if SALESLOFT_BEARER_TOKEN == "":
        print("Please set SALESLOFT_BEARER_TOKEN as env variable")
    else:
        print("SALESLOFT_BEARER_TOKEN is provided ", "SALESLOFT_BEARER_TOKEN")
        mcp_server_name = "salesloft get all actions"
        server_url = "https://api.salesloft.com"
        server_auth_headers={"Authorization": "Bearer " + SALESLOFT_BEARER_TOKEN}
        api_spec_path = "./mcpgateway/toolops/testing/mcp-server-setup/api_specs/Wipro_Salesloft_Get_all_actions_short.json"
        open_api_spec = json.load(open(api_spec_path, "r"))
        start_mcp_server_from_oapi(mcp_server_name,server_url,server_auth_headers,open_api_spec)
        


"""
nohup python -m mcpgateway.translate      --stdio "python ./toolops_fastmcp_server.py"      --expose-streamable-http      --expose-sse      --port 8001 &
"""


# npx @modelcontextprotocol/inspector
