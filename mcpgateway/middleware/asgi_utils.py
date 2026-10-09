# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/asgi_utils.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared raw-header helpers for pure-ASGI middleware: decode scope/message header
pairs into dicts and mutate a response-start header list in place.
"""

# Standard
from typing import Any, Dict, Iterable, List, Optional, Tuple


def headers_to_dict(items: Optional[Iterable[Any]]) -> Dict[str, str]:
    """Decode ASGI raw header pairs into a lowercase-keyed dict.

    Malformed entries are skipped rather than failing the request; later
    duplicates win, matching starlette's ``MutableHeaders`` semantics.

    Args:
        items: The ``headers`` value from an ASGI scope or message.

    Returns:
        Dict of header name (lowercase) to value.
    """
    headers: Dict[str, str] = {}
    for item in items or []:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        key, value = item
        if isinstance(key, (bytes, bytearray)) and isinstance(value, (bytes, bytearray)):
            headers[key.decode("latin-1").lower()] = value.decode("latin-1")
    return headers


class RawHeaderMutator:
    """Get/set/delete against the raw header list of an ASGI message."""

    def __init__(self, headers: List[Tuple[bytes, bytes]]) -> None:
        """Bind to the given raw header list (mutated in place).

        Args:
            headers: Raw ``(name, value)`` byte pairs from an ASGI message.
        """
        self._headers = headers

    def get(self, name: str) -> Optional[str]:
        """Return the first matching header value (case-insensitive) or None."""
        lname = name.lower().encode("latin-1")
        for key, value in self._headers:
            if key.lower() == lname:
                return value.decode("latin-1")
        return None

    def set(self, name: str, value: str) -> None:
        """Set the header, removing existing entries first (starlette semantics)."""
        lname = name.lower().encode("latin-1")
        self._headers[:] = [(k, v) for k, v in self._headers if k.lower() != lname]
        self._headers.append((lname, value.encode("latin-1")))

    def delete(self, name: str) -> None:
        """Remove all instances of the header."""
        lname = name.lower().encode("latin-1")
        self._headers[:] = [(k, v) for k, v in self._headers if k.lower() != lname]
