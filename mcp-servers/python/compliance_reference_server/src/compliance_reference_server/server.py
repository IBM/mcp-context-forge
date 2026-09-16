"""Reference FastMCP server covering the MCP 2025-11-25 capability surface.

Phase 4b expands the Phase 1 stub to exercise every capability the compliance
harness asserts against:

- Tools: echo, add, boom (error path), progress emitter, long-running /
  cancellable, tool-list mutator (fires ``tools/list_changed``), resource
  subscription trigger (fires ``resources/updated``), roots-echo diagnostic,
  sampling-trigger, elicitation-trigger, logging-level echo, pagination stubs.
- Resources: static, templated, subscribable.
- Prompts: greet (with argument).

Completions are deliberately not implemented — FastMCP 2.x does not expose a
`@mcp.completion` decorator at this version. Phase 4c will either add them
via the lower-level MCP Server API or document the gap.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from fastmcp import Context, FastMCP
from pydantic import BaseModel


class ElicitResponse(BaseModel):
    """Shape the ``elicit_trigger`` tool requests from the client."""

    value: str


class ElicitNumericResponse(BaseModel):
    """Multi-field schema for ``elicit_trigger_numeric`` — exercises non-string elicitation."""

    count: int
    ratio: float


mcp: FastMCP = FastMCP(name="compliance-reference-server", version="0.2.0")


# ---------------------------------------------------------------------------
# Shared mutable state — reference server is single-process; no locking needed.
#
# Two separate counters because the names they source are in different
# namespaces: ``_subscribable_counter`` is the value of the subscribable
# resource (incremented by ``bump_subscribable``) so subscribers see a
# monotonic read; ``_mutation_counter`` is a per-call UID used by the
# ``mutate_*_list`` tools to build unique ephemeral names. Sharing one
# counter would let a ``mutate_*_list`` call collide with a previously
# registered ``ephemeral_<n>`` whenever ``bump_subscribable`` hadn't
# advanced in between — FastMCP rejects the duplicate registration.
# ---------------------------------------------------------------------------
_subscribable_counter: int = 0
_mutation_counter: int = 0
_subscribed_uris: set[str] = set()


# ---------------------------------------------------------------------------
# Low-level subscribe / unsubscribe handlers. FastMCP 2.x doesn't register
# these by default, so subscribe requests would get "Method not found" and
# the server's capabilities.resources.subscribe would stay False. Wiring
# directly into the underlying MCP Server surfaces the capability and lets
# the harness exercise the subscribe → notify → unsubscribe flow.
# ---------------------------------------------------------------------------
@mcp._mcp_server.subscribe_resource()
async def _on_subscribe(uri) -> None:
    _subscribed_uris.add(str(uri))


@mcp._mcp_server.unsubscribe_resource()
async def _on_unsubscribe(uri) -> None:
    _subscribed_uris.discard(str(uri))


# ---------------------------------------------------------------------------
# Core tools (Phase 1)
# ---------------------------------------------------------------------------
@mcp.tool(description="Echo the input string back to the caller.")
def echo(message: str) -> str:
    return message


@mcp.tool(description="Add two integers and return their sum.")
def add(a: int, b: int) -> int:
    return a + b


@mcp.tool(description="Always raise; used to exercise MCP error-result propagation.")
def boom() -> None:
    raise ValueError("intentional failure")


# ---------------------------------------------------------------------------
# Utilities — progress, cancel
# ---------------------------------------------------------------------------
@mcp.tool(description="Emit three progress notifications then return.")
async def progress_reporter(ctx: Context, total_steps: int = 3) -> str:
    for step in range(1, total_steps + 1):
        await ctx.report_progress(progress=step, total=total_steps, message=f"step {step}/{total_steps}")
        await asyncio.sleep(0.05)
    return f"completed {total_steps} steps"


_cancellation_count: int = 0


@mcp.tool(description="Sleep for the requested duration; used to exercise cancellation.")
async def long_running(duration_seconds: float = 30.0) -> str:
    global _cancellation_count
    try:
        await asyncio.sleep(duration_seconds)
    except asyncio.CancelledError:
        # Increment a process-wide counter so a follow-up probe can verify
        # the server actually received and honored the client's
        # `notifications/cancelled` (gateways that don't relay the
        # notification leave this counter unchanged even though the
        # client-side timeout fires).
        _cancellation_count += 1
        raise
    return f"slept {duration_seconds}s"


@mcp.tool(description="Report how many times `long_running` has been cancelled since process start.")
def get_cancellation_count() -> int:
    return _cancellation_count


# ---------------------------------------------------------------------------
# Notifications — tools/list_changed, resources/updated
# ---------------------------------------------------------------------------
@mcp.tool(description="Add a one-off tool at runtime; fires tools/list_changed.")
async def mutate_tool_list(ctx: Context) -> str:
    global _mutation_counter
    _mutation_counter += 1
    ephemeral_name = f"ephemeral_{_mutation_counter}"

    @mcp.tool(name=ephemeral_name, description=f"Ephemeral tool #{_mutation_counter}.")
    def _ephemeral() -> str:
        return f"hello from {ephemeral_name}"

    # FastMCP's FunctionTool registration does NOT auto-emit list_changed; the
    # server-session helper does the right shape for this notification.
    await ctx.session.send_tool_list_changed()
    return ephemeral_name


@mcp.tool(description="Add a one-off resource at runtime; fires resources/list_changed.")
async def mutate_resource_list(ctx: Context) -> str:
    global _mutation_counter
    _mutation_counter += 1
    ephemeral_uri = f"reference://ephemeral/resource_{_mutation_counter}"

    @mcp.resource(
        ephemeral_uri,
        name=f"ephemeral-resource-{_mutation_counter}",
        description=f"Ephemeral resource #{_mutation_counter}.",
        mime_type="text/plain",
    )
    def _ephemeral_resource() -> str:
        return f"hello from {ephemeral_uri}"

    await ctx.session.send_resource_list_changed()
    return ephemeral_uri


@mcp.tool(description="Add a one-off prompt at runtime; fires prompts/list_changed.")
async def mutate_prompt_list(ctx: Context) -> str:
    global _mutation_counter
    _mutation_counter += 1
    ephemeral_name = f"ephemeral_prompt_{_mutation_counter}"

    @mcp.prompt(name=ephemeral_name, description=f"Ephemeral prompt #{_mutation_counter}.")
    def _ephemeral_prompt(subject: str = "world") -> str:
        return f"Hello, {subject}, from {ephemeral_name}."

    await ctx.session.send_prompt_list_changed()
    return ephemeral_name


@mcp.tool(description="Mutate the subscribable resource; fires resources/updated for subscribers.")
async def bump_subscribable(ctx: Context) -> int:
    global _subscribable_counter
    _subscribable_counter += 1
    # Use the ServerSession helper — it correctly targets the pydantic
    # union for ResourceUpdatedNotification. The generic
    # ``ctx.send_notification`` with a wrapped ``ServerNotification`` hits
    # a pydantic-model-type validation error in current FastMCP because
    # the union discriminator prefers TaskStatusNotification.
    await ctx.session.send_resource_updated("reference://mutable/counter")
    return _subscribable_counter


# ---------------------------------------------------------------------------
# Client-side capability trigger tools — sampling, elicitation, roots
# ---------------------------------------------------------------------------
@mcp.tool(description="Echo the list of roots the client announced.")
async def roots_echo(ctx: Context) -> list[str]:
    roots = await ctx.list_roots()
    return [str(r.uri) for r in roots]


@mcp.tool(description="Request a sampling/createMessage from the client and return the text it produced.")
async def sample_trigger(ctx: Context, prompt: str = "say hi") -> str:
    result = await ctx.sample(messages=prompt, max_tokens=64)
    # SamplingResult: text in result.content or result.text depending on FastMCP version
    text = getattr(result, "text", None)
    if text is None:
        content = getattr(result, "content", None)
        text = getattr(content, "text", "") if content else ""
    return text or ""


@mcp.tool(description="Request elicitation from the client and return its response value.")
async def elicit_trigger(ctx: Context, message: str = "please respond") -> str:
    result = await ctx.elicit(message=message, response_type=ElicitResponse)
    data = getattr(result, "data", None) or getattr(result, "value", None)
    if isinstance(data, ElicitResponse):
        return data.value
    if isinstance(data, dict) and "value" in data:
        return str(data["value"])
    return str(data) if data is not None else ""


@mcp.tool(
    description=("Request a structured numeric elicitation — two fields (count:int, ratio:float) " "— so the harness can verify non-string schemas round-trip correctly."),
)
async def elicit_trigger_numeric(ctx: Context, message: str = "fill me in") -> str:
    result = await ctx.elicit(message=message, response_type=ElicitNumericResponse)
    data = getattr(result, "data", None) or getattr(result, "value", None)
    if isinstance(data, ElicitNumericResponse):
        return f"count={data.count} ratio={data.ratio}"
    if isinstance(data, dict) and "count" in data and "ratio" in data:
        return f"count={data['count']} ratio={data['ratio']}"
    return f"unexpected elicitation shape: {data!r}"


@mcp.tool(
    description=("Request sampling with explicit max_tokens; echoes whatever text the client's " "sampling handler produced. Used to verify sampling parameters round-trip."),
)
async def sample_trigger_with_params(
    ctx: Context,
    prompt: str = "say hi",
    max_tokens: int = 128,
) -> str:
    result = await ctx.sample(messages=prompt, max_tokens=max_tokens)
    text = getattr(result, "text", None)
    if text is None:
        content = getattr(result, "content", None)
        text = getattr(content, "text", "") if content else ""
    return text or ""


# ---------------------------------------------------------------------------
# Logging — setLevel is handled natively by FastMCP; this tool emits one log
# at the level the client has requested, so the client can observe the effect.
# ---------------------------------------------------------------------------
@mcp.tool(description="Emit a log message at the given level via the MCP logging capability.")
async def log_at_level(ctx: Context, level: str = "info", message: str = "hello log") -> str:
    await ctx.log(message=message, level=level)  # type: ignore[arg-type]
    return f"emitted {level}: {message}"


# ---------------------------------------------------------------------------
# Resources — static, templated, subscribable
# ---------------------------------------------------------------------------
@mcp.resource(
    "reference://static/greeting",
    name="greeting",
    description="Static greeting resource.",
    mime_type="text/plain",
)
def greeting_resource() -> str:
    return "hello from compliance-reference-server"


@mcp.resource(
    "reference://users/{user_id}",
    name="user-profile",
    description="Templated user profile resource.",
    mime_type="application/json",
)
def user_profile(user_id: str) -> str:
    return json.dumps({"user_id": user_id, "name": f"User {user_id}"})


@mcp.resource(
    "reference://mutable/counter",
    name="mutable-counter",
    description="Resource whose contents increase each time ``bump_subscribable`` is called.",
    mime_type="application/json",
)
def mutable_counter_resource() -> str:
    return json.dumps({"counter": _subscribable_counter})


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
@mcp.prompt(description="Prompt asking the assistant to greet someone by name.")
def greet(name: str) -> str:
    return f"Please greet {name} warmly."


# ---------------------------------------------------------------------------
# Pagination stubs — enough tools to exceed any plausible default page size.
# ---------------------------------------------------------------------------
def _register_pagination_stubs(count: int = 120) -> None:
    """Register ``count`` minimal tools named ``stub_000`` .. ``stub_NNN``.

    The loop is gated behind a function to keep top-level module noise low.
    """
    for i in range(count):
        name = f"stub_{i:03d}"

        @mcp.tool(name=name, description=f"No-op pagination fixture tool #{i}.")
        def _stub(*, _i: int = i) -> int:
            return _i


_register_pagination_stubs()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Compliance Reference MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default="stdio",
        help="Transport mode: stdio framing, SSE, or Streamable HTTP.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host for SSE/HTTP transports.")
    parser.add_argument("--port", type=int, default=9100, help="Bind port for SSE/HTTP transports.")
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
