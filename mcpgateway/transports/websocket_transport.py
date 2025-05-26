# -*- coding: utf-8 -*-
"""WebSocket Transport Implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module implements WebSocket transport for MCP, providing
full-duplex communication between client and server.
"""

import asyncio
import logging
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

from mcpgateway.config import settings
from mcpgateway.transports.base import Transport

logger = logging.getLogger(__name__)


class WebSocketTransport(Transport):
    """Transport implementation using WebSocket."""

    def __init__(self, websocket: WebSocket):
        """Initialize WebSocket transport.

        Args:
            websocket: FastAPI WebSocket connection
        """
        self._websocket = websocket
        self._connected = False
        self._ping_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """Set up WebSocket connection."""
        await self._websocket.accept()
        self._connected = True

        # Start ping task
        if settings.websocket_ping_interval > 0:
            self._ping_task = asyncio.create_task(self._ping_loop())

        logger.info("WebSocket transport connected")

    async def disconnect(self) -> None:
        """Clean up WebSocket connection."""
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass

        if self._connected:
            await self._websocket.close()
            self._connected = False
            logger.info("WebSocket transport disconnected")

    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send a message over WebSocket.

        Args:
            message: Message to send

        Raises:
            RuntimeError: If transport is not connected
            Exception: If unable to send json to websocket
        """
        if not self._connected:
            raise RuntimeError("Transport not connected")

        try:
            await self._websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            raise

    async def receive_message(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Receive messages from WebSocket.

        Yields:
            Received messages

        Raises:
            RuntimeError: If transport is not connected
        """
        if not self._connected:
            raise RuntimeError("Transport not connected")

        try:
            while True:
                message = await self._websocket.receive_json()
                yield message

        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
            self._connected = False
        except Exception as e:
            logger.error(f"Error receiving message: {e}")
            self._connected = False
        finally:
            await self.disconnect()

    async def is_connected(self) -> bool:
        """Check if transport is connected.

        Returns:
            True if connected
        """
        return self._connected

    async def _ping_loop(self) -> None:
        """Send periodic ping messages to keep connection alive."""
        try:
            while self._connected:
                await asyncio.sleep(settings.websocket_ping_interval)
                await self._websocket.send_bytes(b"ping")
                try:
                    resp = await asyncio.wait_for(
                        self._websocket.receive_bytes(),
                        timeout=settings.websocket_ping_interval / 2,
                    )
                    if resp != b"pong":
                        logger.warning("Invalid ping response")
                except asyncio.TimeoutError:
                    logger.warning("Ping timeout")
                    break
        except Exception as e:
            logger.error(f"Ping loop error: {e}")
        finally:
            await self.disconnect()

    async def send_ping(self) -> None:
        """Send a manual ping message."""
        if self._connected:
            await self._websocket.send_bytes(b"ping")
