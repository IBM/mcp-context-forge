# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/a2a_protocol.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Helpers for preparing outbound A2A requests across protocol versions.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional
import uuid

# First-Party
from mcpgateway.utils.services_auth import decode_auth
from mcpgateway.utils.url_auth import apply_query_param_auth, sanitize_url_for_logging

_A2A_VERSION_HEADER = "A2A-Version"
_V1_DEFAULT_VERSION = "1.0"
_LEGACY_DEFAULT_VERSION = "0.3"
_V1_SEND_MESSAGE_METHOD = "SendMessage"
_LEGACY_SEND_MESSAGE_METHOD = "message/send"

_LEGACY_TO_V1_METHODS = {
    "message/send": "SendMessage",
    "message/stream": "SendStreamingMessage",
    "tasks/get": "GetTask",
    "tasks/list": "ListTasks",
    "tasks/cancel": "CancelTask",
    "tasks/resubscribe": "SubscribeToTask",
    "tasks/pushNotificationConfig/set": "CreateTaskPushNotificationConfig",
    "tasks/pushNotificationConfig/get": "GetTaskPushNotificationConfig",
    "tasks/pushNotificationConfig/list": "ListTaskPushNotificationConfigs",
    "tasks/pushNotificationConfig/delete": "DeleteTaskPushNotificationConfig",
    "agent/getAuthenticatedExtendedCard": "GetExtendedAgentCard",
    "agent/getExtendedCard": "GetExtendedAgentCard",
}
_V1_TO_LEGACY_METHODS = {value: key for key, value in _LEGACY_TO_V1_METHODS.items()}
_V1_TO_LEGACY_METHODS["GetExtendedAgentCard"] = "agent/getAuthenticatedExtendedCard"
_LEGACY_ROLE_TO_V1 = {"user": "ROLE_USER", "agent": "ROLE_AGENT", "system": "ROLE_SYSTEM"}
_V1_ROLE_TO_LEGACY = {value: key for key, value in _LEGACY_ROLE_TO_V1.items()}
_LEGACY_TASK_STATE_TO_V1 = {
    "submitted": "TASK_STATE_SUBMITTED",
    "working": "TASK_STATE_WORKING",
    "input-required": "TASK_STATE_INPUT_REQUIRED",
    "input_required": "TASK_STATE_INPUT_REQUIRED",
    "completed": "TASK_STATE_COMPLETED",
    "canceled": "TASK_STATE_CANCELED",
    "cancelled": "TASK_STATE_CANCELED",
    "failed": "TASK_STATE_FAILED",
    "auth-required": "TASK_STATE_AUTH_REQUIRED",
    "auth_required": "TASK_STATE_AUTH_REQUIRED",
    "rejected": "TASK_STATE_REJECTED",
}
_V1_TASK_STATE_TO_LEGACY = {
    "TASK_STATE_SUBMITTED": "submitted",
    "TASK_STATE_WORKING": "working",
    "TASK_STATE_INPUT_REQUIRED": "input_required",
    "TASK_STATE_COMPLETED": "completed",
    "TASK_STATE_CANCELED": "canceled",
    "TASK_STATE_FAILED": "failed",
    "TASK_STATE_AUTH_REQUIRED": "auth_required",
    "TASK_STATE_REJECTED": "rejected",
}


@dataclass(frozen=True)
class PreparedA2AInvocation:
    """Prepared outbound A2A invocation payload."""

    endpoint_url: str
    sanitized_endpoint_url: str
    headers: Dict[str, str]
    request_data: Dict[str, Any]
    protocol_version_header: str
    uses_jsonrpc: bool
    sensitive_query_param_names: Optional[Dict[str, str]] = None


