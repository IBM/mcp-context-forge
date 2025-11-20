# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/toolops/testing/mcp-server-setup/sap_successfactors_mcp_server.py
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


def start_mcp_server_from_oapi(mcp_server_name, server_url, server_auth_headers, open_api_spec):
    """
    Method to create the MCP server using Open API specification

    Args:
        mcp_server_name: Name of the MCP server given by user.
        server_url: External application server url used in the open api specification
        server_auth_headers: headers with authorisation details such as bearer token
        open_api_spec: Open API specification in json format

    """
    client = httpx.AsyncClient(base_url=server_url, headers=server_auth_headers)
    mcp = FastMCP.from_openapi(openapi_spec=open_api_spec, client=client, name=mcp_server_name)
    mcp.run()


if __name__ == "__main__":
    SAP_BEARER_TOKEN = os.environ.get("SAP_BEARER_TOKEN", "None")
    if SAP_BEARER_TOKEN == "":
        print("Please set SAAP_BEARER_TOKEN as env variable")
    else:
        print("SAP_BEARER_TOKEN is provided ", "SAP_BEARER_TOKEN")
        mcp_server_name = "sap successfactors get time off"
        server_url = "http://localhost:8000"
        server_auth_headers = {"Authorization": "Bearer " + SAP_BEARER_TOKEN}
        api_spec_path = "./mcpgateway/toolops/testing/mcp-server-setup/api_specs/SAP_success_factor_time_off.json"
        open_api_spec = json.load(open(api_spec_path, "r"))
        start_mcp_server_from_oapi(mcp_server_name, server_url, server_auth_headers, open_api_spec)
