# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_root_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

# Standard
import asyncio
import os
from urllib.parse import urlparse

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.root_service import RootService, RootServiceError


@pytest.mark.asyncio
async def test_add_root_file_uri_and_name(tmp_path):
    service = RootService()
    # Add a filesystem path without a scheme
    dir_path = tmp_path / "mydir"
    # (no need to actually create it on disk for URI logic)
    root = await service.add_root(str(dir_path))
    # Should prefix with file://
    expected_uri = f"file://{dir_path}"
    assert root.uri == expected_uri
    # Name should be the basename of the path
    assert root.name == os.path.basename(urlparse(expected_uri).path)

    await service.shutdown()


@pytest.mark.asyncio
async def test_add_root_with_scheme():
    service = RootService()
    # Add an HTTP URI
    uri = "http://example.com/base/path"
    root = await service.add_root(uri)
    assert root.uri == uri
    # Name should be the basename of the URL path
    assert root.name == os.path.basename(urlparse(uri).path)

    await service.shutdown()


@pytest.mark.asyncio
async def test_add_root_duplicate_raises():
    service = RootService()
    uri = "http://example.com/foo"
    await service.add_root(uri)
    with pytest.raises(RootServiceError) as excinfo:
        await service.add_root(uri)
    assert "Root already exists" in str(excinfo.value)

    await service.shutdown()


@pytest.mark.asyncio
async def test_remove_root_and_list():
    service = RootService()
    uri = "http://example.com/to-remove"
    await service.add_root(uri)
    # Ensure it's listed
    roots = await service.list_roots()
    assert any(r.uri == uri for r in roots)

    # Remove it
    await service.remove_root(uri)
    roots_after = await service.list_roots()
    assert all(r.uri != uri for r in roots_after)

    await service.shutdown()


@pytest.mark.asyncio
async def test_remove_nonexistent_root_raises():
    service = RootService()
    with pytest.raises(RootServiceError) as excinfo:
        await service.remove_root("http://no.such.root")
    assert "Root not found" in str(excinfo.value)

    await service.shutdown()


@pytest.mark.asyncio
async def test_get_root_by_uri():
    """Getting a root by URI should return the correct root object."""
    service = RootService()
    uri = "http://example.com/get-test"
    custom_name = "Test Root"

    # Add a root with a custom name
    await service.add_root(uri, name=custom_name)

    # Retrieve the root by URI
    root = await service.get_root_by_uri(uri)

    # Verify properties
    assert root.uri == uri
    assert root.name == custom_name

    await service.shutdown()


@pytest.mark.asyncio
async def test_get_nonexistent_root_by_uri_raises():
    """Getting a nonexistent root should raise a RootServiceError."""
    service = RootService()

    with pytest.raises(RootServiceError) as excinfo:
        await service.get_root_by_uri("http://nonexistent.root")

    assert "Root not found" in str(excinfo.value)

    await service.shutdown()


@pytest.mark.asyncio
async def test_update_root():
    """Updating a root should modify its properties and notify subscribers."""
    service = RootService()
    uri = "http://example.com/update-test"
    initial_name = "Initial Name"
    updated_name = "Updated Name"

    # Add a root with initial name
    await service.add_root(uri, name=initial_name)

    # Track notifications via subscription
    notifications = []

    async def collect_notification():
        async for event in service.subscribe_changes():
            notifications.append(event)
            if event["type"] == "root_updated":
                break

    # Start subscription and wait a tick
    task = asyncio.create_task(collect_notification())
    await asyncio.sleep(0)

    # Update the root's name
    updated_root = await service.update_root(uri, name=updated_name)

    # Wait for notification
    await asyncio.wait_for(task, timeout=1.0)

    # Verify properties of returned root
    assert updated_root.name == updated_name
    assert updated_root.uri == uri

    # Verify notification was sent
    assert len(notifications) == 1
    assert notifications[0]["type"] == "root_updated"
    assert notifications[0]["data"]["name"] == updated_name
    assert notifications[0]["data"]["uri"] == uri

    # Verify the root in storage was updated
    stored_root = await service.get_root_by_uri(uri)
    assert stored_root.name == updated_name

    await service.shutdown()


@pytest.mark.asyncio
async def test_update_nonexistent_root_raises():
    """Updating a nonexistent root should raise a RootServiceError."""
    service = RootService()

    with pytest.raises(RootServiceError) as excinfo:
        await service.update_root("http://nonexistent.root", name="New Name")

    assert "Root not found" in str(excinfo.value)

    await service.shutdown()


@pytest.mark.asyncio
async def test_initialize_adds_default_roots(monkeypatch):
    # Pretend the app was configured with two default roots
    monkeypatch.setattr(settings, "default_roots", ["http://a.com", "local/path"])

    service = RootService()
    await service.initialize()

    # Cast the FileUrl objects to plain strings for comparison
    uris = {str(r.uri) for r in await service.list_roots()}

    # FileUrl normalises the HTTP URI to include a trailing slash
    assert "http://a.com/" in uris
    assert "file://local/path" in uris

    await service.shutdown()


@pytest.mark.asyncio
async def test_subscribe_changes_receives_events():
    service = RootService()
    events = []

    async def subscriber():
        async for ev in service.subscribe_changes():
            events.append(ev)
            if len(events) >= 2:  # expect "added" then "removed"
                break

    # Start subscription and give the event-loop one tick so the queue
    # is fully registered before we emit any events.
    task = asyncio.create_task(subscriber())
    await asyncio.sleep(0)

    # Add a root, then remove it again.
    r = await service.add_root("subscriber-test")
    await service.remove_root(str(r.uri).rstrip("/"))  # match stored key

    # Collect both events or time-out
    await asyncio.wait_for(task, timeout=1.0)

    assert events[0] == {"type": "root_added", "data": {"uri": r.uri, "name": r.name}}
    assert events[1] == {"type": "root_removed", "data": {"uri": r.uri}}

    await service.shutdown()
