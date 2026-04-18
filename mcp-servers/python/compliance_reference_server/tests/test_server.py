"""In-process FastMCP Client tests for the reference server."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastmcp.client import Client

from compliance_reference_server.server import mcp


@pytest.mark.asyncio
async def test_tools_listed() -> None:
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert {"echo", "add", "boom"} <= names


@pytest.mark.asyncio
async def test_echo_roundtrip() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool_mcp(name="echo", arguments={"message": "hello"})
    assert result.isError is False
    assert "hello" in str(result.content)


@pytest.mark.asyncio
async def test_add_roundtrip() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool_mcp(name="add", arguments={"a": 2, "b": 3})
    assert result.isError is False
    assert "5" in str(result.content)


@pytest.mark.asyncio
async def test_boom_surfaces_error() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool_mcp(name="boom", arguments={})
    assert result.isError is True


@pytest.mark.asyncio
async def test_static_resource_listed_and_readable() -> None:
    async with Client(mcp) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
        assert "reference://static/greeting" in uris

        read = await client.read_resource("reference://static/greeting")
    assert any("hello from compliance-reference-server" in str(c) for c in read)


@pytest.mark.asyncio
async def test_templated_resource_registered_and_resolves() -> None:
    async with Client(mcp) as client:
        templates = {t.uriTemplate for t in await client.list_resource_templates()}
        assert "reference://users/{user_id}" in templates

        read = await client.read_resource("reference://users/42")
    payloads = [getattr(c, "text", "") for c in read]
    decoded = [json.loads(p) for p in payloads if p]
    assert decoded and decoded[0] == {"user_id": "42", "name": "User 42"}


@pytest.mark.asyncio
async def test_prompt_listed_and_renders_argument() -> None:
    async with Client(mcp) as client:
        prompts = {p.name for p in await client.list_prompts()}
        assert "greet" in prompts

        rendered = await client.get_prompt("greet", arguments={"name": "Ada"})
    texts = [getattr(m.content, "text", "") for m in rendered.messages]
    assert any("Ada" in t for t in texts)


# ---------------------------------------------------------------------------
# Phase 4b capability tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_progress_reporter_completes() -> None:
    """progress_reporter emits progress notifications via ctx.report_progress."""
    progress_events: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress, total, message):
        progress_events.append((progress, total, message))

    async with Client(mcp, progress_handler=on_progress) as client:
        result = await client.call_tool_mcp(name="progress_reporter", arguments={"total_steps": 3})
    assert result.isError is False
    assert "completed 3 steps" in str(result.content)
    # FastMCP delivers progress notifications during the call
    assert len(progress_events) >= 3, f"expected >=3 progress events, got {progress_events}"


@pytest.mark.asyncio
async def test_long_running_is_cancellable() -> None:
    """long_running tool can be cancelled via asyncio.wait_for."""
    async with Client(mcp) as client:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                client.call_tool_mcp(name="long_running", arguments={"duration_seconds": 10.0}),
                timeout=0.3,
            )


@pytest.mark.asyncio
async def test_log_at_level_delivers_to_client() -> None:
    """log_at_level emits a log notification observable on the client."""
    received: list[tuple[str, str]] = []

    async def log_handler(msg):
        level = getattr(msg, "level", None) or msg.__dict__.get("level", "")
        data = getattr(msg, "data", None) or msg.__dict__.get("data", "")
        received.append((str(level), str(data)))

    async with Client(mcp, log_handler=log_handler) as client:
        result = await client.call_tool_mcp(name="log_at_level", arguments={"level": "warning", "message": "hello"})
    assert result.isError is False
    assert any("hello" in d for _, d in received), f"expected 'hello' in log data, got {received}"


@pytest.mark.asyncio
async def test_roots_echo_returns_client_roots() -> None:
    """roots_echo returns whatever roots the client advertised."""
    async with Client(mcp, roots=["file:///tmp/root-a", "file:///tmp/root-b"]) as client:
        result = await client.call_tool_mcp(name="roots_echo", arguments={})
    assert result.isError is False
    assert "root-a" in str(result.content)
    assert "root-b" in str(result.content)


@pytest.mark.asyncio
async def test_sample_trigger_invokes_client_handler() -> None:
    """sample_trigger calls ctx.sample which routes to the client sampling_handler."""
    called_with: list[str] = []

    async def sampling_handler(messages, params, ctx):
        called_with.append(str(messages))
        return "canned-sample"

    async with Client(mcp, sampling_handler=sampling_handler) as client:
        result = await client.call_tool_mcp(name="sample_trigger", arguments={"prompt": "ping"})
    assert result.isError is False
    assert "canned-sample" in str(result.content)
    assert called_with, "sampling_handler was not invoked"


@pytest.mark.asyncio
async def test_elicit_trigger_invokes_client_handler() -> None:
    """elicit_trigger calls ctx.elicit which routes to the client elicitation_handler."""

    async def elicitation_handler(message, response_type, params, ctx):
        return {"value": "canned-elicit"}

    async with Client(mcp, elicitation_handler=elicitation_handler) as client:
        result = await client.call_tool_mcp(name="elicit_trigger", arguments={"message": "q"})
    assert result.isError is False
    assert "canned-elicit" in str(result.content)


@pytest.mark.asyncio
async def test_bump_subscribable_and_read() -> None:
    """bump_subscribable increments the mutable counter resource."""
    async with Client(mcp) as client:
        initial = await client.read_resource("reference://mutable/counter")
        initial_val = json.loads(initial[0].text)["counter"]
        await client.call_tool_mcp(name="bump_subscribable", arguments={})
        after = await client.read_resource("reference://mutable/counter")
        after_val = json.loads(after[0].text)["counter"]
    assert after_val == initial_val + 1


@pytest.mark.asyncio
async def test_pagination_stubs_registered() -> None:
    """120 stub_NNN tools are registered for pagination exercise."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
    stub_names = [t.name for t in tools if t.name.startswith("stub_")]
    assert len(stub_names) == 120, f"expected 120 stubs, got {len(stub_names)}"
    # Spot-check lowest and highest
    assert "stub_000" in stub_names
    assert "stub_119" in stub_names


@pytest.mark.asyncio
async def test_mutate_tool_list_adds_new_tool() -> None:
    """mutate_tool_list registers a new tool observable in subsequent list_tools."""
    async with Client(mcp) as client:
        before = {t.name for t in await client.list_tools()}
        result = await client.call_tool_mcp(name="mutate_tool_list", arguments={})
        assert result.isError is False
        new_name = result.content[0].text if result.content else ""
        assert new_name.startswith("ephemeral_"), f"expected ephemeral_* name, got {new_name}"
        after = {t.name for t in await client.list_tools()}
    assert new_name in after
    assert new_name not in before
