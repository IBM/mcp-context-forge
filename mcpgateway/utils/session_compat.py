# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/session_compat.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Backwards-compat shim for the ``mcp.shared.session`` module removed in mcp 2.0.0.

mcp 2.0.0b2 shipped ``mcp.shared.session.RequestResponder`` as a typing-only
stub ("the SDK never instantiates it") so v1-era call sites could keep their
annotations and ``isinstance`` guards. The 2.0.0 final release removed the
whole ``mcp.shared.session`` module: server-initiated requests are now handled
through the return-based callback protocols on
``mcp.client.session.ClientSession`` (``SamplingFnT``, ``ElicitationFnT``,
``ListRootsFnT``) instead of yielded responder objects.

This shim re-creates the stub so existing annotations and ``isinstance``
guards keep working. Neither the v2 SDK nor the gateway ever constructs a
``RequestResponder``, so ``isinstance`` checks are always False at runtime —
identical semantics to the b2 stub. The imperative hold-then-respond
multiplexer built on it has no v2 equivalent; call sites guard every
``.respond()``/``.cancel()`` with ``hasattr`` and drop with a warning.
"""

# Future
from __future__ import annotations

# Standard
from typing import Generic, TypeVar

# Third-Party
from mcp.shared.message import MessageMetadata
from mcp_types import RequestParamsMeta

RequestId = str | int

ReceiveRequestT = TypeVar("ReceiveRequestT")
SendResultT = TypeVar("SendResultT")


class RequestResponder(Generic[ReceiveRequestT, SendResultT]):
    """Typing stub for the v1 responder; neither the SDK nor the gateway instantiates it."""

    request_id: RequestId
    request_meta: RequestParamsMeta | None
    request: ReceiveRequestT
    message_metadata: MessageMetadata
