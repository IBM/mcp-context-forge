# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/meta_protocol.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Per-request ``_meta`` protocol helpers for MCP 2026-07-28 dual-era support.

The MCP 2026-07-28 specification requires two mandatory namespaced keys inside
``params._meta`` on every modern (non-handshake-era) request:

- ``io.modelcontextprotocol/protocolVersion``
- ``io.modelcontextprotocol/clientCapabilities``

Servers must stamp ``io.modelcontextprotocol/serverInfo`` on every response
``result._meta``.  When a required capability was not declared at handshake the
server must return JSON-RPC error **-32021**.

Legacy connections (2024-11-05 / 2025-11-25) carry none of these keys and must
never be rejected for lacking them.

Examples:
    >>> from mcpgateway.utils.meta_protocol import is_modern_meta, extract_protocol_meta
    >>> modern = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
    >>> is_modern_meta(modern)
    True
    >>> legacy = {"progressToken": 1}
    >>> is_modern_meta(legacy)
    False
    >>> pv, caps = extract_protocol_meta(modern)
    >>> pv
    '2026-07-28'
    >>> caps
    {}
"""

# Standard
import logging
from typing import Any, Dict, Optional, Tuple

# Third-Party
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS

logger = logging.getLogger(__name__)

# Namespaced keys defined by MCP 2026-07-28 spec.
_KEY_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
_KEY_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
_KEY_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
_KEY_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

# JSON-RPC error code for "capability not supported" (MCP 2026-07-28).
CAPABILITY_NOT_SUPPORTED = -32021


def is_modern_protocol_version(protocol_version: Optional[str]) -> bool:
    """Return True when *protocol_version* belongs to the 2026-era spec.

    Args:
        protocol_version: Protocol version string from the ``MCP-Protocol-Version``
            header or ``initialize`` params, e.g. ``"2026-07-28"``.

    Returns:
        ``True`` when the version is not in the handshake-era set, ``False`` otherwise.

    Examples:
        >>> from mcpgateway.utils.meta_protocol import is_modern_protocol_version
        >>> is_modern_protocol_version("2026-07-28")
        True
        >>> is_modern_protocol_version("2025-11-25")
        False
        >>> is_modern_protocol_version(None)
        False
    """
    if not protocol_version:
        return False
    return protocol_version not in HANDSHAKE_PROTOCOL_VERSIONS


def is_modern_meta(meta: Optional[Dict[str, Any]]) -> bool:
    """Return True when *meta* contains the MCP 2026-07-28 mandatory protocol key.

    Args:
        meta: The ``_meta`` dict from ``params``.

    Returns:
        ``True`` when the namespaced protocol-version key is present.

    Examples:
        >>> from mcpgateway.utils.meta_protocol import is_modern_meta
        >>> is_modern_meta({"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}})
        True
        >>> is_modern_meta(None)
        False
        >>> is_modern_meta({"progressToken": 1})
        False
    """
    if not meta or not isinstance(meta, dict):
        return False
    return _KEY_PROTOCOL_VERSION in meta


def extract_protocol_meta(meta: Optional[Dict[str, Any]]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Extract the two mandatory 2026-era keys from *meta*.

    Args:
        meta: The ``_meta`` dict from ``params``.

    Returns:
        A tuple of ``(protocol_version, client_capabilities)`` where either value
        may be ``None`` when absent.

    Examples:
        >>> from mcpgateway.utils.meta_protocol import extract_protocol_meta
        >>> m = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {"elicitation": {}}}
        >>> pv, caps = extract_protocol_meta(m)
        >>> pv
        '2026-07-28'
        >>> caps == {"elicitation": {}}
        True
        >>> extract_protocol_meta(None)
        (None, None)
    """
    if not meta or not isinstance(meta, dict):
        return None, None
    pv = meta.get(_KEY_PROTOCOL_VERSION)
    caps = meta.get(_KEY_CLIENT_CAPABILITIES)
    return (pv if isinstance(pv, str) else None), (caps if isinstance(caps, dict) else None)


def check_capability(client_capabilities: Optional[Dict[str, Any]], required: str) -> bool:
    """Return True when *required* capability is present in *client_capabilities*.

    Args:
        client_capabilities: The capabilities dict from ``_meta`` or from the
            stored handshake capabilities for the session.
        required: Dot-separated capability path, e.g. ``"elicitation"`` or
            ``"sampling"``.

    Returns:
        ``True`` when the capability key exists and is not falsy.

    Examples:
        >>> from mcpgateway.utils.meta_protocol import check_capability
        >>> check_capability({"elicitation": {}}, "elicitation")
        True
        >>> check_capability({"sampling": {"maxTokens": 100}}, "sampling")
        True
        >>> check_capability({}, "elicitation")
        False
        >>> check_capability(None, "elicitation")
        False
        >>> check_capability({"elicitation": None}, "elicitation")
        True
    """
    if not client_capabilities or not isinstance(client_capabilities, dict):
        return False
    # Presence of the key signals the capability, even when the value is an empty dict.
    return required in client_capabilities


def stamp_server_info_meta(result: Dict[str, Any], app_name: str, version: str) -> Dict[str, Any]:
    """Inject ``io.modelcontextprotocol/serverInfo`` into *result* ``_meta``.

    Mutates *result* in place and also returns it for convenience.  Only
    injects when *result* is a plain dict — Pydantic model dumps and list
    results are left unchanged.

    Args:
        result: The JSON-serialisable result dict to annotate.
        app_name: Server application name (e.g. ``"ContextForge"``).
        version: Server version string (e.g. ``"1.0.11"``).

    Returns:
        The same *result* dict with ``_meta`` populated.

    Examples:
        >>> from mcpgateway.utils.meta_protocol import stamp_server_info_meta
        >>> r = {"tools": []}
        >>> out = stamp_server_info_meta(r, "ContextForge", "1.0.11")
        >>> out["_meta"]["io.modelcontextprotocol/serverInfo"]["name"]
        'ContextForge'
        >>> r is out
        True
    """
    if not isinstance(result, dict):
        return result
    existing_meta = result.get("_meta")
    if existing_meta is None:
        existing_meta = {}
    meta = dict(existing_meta)
    meta[_KEY_SERVER_INFO] = {"name": app_name, "version": version}
    result["_meta"] = meta
    return result


def build_client_meta(protocol_version: str, app_name: str, version: str, client_capabilities: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build the ``_meta`` block a gateway-as-client sends on outbound modern requests.

    Args:
        protocol_version: The negotiated protocol version, e.g. ``"2026-07-28"``.
        app_name: Gateway application name.
        version: Gateway application version.
        client_capabilities: Optional capabilities dict.  Defaults to ``{}``.

    Returns:
        A ``_meta`` dict with the three mandatory keys.

    Examples:
        >>> from mcpgateway.utils.meta_protocol import build_client_meta
        >>> m = build_client_meta("2026-07-28", "ContextForge", "1.0.11")
        >>> m["io.modelcontextprotocol/protocolVersion"]
        '2026-07-28'
        >>> m["io.modelcontextprotocol/clientInfo"]["name"]
        'ContextForge'
        >>> m["io.modelcontextprotocol/clientCapabilities"]
        {}
    """
    return {
        _KEY_PROTOCOL_VERSION: protocol_version,
        _KEY_CLIENT_INFO: {"name": app_name, "version": version},
        _KEY_CLIENT_CAPABILITIES: client_capabilities if isinstance(client_capabilities, dict) else {},
    }


def synthesise_meta_for_modern_upstream(existing_meta: Optional[Dict[str, Any]], session_capabilities: Optional[Dict[str, Any]], protocol_version: str, app_name: str, version: str) -> Dict[str, Any]:
    """Build a ``_meta`` dict for forwarding a legacy-client request to a modern upstream.

    When the inbound request has no protocol keys (legacy client), the gateway
    synthesises them from the session's handshake capabilities so the upstream
    modern server receives a valid 2026-era ``_meta``.

    Existing non-protocol keys (e.g. ``progressToken``, tracing IDs) are
    preserved.

    Args:
        existing_meta: The ``_meta`` from the inbound request (may be ``None``).
        session_capabilities: Capabilities declared by the client at ``initialize``
            time; retrieved from the session registry.
        protocol_version: The MCP version to advertise to the upstream server.
        app_name: Gateway application name.
        version: Gateway application version.

    Returns:
        A merged ``_meta`` dict ready to send upstream.

    Examples:
        >>> from mcpgateway.utils.meta_protocol import synthesise_meta_for_modern_upstream
        >>> m = synthesise_meta_for_modern_upstream({"progressToken": 1}, {"sampling": {}}, "2026-07-28", "ContextForge", "1.0.0")
        >>> m["io.modelcontextprotocol/protocolVersion"]
        '2026-07-28'
        >>> m["progressToken"]
        1
    """
    merged = dict(existing_meta) if existing_meta and isinstance(existing_meta, dict) else {}
    if _KEY_PROTOCOL_VERSION not in merged:
        merged[_KEY_PROTOCOL_VERSION] = protocol_version
    if _KEY_CLIENT_INFO not in merged:
        merged[_KEY_CLIENT_INFO] = {"name": app_name, "version": version}
    if _KEY_CLIENT_CAPABILITIES not in merged:
        merged[_KEY_CLIENT_CAPABILITIES] = session_capabilities if isinstance(session_capabilities, dict) else {}
    return merged
