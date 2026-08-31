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


# ---------------------------------------------------------------------------
# Notification side-effect witnesses
#
# The harness treats this server as the "ground truth" witness for several
# gateway xfails (GAP-001 through GAP-005). If these notifications silently
# stop firing here, the gateway tests would XPASS / flip the wrong way
# without anyone noticing the reference itself broke. These tests pin the
# invariant so a FastMCP bump or a reference-server refactor doesn't let
# the witness drift out from under the harness.
# ---------------------------------------------------------------------------
def _notification_method(msg) -> str | None:
    """Return the JSON-RPC method string if ``msg`` is a notification, else None."""
    inner = getattr(msg, "root", None) or msg
    method = getattr(inner, "method", None)
    return str(method) if method else None


@pytest.mark.asyncio
async def test_mutate_resource_list_fires_list_changed() -> None:
    """mutate_resource_list registers a resource AND emits notifications/resources/list_changed."""
    observed: list[str] = []

    async def msg_handler(msg):
        method = _notification_method(msg)
        if method:
            observed.append(method)

    async with Client(mcp, message_handler=msg_handler) as client:
        before_uris = {str(r.uri) for r in await client.list_resources()}
        result = await client.call_tool_mcp(name="mutate_resource_list", arguments={})
        assert result.isError is False
        new_uri = result.content[0].text if result.content else ""
        assert new_uri.startswith("reference://ephemeral/resource_"), f"expected ephemeral resource uri, got {new_uri!r}"
        await asyncio.sleep(0.1)  # fire-and-forget notification — give transport a beat
        after_uris = {str(r.uri) for r in await client.list_resources()}

    assert new_uri in after_uris and new_uri not in before_uris, f"resource {new_uri!r} must appear after mutator call"
    assert "notifications/resources/list_changed" in observed, f"expected notifications/resources/list_changed; observed: {observed}"


@pytest.mark.asyncio
async def test_mutate_prompt_list_fires_list_changed() -> None:
    """mutate_prompt_list registers a prompt AND emits notifications/prompts/list_changed."""
    observed: list[str] = []

    async def msg_handler(msg):
        method = _notification_method(msg)
        if method:
            observed.append(method)

    async with Client(mcp, message_handler=msg_handler) as client:
        before_names = {p.name for p in await client.list_prompts()}
        result = await client.call_tool_mcp(name="mutate_prompt_list", arguments={})
        assert result.isError is False
        new_name = result.content[0].text if result.content else ""
        assert new_name.startswith("ephemeral_prompt_"), f"expected ephemeral prompt name, got {new_name!r}"
        await asyncio.sleep(0.1)
        after_names = {p.name for p in await client.list_prompts()}

    assert new_name in after_names and new_name not in before_names, f"prompt {new_name!r} must appear after mutator call"
    assert "notifications/prompts/list_changed" in observed, f"expected notifications/prompts/list_changed; observed: {observed}"


@pytest.mark.asyncio
async def test_bump_subscribable_fires_resource_updated_for_subscriber() -> None:
    """After subscribe + bump, the client observes notifications/resources/updated.

    Pins the subscription contract that the gateway xfail (GAP-011)
    inherits: if the reference server stops firing ``resources/updated``
    in response to ``bump_subscribable``, the gateway test can't
    meaningfully report compliance — it'd pass for the wrong reason.
    """
    observed_uris: list[str] = []

    async def msg_handler(msg):
        if _notification_method(msg) != "notifications/resources/updated":
            return
        inner = getattr(msg, "root", None) or msg
        params = getattr(inner, "params", None)
        uri = getattr(params, "uri", None)
        if uri is not None:
            observed_uris.append(str(uri))

    async with Client(mcp, message_handler=msg_handler) as client:
        await client.session.subscribe_resource("reference://mutable/counter")
        await client.call_tool_mcp(name="bump_subscribable", arguments={})
        await asyncio.sleep(0.1)

    assert "reference://mutable/counter" in observed_uris, f"expected notifications/resources/updated with the counter uri; " f"observed uris: {observed_uris}"


@pytest.mark.asyncio
async def test_subscribe_unsubscribe_tracks_uri_set() -> None:
    """resources/subscribe and unsubscribe update the server's subscription set.

    The reference server wires these via ``mcp._mcp_server.subscribe_resource`` /
    ``unsubscribe_resource`` hooks; a FastMCP bump that renames the low-level
    decorator would silently desync these handlers without surfacing here —
    unless something asserts the hook wiring still works.
    """
    from compliance_reference_server.server import _subscribed_uris

    uri = "reference://mutable/counter"
    async with Client(mcp) as client:
        _subscribed_uris.discard(uri)  # isolate from prior-test state
        await client.session.subscribe_resource(uri)
        assert uri in _subscribed_uris, f"subscribe handler must add {uri!r} to the tracking set; " f"current: {_subscribed_uris}"
        await client.session.unsubscribe_resource(uri)
        assert uri not in _subscribed_uris, f"unsubscribe handler must remove {uri!r}; current: {_subscribed_uris}"
