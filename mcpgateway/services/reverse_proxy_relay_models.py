# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_relay_models.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Strict Redis boundary contracts for reverse-proxy relay messages.
"""
# pylint: disable=unnecessary-ellipsis

from collections.abc import AsyncIterator, Set
from typing import Annotated, Literal, Protocol, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictStr, StringConstraints, model_validator
from pydantic_core import PydanticCustomError

from mcpgateway.services.reverse_proxy_protocol import JsonRpcRequest, JsonRpcResponse


RelayIdentifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class RelayPubSub(Protocol):
    """redis-py pub/sub operations used by the relay."""

    async def subscribe(self, *channels: str) -> None:
        """Subscribe before request publication."""
        ...

    async def unsubscribe(self, *channels: str) -> None:
        """Release channel subscriptions."""
        ...

    async def aclose(self) -> None:
        """Close the pub/sub connection using redis-py's async API."""
        ...

    def listen(self) -> AsyncIterator[dict[str, str | bytes | int | None]]:
        """Yield Redis pub/sub entries, including control acknowledgements."""
        ...


class RelayRedis(Protocol):
    """Minimal asynchronous Redis contract required by the relay."""

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        """Set a value with optional claim semantics."""
        ...

    async def get(self, key: str) -> bytes | str | None:
        """Read one value."""
        ...

    async def setex(self, key: str, seconds: int, value: str) -> bool:
        """Set one expiring value."""
        ...

    async def exists(self, key: str) -> int:
        """Return whether a key exists."""
        ...

    async def delete(self, *keys: str) -> int:
        """Delete keys and return the number removed."""
        ...

    async def sadd(self, key: str, *values: str) -> int:
        """Add values to a set."""
        ...

    async def srem(self, key: str, *values: str) -> int:
        """Remove values from a set."""
        ...

    async def smembers(self, key: str) -> Set[bytes | str]:
        """Read all members from a set."""
        ...

    async def eval(self, script: str, numkeys: int, *args: str | int) -> int:
        """Execute one ownership CAS script."""
        ...

    async def publish(self, channel: str, message: bytes) -> int:
        """Publish one serialized envelope."""
        ...

    def pubsub(self) -> RelayPubSub:
        """Create an isolated pub/sub resource."""
        ...


class _RelayModel(BaseModel):
    """Frozen strict base for every Redis relay boundary model."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class RelayOwner(_RelayModel):
    """One worker and process-local connection generation owning a stable ID."""

    worker_id: RelayIdentifier
    connection_id: RelayIdentifier


class RelaySessionEntry(_RelayModel):
    """Redis directory metadata for one globally addressable connection."""

    connection_id: RelayIdentifier
    stable_id: RelayIdentifier
    owner: RelayOwner
    owner_email: StrictStr | None = None
    connected_at: StrictStr
    last_activity: StrictStr
    message_count: int = Field(ge=0)
    bytes_transferred: int = Field(ge=0)
    server_info: dict[StrictStr, JsonValue]


class RelayAuth(_RelayModel):
    """Strict downstream authentication boundary."""

    headers: dict[StrictStr, StrictStr]
    auth_type: StrictStr | None = None


class RelayResponseMessage(_RelayModel):
    """Strict relay copy of a client response envelope."""

    type: Literal["response"]
    payload: JsonRpcResponse


class RelayRequestEnvelope(_RelayModel):
    """Signed request published to one reverse-proxy worker channel."""

    type: Literal["rp_request"]
    request_id: RelayIdentifier
    stable_id: RelayIdentifier
    owner_connection_id: RelayIdentifier
    origin_worker_id: RelayIdentifier
    payload: JsonRpcRequest
    auth: RelayAuth | None = None
    deadline_utc: float = Field(gt=0, allow_inf_nan=False)
    expect_response: bool = True
    forward_sig: str = Field(min_length=64, max_length=64)


class RelayCancelEnvelope(_RelayModel):
    """Signed cancellation for one owner-side request task."""

    type: Literal["rp_cancel"]
    request_id: RelayIdentifier
    stable_id: RelayIdentifier
    owner_connection_id: RelayIdentifier
    origin_worker_id: RelayIdentifier
    forward_sig: str = Field(min_length=64, max_length=64)


class RelayDisconnectEnvelope(_RelayModel):
    """Signed request for the exact owner worker to retire one session."""

    type: Literal["rp_disconnect"]
    request_id: RelayIdentifier
    stable_id: RelayIdentifier
    owner_connection_id: RelayIdentifier
    origin_worker_id: RelayIdentifier
    forward_sig: str = Field(min_length=64, max_length=64)


class RelayResponseEnvelope(_RelayModel):
    """Signed correlated response or typed relay failure."""

    type: Literal["rp_response"]
    request_id: RelayIdentifier
    response: RelayResponseMessage | None = None
    error: Literal["connection_not_found", "connection_closed", "timeout", "internal_error"] | None = None
    forward_sig: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def require_one_outcome(self) -> "RelayResponseEnvelope":
        """Require exactly one response outcome."""
        if (self.response is None) == (self.error is None):
            raise PydanticCustomError("relay_response_outcome", "relay response must contain exactly one outcome")
        return self


RelayInboundEnvelope: TypeAlias = RelayRequestEnvelope | RelayCancelEnvelope | RelayDisconnectEnvelope
RelayJson: TypeAlias = dict[str, JsonValue]
