# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_log_config_watcher.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Authors: ContextForge Team

Unit tests for LogConfigWatcher and read_log_level_from_config.

Covers:
- read_log_level_from_config(): valid YAML, missing file, bad YAML, invalid level
- LogConfigWatcher.start(): happy path, already running guard, missing path, missing file
- LogConfigWatcher.stop(): active and idle paths
- LogConfigWatcher._on_config_change(): delegates to _load_and_apply_config
- LogConfigWatcher._load_and_apply_config(): level change, unchanged level, deleted file, invalid level
- get_log_config_watcher() singleton behaviour
"""

# Standard
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
import yaml

# First-Party
from mcpgateway.common.models import LogLevel
from mcpgateway.services.file_watcher_service import ChangeType, FileChangeEvent
from mcpgateway.services.log_config_watcher import (
    LogConfigWatcher,
    get_log_config_watcher,
    read_log_level_from_config,
)


# ---------------------------------------------------------------------------
# read_log_level_from_config
# ---------------------------------------------------------------------------


def test_read_log_level_valid(tmp_path):
    """Returns uppercase level string for a valid YAML config."""
    cfg = tmp_path / "log.yaml"
    cfg.write_text("level: debug\n")
    assert read_log_level_from_config(str(cfg)) == "DEBUG"


def test_read_log_level_already_uppercase(tmp_path):
    """Returns level unchanged when already uppercase."""
    cfg = tmp_path / "log.yaml"
    cfg.write_text("level: WARNING\n")
    assert read_log_level_from_config(str(cfg)) == "WARNING"


def test_read_log_level_missing_file(tmp_path):
    """Returns None when the file does not exist."""
    result = read_log_level_from_config(str(tmp_path / "nonexistent.yaml"))
    assert result is None


def test_read_log_level_invalid_yaml(tmp_path):
    """Returns None when the file contains invalid YAML."""
    cfg = tmp_path / "bad.yaml"
    cfg.write_text(": : : this is not valid yaml :::\n")
    result = read_log_level_from_config(str(cfg))
    assert result is None


def test_read_log_level_non_dict_yaml(tmp_path):
    """Returns None when YAML root is not a mapping."""
    cfg = tmp_path / "list.yaml"
    cfg.write_text("- item1\n- item2\n")
    result = read_log_level_from_config(str(cfg))
    assert result is None


def test_read_log_level_missing_key(tmp_path):
    """Returns None when the 'level' key is absent."""
    cfg = tmp_path / "nokey.yaml"
    cfg.write_text("other: value\n")
    result = read_log_level_from_config(str(cfg))
    assert result is None


def test_read_log_level_empty_value(tmp_path):
    """Returns None when 'level' is null/empty."""
    cfg = tmp_path / "empty.yaml"
    cfg.write_text("level:\n")
    result = read_log_level_from_config(str(cfg))
    assert result is None


def test_read_log_level_invalid_value(tmp_path):
    """Returns None and logs a warning for an unrecognised level string."""
    cfg = tmp_path / "bad_level.yaml"
    cfg.write_text("level: VERBOSENESS\n")
    result = read_log_level_from_config(str(cfg))
    assert result is None


def test_read_log_level_all_valid_levels(tmp_path):
    """All LogLevel enum members are accepted."""
    for level in LogLevel:
        cfg = tmp_path / f"log_{level.value}.yaml"
        cfg.write_text(f"level: {level.value}\n")
        assert read_log_level_from_config(str(cfg)) == level.value.upper()


# ---------------------------------------------------------------------------
# LogConfigWatcher.start()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_happy_path(tmp_path):
    """start() registers a watcher and sets _running=True."""
    cfg = tmp_path / "log.yaml"
    cfg.write_text("level: info\n")

    mock_logging_service = MagicMock()
    mock_logging_service.set_level = AsyncMock()

    mock_file_watcher = AsyncMock()
    mock_file_watcher.watch = AsyncMock(return_value="handler-id-1")

    with patch("mcpgateway.services.log_config_watcher.get_file_watcher_service", return_value=mock_file_watcher):
        watcher = LogConfigWatcher(mock_logging_service)
        await watcher.start(str(cfg))

    assert watcher.is_running is True
    assert watcher._watch_id == "handler-id-1"


@pytest.mark.asyncio
async def test_start_already_running_is_noop(tmp_path):
    """start() is a no-op when the watcher is already running."""
    cfg = tmp_path / "log.yaml"
    cfg.write_text("level: info\n")

    mock_logging_service = MagicMock()
    mock_logging_service.set_level = AsyncMock()

    mock_file_watcher = AsyncMock()
    mock_file_watcher.watch = AsyncMock(return_value="handler-id-2")

    with patch("mcpgateway.services.log_config_watcher.get_file_watcher_service", return_value=mock_file_watcher):
        watcher = LogConfigWatcher(mock_logging_service)
        await watcher.start(str(cfg))
        # Second call — watch() must NOT be called again
        await watcher.start(str(cfg))

    assert mock_file_watcher.watch.call_count == 1


@pytest.mark.asyncio
async def test_start_raises_without_config_path():
    """start() raises RuntimeError when no config_path is provided."""
    mock_logging_service = MagicMock()
    mock_file_watcher = AsyncMock()

    with patch("mcpgateway.services.log_config_watcher.get_file_watcher_service", return_value=mock_file_watcher):
        watcher = LogConfigWatcher(mock_logging_service)
        with pytest.raises(RuntimeError, match="must be provided"):
            await watcher.start(config_path=None)


@pytest.mark.asyncio
async def test_start_raises_for_missing_file(tmp_path):
    """start() raises FileNotFoundError when the config file does not exist."""
    mock_logging_service = MagicMock()
    mock_file_watcher = AsyncMock()

    with patch("mcpgateway.services.log_config_watcher.get_file_watcher_service", return_value=mock_file_watcher):
        watcher = LogConfigWatcher(mock_logging_service)
        with pytest.raises(FileNotFoundError):
            await watcher.start(str(tmp_path / "ghost.yaml"))


@pytest.mark.asyncio
async def test_start_propagates_watch_error(tmp_path):
    """start() re-raises exceptions from FileWatcherService.watch()."""
    cfg = tmp_path / "log.yaml"
    cfg.write_text("level: info\n")

    mock_logging_service = MagicMock()
    mock_logging_service.set_level = AsyncMock()

    mock_file_watcher = AsyncMock()
    mock_file_watcher.watch = AsyncMock(side_effect=RuntimeError("watcher failed"))

    with patch("mcpgateway.services.log_config_watcher.get_file_watcher_service", return_value=mock_file_watcher):
        watcher = LogConfigWatcher(mock_logging_service)
        with pytest.raises(RuntimeError, match="watcher failed"):
            await watcher.start(str(cfg))

    assert watcher.is_running is False


# ---------------------------------------------------------------------------
# LogConfigWatcher.stop()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_when_running(tmp_path):
    """stop() calls unwatch and sets _running=False."""
    cfg = tmp_path / "log.yaml"
    cfg.write_text("level: info\n")

    mock_logging_service = MagicMock()
    mock_logging_service.set_level = AsyncMock()

    mock_file_watcher = AsyncMock()
    mock_file_watcher.watch = AsyncMock(return_value="wid-123")
    mock_file_watcher.unwatch = AsyncMock()

    with patch("mcpgateway.services.log_config_watcher.get_file_watcher_service", return_value=mock_file_watcher):
        watcher = LogConfigWatcher(mock_logging_service)
        await watcher.start(str(cfg))
        await watcher.stop()

    mock_file_watcher.unwatch.assert_called_once_with("wid-123")
    assert watcher.is_running is False
    assert watcher._watch_id is None


@pytest.mark.asyncio
async def test_stop_when_not_running():
    """stop() is a no-op when the watcher is not active."""
    mock_logging_service = MagicMock()
    watcher = LogConfigWatcher(mock_logging_service)
    await watcher.stop()  # must not raise
    assert watcher.is_running is False


# ---------------------------------------------------------------------------
# LogConfigWatcher._on_config_change()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_config_change_delegates_to_load_and_apply(tmp_path):
    """_on_config_change calls _load_and_apply_config with event.path."""
    cfg = tmp_path / "log.yaml"
    cfg.write_text("level: error\n")

    mock_logging_service = MagicMock()
    watcher = LogConfigWatcher(mock_logging_service)

    event = FileChangeEvent(
        change_type=ChangeType.MODIFIED,
        path=str(cfg),
        relative_path=cfg.name,
    )

    with patch.object(watcher, "_load_and_apply_config", new_callable=AsyncMock) as mock_load:
        await watcher._on_config_change(event)
        mock_load.assert_called_once_with(str(cfg))


@pytest.mark.asyncio
async def test_on_config_change_swallows_exceptions(tmp_path):
    """_on_config_change logs but does not propagate handler errors."""
    mock_logging_service = MagicMock()
    watcher = LogConfigWatcher(mock_logging_service)

    event = FileChangeEvent(
        change_type=ChangeType.MODIFIED,
        path="/nonexistent/path.yaml",
        relative_path="path.yaml",
    )

    with patch.object(watcher, "_load_and_apply_config", new_callable=AsyncMock, side_effect=RuntimeError("oops")):
        await watcher._on_config_change(event)  # must not raise


# ---------------------------------------------------------------------------
# LogConfigWatcher._load_and_apply_config()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_and_apply_updates_level(tmp_path):
    """_load_and_apply_config calls set_level when a new valid level is found."""
    cfg = tmp_path / "log.yaml"
    cfg.write_text("level: warning\n")

    mock_logging_service = MagicMock()
    mock_logging_service.set_level = AsyncMock()

    watcher = LogConfigWatcher(mock_logging_service)
    await watcher._load_and_apply_config(str(cfg))

    mock_logging_service.set_level.assert_called_once_with(LogLevel.WARNING)
    assert watcher._last_level == "warning"


@pytest.mark.asyncio
async def test_load_and_apply_skips_unchanged_level(tmp_path):
    """_load_and_apply_config skips set_level when the level hasn't changed."""
    cfg = tmp_path / "log.yaml"
    cfg.write_text("level: info\n")

    mock_logging_service = MagicMock()
    mock_logging_service.set_level = AsyncMock()

    watcher = LogConfigWatcher(mock_logging_service)
    watcher._last_level = "info"  # pre-set so it matches

    await watcher._load_and_apply_config(str(cfg))

    mock_logging_service.set_level.assert_not_called()


