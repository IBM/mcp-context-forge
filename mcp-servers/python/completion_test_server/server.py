# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/completion_test_server/server.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Minimal MCP server advertising the ``completions`` capability, used by
``tests/live_gateway/mcp/test_completion_federation.py`` (issue #6629) to
prove that ContextForge forwards ``completion/complete`` for a federated
prompt to the upstream server that owns it, rather than answering from a
stale locally-synced ``argument_schema``.

Exposes one prompt (``greet``) whose ``style`` argument has no ``enum`` in
its schema at all -- so a value that comes back from the gateway's
``completion/complete`` call could only have come from this server's own
``completion`` handler, never from a synced-schema fallback.

Pinned ``mcp>=2.0.0`` (see spec §8.1): the sibling branch's
``completion_test_server`` pins ``mcp>=1.0.0,<2`` and uses
``mcp.server.fastmcp.FastMCP``, which does not exist on this SDK generation
-- this module is a from-scratch build against ``mcp.server.mcpserver.MCPServer``,
not a port.

Set ``COMPLETIONS_ENABLED=false`` to run this same server without
registering a ``completion`` handler at all -- the resulting instance still
owns the ``greet`` prompt but does not advertise the ``completions``
server capability, simulating the upstream #6629's R3 "not supported" path
targets. The gateway's ``completion/complete`` forwarding must map that
case to ``-32601`` (or, for a federated prompt, fall back to the locally
synced ``argument_schema``) rather than crash.

Usage:
    python server.py                        # streamable-http on 0.0.0.0:9102 (see below)
    COMPLETION_TEST_SERVER_PORT=9200 python server.py
    COMPLETIONS_ENABLED=false python server.py  # no `completions` capability
"""

# Standard
import os

# Third-Party
from mcp.server.mcpserver import MCPServer
from mcp_types import Completion, CompletionArgument, PromptReference, ResourceTemplateReference

server = MCPServer("completion-test-server")

# Values only this server's completion handler knows about -- not derivable
# from `greet`'s synced argument_schema, which carries no enum for `style`.
_STYLE_OPTIONS = ["formal", "friendly", "playful"]

_COMPLETIONS_ENABLED = os.environ.get("COMPLETIONS_ENABLED", "true").strip().lower() not in ("false", "0", "no")


@server.prompt()
def greet(style: str) -> str:
    """A prompt whose ``style`` argument has completable values.

    Args:
        style: Desired tone for the greeting (e.g. "formal", "friendly").

    Returns:
        A prompt string asking for a greeting in the requested style.
    """
    return f"Say hello in a {style} style."


if _COMPLETIONS_ENABLED:

    @server.completion()
    async def complete_greet_style(ref, argument: CompletionArgument, context=None) -> Completion:
        """Provide completions for the ``greet`` prompt's ``style`` argument.

        Args:
            ref: Reference to the prompt or resource template being completed.
            argument: The argument name/partial-value being completed.
            context: Optional previously-resolved argument context (unused here).

        Returns:
            A :class:`Completion` naming the matching style options, or an
            empty one for any reference/argument this server does not
            recognize.
        """
        if isinstance(ref, PromptReference) and ref.name == "greet" and argument.name == "style":
            matches = [option for option in _STYLE_OPTIONS if argument.value.lower() in option.lower()]
            return Completion(values=matches, total=len(matches), has_more=False)
        if isinstance(ref, ResourceTemplateReference):
            return Completion(values=[], total=0, has_more=False)
        return Completion(values=[], total=0, has_more=False)


if __name__ == "__main__":
    port = int(os.environ.get("COMPLETION_TEST_SERVER_PORT", "9102"))
    server.run(transport="streamable-http", host="0.0.0.0", port=port, streamable_http_path="/mcp")  # nosec B104 - intentional bind-all inside an isolated compose test network
