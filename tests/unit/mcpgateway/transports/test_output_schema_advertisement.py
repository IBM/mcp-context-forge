# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_output_schema_advertisement.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

The vendored MCP SDK validates outputSchema with stock jsonschema at
mcp/server/lowlevel/server.py:573, ungated by validate_input=False. The gateway must not
hand it a schema that can backtrack.

Two paths advertise a tool to the SDK: ``_to_mcp_tool`` for database-backed tools, and
``_proxy_list_tools_to_gateway`` for direct-proxy gateways, which returns the remote's SDK
models unchanged. Both are covered here.
"""

# Standard
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from mcp import types
import pytest

# First-Party
from mcpgateway.transports.streamablehttp_transport import _proxy_list_tools_to_gateway, _to_mcp_tool

REGEX_SCHEMA = {"type": "object", "properties": {"q": {"type": "string", "pattern": "^(a+)+$"}}}
NESTED_REGEX_SCHEMA = {"type": "object", "properties": {"q": {"$ref": "#/$defs/s"}}, "$defs": {"s": {"patternProperties": {"^x": {"type": "string"}}}}}
PLAIN_SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}}


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
    assert _to_mcp_tool(_Tool(REGEX_SCHEMA)).outputSchema is None


def test_nested_regex_output_schema_is_not_advertised():
    """A regex buried under ``$defs`` is still withheld.

    Returns:
        None.
    """
    assert _to_mcp_tool(_Tool(NESTED_REGEX_SCHEMA)).outputSchema is None


def test_plain_output_schema_is_still_advertised():
    """A schema with no regex keyword is advertised unchanged.

    Returns:
        None.
    """
    assert _to_mcp_tool(_Tool(PLAIN_SCHEMA)).outputSchema == PLAIN_SCHEMA


def test_regex_input_schema_is_still_advertised():
    """inputSchema is withheld from nothing; the SDK's input validator is gated off.

    Returns:
        None.
    """
    tool = _Tool(None)
    tool.input_schema = REGEX_SCHEMA
    assert _to_mcp_tool(tool).inputSchema == REGEX_SCHEMA


def test_absent_output_schema_stays_absent():
    """A tool with no outputSchema advertises none, and the regex check tolerates ``None``.

    Returns:
        None.
    """
    assert _to_mcp_tool(_Tool(None)).outputSchema is None


async def _proxy_tools(remote_tools):
    """Run the direct-proxy tools/list path over a remote server returning ``remote_tools``.

    Mocks only the network boundary, so the guard under test runs for real.

    Args:
        remote_tools: SDK tool models the remote gateway returns.

    Returns:
        The tool list the gateway advertises to the SDK.
    """
    gateway = MagicMock()
    gateway.id = "gw-probe"
    gateway.url = "http://remote.example.com/mcp"
    gateway.passthrough_headers = None

    session = AsyncMock()
    session.list_tools = AsyncMock(return_value=MagicMock(tools=remote_tools))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _client(*_args, **_kwargs):
        """Stand in for the streamable HTTP client.

        Args:
            _args: Ignored positional arguments.
            _kwargs: Ignored keyword arguments.

        Yields:
            The read stream, write stream and session-id getter the caller unpacks.
        """
        yield (None, None, lambda: "session-id")

    with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", _client):
        with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=session):
            with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                return await _proxy_list_tools_to_gateway(gateway, {}, {}, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("schema", [REGEX_SCHEMA, NESTED_REGEX_SCHEMA])
async def test_direct_proxy_withholds_regex_output_schema(schema):
    """A direct-proxy gateway must not relay a remote's regex outputSchema to the SDK.

    Args:
        schema: The regex-bearing schema the remote advertises.

    Returns:
        None.
    """
    remote = types.Tool(name="probe", inputSchema={"type": "object"}, outputSchema=schema)
    assert remote.outputSchema == schema, "the remote model must carry the schema, or the test proves nothing"

    advertised = await _proxy_tools([remote])

    assert [tool.name for tool in advertised] == ["probe"], "the proxy path swallowed the tool; the test never reached the guard"
    assert advertised[0].outputSchema is None


@pytest.mark.asyncio
async def test_direct_proxy_relays_a_plain_output_schema():
    """A remote schema with no regex keyword is relayed unchanged, with other fields intact.

    Returns:
        None.
    """
    remote = types.Tool(name="probe", description="probe", inputSchema={"type": "object"}, outputSchema=PLAIN_SCHEMA)

    advertised = await _proxy_tools([remote])

    assert advertised[0].outputSchema == PLAIN_SCHEMA
    assert advertised[0].description == "probe"


@pytest.mark.asyncio
async def test_direct_proxy_preserves_sibling_fields_when_withholding():
    """Withholding replaces only outputSchema; every other advertised field survives.

    Returns:
        None.
    """
    remote = types.Tool(name="probe", title="Probe", description="probe", inputSchema=REGEX_SCHEMA, outputSchema=REGEX_SCHEMA)

    advertised = await _proxy_tools([remote])

    assert advertised[0].outputSchema is None
    assert advertised[0].title == "Probe"
    assert advertised[0].description == "probe"
    assert advertised[0].inputSchema == REGEX_SCHEMA