@pytest.mark.asyncio
async def test_load_and_apply_handles_deleted_file(tmp_path):
    """_load_and_apply_config preserves the current level when the file is missing."""
    cfg = tmp_path / "log.yaml"
    # Do NOT create the file — simulate deletion

    mock_logging_service = MagicMock()
    mock_logging_service.set_level = AsyncMock()

    watcher = LogConfigWatcher(mock_logging_service)
    watcher._last_level = "info"

    await watcher._load_and_apply_config(str(cfg))

    mock_logging_service.set_level.assert_not_called()
    assert watcher._last_level == "info"  # preserved


@pytest.mark.asyncio
async def test_load_and_apply_skips_invalid_level(tmp_path):
    """_load_and_apply_config skips set_level when config contains an invalid level."""
    cfg = tmp_path / "log.yaml"
    cfg.write_text("level: NONSENSE\n")

    mock_logging_service = MagicMock()
    mock_logging_service.set_level = AsyncMock()

    watcher = LogConfigWatcher(mock_logging_service)
    await watcher._load_and_apply_config(str(cfg))

    mock_logging_service.set_level.assert_not_called()


@pytest.mark.asyncio
async def test_load_and_apply_swallows_unexpected_exceptions(tmp_path):
    """_load_and_apply_config logs errors and does not propagate them."""
    cfg = tmp_path / "log.yaml"
    cfg.write_text("level: debug\n")

    mock_logging_service = MagicMock()
    mock_logging_service.set_level = AsyncMock(side_effect=RuntimeError("db exploded"))

    watcher = LogConfigWatcher(mock_logging_service)
    await watcher._load_and_apply_config(str(cfg))  # must not raise


