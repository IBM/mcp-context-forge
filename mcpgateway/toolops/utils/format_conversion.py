# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/toolops/utils/tool_format_conversion.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Jay Bandlamudi

MCP Gateway - module for converting MCP tool format to toolops specific internal format.

"""
# Standard
from copy import deepcopy

toolops_spec_template = {
    "binding": {"python": {"connections": {}, "function": "mcp-cf-tool-default", "requirements": []}},
    "description": None,
    "display_name": None,
    "id": None,
    "input_schema": {"description": None, "properties": {}, "required": [], "type": "object"},
    "is_async": False,
    "name": None,
    "output_schema": {"description": None, "properties": {}, "required": [], "type": "object"},
    "permission": "read_only",
}


def convert_to_toolops_spec(mcp_cf_tool):
    """
    Method to convert MCP tool json format to toolops specific internal format

    Args:
        mcp_cf_tool: MCP tool in json format

    Returns:
        toolops_spec: Toolops specific internal format of the tool in json notation. \
                        This internal format is similar to MCP tool format.
    """
    toolops_spec = deepcopy(toolops_spec_template)
    toolops_spec["description"] = mcp_cf_tool.get("description", None)
    toolops_spec["display_name"] = mcp_cf_tool.get("displayName", None)
    toolops_spec["id"] = mcp_cf_tool.get("id", None)
    toolops_spec["input_schema"]["description"] = mcp_cf_tool.get("inputSchema", {}).get("description", None)
    toolops_spec["input_schema"]["properties"] = mcp_cf_tool.get("inputSchema", {}).get("properties", {})
    toolops_spec["input_schema"]["required"] = mcp_cf_tool.get("inputSchema", {}).get("required", [])
    toolops_spec["name"] = mcp_cf_tool.get("name", None)
    if mcp_cf_tool.get("outputSchema") is not None:
        toolops_spec["output_schema"]["description"] = mcp_cf_tool.get("outputSchema", {}).get("description", None)
        toolops_spec["output_schema"]["properties"] = mcp_cf_tool.get("outputSchema", {}).get("properties", {})
        toolops_spec["output_schema"]["required"] = mcp_cf_tool.get("outputSchema", {}).get("required", [])
    else:
        toolops_spec["output_schema"] = {}
    return toolops_spec


def post_process_nl_test_cases(nl_test_cases):
    """
    Method for post processing of generated test cases to remove unwanted parameters

    Args:
        nl_test_cases: test cases dictionary object from test case geneation module, which contains test cases and other information.

    Returns:
        test_cases: processed list of test cases after removing un-necessary parameters.
    """
    test_cases = nl_test_cases.get("Test_scenarios")
    for tc in test_cases:
        for un_wanted in ["scenario_type", "input"]:
            del tc[un_wanted]
    return test_cases


# if __name__ == "__main__":
#     import json
#     import os
#     # mcp_cf_tools = json.load(open('./list_of_tools_from_mcp_cf.json','r'))
#     mcp_cf_tools = [json.load(open("mcp_cf_spec.json", "r"))]
#     for mcp_cf_tool in mcp_cf_tools:
#         toolops_spec = convert_to_toolops_spec(mcp_cf_tool)
#         print(toolops_spec)
