# -*- coding: utf-8 -*-
"""A2AComplianceTarget abstraction.

Location: ./tests/live_gateway/a2a_compliance/targets/base.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

A target is a runnable A2A endpoint plus the logic to construct an
``a2a.client.Client`` bound to it over a given transport. Each target
declares which transports it supports; the parametrized ``client``
fixture then enumerates every ``(target, transport)`` pair the harness
should exercise.

Subclass contract (enforced at class-definition time via
``__init_subclass__``):
  * Set ``name`` to a non-empty ``ClassVar[str]``.
  * Set ``supported_transports`` to a non-empty
    ``ClassVar[frozenset[Transport]]``.
  * Implement ``async def _open_client(transport, **kwargs)`` as an
    async context manager yielding a connected ``Client``.

Subclasses do **not** implement ``client()`` — the base class validates
the transport against ``supported_transports`` before dispatching to
``_open_client``. Mirrors the
``tests/live_gateway/protocol_compliance/targets/base.py`` shape so the
two harnesses read identically.

Transport vocabulary: A2A's wire-format choices are JSON-RPC,
HTTP+JSON, and gRPC (per ``a2a.client.client_factory.TransportProtocol``).
Phase 1 covers ``jsonrpc`` only — the bundled ``a2a_echo_agent``
advertises JSON-RPC and nothing else. ``grpc`` / ``rest`` can be added
by extending the ``Transport`` literal and any target's
``supported_transports`` set; the base class will route them through
``_open_client`` automatically.
"""

from __future__ import annotations

import abc
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import AsyncIterator, ClassVar, Literal

from a2a.client.client import Client

Transport = Literal["jsonrpc"]


class A2AComplianceTarget(abc.ABC):
    """A connectable A2A endpoint under test."""

    name: ClassVar[str]
    supported_transports: ClassVar[frozenset[Transport]]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if abc.ABC in cls.__bases__:
            return
        if not isinstance(getattr(cls, "name", None), str) or not cls.name:
            raise TypeError(f"{cls.__name__} must set a non-empty `name: ClassVar[str]`")
        if not isinstance(getattr(cls, "supported_transports", None), frozenset) or not cls.supported_transports:
            raise TypeError(f"{cls.__name__} must set a non-empty `supported_transports: ClassVar[frozenset[Transport]]`")

    @abc.abstractmethod
    def _open_client(self, transport: Transport, **client_kwargs: object) -> AbstractAsyncContextManager[Client]:
        """Return an async context manager yielding a connected Client.

        Concrete targets resolve the agent card, pick the matching
        transport, instantiate the A2A SDK ``Client``, and tear down on
        exit. The base class guarantees ``transport`` is in
        ``supported_transports`` when this is called, so implementations
        don't need to re-check.
        """

    @asynccontextmanager
    async def client(self, transport: Transport, **client_kwargs: object) -> AsyncIterator[Client]:
        """Validate transport support then dispatch to ``_open_client``.

        This is the single entry point the harness uses. Rejecting an
        unsupported transport here is an early hard error (rather than
        letting each subclass pick its own ``NotImplementedError``
        wording) so matrix skip attribution stays consistent.
        """
        if transport not in self.supported_transports:
            raise NotImplementedError(f"{type(self).__name__} does not support transport {transport!r}; " f"supported: {sorted(self.supported_transports)}")
        async with self._open_client(transport, **client_kwargs) as connected:
            yield connected
