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
    Converts an MCP tool JSON format to ToolOps-specific internal format.

    This method takes a JSON representation of an MCP tool and converts it into a
    format that is compatible with ToolOps' internal specification, while keeping
    the general structure similar to the MCP tool format.

    Args:
        mcp_cf_tool (dict): The MCP tool in JSON format. It must contain the
                            fields: 'description', 'displayName', 'id',
                            'inputSchema', and optionally 'outputSchema'.

    Returns:
        dict: The ToolOps-specific internal format of the tool, which includes:
            - description
            - display_name
            - id
            - input_schema (description, properties, required)
            - output_schema (description, properties, required, or an empty dict if not present)
            - name

    Example:
        >>> mcp_cf_tool = {
        ...     "description": "A sample tool",
        ...     "displayName": "Sample Tool",
        ...     "id": "tool123",
        ...     "inputSchema": {
        ...         "description": "Input data",
        ...         "properties": {},
        ...         "required": []
        ...     },
        ...     "outputSchema": {
        ...         "description": "Output data",
        ...         "properties": {},
        ...         "required": []
        ...     },
        ...     "name": "Sample Tool Name"
        ... }
        >>> convert_to_toolops_spec(mcp_cf_tool)
        {'binding': {'python': {'connections': {}, 'function': 'mcp-cf-tool-default', 'requirements': []}}, 'description': 'A sample tool', 'display_name': 'Sample Tool', 'id': 'tool123', 'input_schema': {'description': 'Input data', 'properties': {}, 'required': [], 'type': 'object'}, 'is_async': False, 'name': 'Sample Tool Name', 'output_schema': {'description': 'Output data', 'properties': {}, 'required': [], 'type': 'object'}, 'permission': 'read_only'}
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
    Post-processes generated test cases to remove unwanted parameters.

    This method processes the test cases by removing unnecessary parameters, such as
    "scenario_type" and "input", from the input test case dictionary.

    Args:
        nl_test_cases (dict): A dictionary containing test cases under the key "Test_scenarios".
                               Each test case may contain parameters like "scenario_type", "input", etc.

    Returns:
        list: A list of processed test cases with unwanted parameters removed.

    Example:
        >>> nl_test_cases = {
        ...     "Test_scenarios": [
        ...         {"scenario_type": "type1", "input": "data1", "other_param": "value1"},
        ...         {"scenario_type": "type2", "input": "data2", "other_param": "value2"}
        ...     ]
        ... }
        >>> post_process_nl_test_cases(nl_test_cases)
        [{'other_param': 'value1'}, {'other_param': 'value2'}]

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