def is_v1_a2a_protocol(protocol_version: Optional[str]) -> bool:
    """Return whether the configured protocol version should use A2A v1 semantics."""
    normalized = str(protocol_version or "").strip()
    if not normalized:
        return True
    parts = [part for part in normalized.split(".") if part != ""]
    if not parts:
        return True
    try:
        return int(parts[0]) >= 1
    except ValueError:
        return normalized.startswith("1")


def normalize_a2a_version_header(protocol_version: Optional[str]) -> str:
    """Return the canonical A2A-Version header value for the target protocol."""
    normalized = str(protocol_version or "").strip()
    if not normalized:
        return _V1_DEFAULT_VERSION

    parts = [part for part in normalized.split(".") if part != ""]
    if not parts:
        return _V1_DEFAULT_VERSION
    if len(parts) == 1:
        if parts[0].isdigit():
            return f"{parts[0]}.0"
        return normalized
    return f"{parts[0]}.{parts[1]}"


def is_jsonrpc_a2a_agent(agent_type: Optional[str], endpoint_url: Optional[str]) -> bool:
    """Return whether the registered agent should be invoked as JSON-RPC A2A."""
    return str(agent_type or "").lower() in {"generic", "jsonrpc"} or str(endpoint_url or "").endswith("/")


def normalize_a2a_method(method: Optional[str], protocol_version: Optional[str]) -> str:
    """Map method names between A2A v0.3 and v1."""
    candidate = str(method or "").strip()
    if not candidate:
        return _V1_SEND_MESSAGE_METHOD if is_v1_a2a_protocol(protocol_version) else _LEGACY_SEND_MESSAGE_METHOD

    if is_v1_a2a_protocol(protocol_version):
        return _LEGACY_TO_V1_METHODS.get(candidate, candidate)
    return _V1_TO_LEGACY_METHODS.get(candidate, candidate)


def _normalize_role(role: Any, protocol_version: Optional[str]) -> Any:
    """Normalize an A2A message role between v1 and legacy protocol forms."""
    value = str(role or "").strip()
    if not value:
        return role
    if is_v1_a2a_protocol(protocol_version):
        return _LEGACY_ROLE_TO_V1.get(value.lower(), value)
    return _V1_ROLE_TO_LEGACY.get(value, value.lower())


def _normalize_part(part: Any, protocol_version: Optional[str]) -> Any:
    """Normalize an A2A message part between v1 and legacy protocol forms."""
    if not isinstance(part, Mapping):
        return part

    source = dict(part)
    discriminator = source.pop("kind", None) or source.pop("type", None)
    if is_v1_a2a_protocol(protocol_version):
        if discriminator in {"text", "TEXT", None} and "text" in source:
            return source
        return source

    target = dict(source)
    if discriminator:
        target["kind"] = discriminator
        return target
    if "text" in target:
        target["kind"] = "text"
    elif "data" in target:
        target["kind"] = "data"
    elif any(key in target for key in ("file", "fileId", "uri", "url")):
        target["kind"] = "file"
    return target


def _normalize_task_state(state: Any, protocol_version: Optional[str]) -> Any:
    """Normalize an A2A task state between v1 and legacy protocol forms."""
    value = str(state or "").strip()
    if not value:
        return state
    if is_v1_a2a_protocol(protocol_version):
        return _LEGACY_TASK_STATE_TO_V1.get(value.lower(), value)
    return _V1_TASK_STATE_TO_LEGACY.get(value, value.lower())


def _normalize_message(message: Any, protocol_version: Optional[str]) -> Any:
    """Normalize an A2A message object for the target protocol version."""
    if not isinstance(message, Mapping):
        return message

    target = dict(message)
    if is_v1_a2a_protocol(protocol_version):
        target.pop("kind", None)
    else:
        target.setdefault("kind", "message")
    if "role" in target:
        target["role"] = _normalize_role(target["role"], protocol_version)
    if isinstance(target.get("parts"), list):
        target["parts"] = [_normalize_part(part, protocol_version) for part in target["parts"]]
    return target


