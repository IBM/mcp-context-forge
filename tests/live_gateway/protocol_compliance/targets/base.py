# -*- coding: utf-8 -*-
"""Location: ./tests/protocol_compliance/targets/base.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

ComplianceTarget abstraction.

A target is a runnable MCP endpoint plus the logic to construct a FastMCP
`Client` bound to it over a given transport. Each target declares which
transports it supports; the parametrized `client` fixture then enumerates
every `(target, transport)` pair the harness should exercise.

Subclass contract (enforced at class-definition time via
``__init_subclass__``):
  * Set ``name`` to a non-empty ``ClassVar[str]``.
  * Set ``supported_transports`` to a non-empty
    ``ClassVar[frozenset[Transport]]``.
  * Implement ``async def _open_client(transport, **kwargs)`` as an async
    context manager yielding a connected ``Client``.

Subclasses do **not** implement ``client()`` — the base class validates
the transport against ``supported_transports`` before dispatching to
``_open_client``. This removes the triplicated ``if transport != "X":
raise NotImplementedError`` boilerplate previously present in every
subclass and makes the advertised / implemented transport sets
impossible to disagree.
"""

from __future__ import annotations

import abc
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import AsyncIterator, ClassVar, Literal

from fastmcp.client import Client

Transport = Literal["stdio", "sse", "http"]


class ComplianceTarget(abc.ABC):
    """A connectable MCP endpoint under test."""

    name: ClassVar[str]
    supported_transports: ClassVar[frozenset[Transport]]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Abstract subclasses are allowed to defer the declarations to
        # concrete subclasses; concrete ones must satisfy the contract.
        if abc.ABC in cls.__bases__:
            return
        if not isinstance(getattr(cls, "name", None), str) or not cls.name:
            raise TypeError(f"{cls.__name__} must set a non-empty `name: ClassVar[str]`")
        if not isinstance(getattr(cls, "supported_transports", None), frozenset) or not cls.supported_transports:
            raise TypeError(f"{cls.__name__} must set a non-empty `supported_transports: ClassVar[frozenset[Transport]]`")

    @abc.abstractmethod
    def _open_client(self, transport: Transport, **client_kwargs: object) -> AbstractAsyncContextManager[Client]:
        """Return an async context manager yielding a connected Client.

        Concrete targets open the transport, run the initialize handshake
        via FastMCP's ``Client`` constructor, and tear down on exit.
        The base class guarantees ``transport`` is in
        ``supported_transports`` when this is called, so implementations
        don't need to re-check.
        """

    @asynccontextmanager
    async def client(self, transport: Transport, **client_kwargs: object) -> AsyncIterator[Client]:
        """Validate transport support then dispatch to ``_open_client``.

        This is the single entry point the harness uses. Rejecting an
        unsupported transport here is an early hard error (rather than
        letting each subclass pick its own ``NotImplementedError``
        wording) so the matrix skip attribution stays consistent.
        """
        if transport not in self.supported_transports:
            raise NotImplementedError(f"{type(self).__name__} does not support transport {transport!r}; " f"supported: {sorted(self.supported_transports)}")
        async with self._open_client(transport, **client_kwargs) as connected:
            yield connected
