# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/log_config_watcher.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Log Configuration Watcher Implementation.

This module provides a handler for watching YAML log configuration files
and automatically reloading log levels when the configuration changes.

Configuration Format:
    level: INFO
"""

# Standard
import asyncio
import logging
from pathlib import Path
from typing import Optional

# Third-Party
import yaml

# First-Party
from mcpgateway.common.models import LogLevel
from mcpgateway.services.file_watcher_service import FileChangeEvent, FileWatcherService, get_file_watcher_service
from mcpgateway.services.logging_service import LoggingService

logger = logging.getLogger(__name__)


def read_log_level_from_config(config_path: str) -> Optional[str]:
    """Read log level from YAML config file.

    Args:
        config_path: Path to YAML config file (can be a symlink for Kubernetes ConfigMaps)

    Returns:
        Log level string (uppercase) if found and valid, None otherwise
    """
    try:
        config_file = Path(config_path)
        if not config_file.exists():
            return None

        content = config_file.read_text(encoding="utf-8")
        config = yaml.safe_load(content)
    except Exception as e:
        logger.debug(f"Could not read log config file: {e}")
        return None

    if not isinstance(config, dict):
        return None

    # Safe to call .get() on validated dict - cannot raise AttributeError/TypeError
    level_raw = config.get("level")
    if not level_raw:
        return None

    level_str = str(level_raw).upper()

    # Validate it's a valid LogLevel
    try:
        LogLevel(level_str.lower())
        return level_str
    except ValueError:
        logger.warning(f"Invalid log level in config file: {level_str}")
        return None


class LogConfigWatcher:
    """Watcher for YAML log configuration files that automatically reloads log levels.

    This class integrates with FileWatcherService to monitor YAML configuration files
    and automatically reload the root log level when the configuration changes.

    Configuration Format:
        level: INFO
    """

    def __init__(self, logging_service: LoggingService):
        """Initialize the log config watcher.

        Args:
            logging_service: The LoggingService instance to update log levels
        """
        self._watcher: Optional[FileWatcherService] = None
        self._logging_service = logging_service
        self._watch_id: Optional[str] = None
        self._running: bool = False
        self._last_level: Optional[str] = None

    async def start(self, config_path: Optional[str] = None) -> None:
        """Start watching the log configuration file.

        Args:
            config_path: Path to YAML config file to watch. If None, watcher will not start.

        Raises:
            RuntimeError: If file watcher is disabled (checked by FileWatcherService) or no config path provided
            FileNotFoundError: If config file doesn't exist
        """
        if self._running:
            logger.warning("Log config watcher already running")
            return

        # Initialize watcher if not already done
        if self._watcher is None:
            self._watcher = await get_file_watcher_service()

        # Require explicit config path
        if config_path is None:
            raise RuntimeError("Log config path must be provided to start watcher")

        watch_path = Path(config_path)

        if not watch_path.exists():
            raise FileNotFoundError(f"Log config file not found: {watch_path}")

        await self._load_and_apply_config(str(watch_path))
        try:
            self._watch_id = await self._watcher.watch(str(watch_path), self._on_config_change)
            self._running = True
            logger.info(f"Started watching log config file: {watch_path}")
        except Exception as e:
            logger.error(f"Failed to start log config watcher: {e}")
            raise

    async def stop(self) -> None:
        """Stop watching the log configuration file."""
        if not self._running:
            return

        if self._watch_id:
            await self._watcher.unwatch(self._watch_id)
            self._watch_id = None

        self._running = False
        logger.info("Stopped log config watcher")

    async def _on_config_change(self, event: FileChangeEvent) -> None:
        """Handle configuration file changes.

        Args:
            event: File change event from the watcher
        """
        try:
            logger.info(f"Log config file {event.change_type}: {event.relative_path}")
            await self._load_and_apply_config(event.path)
        except Exception as e:
            logger.error(f"Error processing log config change: {e}", exc_info=True)

    async def _load_and_apply_config(self, file_path: str) -> None:
        """Load YAML config and apply log level changes.

        If the config file is deleted, the current log level is preserved.
        This ensures stable logging behavior during file operations.

        Args:
            file_path: Path to the YAML config file
        """
        try:
            # Check if file exists before attempting to read
            config_file = Path(file_path)
            if not config_file.exists():
                logger.warning(f"Log config file deleted or not found: {file_path}. Keeping current log level: {self._last_level}")
                return

            # Use read_log_level_from_config for consistent parsing and validation
            new_level_str = read_log_level_from_config(file_path)

            if not new_level_str:
                logger.warning("No valid log level found in config file")
                return

            new_level = new_level_str.lower()

            # Check if level changed
            if new_level == self._last_level:
                logger.debug(f"Log level unchanged ({new_level}), no action needed")
                return

            logger.info(f"Log level changed from {self._last_level} to {new_level}")

            # Apply new log level using LogLevel enum
            log_level_enum = LogLevel(new_level)
            await self._logging_service.set_level(log_level_enum)
            self._last_level = new_level
            logger.info(f"Successfully updated log level to {new_level}")

        except Exception as e:
            logger.error(f"Error loading log config: {e}", exc_info=True)

    @property
    def is_running(self) -> bool:
        """Check if the log config watcher is currently running."""
        return self._running


# Singleton instance
_log_config_watcher: Optional[LogConfigWatcher] = None
_log_config_watcher_lock = asyncio.Lock()


async def get_log_config_watcher(logging_service: LoggingService) -> LogConfigWatcher:
    """Get the singleton LogConfigWatcher instance.

    Args:
        logging_service: The LoggingService instance to update log levels

    Returns:
        LogConfigWatcher: The singleton instance
    """
    global _log_config_watcher  # pylint: disable=global-statement
    if _log_config_watcher is None:
        async with _log_config_watcher_lock:
            if _log_config_watcher is None:
                _log_config_watcher = LogConfigWatcher(logging_service)
    return _log_config_watcher
