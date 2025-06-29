# -*- coding: utf-8 -*-
"""Base Transport Interface.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module defines the base protocol for MCP transports.
"""

# Standard
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict


class Transport(ABC):
    """Base class for MCP transport implementations."""

    @abstractmethod
    async def connect(self) -> None:
        """Initialize transport connection."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close transport connection."""

    @abstractmethod
    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send a message over the transport.

        Args:
            message: Message to send
        """

    @abstractmethod
    async def receive_message(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Receive messages from the transport.

        Yields:
            Received messages
        """

    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if transport is connected.

        Returns:
            True if connected
        """
