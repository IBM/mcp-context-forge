# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_output_schema_advertisement.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

The vendored MCP SDK validates outputSchema with stock jsonschema at
mcp/server/lowlevel/server.py:573, ungated by validate_input=False. The gateway must not
hand it a schema that can backtrack.
"""

# First-Party
from mcpgateway.transports.streamablehttp_transport import _to_mcp_tool


class _Tool:
    """Stand-in carrying every attribute ``_to_mcp_tool`` reads."""

    def __init__(self, output_schema):
        """Store the schema under test.

        Args:
            output_schema: The output schema to advertise.
        """
        self.name = "probe"
        self.title = None
        self.description = "probe"
        self.input_schema = {"type": "object"}
        self.output_schema = output_schema
        self.annotations = None
        self.extension_metadata = None


def test_regex_bearing_output_schema_is_not_advertised():
    """A regex outputSchema must not reach the SDK's stock validator.

    Returns:
        None.
    """
    tool = _Tool({"type": "object", "properties": {"q": {"type": "string", "pattern": "^(a+)+$"}}})
    assert _to_mcp_tool(tool).outputSchema is None


def test_nested_regex_output_schema_is_not_advertised():
    """A regex buried under ``$defs`` is still withheld.

    Returns:
        None.
    """
    tool = _Tool({"type": "object", "properties": {"q": {"$ref": "#/$defs/s"}}, "$defs": {"s": {"patternProperties": {"^x": {"type": "string"}}}}})
    assert _to_mcp_tool(tool).outputSchema is None


def test_plain_output_schema_is_still_advertised():
    """A schema with no regex keyword is advertised unchanged.

    Returns:
        None.
    """
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
    assert _to_mcp_tool(_Tool(schema)).outputSchema == schema


def test_regex_input_schema_is_still_advertised():
    """inputSchema is withheld from nothing; the SDK's input validator is gated off.

    Returns:
        None.
    """
    tool = _Tool(None)
    tool.input_schema = {"type": "object", "properties": {"q": {"type": "string", "pattern": "^(a+)+$"}}}
    assert _to_mcp_tool(tool).inputSchema == tool.input_schema


def test_absent_output_schema_stays_absent():
    """A tool with no outputSchema advertises none, and the regex check tolerates ``None``.

    Returns:
        None.
    """
    assert _to_mcp_tool(_Tool(None)).outputSchema is None
