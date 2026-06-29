# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/file_watcher_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Authors: ContextForge Team

Reusable file watcher service that monitors file system changes and notifies
registered handlers. Uses watchfiles library for efficient, async-native file
monitoring with native inotify support on Linux. Installed as a dependency of
uvicorn[standard].
"""

# Standard
import asyncio
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, Optional
import uuid

# Third-Party
from watchfiles import awatch, Change

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class ChangeType(str, Enum):
    """File change types."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass
class FileChangeEvent:
    """Event data for file changes.

    Attributes:
        change_type: Type of change (added, modified, deleted).
        path: Absolute path to the changed file.
        relative_path: Path relative to the watched directory.
    """

    change_type: ChangeType
    path: str
    relative_path: str


# Type alias for handler functions
FileChangeHandler = Callable[[FileChangeEvent], Coroutine[Any, Any, None]]


class FileWatcherService:
    """Service for monitoring file system changes with callback notifications.

    This service uses watchfiles (Rust-based, async-native) for efficient file
    monitoring. It supports multiple concurrent watchers, each with their own
    callback handlers.

    Features:
        - Async-native using watchfiles (native inotify on Linux)
        - Multiple concurrent watchers with independent handlers
        - Optional file filtering (glob patterns)
        - Recursive directory watching
        - Graceful error handling and recovery
        - Clean shutdown support

    Example:
        >>> watcher = FileWatcherService()
        >>> async def handler(event: FileChangeEvent):  # doctest: +SKIP
        ...     print(f"{event.change_type}: {event.path}")  # doctest: +SKIP
        >>> handler_id = await watcher.watch("./config", handler)  # doctest: +SKIP
        >>> # Later...
        >>> await watcher.unwatch(handler_id)  # doctest: +SKIP
    """

    def __init__(self) -> None:
        """Initialize the file watcher service."""
        self._watchers: Dict[str, asyncio.Task[None]] = {}
        self._watch_configs: Dict[str, Dict[str, Any]] = {}
        self._shutdown_event = asyncio.Event()
        logger.info("FileWatcherService initialized")

    async def watch(
        self,
        path: str,
        handler: FileChangeHandler,
    ) -> str:
        """Start watching a file and notify handler on changes.

        Args:
            path: File path to watch (relative or absolute). Must be a file, not a directory.
                  Can be a symlink (e.g., Kubernetes ConfigMap) - will watch the parent directory
                  to handle atomic symlink swaps.
            handler: Async callback function to invoke on file changes.
                     Receives FileChangeEvent as argument.

        Returns:
            Unique handler ID that can be used to stop watching via unwatch().

        Raises:
            FileNotFoundError: If the specified file does not exist.
            ValueError: If path is a directory or handler is not a coroutine function.
            RuntimeError: If file watcher is disabled via FILE_WATCHER_ENABLED=false.

        Example:
            >>> async def my_handler(event: FileChangeEvent):  # doctest: +SKIP
            ...     print(f"Changed: {event.path}")  # doctest: +SKIP
            >>> handler_id = await watcher.watch("./config.yaml", my_handler)  # doctest: +SKIP
        """
        # Check if file watcher is enabled
        if not settings.file_watcher_enabled:
            logger.warning("File watcher is disabled (FILE_WATCHER_ENABLED=false). " "Enable it in configuration to use file watching.")
            raise RuntimeError("File watcher is disabled. Set FILE_WATCHER_ENABLED=true to enable.")

        watch_path = Path(path)

        if not watch_path.exists():
            raise FileNotFoundError(f"Watch path does not exist: {path}")

        if not watch_path.is_file() and not (watch_path.is_symlink() and watch_path.resolve().is_file()):
            raise ValueError(f"Watch path must be a file, not a directory: {path}")

        # Validate handler is async
        if not asyncio.iscoroutinefunction(handler):
            raise ValueError("Handler must be an async function (coroutine)")

        # Generate unique handler ID
        handler_id = str(uuid.uuid4())

        watch_dir = watch_path.parent
        self._watch_configs[handler_id] = {
            "path": str(watch_path),
            "watch_dir": str(watch_dir),
            "handler": handler,
        }

        task = asyncio.create_task(
            self._watch_loop(handler_id, watch_dir, watch_path, handler),
            name=f"file_watcher_{handler_id[:8]}",
        )
        self._watchers[handler_id] = task

        logger.info(f"Started file watcher {handler_id[:8]} for file: {path} (watching parent: {watch_dir})")

        return handler_id

    async def unwatch(self, handler_id: str) -> bool:
        """Stop watching a specific path.

        Args:
            handler_id: The handler ID returned by watch().

        Returns:
            True if watcher was stopped, False if handler_id not found.

        Example:
            >>> await watcher.unwatch(handler_id)  # doctest: +SKIP
        """
        if handler_id not in self._watchers:
            logger.warning(f"Handler ID not found: {handler_id[:8]}")
            return False

        # Cancel the watcher task
        task = self._watchers[handler_id]
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass  # Expected when cancelling

        # Cleanup
        del self._watchers[handler_id]
        del self._watch_configs[handler_id]

        logger.info(f"Stopped file watcher {handler_id[:8]}")
        return True

    async def stop_all(self) -> None:
        """Stop all active watchers and cleanup resources.

        This should be called during application shutdown to ensure
        all watcher tasks are properly cancelled.

        Example:
            >>> await watcher.stop_all()  # doctest: +SKIP
        """
        logger.info(f"Stopping all file watchers ({len(self._watchers)} active)")

        # Signal shutdown
        self._shutdown_event.set()

        # Cancel all watcher tasks
        for _handler_id, task in list(self._watchers.items()):
            task.cancel()

        # Wait for all tasks to complete
        if self._watchers:
            await asyncio.gather(*self._watchers.values(), return_exceptions=True)

        # Cleanup
        self._watchers.clear()
        self._watch_configs.clear()

        logger.info("All file watchers stopped")

    def get_active_watchers(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all active watchers.

        Returns:
            Dictionary mapping handler IDs to their configurations.

        Example:
            >>> watcher = FileWatcherService()
            >>> watchers = watcher.get_active_watchers()
            >>> for handler_id, config in watchers.items():  # doctest: +SKIP
            ...     print(f"{handler_id}: watching {config['path']}")  # doctest: +SKIP
        """
        return {
            handler_id: {
                "path": config["path"],
            }
            for handler_id, config in self._watch_configs.items()
        }

    async def _watch_loop(
        self,
        handler_id: str,
        watch_dir: Path,
        target_file: Path,
        handler: FileChangeHandler,
    ) -> None:
        """Internal watch loop that monitors file changes.

        Args:
            handler_id: Unique identifier for this watcher.
            watch_dir: Parent directory to watch.
            target_file: Specific file to monitor within the directory.
            handler: Callback function to invoke on changes.
        """
        try:
            logger.debug(f"Watch loop started for {handler_id[:8]}: watching {watch_dir} for changes to {target_file.name}")

            # Watch parent directory but use watch_filter to only get events for our target file
            # This reduces noise from other files in the directory
            target_filename = target_file.name

            async for changes in awatch(
                watch_dir,
                recursive=False,
                stop_event=self._shutdown_event,
                watch_filter=lambda change, path: Path(path).name == target_filename,
            ):
                for change_type_raw, changed_path in changes:
                    change_type = self._convert_change_type(change_type_raw)
                    logger.debug(f"Processing {change_type} event for {changed_path}")

                    # Create event
                    event = FileChangeEvent(
                        change_type=change_type,
                        path=str(changed_path),
                        relative_path=target_file.name,
                    )

                    # Invoke handler
                    try:
                        await handler(event)
                    except Exception as e:
                        logger.error(
                            f"Error in file change handler {handler_id[:8]} " f"for {changed_path}: {e}",
                            exc_info=True,
                        )

        except asyncio.CancelledError:
            logger.debug(f"Watch loop cancelled for {handler_id[:8]}")
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error in watch loop {handler_id[:8]}: {e}",
                exc_info=True,
            )
            raise

    @staticmethod
    def _convert_change_type(change: Change) -> ChangeType:
        """Convert watchfiles.Change to our ChangeType enum.

        Args:
            change: watchfiles.Change enum value.

        Returns:
            Corresponding ChangeType enum value.
        """
        if change == Change.added:
            return ChangeType.ADDED
        elif change == Change.modified:
            return ChangeType.MODIFIED
        elif change == Change.deleted:
            return ChangeType.DELETED
        else:
            # Fallback for any future change types
            return ChangeType.MODIFIED


# Singleton instance for convenience
_file_watcher_service: Optional[FileWatcherService] = None
_file_watcher_lock = asyncio.Lock()


async def get_file_watcher_service() -> FileWatcherService:
    """Get or create the singleton FileWatcherService instance.

    Returns:
        The global FileWatcherService instance.

    Example:
        >>> watcher = await get_file_watcher_service()  # doctest: +SKIP
        >>> handler_id = await watcher.watch("./config", my_handler)  # doctest: +SKIP
    """
    global _file_watcher_service
    if _file_watcher_service is None:
        async with _file_watcher_lock:
            if _file_watcher_service is None:
                _file_watcher_service = FileWatcherService()
    return _file_watcher_service
