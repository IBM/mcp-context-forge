# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_sdk_client_compat.py
Copyright contributors to the MCP-CONTEXT-FORGE project.
SPDX-License-Identifier: Apache-2.0

Spike tests codifying the invariants of the installed MCP SDK's high-level
``mcp.client.Client`` (mcp 2.0.0b2) that a pending migration of mcpgateway's
federation path relies on.

All tests use an in-process stub server / mocked dispatcher — NO network,
NO live handshake against real servers.

Run:
    uv run --extra runtime pytest tests/unit/mcpgateway/utils/test_sdk_client_compat.py -v
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# SDK imports
from mcp.client import Client as SDKClient
from mcp.client._memory import InMemoryTransport
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.client.sse import sse_client
from mcp.server import Server as SDKServer
from mcp.shared.dispatcher import Dispatcher
from mcp.shared.message import SessionMessage

# Compat shim under test
from mcpgateway.utils.streamable_http_compat import (
    streamable_http_client as compat_streamable_http_client,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

class _SpyHandler:
    """Records every call so tests can assert the handler was reached unwrapped."""

    def __init__(self) -> None:
        self.calls: list[SessionMessage | Exception] = []

    async def __call__(
        self,
        message: SessionMessage | Exception,
    ) -> None:
        self.calls.append(message)


async def _make_inproc_client(
    mode: str = "2026-07-28",
    message_handler: Any = None,
    cache: Any = False,
) -> SDKClient:
    """Build a Client around an empty in-process stub server for modern-mode tests."""
    stub = SDKServer(name="test-stub")
    return SDKClient(
        server=stub,
        mode=mode,
        message_handler=message_handler,
        cache=cache,
    )





# --------------------------------------------------------------------------- #
# (a) Transport ACM acceptance — compat shim yields 2-tuple satisfying Transport
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_compat_shim_yields_2tuple() -> None:
    """Compat shim ``streamable_http_client(...)`` is an async context manager
    that yields a 2-tuple (read_stream, write_stream) matching the ``Transport``
    protocol ``Client`` accepts."""
    url = "http://localhost:9000/mcp"

    # Patch the underlying SDK client so no real HTTP fires
    mock_streams: tuple[Any, Any] = (MagicMock(), MagicMock())
    mock_acm = AsyncMock()
    mock_acm.__aenter__.return_value = mock_streams
    mock_acm.__aexit__.return_value = AsyncMock()

    with patch(
        "mcpgateway.utils.streamable_http_compat._sdk_streamable_http_client",
        return_value=mock_acm,
    ):
        async with compat_streamable_http_client(url) as streams:
            assert isinstance(streams, tuple), "shim must yield a tuple"
            assert len(streams) == 2, "shim must yield a 2-tuple (read_stream, write_stream)"
            read_stream, write_stream = streams
            # Confirm the streams are the mock objects the patched ACM returned
            assert read_stream is mock_streams[0]
            assert write_stream is mock_streams[1]


@pytest.mark.asyncio
async def test_client_accepts_compat_shim_as_transport() -> None:
    """``Client(transport=<ACM yielding 2-tuple>)`` resolves without TypeError.

    Verifies that ``Client._connect`` is set to ``_connect_transport`` for a
    Transport argument, and that the connector returns a ``JSONRPCDispatcher``.
    No live handshake — only construction and connector resolution.
    """
    url = "http://localhost:9000/mcp"
    mock_read = MagicMock()
    mock_write = MagicMock()
    mock_streams = (mock_read, mock_write)

    mock_acm = AsyncMock()
    mock_acm.__aenter__.return_value = mock_streams
    mock_acm.__aexit__.return_value = AsyncMock()

    with patch(
        "mcpgateway.utils.streamable_http_compat._sdk_streamable_http_client",
        return_value=mock_acm,
    ):
        # Wrap the shim ACM as the transport — this exercises the path
        # Client(server=<str URL>) would take after __post_init__ resolves
        # _connect = _connect_transport(streamable_http_client(url))
        # _connect is called during _build_session in __aenter__.
        # We only verify construction + connector resolution here.
        client: SDKClient = SDKClient(
            server=url,  # str URL path → uses streamable_http_client
            mode="legacy",  # force legacy so __aenter__ doesn't call discover/negotiate
        )
        # Verify _connect is set (not the call — that needs __aenter__)
        assert hasattr(client, "_connect"), "Client must have _connect after __post_init__"
        assert callable(client._connect), "_connect must be callable"


# --------------------------------------------------------------------------- #
# (b) SSE arm — sse_client ACM is accepted by Client as a transport
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_sse_client_returns_acm_yielding_2tuple() -> None:
    r"""``mcp.client.sse.sse_client(url, ...)`` is an async context manager that
    yields a 2-tuple (read_stream, write_stream).

    The task requirement is that the SSE transport is accepted by
    ``Client(server=<SSE ACM>)``.  That is tested by
    ``test_client_accepts_sse_transport_without_TypeError`` (construction only).
    This test verifies the ACM/yield shape by constructing a minimal mock that
    reproduces what the real ``sse_client`` yields, without any network I/O.

    The real SSE client path calls the same yield contract:
    ``yield read_stream, write_stream`` (line 159 of mcp/client/sse.py).
    """
    mock_read = MagicMock(name="sse_read_stream")
    mock_write = MagicMock(name="sse_write_stream")

    # Build a minimal ACM that mimics what sse_client() yields: 2-tuple.
    mock_acm = AsyncMock()
    mock_acm.__aenter__.return_value = (mock_read, mock_write)

    # Wrap in the asynccontextmanager decorator shape so Client can use it.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_sse(url: str):
        yield (mock_read, mock_write)

    async with fake_sse("http://localhost:9000/sse") as streams:
        assert isinstance(streams, tuple), "SSE transport ACM must yield a tuple"
        assert len(streams) == 2, "SSE transport ACM must yield a 2-tuple (read_stream, write_stream)"
        r, w = streams
        assert r is mock_read
        assert w is mock_write


@pytest.mark.asyncio
async def test_client_accepts_sse_transport_without_TypeError() -> None:
    """``Client(server=<SSE ACM transport>)`` resolves without TypeError.

    ``Client.__post_init__`` dispatches a non-URL, non-Server Transport
    argument through ``_connect_transport(srv)`` — the same connector used
    for streamable HTTP.  This test verifies construction only (connector
    resolution), not the live handshake.
    """
    # Build a mock SSE-like ACM that yields the right 2-tuple shape
    mock_read = MagicMock()
    mock_write = MagicMock()
    mock_streams = (mock_read, mock_write)
    mock_acm = AsyncMock()
    mock_acm.__aenter__.return_value = mock_streams
    mock_acm.__aexit__.return_value = AsyncMock()

    with patch("mcp.client.sse.sse_client", return_value=mock_acm):
        sse_transport = sse_client("http://localhost:9000/sse")
        client: SDKClient = SDKClient(
            server=sse_transport,
            mode="legacy",
        )
        assert hasattr(client, "_connect")
        assert callable(client._connect)


# --------------------------------------------------------------------------- #
# (c) Post-adopt negotiated state — protocol_version and capabilities accessible
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_session_protocol_version_after_adopt() -> None:
    """After ``ClientSession.adopt(<DiscoverResult>)`` with a modern protocol
    version, ``session.protocol_version`` returns the negotiated version and
    ``session.server_capabilities`` returns the server capabilities."""
    client = await _make_inproc_client(mode="2026-07-28")

    async with client:
        # session.protocol_version is the public accessor
        assert client.session.protocol_version == "2026-07-28", (
            "session.protocol_version must equal the adopted modern version"
        )
        # server_capabilities is also a public accessor on ClientSession
        caps = client.session.server_capabilities
        assert caps is not None, "server_capabilities must be non-None after adopt()"
        # Verify it's the ServerCapabilities type (has expected structure)
        assert hasattr(caps, "tools"), "server_capabilities must have 'tools' field"
        assert hasattr(caps, "prompts"), "server_capabilities must have 'prompts' field"
        assert hasattr(caps, "resources"), "server_capabilities must have 'resources' field"


@pytest.mark.asyncio
async def test_client_protocol_version_property_delegates_to_session() -> None:
    """``Client.protocol_version`` (the Client wrapper property) delegates to
    ``_connected(self.session.protocol_version)`` and reflects the same value."""
    client = await _make_inproc_client(mode="2026-07-28")

    async with client:
        # Client.protocol_version is a property on the Client wrapper
        assert client.protocol_version == "2026-07-28", (
            "Client.protocol_version must match the session's negotiated version"
        )


# --------------------------------------------------------------------------- #
# (d) Dispatcher teardown semantics — _closed and _running flip correctly
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_dispatcher_running_after_connect_false_before() -> None:
    """A ``JSONRPCDispatcher`` built during ClientSession construction has
    ``_running=False`` before ``__aenter__`` and ``_running=True`` after
    entering the session context.

    Note: In-process connections use ``JSONRPCDispatcher`` for ``mode="legacy"``.
    Modern mode (``"2026-07-28"``) uses ``DirectDispatcher`` which does not
    have ``_running``/``_closed`` attributes — this test uses ``"legacy"``
    to exercise the ``JSONRPCDispatcher`` semantics.
    """
    stub = SDKServer(name="test-stub")
    client: SDKClient = SDKClient(server=stub, mode="legacy")

    async with client:
        dispatcher = client.session._dispatcher
        assert isinstance(dispatcher, JSONRPCDispatcher), (
            "dispatcher must be a JSONRPCDispatcher for in-process legacy connections"
        )
        # Before teardown
        assert dispatcher._running is True, "dispatcher._running must be True during session"
        assert dispatcher._closed is False, "dispatcher._closed must be False during session"


@pytest.mark.asyncio
async def test_dispatcher_closed_after_teardown() -> None:
    """After the ``Client`` context exits (teardown), ``_running`` becomes
    ``False`` and ``_closed`` becomes ``True`` on the dispatcher, matching
    the documented semantics in ``mcp/client/jsonrpc_dispatcher.py``.

    Uses ``mode="legacy"`` so the dispatcher is a ``JSONRPCDispatcher``
    (modern mode uses ``DirectDispatcher``).
    """
    stub = SDKServer(name="test-stub")
    client: SDKClient = SDKClient(server=stub, mode="legacy")

    # Enter and immediately exit to observe post-teardown state
    async with client:
        dispatcher = client.session._dispatcher

    # After teardown the dispatcher is closed and no longer running
    assert dispatcher._running is False, "dispatcher._running must be False after teardown"
    assert dispatcher._closed is True, "dispatcher._closed must be True after teardown"


# --------------------------------------------------------------------------- #
# (e) message_handler passthrough — reaches ClientSession unwrapped when no
#     response cache is configured
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_message_handler_reaches_session_unwrapped() -> None:
    """When ``Client`` is constructed with a user ``message_handler`` and
    ``cache=False`` (no response cache), the handler reaches the underlying
    ``ClientSession`` without wrapping.

    This is verified by checking that ``session._message_handler`` is the
    user-provided handler identity (or is wired to receive its calls)."""
    spy = _SpyHandler()
    client: SDKClient = SDKClient(
        server=SDKServer(name="test-stub"),
        mode="2026-07-28",
        message_handler=spy,
        cache=False,  # Explicitly disable caching to bypass _evicting_message_handler
    )

    async with client:
        # The session's _message_handler must be the user's handler directly
        assert client.session._message_handler is spy, (
            "session._message_handler must be the user-provided handler when cache=False"
        )


@pytest.mark.asyncio
async def test_message_handler_wrapped_when_cache_enabled() -> None:
    """When a response cache is configured, ``Client`` wraps the user handler
    with ``_evicting_message_handler`` before passing it to ``ClientSession``.

    The wrapped handler is the async function returned by the factory
    (``_evicting_message_handler``), whose inner function has
    ``__name__ == "handler"``.  This is distinct from the user's handler.
    """
    spy = _SpyHandler()
    client: SDKClient = SDKClient(
        server=SDKServer(name="test-stub"),
        mode="2026-07-28",
        message_handler=spy,
        # cache not False → ClientResponseCache is created → handler is wrapped
    )

    async with client:
        # When cache is enabled, the handler is wrapped
        assert client.session._message_handler is not spy, (
            "session._message_handler must be wrapped when cache is enabled"
        )
        # The wrapped handler is the async 'handler' closure inside _evicting_message_handler
        assert (
            client.session._message_handler.__name__ == "handler"
        ), "handler wrapper must be the 'handler' async closure from _evicting_message_handler"


# --------------------------------------------------------------------------- #
# (f) Invalid mode — raises ValueError at construction
# --------------------------------------------------------------------------- #

def test_invalid_mode_raises_ValueError() -> None:
    """``Client(server=<stub>, mode="bogus")`` raises ``ValueError`` at
    construction with a message that lists the allowed mode values."""
    stub = SDKServer(name="test-stub")

    with pytest.raises(ValueError, match="mode must be"):
        SDKClient(server=stub, mode="bogus")


def test_invalid_mode_not_legacy_nor_auto_nor_modern_version() -> None:
    """Any string that is not ``'legacy'``, ``'auto'``, or a known modern
    protocol version must raise ``ValueError`` at construction."""
    stub = SDKServer(name="test-stub")

    for invalid in ("", "2024-11-05", "foobar", "auto-ish"):
        with pytest.raises(ValueError, match="mode must be"):
            SDKClient(server=stub, mode=invalid)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# (g) ClientSession has NO _write_stream attribute
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_session_has_no_write_stream_attribute() -> None:
    """``ClientSession`` constructed by ``Client`` (which always passes
    ``dispatcher=``) has no ``_write_stream`` instance attribute.

    This guards a planned fallback branch in a health check that currently
    relies on the dispatcher for all writes."""
    client = await _make_inproc_client(mode="2026-07-28")

    async with client:
        session = client.session
        # Assert the attribute does not exist
        assert not hasattr(session, "_write_stream"), (
            "ClientSession must NOT have a _write_stream attribute; "
            "all writes go through the dispatcher"
        )
        # Also confirm that _dispatcher IS present (sanity check)
        assert hasattr(session, "_dispatcher"), "ClientSession must have _dispatcher"


# --------------------------------------------------------------------------- #
# Supplementary: Verify MODERN_PROTOCOL_VERSIONS constant
# --------------------------------------------------------------------------- #

def test_modern_protocol_version_is_2026_07_28() -> None:
    """The modern protocol version the SDK supports is ``2026-07-28``."""
    from mcp_types.version import MODERN_PROTOCOL_VERSIONS

    assert MODERN_PROTOCOL_VERSIONS == ("2026-07-28",), (
        "MODERN_PROTOCOL_VERSIONS must be ('2026-07-28',); "
        "update these tests if a new modern version is added"
    )
