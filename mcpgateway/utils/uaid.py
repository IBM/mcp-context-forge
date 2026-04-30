# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/uaid.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

UAID (Universal Agent ID) utilities for HCS-14 support.

This module implements parsing, validation, and generation of Universal Agent IDs
following the HCS-14 standard. UAIDs embed routing metadata directly in the agent
identifier, enabling zero-config cross-gateway routing.

UAID Format:
    uaid:aid:{base58-sha384-hash};uid={uid};registry={registry};proto={protocol};nativeId={endpoint}
    uaid:did:{did-string};uid={uid};proto={protocol};nativeId={endpoint}

Example:
    uaid:aid:9BjK3mP7xQv...;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com

References:
    - HCS-14 Standard: https://hol.org/docs/standards
    - SDK Repository: https://github.com/hashgraph-online/standards-sdk
"""

# Standard
from dataclasses import dataclass
import hashlib
import json
import logging
from typing import Mapping, MutableMapping, Optional

# Third-Party
import base58

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Federation-loop hop counter
# ────────────────────────────────────────────────────────────────────────────
#
# The hop counter is the cross-runtime contract that breaks UAID federation
# recursion (A→B→A loops AND self-referential `endpoint_url` loops).  Every
# outbound cross-gateway or local-agent invocation stamps `HOP_HEADER: N+1`;
# every inbound reads it and rejects at `uaid_max_federation_hops`.
#
# The parser is deliberately STRICT and identical across Python and Rust:
# ASCII digits only, no leading sign, no whitespace, saturating on overflow.
# A lenient parser creates a split-brain where an attacker-controlled
# intermediate can pad values with whitespace to reset the counter on one
# runtime's side but not the other's.

HOP_HEADER = "X-Contextforge-UAID-Hop"

# Ceiling at which we treat a parsed value as "definitely at the limit".
# Clamped to int32 so the value fits the Rust `u32` counterpart without
# surprise on the wire.
_HOP_MAX = 2**31 - 1


def _parse_single_hop_piece(piece: str) -> int:
    """Parse ONE hop value — strict ASCII digits, no whitespace, saturating.

    `str.isdigit()` alone is too permissive: it returns True for
    fullwidth digits (U+FF10–FF19), Arabic-Indic digits (U+0660–0669),
    Kaktovik numerals, etc., and `int()` happily parses them.  Rust's
    counterpart uses `bytes().all(|b| b.is_ascii_digit())` which
    rejects them outright, so without the `isascii()` gate an attacker
    could send `"１"` and have Python count it as hop 1 while Rust
    treats it as 0 — defeating the federation guard by split-brain.

    Args:
        piece: A single hop-count substring (the full header value
            on the single-value path, or one comma-separated element
            on the RFC 7230 coalesced path).

    Returns:
        The non-negative hop count, saturated at `_HOP_MAX`.  Malformed
        input returns 0 and logs at ERROR level (federation-loop protection
        is a security event, not a lint; see `CLAUDE.md` default
        `LOG_LEVEL=ERROR`).
    """
    # Log at ERROR level — not WARNING.  Default production LOG_LEVEL is
    # ERROR (see CLAUDE.md), and a malformed hop token silently resets
    # the federation counter to 0.  That's a loop-protection bypass,
    # not a lint; it must be visible under the default log level.
    if not piece or not piece.isascii() or not piece.isdigit():
        if piece:
            logger.error("rejecting malformed %s element %r; treating as 0 (federation-loop protection)", HOP_HEADER, piece)
        return 0
    try:
        value = int(piece)
    except ValueError:
        logger.error("rejecting malformed %s element %r; treating as 0 (federation-loop protection)", HOP_HEADER, piece)
        return 0
    return min(value, _HOP_MAX)


def parse_hop_count(raw: Optional[str]) -> int:
    """Parse a `HOP_HEADER` value into a non-negative hop count.

    Rules (must match `parse_hop_count` in `crates/a2a_runtime/src/server.rs`):
      - Missing or `None` header → 0.
      - Single value: strict ASCII digits (`[0-9]+`), no whitespace,
        no sign, no hex; saturate at `_HOP_MAX`.
      - Coalesced form (RFC 7230 §3.2.2): a proxy allowed to combine
        `X-Hop: 0` and `X-Hop: 10` into `X-Hop: 0, 10`.  Split on `,`,
        trim OWS (space or tab) per RFC 7230, parse each token with
        the single-value rules, and return the MAX across all valid
        tokens — fail-closed so a smuggled low value cannot mask a
        real high value.
      - Malformed tokens inside a coalesced value are ignored (the
        warn logs are still emitted) rather than tainting the whole
        header, which would otherwise let an attacker pair a good
        value with garbage to drop the whole thing to 0.
    """
    if raw is None:
        return 0
    if "," not in raw:
        # Fast path: single value.  Keep the strict-digits contract —
        # no leading/trailing whitespace allowed here either.  OWS
        # trimming only applies to the coalesced branch below per
        # RFC 7230.
        return _parse_single_hop_piece(raw)
    max_hop = 0
    for piece in raw.split(","):
        # Trim only OWS (space or tab), matching RFC 7230 §3.2.6 OWS.
        # Stripping other whitespace (e.g. newline) would make us more
        # lenient than the wire format allows.
        stripped = piece.strip(" \t")
        parsed = _parse_single_hop_piece(stripped)
        max_hop = max(max_hop, parsed)
    return max_hop


def read_hop_count(headers: Mapping[str, str]) -> int:
    """Return the inbound hop count from a request's headers.

    Defends against header smuggling: when multiple values of
    `HOP_HEADER` are present (e.g. a client sending two headers with
    different cases, or two same-name headers), take the MAX so an
    attacker can't reset the counter by adding a lower-valued duplicate.

    Works with starlette `Headers` (case-insensitive, exposes
    `getlist()`) and with plain dicts.  Plain dicts collapse duplicates
    on insert, so on that path we fall back to a single `get()` + scan
    the keys for case-insensitive matches.
    """
    # Prefer starlette's `getlist` when available — it returns every
    # value for the header name, across all case variants.
    getlist = getattr(headers, "getlist", None)
    if callable(getlist):
        values = getlist(HOP_HEADER)
        # `values` may iterate to empty even after passing the truthiness
        # check — e.g. a MagicMock-typed headers object whose `getlist`
        # returns a MagicMock that is truthy but iterates empty.  Build
        # the parsed list first, then fall through to the zero-default
        # when it's empty, so `max([])` cannot raise.
        parsed = [parse_hop_count(v) for v in (values or [])]
        if not parsed:
            return 0
        if len(parsed) > 1:
            logger.error("multiple %s header values present; failing closed to max=%d (federation-loop protection)", HOP_HEADER, max(parsed))
        return max(parsed)
    # Plain dict path: case-insensitive scan; the HashMap on this side
    # already collapsed duplicates, but the max-over-variants defense
    # still matters when a caller sends mixed case (title case vs
    # lowercase).
    target = HOP_HEADER.lower()
    matches: list[int] = []
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == target:
            matches.append(parse_hop_count(value))
    if not matches:
        return 0
    if len(matches) > 1:
        logger.error("multiple %s case-variant headers present; failing closed to max=%d (federation-loop protection)", HOP_HEADER, max(matches))
    return max(matches)


def stamp_hop(headers: MutableMapping[str, str], hop_count: int) -> None:
    """Write the outbound hop counter into `headers`, incrementing by 1.

    Use a `saturating_add` idiom so a degenerate `hop_count` near
    `_HOP_MAX` can't wrap.  In practice `uaid_max_federation_hops` keeps
    the actual value small; this is defensive insurance only.
    """
    next_hop = hop_count + 1 if hop_count < _HOP_MAX else _HOP_MAX
    headers[HOP_HEADER] = str(next_hop)


@dataclass
class UaidComponents:
    """Parsed UAID components.

    Attributes:
        method: UAID method - "aid" (agent identity hash) or "did" (decentralized identifier)
        hash_or_did: Base58-encoded SHA-384 hash (for aid) or DID string (for did)
        uid: User/agent instance identifier (typically "0")
        registry: Registry name (e.g., "context-forge") - optional for did method
        proto: Protocol name (e.g., "a2a", "mcp", "rest", "grpc")
        native_id: Native endpoint URL for routing
    """

    method: str
    hash_or_did: str
    uid: str
    registry: Optional[str]
    proto: str
    native_id: str


def is_uaid(identifier: str) -> bool:
    """Check if string is UAID format.

    Args:
        identifier: String to check

    Returns:
        True if identifier starts with "uaid:aid:" or "uaid:did:", False otherwise
    """
    return identifier.startswith("uaid:aid:") or identifier.startswith("uaid:did:")


def parse_uaid(uaid: str) -> UaidComponents:
    """Parse UAID string into components.

    Parses both aid-based and did-based UAIDs:
        - aid: uaid:aid:{hash};uid={uid};registry={registry};proto={proto};nativeId={endpoint}
        - did: uaid:did:{did};uid={uid};proto={proto};nativeId={endpoint}

    Args:
        uaid: UAID string to parse

    Returns:
        UaidComponents with parsed values

    Raises:
        ValueError: If UAID format is invalid or required components are missing
    """
    # DoS Protection: Reject excessively long UAIDs before parsing
    # Note: settings.uaid_max_length is enforced by Pydantic Field(le=2048) in config.py
    # which matches the database column limit (a2a_agents.uaid String(2048)).
    # If database schema changes, Alembic migration will fail visibly.
    if len(uaid) > settings.uaid_max_length:
        raise ValueError(f"UAID exceeds maximum length of {settings.uaid_max_length} characters. Received {len(uaid)} characters. This may indicate a malformed or malicious UAID.")

    # Reject ASCII control characters including CR, LF, and NUL — these
    # turn UAIDs into log-injection vectors because this module's callers
    # frequently interpolate the raw string into log lines, structured-
    # log metadata, and error messages.  Out-of-spec per HCS-14 anyway
    # (which expects printable structured fields).  Rust's parse_uaid
    # enforces the same contract via `uaid.bytes().any(|b| b < 0x20 || b == 0x7F)`
    # (crates/a2a_runtime/src/uaid.rs), so reject wholesale here so the
    # rejection happens before any downstream formatting or logging.
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in uaid):
        raise ValueError("UAID contains ASCII control characters and cannot be parsed")

    # Existing validation continues...
    if not is_uaid(uaid):
        raise ValueError(f"Invalid UAID format: must start with 'uaid:aid:' or 'uaid:did:', got: {uaid!r}")

    # Split only on the first two colons to get prefix and remainder
    # Do NOT split on all colons as that would break port numbers in nativeId (e.g., gateway.example.com:8443)
    parts = uaid.split(":", 2)  # Split on first 2 colons only: "uaid" : "aid" : "rest..."
    if len(parts) < 3:
        raise ValueError(f"Invalid UAID format: expected 'uaid:METHOD:...' format, got: {uaid!r}")

    method = parts[1]  # "aid" or "did"
    if method not in ("aid", "did"):
        raise ValueError(f"Invalid UAID method: expected 'aid' or 'did', got: {method!r}")

    # Split remainder on semicolons
    remainder = parts[2]
    segments = remainder.split(";")
    if len(segments) < 2:
        raise ValueError(f"Invalid UAID format: expected hash/did and parameters separated by ';', got: {uaid!r}")

    hash_or_did = segments[0]
    # Empty `hash_or_did` (e.g. `uaid:aid:;uid=0;...`) is rejected by
    # the Rust counterpart via `MissingParams`; rejecting here too
    # keeps the cross-runtime contract airtight so a mixed Python↔Rust
    # federation chain never disagrees on whether a UAID is valid.
    if not hash_or_did:
        raise ValueError("Invalid UAID: empty hash or DID segment")

    # Parse key=value parameters
    params = {}
    for segment in segments[1:]:
        if "=" not in segment:
            raise ValueError(f"Invalid UAID parameter: expected 'key=value' format, got: {segment!r}")
        key, value = segment.split("=", 1)
        params[key] = value

    # Extract required parameters
    if "uid" not in params:
        raise ValueError(f"Invalid UAID: missing required 'uid' parameter in: {uaid!r}")
    if "proto" not in params:
        raise ValueError(f"Invalid UAID: missing required 'proto' parameter in: {uaid!r}")
    if "nativeId" not in params:
        raise ValueError(f"Invalid UAID: missing required 'nativeId' parameter in: {uaid!r}")

    # Registry is required for aid method but optional for did method
    registry = params.get("registry")
    if method == "aid" and not registry:
        raise ValueError(f"Invalid UAID: 'registry' parameter required for aid method in: {uaid!r}")

    return UaidComponents(
        method=method,
        hash_or_did=hash_or_did,
        uid=params["uid"],
        registry=registry,
        proto=params["proto"],
        native_id=params["nativeId"],
    )


def extract_routing_info(uaid: str) -> dict:
    """Extract routing information from UAID.

    Args:
        uaid: UAID string

    Returns:
        Dictionary with keys:
            - protocol: Protocol name (e.g., "a2a", "mcp")
            - endpoint: Native endpoint URL
            - registry: Registry name (optional, may be None for did method)

    Raises:
        ValueError: If UAID format is invalid
    """
    components = parse_uaid(uaid)
    return {
        "protocol": components.proto,
        "endpoint": components.native_id,
        "registry": components.registry,
    }


def generate_uaid(
    registry: str,
    name: str,
    version: str,
    protocol: str,
    native_id: str,
    skills: list[int],
    uid: str = "0",
) -> str:
    """Generate UAID from agent metadata.

    Implements HCS-14 canonicalization logic:
    1. Create canonical JSON with normalized, sorted keys
    2. Hash with SHA-384
    3. Encode as Base58
    4. Construct UAID string

    Args:
        registry: Registry name (e.g., "context-forge")
        name: Agent name
        version: Agent version (e.g., "1.0.0")
        protocol: Protocol (e.g., "a2a", "mcp", "rest", "grpc")
        native_id: Native endpoint URL
        skills: List of skill IDs (will be sorted for deterministic hash)
        uid: User/agent instance identifier (default: "0")

    Returns:
        UAID string in format: uaid:aid:{hash};uid={uid};registry={registry};proto={proto};nativeId={endpoint}
    """
    # Canonical data (sorted keys, normalized values)
    canonical = {
        "name": name.strip(),
        "nativeId": native_id.strip(),
        "protocol": protocol.strip().lower(),
        "registry": registry.strip().lower(),
        "skills": sorted(skills),
        "version": version.strip(),
    }

    # SHA-384 hash of canonical JSON
    canonical_json = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    hash_bytes = hashlib.sha384(canonical_json.encode("utf-8")).digest()
    hash_b58 = base58.b58encode(hash_bytes).decode("ascii")

    # Construct UAID with normalized values (same normalization as canonical data)
    normalized_registry = registry.lower().strip()
    normalized_protocol = protocol.lower().strip()
    normalized_native_id = native_id.strip()

    parts = [
        f"uaid:aid:{hash_b58}",
        f"uid={uid}",
    ]
    if normalized_registry:
        parts.append(f"registry={normalized_registry}")
    parts.extend(
        [
            f"proto={normalized_protocol}",
            f"nativeId={normalized_native_id}",
        ]
    )

    uaid = ";".join(parts)

    # Validate generated UAID length to prevent database constraint violations
    if len(uaid) > settings.uaid_max_length:
        raise ValueError(
            f"Generated UAID exceeds maximum length ({len(uaid)} > {settings.uaid_max_length} characters). "
            f"Reduce input field sizes (name={len(name)}, endpoint={len(native_id)}, skills={len(skills)})."
        )

    return uaid


def validate_uaid(uaid: str) -> tuple[bool, Optional[str]]:
    """Validate UAID format and return validation result.

    Args:
        uaid: UAID string to validate

    Returns:
        Tuple of (is_valid, error_message)
        - (True, None) if valid
        - (False, error_message) if invalid
    """
    try:
        parse_uaid(uaid)
        return (True, None)
    except ValueError as e:
        return (False, str(e))
