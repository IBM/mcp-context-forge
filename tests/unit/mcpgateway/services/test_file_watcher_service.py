# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_file_watcher_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Authors: ContextForge Team

Unit tests for FileWatcherService.

Covers:
- watch() / unwatch() / stop_all() lifecycle
- FileChangeEvent and ChangeType dataclasses
- get_file_watcher_service() singleton
- _watch_loop() happy-path and error branches
- _convert_change_type() mapping
- FILE_WATCHER_ENABLED guard
"""

# Standard
import asyncio
import tempfile
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from watchfiles import Change

# First-Party
from mcpgateway.services.file_watcher_service import (
    ChangeType,
    FileChangeEvent,
    FileWatcherService,
    get_file_watcher_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler() -> AsyncMock:
    """Return an async callable that records every FileChangeEvent it receives."""
    handler = AsyncMock()
    handler.events: List[FileChangeEvent] = []

    async def _capture(event: FileChangeEvent) -> None:
        handler.events.append(event)
        await handler(event)

    return handler, _capture


# ---------------------------------------------------------------------------
# ChangeType / FileChangeEvent
# ---------------------------------------------------------------------------


def test_change_type_values():
    """ChangeType enum has the expected string values."""
    assert ChangeType.ADDED == "added"
    assert ChangeType.MODIFIED == "modified"
    assert ChangeType.DELETED == "deleted"


def test_file_change_event_fields():
    """FileChangeEvent stores all three fields correctly."""
    event = FileChangeEvent(
        change_type=ChangeType.MODIFIED,
        path="/tmp/foo.yaml",
        relative_path="foo.yaml",
    )
    assert event.change_type == ChangeType.MODIFIED
    assert event.path == "/tmp/foo.yaml"
    assert event.relative_path == "foo.yaml"


# ---------------------------------------------------------------------------
# _convert_change_type
# ---------------------------------------------------------------------------


def test_convert_change_type_added():
    assert FileWatcherService._convert_change_type(Change.added) == ChangeType.ADDED


def test_convert_change_type_modified():
    assert FileWatcherService._convert_change_type(Change.modified) == ChangeType.MODIFIED


def test_convert_change_type_deleted():
    assert FileWatcherService._convert_change_type(Change.deleted) == ChangeType.DELETED


def test_convert_change_type_unknown_falls_back_to_modified():
    """Any unknown Change value falls back to MODIFIED."""
    unknown = MagicMock()  # not a real Change enum member
    assert FileWatcherService._convert_change_type(unknown) == ChangeType.MODIFIED


# ---------------------------------------------------------------------------
# watch() guard: FILE_WATCHER_ENABLED=false
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_raises_when_disabled(tmp_path):
    """watch() raises RuntimeError when FILE_WATCHER_ENABLED=false."""
    test_file = tmp_path / "cfg.yaml"
    test_file.write_text("level: INFO")

    with patch("mcpgateway.services.file_watcher_service.settings") as mock_settings:
        mock_settings.file_watcher_enabled = False

        service = FileWatcherService()
        handler = AsyncMock()

        with pytest.raises(RuntimeError, match="File watcher is disabled"):
            await service.watch(str(test_file), handler)


# ---------------------------------------------------------------------------
# watch() validation errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_raises_for_missing_file(tmp_path):
    """watch() raises FileNotFoundError when the file does not exist."""
    with patch("mcpgateway.services.file_watcher_service.settings") as mock_settings:
        mock_settings.file_watcher_enabled = True

        service = FileWatcherService()
        handler = AsyncMock()

        with pytest.raises(FileNotFoundError):
            await service.watch(str(tmp_path / "nonexistent.yaml"), handler)


@pytest.mark.asyncio
async def test_watch_raises_for_directory(tmp_path):
    """watch() raises ValueError when the path is a directory."""
    with patch("mcpgateway.services.file_watcher_service.settings") as mock_settings:
        mock_settings.file_watcher_enabled = True

        service = FileWatcherService()
        handler = AsyncMock()

        with pytest.raises(ValueError, match="must be a file"):
            await service.watch(str(tmp_path), handler)


@pytest.mark.asyncio
async def test_watch_raises_for_sync_handler(tmp_path):
    """watch() raises ValueError when handler is not a coroutine function."""
    test_file = tmp_path / "cfg.yaml"
    test_file.write_text("level: INFO")

    with patch("mcpgateway.services.file_watcher_service.settings") as mock_settings:
        mock_settings.file_watcher_enabled = True

        service = FileWatcherService()

        def sync_handler(event):
            pass

        with pytest.raises(ValueError, match="async function"):
            await service.watch(str(test_file), sync_handler)


# ---------------------------------------------------------------------------
# watch() / unwatch() happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_returns_handler_id_and_stores_config(tmp_path):
    """watch() returns a non-empty string handler ID and stores watcher config."""
    test_file = tmp_path / "cfg.yaml"
    test_file.write_text("level: INFO")

    with patch("mcpgateway.services.file_watcher_service.settings") as mock_settings:
        mock_settings.file_watcher_enabled = True
        # Patch awatch so the loop doesn't actually run
        with patch("mcpgateway.services.file_watcher_service.awatch") as mock_awatch:
            mock_awatch.return_value = _async_empty_iterator()

            service = FileWatcherService()
            handler = AsyncMock()
            handler_id = await service.watch(str(test_file), handler)

            assert isinstance(handler_id, str)
            assert len(handler_id) > 0
            assert handler_id in service._watch_configs
            assert handler_id in service._watchers

            # Cleanup
            await service.stop_all()


@pytest.mark.asyncio
async def test_unwatch_returns_true_for_known_handler(tmp_path):
    """unwatch() returns True and removes the watcher entry."""
    test_file = tmp_path / "cfg.yaml"
    test_file.write_text("level: INFO")

    with patch("mcpgateway.services.file_watcher_service.settings") as mock_settings:
        mock_settings.file_watcher_enabled = True
        with patch("mcpgateway.services.file_watcher_service.awatch") as mock_awatch:
            mock_awatch.return_value = _async_empty_iterator()

            service = FileWatcherService()
            handler = AsyncMock()
            handler_id = await service.watch(str(test_file), handler)

            result = await service.unwatch(handler_id)

            assert result is True
            assert handler_id not in service._watchers
            assert handler_id not in service._watch_configs


@pytest.mark.asyncio
async def test_unwatch_returns_false_for_unknown_handler():
    """unwatch() returns False when the handler ID is not found."""
    service = FileWatcherService()
    result = await service.unwatch("00000000-0000-0000-0000-000000000000")
    assert result is False


# ---------------------------------------------------------------------------
# stop_all()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_all_clears_watchers(tmp_path):
    """stop_all() cancels all tasks and empties internal dicts."""
    test_file = tmp_path / "cfg.yaml"
    test_file.write_text("level: INFO")

    with patch("mcpgateway.services.file_watcher_service.settings") as mock_settings:
        mock_settings.file_watcher_enabled = True
        with patch("mcpgateway.services.file_watcher_service.awatch") as mock_awatch:
            mock_awatch.return_value = _async_empty_iterator()

            service = FileWatcherService()
            handler = AsyncMock()
            await service.watch(str(test_file), handler)

            await service.stop_all()

            assert len(service._watchers) == 0
            assert len(service._watch_configs) == 0


@pytest.mark.asyncio
async def test_stop_all_with_no_watchers():
    """stop_all() is a no-op when there are no active watchers."""
    service = FileWatcherService()
    await service.stop_all()  # should not raise
    assert len(service._watchers) == 0


# ---------------------------------------------------------------------------
# get_active_watchers()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_watchers_returns_paths(tmp_path):
    """get_active_watchers() returns a dict with path keys."""
    test_file = tmp_path / "cfg.yaml"
    test_file.write_text("level: INFO")

    with patch("mcpgateway.services.file_watcher_service.settings") as mock_settings:
        mock_settings.file_watcher_enabled = True
        with patch("mcpgateway.services.file_watcher_service.awatch") as mock_awatch:
            mock_awatch.return_value = _async_empty_iterator()

            service = FileWatcherService()
            handler = AsyncMock()
            handler_id = await service.watch(str(test_file), handler)

            active = service.get_active_watchers()
            assert handler_id in active
            assert active[handler_id]["path"] == str(test_file)

            # handler key must NOT be exposed externally
            assert "handler" not in active[handler_id]

            await service.stop_all()


# ---------------------------------------------------------------------------
# _watch_loop() – event delivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_loop_delivers_events_to_handler(tmp_path):
    """_watch_loop delivers FileChangeEvents to the registered handler."""
    test_file = tmp_path / "cfg.yaml"
    test_file.write_text("level: INFO")

    received: List[FileChangeEvent] = []

    async def handler(event: FileChangeEvent) -> None:
        received.append(event)

    fake_changes = [{(Change.modified, str(test_file))}]

    with patch("mcpgateway.services.file_watcher_service.awatch") as mock_awatch:
        mock_awatch.return_value = _async_iterator_from(fake_changes)

        service = FileWatcherService()
        await service._watch_loop(
            handler_id="test-id-1234",
            watch_dir=test_file.parent,
            target_file=test_file,
            handler=handler,
        )

    assert len(received) == 1
    assert received[0].change_type == ChangeType.MODIFIED
    assert received[0].relative_path == test_file.name


@pytest.mark.asyncio
async def test_watch_loop_swallows_handler_exceptions(tmp_path):
    """_watch_loop logs but does not propagate exceptions raised in the handler."""
    test_file = tmp_path / "cfg.yaml"
    test_file.write_text("level: INFO")

    async def bad_handler(event: FileChangeEvent) -> None:
        raise ValueError("handler exploded")

    fake_changes = [{(Change.added, str(test_file))}]

    with patch("mcpgateway.services.file_watcher_service.awatch") as mock_awatch:
        mock_awatch.return_value = _async_iterator_from(fake_changes)

        service = FileWatcherService()
        # Should not raise
        await service._watch_loop(
            handler_id="test-id-5678",
            watch_dir=test_file.parent,
            target_file=test_file,
            handler=bad_handler,
        )


@pytest.mark.asyncio
async def test_watch_loop_propagates_non_cancelled_exceptions(tmp_path):
    """_watch_loop re-raises unexpected errors from awatch."""
    test_file = tmp_path / "cfg.yaml"
    test_file.write_text("level: INFO")

    async def handler(event: FileChangeEvent) -> None:
        pass

    with patch("mcpgateway.services.file_watcher_service.awatch", side_effect=RuntimeError("boom")):
        service = FileWatcherService()
        with pytest.raises(RuntimeError, match="boom"):
            await service._watch_loop(
                handler_id="test-id-abcd",
                watch_dir=test_file.parent,
                target_file=test_file,
                handler=handler,
            )


@pytest.mark.asyncio
async def test_watch_loop_reraises_cancelled_error(tmp_path):
    """_watch_loop re-raises CancelledError after logging."""
    test_file = tmp_path / "cfg.yaml"
    test_file.write_text("level: INFO")

    async def handler(event: FileChangeEvent) -> None:
        pass

    with patch("mcpgateway.services.file_watcher_service.awatch", side_effect=asyncio.CancelledError):
        service = FileWatcherService()
        with pytest.raises(asyncio.CancelledError):
            await service._watch_loop(
                handler_id="test-id-efgh",
                watch_dir=test_file.parent,
                target_file=test_file,
                handler=handler,
            )


# ---------------------------------------------------------------------------
# get_file_watcher_service() singleton
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_file_watcher_service_returns_singleton():
    """get_file_watcher_service() returns the same instance on repeated calls."""
    import mcpgateway.services.file_watcher_service as fws_module

    # Reset singleton so the test is deterministic regardless of import order
    fws_module._file_watcher_service = None

    svc1 = await get_file_watcher_service()
    svc2 = await get_file_watcher_service()

    assert svc1 is svc2
    assert isinstance(svc1, FileWatcherService)

    # Restore so other tests get a fresh instance if needed
    fws_module._file_watcher_service = None


# ---------------------------------------------------------------------------
# Async iterator helpers
# ---------------------------------------------------------------------------


async def _async_empty_iterator():
    """Async generator that yields nothing (simulates an idle watcher)."""
    return
    yield  # pragma: no cover – makes this an async generator


async def _async_iterator_from(items):
    """Async generator that yields each item from a list, then stops."""
    for item in items:
        yield item
