# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/dataplane_publisher/dataplane_publisher.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Dataplane publisher background service for periodic and event-driven configuration syncing.
"""

# Standard
import asyncio
import logging
import os
import random
import socket
from weakref import WeakSet

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.dataplane_publisher.dataplane_schema import UserConfig
from mcpgateway.services.dataplane_publisher.db_loader import get_user_configs
from mcpgateway.services.dataplane_publisher.redis_store import DataplaneRedisStore

logger = logging.getLogger(__name__)

PUBLISHER_DEBOUNCE_SECONDS = 1
PUBLISHER_RETRY_RAND_SECONDS = (2, 5)


_listeners: WeakSet[asyncio.Event] = WeakSet()


def register_publisher(event: asyncio.Event) -> None:
    """Register a running publisher notification event"""
    _listeners.add(event)


def unregister_publisher(event: asyncio.Event) -> None:
    """Remove a stopped publisher notification event."""
    _listeners.discard(event)


def notify_dataplane() -> None:
    """Request a new db read and publish"""
    for event in tuple(_listeners):
        event.set()


def get_publisher_interval() -> int:
    """Return the configured interval between dataplane publish."""
    return settings.dataplane_publisher_interval_seconds


class DataplanePublisherService:
    """Publish user routing data to Redis using the UserConfig contract."""

    def __init__(self) -> None:
        """Initialize the user configuration publisher."""
        self.task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        self._publish_requested = asyncio.Event()
        # Workers must compute ownership after fork
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self._store = DataplaneRedisStore(self.worker_id)

    async def start(self) -> None:
        """Start the background publisher task."""
        if self.task is not None and not self.task.done():
            logger.warning("Dataplane publisher is already running.")
            return
        self._shutdown_event.clear()
        self._publish_requested.clear()
        self.task = asyncio.create_task(self.publish_to_redis())
        register_publisher(self._publish_requested)
        self.task.add_done_callback(self._publisher_done)
        logger.info("Dataplane publisher started.")

    def _publisher_done(self, task: asyncio.Task[None]) -> None:
        """Remove the listener when its owning task exits."""
        if task is self.task:
            unregister_publisher(self._publish_requested)

    async def notify_dataplane(self) -> None:
        """Request a data load while this publisher runs on the current event loop."""
        if self.task is not None and not self.task.done() and not self._shutdown_event.is_set():
            self._publish_requested.set()

    async def shutdown(self) -> None:
        """Gracefully shutdown the publisher."""
        unregister_publisher(self._publish_requested)
        if self.task is None:
            return
        logger.info("Shutting down dataplane publisher.")
        self._shutdown_event.set()
        try:
            await asyncio.wait_for(self.task, timeout=5)
        except asyncio.TimeoutError:
            logger.warning("Dataplane publisher shutdown timed out; cancelling task.")
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            current_task = asyncio.current_task()
            if current_task is not None and current_task.cancelling():
                raise
        finally:
            self.task = None
            self._publish_requested.clear()
        logger.info("Dataplane publisher stopped.")

    async def fetch_payload(self) -> dict[str, UserConfig] | None:
        """Load visible routing configurations for all active users."""
        try:
            return get_user_configs()
        except Exception as err:
            logger.error("Could not build dataplane payload data from the database: %s", err)
            return None

    async def publish_to_redis(self) -> None:
        """Publish full data on notification and at the configured interval."""
        while not self._shutdown_event.is_set():
            publisher_interval = get_publisher_interval()
            published = await self._publish(publisher_interval)
            if not published and self._publish_requested.is_set():
                if await self._wait_for_shutdown(random.uniform(*PUBLISHER_RETRY_RAND_SECONDS)):
                    break
            elif await self._wait_for_next_publish(publisher_interval):
                break

    async def _wait_for_shutdown(self, timeout: float) -> bool:
        """Wait for shutdown without letting pending notifications bypass backoff.

        Args:
            timeout: Maximum wait in seconds.

        Returns:
            Whether shutdown was requested.
        """
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return self._shutdown_event.is_set()

    async def _wait_for_next_publish(self, interval: float) -> bool:
        """Publish on scheduled time or wait for the Debounce, to avoid multiple publish requests
        wait until:
            shutdown requested
            OR publish requested
            OR timeout reached
        then cancel other tasks.
        """
        waiters = [asyncio.create_task(self._shutdown_event.wait()), asyncio.create_task(self._publish_requested.wait())]
        try:
            await asyncio.wait(waiters, timeout=interval, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
        if self._shutdown_event.is_set():
            return True
        if self._publish_requested.is_set():
            return await self._wait_for_shutdown(PUBLISHER_DEBOUNCE_SECONDS)
        return False

    async def _publish(self, publisher_interval: int) -> bool:
        """Attempt to publish while retaining notifications on failure.

        Args:
            publisher_interval: Configured interval used for Redis TTLs.

        Returns:
            Whether the data was written successfully.
        """
        had_pending_notification = False
        published = False
        acquired = False
        try:
            redis, acquired = await self._store.try_acquire_lock(publisher_interval + 30)
            if not acquired:
                return False
            had_pending_notification = self._publish_requested.is_set()
            self._publish_requested.clear()
            logger.info("Worker %s publishing dataplane payload...", self.worker_id)
            payload = await self.fetch_payload()
            if payload is None:
                logger.warning("Skipping publish cycle due to data fetch failure - keeping existing Redis data")
                return False
            await self._store.write_payload(redis, payload, ttl=publisher_interval * 2 + 10)
            published = True
            return True
        except Exception as e:
            logger.error("Error during publish: %s", e)
            return False
        finally:
            if had_pending_notification and not published:
                self._publish_requested.set()
            if acquired:
                await self._store.release_lock(redis)