def _normalize_task_status(status: Any, protocol_version: Optional[str]) -> Any:
    """Normalize an A2A task status for the target protocol version."""
    if isinstance(status, str):
        return _normalize_task_state(status, protocol_version)
    if not isinstance(status, Mapping):
        return status

    target = dict(status)
    if "state" in target:
        target["state"] = _normalize_task_state(target["state"], protocol_version)
    if "message" in target:
        target["message"] = _normalize_message(target["message"], protocol_version)
    return target


def _normalize_task(task: Any, protocol_version: Optional[str]) -> Any:
    """Normalize an A2A task object for the target protocol version."""
    if not isinstance(task, Mapping):
        return task

    target = dict(task)
    if is_v1_a2a_protocol(protocol_version):
        target.pop("kind", None)
    else:
        target.setdefault("kind", "task")
    if "status" in target:
        target["status"] = _normalize_task_status(target["status"], protocol_version)
    if isinstance(target.get("history"), list):
        target["history"] = [_normalize_message(item, protocol_version) if isinstance(item, Mapping) else item for item in target["history"]]
    if isinstance(target.get("artifacts"), list):
        normalized_artifacts = []
        for artifact in target["artifacts"]:
            if not isinstance(artifact, Mapping):
                normalized_artifacts.append(artifact)
                continue
            normalized_artifact = dict(artifact)
            if is_v1_a2a_protocol(protocol_version):
                normalized_artifact.pop("kind", None)
            else:
                normalized_artifact.setdefault("kind", "artifact")
            if isinstance(normalized_artifact.get("parts"), list):
                normalized_artifact["parts"] = [_normalize_part(part, protocol_version) for part in normalized_artifact["parts"]]
            normalized_artifacts.append(normalized_artifact)
        target["artifacts"] = normalized_artifacts
    return target


def normalize_a2a_params(params: Any, protocol_version: Optional[str]) -> Any:
    """Normalize A2A request params for the target protocol version."""
    if not isinstance(params, Mapping):
        return params

    normalized: Dict[str, Any] = {}
    for key, value in dict(params).items():
        if key == "message":
            normalized[key] = _normalize_message(value, protocol_version)
        elif key in {"history", "messages"} and isinstance(value, list):
            normalized[key] = [_normalize_message(item, protocol_version) if isinstance(item, Mapping) else item for item in value]
        elif key == "task":
            normalized[key] = _normalize_task(value, protocol_version)
        elif key == "status":
            normalized[key] = _normalize_task_status(value, protocol_version)
        else:
            normalized[key] = value
    return normalized


def _build_default_message(query: str, protocol_version: Optional[str], message_id: Optional[str] = None) -> Dict[str, Any]:
    """Build a default user message in the appropriate protocol format."""
    target_message_id = message_id or f"contextforge-{uuid.uuid4().hex}"
    if is_v1_a2a_protocol(protocol_version):
        return {
            "messageId": target_message_id,
            "role": "ROLE_USER",
            "parts": [{"text": query}],
        }
    return {
        "kind": "message",
        "messageId": target_message_id,
        "role": "user",
        "parts": [{"kind": "text", "text": query}],
    }


def build_a2a_jsonrpc_request(parameters: Dict[str, Any], protocol_version: Optional[str], *, interaction_type: str = "query") -> Dict[str, Any]:  # pylint: disable=unused-argument
    """Build a JSON-RPC A2A request body for the target protocol version."""
    payload = dict(parameters or {})
    request_id = payload.pop("id", 1)

    if "jsonrpc" in payload and "method" in payload:
        method = normalize_a2a_method(payload.get("method"), protocol_version)
        params = normalize_a2a_params(payload.get("params", {}), protocol_version)
        return {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}

    explicit_params = payload.pop("params", None)
    explicit_message = payload.pop("message", None)
    method = normalize_a2a_method(payload.pop("method", None), protocol_version)

    if explicit_params is not None:
        params = explicit_params
    elif explicit_message is not None:
        params = {"message": explicit_message}
    elif isinstance(payload.get("query"), str):
        query = str(payload.pop("query"))
        message_id = str(payload.pop("messageId", "")) or None
        params = dict(payload)
        params["message"] = _build_default_message(query, protocol_version, message_id=message_id)
    elif isinstance(payload.get("text"), str):
        text = str(payload.pop("text"))
        message_id = str(payload.pop("messageId", "")) or None
        params = dict(payload)
        params["message"] = _build_default_message(text, protocol_version, message_id=message_id)
    else:
        params = payload

    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": normalize_a2a_params(params, protocol_version),
        "id": request_id,
    }


