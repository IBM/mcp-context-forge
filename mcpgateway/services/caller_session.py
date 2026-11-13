# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/caller_session.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Resolve authenticated upstream session bindings without trusting client ownership fields."""

from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import time
from typing import Any, Awaitable, Callable, Mapping, Optional

SESSION_KEY_META = "io.contextforge/sessionKey"
MAX_SESSION_KEY_BYTES = 256
REQUEST_HEADERS = frozenset({"traceparent", "tracestate", "baggage", "x-correlation-id"})
INTERNAL_HEADERS = frozenset({"mcp-session-id", "x-mcp-session-id", "x-forwarded-internally"})
ENVELOPE_META_KEYS = frozenset({"io.modelcontextprotocol/protocolVersion", "io.modelcontextprotocol/clientInfo", "io.modelcontextprotocol/clientCapabilities"})


def upstream_meta(meta: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """Remove downstream negotiation metadata so the upstream SDK stamps its own envelope.

    Args:
        meta: Downstream request metadata.

    Returns:
        Application metadata without hop-specific client negotiation fields.
    """
    return {name: value for name, value in meta.items() if name not in ENVELOPE_META_KEYS} if meta is not None else None


class CallerSessionError(RuntimeError):
    """Report a caller-binding failure through the MCP error envelope."""

    code = -32000


class InvalidSessionKeyError(CallerSessionError):
    """Reject malformed correlation keys before upstream session creation."""

    code = -32602


class CallerOwnershipLostError(CallerSessionError):
    """Reject operations whose worker ownership has expired or been revoked."""

    def __init__(self) -> None:
        """Use a stable MCP error message for rejected ownership tickets."""
        super().__init__("Caller session ownership lost")


class CallerOwnershipState(str, Enum):
    """Local initialization and revocation state for one ownership generation."""

    PENDING = "pending"
    READY = "ready"
    REVOKED = "revoked"


@dataclass(eq=False)
class CallerOwnershipTicket:
    """Carry server-issued authority whose revocation survives removal of session entries."""

    routing_key: str
    owner: str
    generation: str
    expires_at: float
    validator: Callable[["CallerOwnershipTicket"], Awaitable[None]]
    state: CallerOwnershipState = CallerOwnershipState.PENDING
    retained_until: float = field(default_factory=lambda: time.monotonic() + 30)

    def require_valid(self, *, ready: bool = True) -> None:
        """Reject revoked, expired, or uninitialized ownership.

        Args:
            ready: Whether initialization must already be complete.

        Raises:
            CallerOwnershipLostError: If this generation cannot admit work.
        """
        if self.expires_at <= time.monotonic():
            self.revoke()
        if self.state is CallerOwnershipState.REVOKED or (ready and self.state is not CallerOwnershipState.READY):
            raise CallerOwnershipLostError()

    def revoke(self) -> None:
        """Permanently revoke this ticket and every operation holding its reference."""
        self.state = CallerOwnershipState.REVOKED

    async def validate(self) -> None:
        """Check local revocation and shared ownership before admitting an operation."""
        self.require_valid()
        await self.validator(self)
        self.require_valid()


@dataclass(frozen=True)
class CallerRoutingResult:
    """Return either a forwarded result or verified local ownership to a service."""

    result: Optional[dict[str, Any]] = None
    ownership: Optional[CallerOwnershipTicket] = None


# Only the signed Redis consumer sets this context; inbound HTTP headers cannot supply ownership authority.
forwarded_caller_ownership: ContextVar[Optional[tuple[str, str, str]]] = ContextVar("forwarded_caller_ownership", default=None)


def _digest(parts: Any) -> str:
    """Hash structurally encoded identity components."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verified_caller_identity(token: str, principal: str, issuer: str = "") -> str:
    """Fingerprint a token only after authentication establishes its principal.

    Args:
        token: Verified bearer token.
        principal: Authenticated principal identifier.
        issuer: Verified token issuer.

    Returns:
        An opaque identity that isolates distinct bearer tokens.
    """
    return _digest([issuer, principal, token])


def session_key_from_meta(meta: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Validate the correlation key from JSON-RPC params metadata.

    Args:
        meta: The request's params._meta mapping.

    Returns:
        The validated key, or None when absent.

    Raises:
        InvalidSessionKeyError: If a supplied key is empty, oversized, or not a string.
    """
    if meta is None or SESSION_KEY_META not in meta:
        return None
    value = meta[SESSION_KEY_META]
    if not isinstance(value, str) or not value.strip():
        raise InvalidSessionKeyError(f"{SESSION_KEY_META} must be a non-empty string")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise InvalidSessionKeyError(f"{SESSION_KEY_META} must contain valid UTF-8") from exc
    if size > MAX_SESSION_KEY_BYTES:
        raise InvalidSessionKeyError(f"{SESSION_KEY_META} exceeds {MAX_SESSION_KEY_BYTES} bytes")
    return value


@dataclass(frozen=True)
class CallerBinding:
    """Separate an internal binding identity from its optional downstream listener."""

    key: str
    downstream_session_id: Optional[str]
    routing_key: str


def resolve_caller_binding(
    *,
    caller_identity: Optional[str],
    server_id: Optional[str],
    downstream_session_id: Optional[str],
    meta: Optional[Mapping[str, Any]],
    pin_sessions_by_caller: bool,
) -> Optional[CallerBinding]:
    """Resolve opt-in caller continuity while preserving downstream-session isolation.

    Args:
        caller_identity: Fingerprint established by authenticated ingress.
        server_id: Authorized virtual server context.
        downstream_session_id: Real downstream session ID, when present.
        meta: JSON-RPC params metadata.
        pin_sessions_by_caller: Gateway opt-in for requests without explicit keys.

    Returns:
        A caller binding, or None to preserve the existing invocation path.
    """
    key = session_key_from_meta(meta)
    if not isinstance(caller_identity, str) or not caller_identity:
        return None
    if key is None and (downstream_session_id or not pin_sessions_by_caller):
        return None
    components = ["caller-v1", caller_identity, server_id, downstream_session_id, key]
    digest = _digest(components)
    return CallerBinding(key=digest, downstream_session_id=downstream_session_id, routing_key=f"caller-{digest}")


def connection_fingerprint(url: str, transport: str, headers: Mapping[str, str], tls_identity: Any = None) -> str:
    """Fingerprint effective credentials without retaining their plaintext values.

    Args:
        url: Effective upstream URL.
        transport: Upstream transport name.
        headers: Headers resolved after authentication and plugins.
        tls_identity: Effective trust and client certificate material.

    Returns:
        A fingerprint that changes when persistent connection material changes.
    """
    stable_headers = {name.lower(): value for name, value in headers.items() if name.lower() not in REQUEST_HEADERS | INTERNAL_HEADERS}
    return _digest([url, transport, stable_headers, tls_identity])