# ---------------------------------------------------------------------------
# Level change detected between two consecutive reads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_level_transition_info_to_error(tmp_path):
    """set_level is called with the new level when level transitions from INFO to ERROR."""
    cfg = tmp_path / "log.yaml"
    cfg.write_text("level: info\n")

    mock_logging_service = MagicMock()
    mock_logging_service.set_level = AsyncMock()

    watcher = LogConfigWatcher(mock_logging_service)
    await watcher._load_and_apply_config(str(cfg))
    assert watcher._last_level == "info"

    # Simulate file update
    cfg.write_text("level: error\n")
    await watcher._load_and_apply_config(str(cfg))

    assert watcher._last_level == "error"
    assert mock_logging_service.set_level.call_count == 2
    mock_logging_service.set_level.assert_called_with(LogLevel.ERROR)


# ---------------------------------------------------------------------------
# get_log_config_watcher() singleton
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_log_config_watcher_returns_singleton():
    """get_log_config_watcher() returns the same instance on repeated calls."""
    import mcpgateway.services.log_config_watcher as lcw_module

    lcw_module._log_config_watcher = None  # reset singleton

    mock_logging_service = MagicMock()

    w1 = await get_log_config_watcher(mock_logging_service)
    w2 = await get_log_config_watcher(mock_logging_service)

    assert w1 is w2
    assert isinstance(w1, LogConfigWatcher)

    lcw_module._log_config_watcher = None  # restore