def prepare_a2a_invocation(
    *,
    agent_type: Optional[str],
    endpoint_url: str,
    protocol_version: Optional[str],
    parameters: Optional[Dict[str, Any]],
    interaction_type: str,
    auth_type: Optional[str] = None,
    auth_value: Any = None,
    auth_query_params: Optional[Dict[str, str]] = None,
    base_headers: Optional[Mapping[str, str]] = None,
    correlation_id: Optional[str] = None,
) -> PreparedA2AInvocation:
    """Prepare endpoint, headers, and request body for an outbound A2A invocation."""
    headers = {str(key): str(value) for key, value in dict(base_headers or {}).items()}
    headers.setdefault("Content-Type", "application/json")
    if correlation_id:
        headers["X-Correlation-ID"] = correlation_id

    if auth_type in {"basic", "bearer", "authheaders", "api_key"} and auth_value:
        if isinstance(auth_value, str):
            if auth_type == "api_key":
                headers.setdefault("Authorization", f"Bearer {auth_value}")
            else:
                decoded = decode_auth(auth_value)
                if not isinstance(decoded, Mapping):
                    raise ValueError("Decoded A2A authentication payload must be a mapping")
                headers.update({str(key): str(value) for key, value in decoded.items()})
        elif isinstance(auth_value, Mapping):
            headers.update({str(key): str(value) for key, value in auth_value.items()})

    auth_query_params_decrypted: Dict[str, str] = {}
    target_endpoint_url = endpoint_url
    if auth_type == "query_param" and auth_query_params:
        for param_key, encrypted_value in auth_query_params.items():
            if not encrypted_value:
                continue
            try:
                decrypted = decode_auth(encrypted_value)
                auth_query_params_decrypted[str(param_key)] = str(decrypted.get(param_key, ""))
            except Exception:
                continue
        if auth_query_params_decrypted:
            target_endpoint_url = apply_query_param_auth(target_endpoint_url, auth_query_params_decrypted)

    uses_jsonrpc = is_jsonrpc_a2a_agent(agent_type, endpoint_url)
    protocol_version_header = normalize_a2a_version_header(protocol_version)
    if uses_jsonrpc:
        headers[_A2A_VERSION_HEADER] = protocol_version_header
        headers.setdefault("Accept", "application/json, text/event-stream")
        request_data = build_a2a_jsonrpc_request(parameters or {}, protocol_version, interaction_type=interaction_type)
    else:
        request_data = {
            "interaction_type": interaction_type,
            "parameters": parameters or {},
            "protocol_version": protocol_version or (_V1_DEFAULT_VERSION if is_v1_a2a_protocol(protocol_version) else _LEGACY_DEFAULT_VERSION),
        }

    sanitized_endpoint_url = sanitize_url_for_logging(target_endpoint_url, auth_query_params_decrypted or None)
    return PreparedA2AInvocation(
        endpoint_url=target_endpoint_url,
        sanitized_endpoint_url=sanitized_endpoint_url,
        headers=headers,
        request_data=request_data,
        protocol_version_header=protocol_version_header,
        uses_jsonrpc=uses_jsonrpc,
        sensitive_query_param_names=auth_query_params_decrypted or None,
    )
