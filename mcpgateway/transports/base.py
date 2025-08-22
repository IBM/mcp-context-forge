# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/transports/base.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Base Transport Interface.
This module defines the base protocol for MCP transports.
"""

# Standard
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict


class Transport(ABC):
    """Base class for MCP transport implementations.

    This abstract base class defines the interface that all MCP transport
    implementations must follow. It provides the core methods for connection
    management and message exchange.

    Examples:
        >>> # Transport is abstract and cannot be instantiated directly
        >>> try:
        ...     Transport()
        ... except TypeError as e:
        ...     print("Cannot instantiate abstract class")
        Cannot instantiate abstract class

        >>> # Check if Transport is an abstract base class
        >>> from abc import ABC
        >>> issubclass(Transport, ABC)
        True

        >>> # Verify abstract methods are defined
        >>> hasattr(Transport, 'connect')
        True
        >>> hasattr(Transport, 'disconnect')
        True
        >>> hasattr(Transport, 'send_message')
        True
        >>> hasattr(Transport, 'receive_message')
        True
        >>> hasattr(Transport, 'is_connected')
        True
    """

    @abstractmethod
    async def connect(self) -> None:
        """Initialize transport connection.

        This method should establish the underlying connection for the transport.
        It must be called before sending or receiving messages.

        Examples:
            >>> # This is an abstract method - implementation required in subclasses
            >>> import inspect
            >>> inspect.ismethod(Transport.connect)
            False
            >>> hasattr(Transport, 'connect')
            True
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Close transport connection.

        This method should clean up the underlying connection and any associated
        resources. It should be called when the transport is no longer needed.

        Examples:
            >>> # This is an abstract method - implementation required in subclasses
            >>> import inspect
            >>> inspect.ismethod(Transport.disconnect)
            False
            >>> hasattr(Transport, 'disconnect')
            True
        """

    @abstractmethod
    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send a message over the transport.

        Args:
            message: Message to send

        Examples:
            >>> # This is an abstract method - implementation required in subclasses
            >>> import inspect
            >>> inspect.ismethod(Transport.send_message)
            False
            >>> hasattr(Transport, 'send_message')
            True
        """

    @abstractmethod
    async def receive_message(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Receive messages from the transport.

        Yields:
            Received messages

        Examples:
            >>> # This is an abstract method - implementation required in subclasses
            >>> import inspect
            >>> inspect.ismethod(Transport.receive_message)
            False
            >>> hasattr(Transport, 'receive_message')
            True
        """

    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if transport is connected.

        Returns:
            True if connected

        Examples:
            >>> # This is an abstract method - implementation required in subclasses
            >>> import inspect
            >>> inspect.ismethod(Transport.is_connected)
            False
            >>> hasattr(Transport, 'is_connected')
            True
        """
