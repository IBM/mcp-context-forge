"""UAID (Universal Agent ID) utilities for HCS-14 support.

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
from typing import Optional

# Third-Party
import base58


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
    if not is_uaid(uaid):
        raise ValueError(f"Invalid UAID format: must start with 'uaid:aid:' or 'uaid:did:', got: {uaid}")

    # Split on first two colons to get method and rest
    parts = uaid.split(":", 3)
    if len(parts) < 3:
        raise ValueError(f"Invalid UAID format: expected 'uaid:METHOD:...' format, got: {uaid}")

    method = parts[1]  # "aid" or "did"
    if method not in ("aid", "did"):
        raise ValueError(f"Invalid UAID method: expected 'aid' or 'did', got: {method}")

    # Split remainder on semicolons
    remainder = parts[2]
    segments = remainder.split(";")
    if len(segments) < 2:
        raise ValueError(f"Invalid UAID format: expected hash/did and parameters separated by ';', got: {uaid}")

    hash_or_did = segments[0]

    # Parse key=value parameters
    params = {}
    for segment in segments[1:]:
        if "=" not in segment:
            raise ValueError(f"Invalid UAID parameter: expected 'key=value' format, got: {segment}")
        key, value = segment.split("=", 1)
        params[key] = value

    # Extract required parameters
    if "uid" not in params:
        raise ValueError(f"Invalid UAID: missing required 'uid' parameter in: {uaid}")
    if "proto" not in params:
        raise ValueError(f"Invalid UAID: missing required 'proto' parameter in: {uaid}")
    if "nativeId" not in params:
        raise ValueError(f"Invalid UAID: missing required 'nativeId' parameter in: {uaid}")

    # Registry is required for aid method but optional for did method
    registry = params.get("registry")
    if method == "aid" and not registry:
        raise ValueError(f"Invalid UAID: 'registry' parameter required for aid method in: {uaid}")

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

    return ";".join(parts)


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
