# -*- coding: utf-8 -*-
"""Unit tests for Federation Discovery Service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive unit tests for the discovery service module.
"""

# tests/test_discovery.py
import asyncio
from datetime import datetime

import pytest

from mcpgateway.federation.discovery import (
    PROTOCOL_VERSION,
    DiscoveryService,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def discovery():
    """
    Provide a DiscoveryService instance whose network-touching method
    `_get_gateway_info` is monkey-patched so no real HTTP requests are made.
    """
    ds = DiscoveryService()

    async def _fake_gateway_info(url: str):  # noqa: D401, ANN001
        # Return an *empty* capabilities object – structure is unimportant here.
        from mcpgateway.types import ServerCapabilities

        return ServerCapabilities()

    # Patch the network call
    ds._get_gateway_info = _fake_gateway_info  # type: ignore[attr-defined]

    yield ds
    await ds.stop()  # ensure graceful cleanup


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_add_peer_success(discovery):
    added = await discovery.add_peer("http://example.com", source="test", name="Example")
    assert added is True, "first call should add the peer"

    peers = discovery.get_discovered_peers()
    assert len(peers) == 1
    peer = peers[0]

    assert peer.url == "http://example.com"
    assert peer.name == "Example"
    assert peer.protocol_version == PROTOCOL_VERSION
    assert peer.source == "test"


@pytest.mark.anyio
async def test_add_duplicate_peer_is_ignored(discovery):
    await discovery.add_peer("http://dup.com", source="test")
    second_add = await discovery.add_peer("http://dup.com", source="test-again")
    assert second_add is False, "duplicate add should be a no-op"

    peers = discovery.get_discovered_peers()
    assert len(peers) == 1, "still only one peer stored"


@pytest.mark.anyio
async def test_add_peer_invalid_url_returns_false(discovery):
    added = await discovery.add_peer("not-a-valid-url", source="test")
    assert added is False
    assert discovery.get_discovered_peers() == []


@pytest.mark.anyio
async def test_refresh_peer_updates_last_seen(discovery):
    await discovery.add_peer("http://refresh.me", source="test")
    peer = discovery.get_discovered_peers()[0]
    first_seen = peer.last_seen

    # Wait a moment to ensure a measurable delta
    await asyncio.sleep(0.01)

    refreshed = await discovery.refresh_peer("http://refresh.me")
    assert refreshed is True
    assert peer.last_seen > first_seen
