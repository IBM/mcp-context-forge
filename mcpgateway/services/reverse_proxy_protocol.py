# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_protocol.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Typed wire models for reverse-proxy WebSocket text frames.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Mapping, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, JsonValue, StrictInt, StrictStr, StringConstraints, TypeAdapter
from pydantic_core import PydanticCustomError


JsonRpcId: TypeAlias = StrictInt | StrictStr
JsonObject: TypeAlias = dict[str, JsonValue]
JsonArray: TypeAlias = list[JsonValue]
JsonParams: TypeAlias = JsonObject | JsonArray
BoundedName: TypeAlias = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
BoundedDescription: TypeAlias = Annotated[str, StringConstraints(max_length=1024)]
JsonRpcMethod: TypeAlias = Annotated[StrictStr, StringConstraints(min_length=1)]


class _WireModel(BaseModel):
    """Base for wire frames: immutable and tolerant of unknown members."""

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)


class _JsonRpcModel(BaseModel):
    """Base for strict JSON-RPC payloads: immutable with no extra members."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class _JsonRpcCall(_JsonRpcModel):
    """Shared shape of JSON-RPC request and notification calls."""

    jsonrpc: Literal["2.0"]
    method: JsonRpcMethod
    params: JsonParams | None = None

    @field_validator("params")
    @classmethod
    def require_structured_params(_cls, value: JsonParams | None) -> JsonParams | None:
        """Reject explicit null while permitting an omitted params member."""
        if value is None:
            raise PydanticCustomError("json_rpc_params", "params must be an object or array")
        return value


class JsonRpcRequest(_JsonRpcCall):
    """Strict JSON-RPC request carrying a correlation identifier."""

    id: JsonRpcId


class JsonRpcNotification(_JsonRpcCall):
    """Strict JSON-RPC notification without an identifier."""


class JsonRpcError(_JsonRpcModel):
    """JSON-RPC error payload."""

    code: StrictInt
    message: str
    data: JsonValue = None


class JsonRpcSuccessResponse(_JsonRpcModel):
    """Strict JSON-RPC success response, including a nullable result."""

    jsonrpc: Literal["2.0"]
    id: JsonRpcId
    result: JsonValue


class JsonRpcErrorResponse(_JsonRpcModel):
    """Strict JSON-RPC error response."""

    jsonrpc: Literal["2.0"]
    id: JsonRpcId
    error: JsonRpcError


JsonRpcResponse: TypeAlias = JsonRpcSuccessResponse | JsonRpcErrorResponse
ServerRequestPayload: TypeAlias = JsonRpcRequest | JsonRpcNotification


class RegistrationServer(_WireModel):
    """Non-authoritative server metadata accepted during registration."""

    name: BoundedName
    description: BoundedDescription | None = None
    protocol: str | None = None


class RegisterMessage(_WireModel):
    """Client request to register non-authoritative server metadata."""

    type: Literal["register"]
    server: RegistrationServer


class UnregisterMessage(_WireModel):
    """Client request to end its local registration."""

    type: Literal["unregister"]


class HeartbeatMessage(_WireModel):
    """Client connection heartbeat."""

    type: Literal["heartbeat"]


class ResponseMessage(_WireModel):
    """Client JSON-RPC response envelope."""

    type: Literal["response"]
    payload: JsonRpcResponse


class NotificationMessage(_WireModel):
    """Client JSON-RPC notification envelope."""

    type: Literal["notification"]
    payload: JsonRpcNotification


ClientMessage: TypeAlias = RegisterMessage | UnregisterMessage | HeartbeatMessage | ResponseMessage | NotificationMessage
_CLIENT_MESSAGE_ADAPTER = TypeAdapter(Annotated[ClientMessage, Field(discriminator="type")])


class RegistrationStatus(StrEnum):
    """Server registration lifecycle states."""

    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"


class _ServerMessage(_WireModel):
    """Base for gateway-to-server frames carrying the assigned session id."""

    session_id: str = Field(alias="sessionId")


class RegisterAckMessage(_ServerMessage):
    """Server acknowledgement that registration processing started."""

    type: Literal["register_ack"] = "register_ack"
    status: Literal[RegistrationStatus.PROCESSING] = RegistrationStatus.PROCESSING


class RegisterCompleteMessage(_ServerMessage):
    """Server registration completion result."""

    type: Literal["register_complete"] = "register_complete"
    status: Literal[RegistrationStatus.SUCCESS, RegistrationStatus.ERROR]
    message: str | None = None


class ServerHeartbeatMessage(_ServerMessage):
    """Server heartbeat acknowledgement."""

    type: Literal["heartbeat"] = "heartbeat"
    timestamp: datetime


class RequestMessage(_ServerMessage):
    """Server JSON-RPC request for the connected client."""

    type: Literal["request"] = "request"
    payload: ServerRequestPayload
    authentication: Mapping[str, str] | None = None
    auth_type: str | None = Field(default=None, alias="authType")


class ErrorMessage(_ServerMessage):
    """Server protocol error envelope."""

    type: Literal["error"] = "error"
    message: str


ServerMessage: TypeAlias = RegisterAckMessage | RegisterCompleteMessage | ServerHeartbeatMessage | RequestMessage | ErrorMessage


class DownstreamAuth(_WireModel):
    """Optional downstream authentication attached to a server request."""

    headers: Mapping[str, str]
    auth_type: str | None = None


def parse_client_message(frame: str) -> ClientMessage:
    """Parse one untrusted JSON text frame into a frozen message variant."""
    return _CLIENT_MESSAGE_ADAPTER.validate_json(frame)


def register_ack(connection_id: str) -> RegisterAckMessage:
    """Build a registration acknowledgement."""
    return RegisterAckMessage(sessionId=connection_id)


def register_complete(
    connection_id: str,
    status: Literal[RegistrationStatus.SUCCESS, RegistrationStatus.ERROR],
    message: str | None = None,
) -> RegisterCompleteMessage:
    """Build a registration completion result."""
    return RegisterCompleteMessage(sessionId=connection_id, status=status, message=message)


def heartbeat(connection_id: str, timestamp: datetime) -> ServerHeartbeatMessage:
    """Build a heartbeat acknowledgement."""
    return ServerHeartbeatMessage(sessionId=connection_id, timestamp=timestamp)


def request(connection_id: str, payload: ServerRequestPayload, auth: DownstreamAuth | None = None) -> RequestMessage:
    """Build a JSON-RPC request with optional downstream authentication."""
    if auth is None:
        return RequestMessage(sessionId=connection_id, payload=payload)
    return RequestMessage(sessionId=connection_id, payload=payload, authentication=auth.headers, authType=auth.auth_type)


def error(connection_id: str, message: str) -> ErrorMessage:
    """Build a protocol error envelope."""
    return ErrorMessage(sessionId=connection_id, message=message)


def encode_server_message(message: ServerMessage) -> str:
    """Serialize one typed server message to a WebSocket text frame."""
    return message.model_dump_json(by_alias=True, exclude_none=True)
