# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_relay_io.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Stateless signing, parsing, and pub/sub cleanup for reverse-proxy relay.
"""

from collections.abc import Mapping

import anyio
import orjson
from pydantic import ValidationError

from mcpgateway.auth_context import FORWARD_SIG_FIELD, sign_redis_forward_envelope, verify_redis_forward_envelope
from mcpgateway.services.reverse_proxy_protocol import JsonRpcId, ResponseMessage
from mcpgateway.services.reverse_proxy_relay_models import RelayCancelEnvelope, RelayInboundEnvelope, RelayPubSub, RelayRequestEnvelope, RelayResponseEnvelope
from mcpgateway.services.reverse_proxy_sessions import ConnectionClosedError, ConnectionId, ConnectionNotFoundError


def sign_envelope(envelope: dict[str, object]) -> dict[str, object]:
    """Attach the established whole-envelope HMAC signature."""
    envelope[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(envelope)
    return envelope


def parse_pubsub_message(entry: Mapping[str, str | bytes | int | None] | str) -> str | bytes | None:
    """Return data only from real Redis message entries."""
    if not isinstance(entry, Mapping) or entry.get("type") != "message":
        return None
    data = entry.get("data")
    return data if isinstance(data, (str, bytes)) else None


def parse_inbound(raw: str | bytes, max_payload_bytes: int) -> RelayInboundEnvelope | None:
    """Verify and strictly parse one bounded request or cancellation envelope."""
    if len(raw) > max_payload_bytes:
        return None
    try:
        decoded = orjson.loads(raw)
        if not isinstance(decoded, dict) or not verify_redis_forward_envelope(decoded):
            return None
        match decoded.get("type"):
            case "rp_request":
                return RelayRequestEnvelope.model_validate(decoded)
            case "rp_cancel":
                return RelayCancelEnvelope.model_validate(decoded)
            case _:
                return None
    except (orjson.JSONDecodeError, ValidationError, TypeError, AttributeError):
        return None


def parse_response(raw: str | bytes, request_id: str, json_rpc_id: JsonRpcId, max_payload_bytes: int) -> RelayResponseEnvelope | None:
    """Verify and correlate one strict response envelope."""
    if len(raw) > max_payload_bytes:
        return None
    try:
        decoded = orjson.loads(raw)
        if not isinstance(decoded, dict) or not verify_redis_forward_envelope(decoded):
            return None
        response = RelayResponseEnvelope.model_validate(decoded)
    except (orjson.JSONDecodeError, ValidationError, TypeError, AttributeError):
        return None
    if response.request_id != request_id or (response.response is not None and response.response.payload.id != json_rpc_id):
        return None
    return response


def unwrap_response(envelope: RelayResponseEnvelope, connection_id: str) -> ResponseMessage:
    """Return a correlated response or raise its typed relay failure."""
    if envelope.response is not None:
        return ResponseMessage.model_validate(envelope.response.model_dump())
    if envelope.error == "timeout":
        raise TimeoutError
    if envelope.error == "connection_closed":
        raise ConnectionClosedError(ConnectionId(connection_id))
    raise ConnectionNotFoundError(ConnectionId(connection_id))


async def cleanup_pubsub(pubsub: RelayPubSub, channel: str) -> None:
    """Independently bound unsubscribe and redis-py aclose without masking results."""
    with anyio.move_on_after(1, shield=True):
        await _unsubscribe_best_effort(pubsub, channel)
    with anyio.move_on_after(1, shield=True):
        await _close_best_effort(pubsub)


async def _unsubscribe_best_effort(pubsub: RelayPubSub, channel: str) -> bool:
    """Return whether unsubscribe completed; cleanup callers continue either way."""
    try:
        await pubsub.unsubscribe(channel)
    except Exception:  # pylint: disable=broad-exception-caught
        return False
    return True


async def _close_best_effort(pubsub: RelayPubSub) -> bool:
    """Return whether redis-py aclose completed without propagating cleanup errors."""
    try:
        await pubsub.aclose()
    except Exception:  # pylint: disable=broad-exception-caught
        return False
    return True
