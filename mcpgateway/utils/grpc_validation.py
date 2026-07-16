# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/grpc_validation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

gRPC Target and TLS Path Validation

Shared SSRF / path-traversal validators for gRPC connections, used by both
``mcpgateway.services.grpc_service`` and ``mcpgateway.translate_grpc``. This
module depends on neither of them, keeping the dependency tree one-way.
"""

# Standard
import ipaddress
from pathlib import Path

# First-Party
from mcpgateway.config import settings


class GrpcServiceError(Exception):
    """Base class for gRPC service-related errors."""


_GRPC_DISALLOWED_SCHEMES = ("unix:", "unix-abstract:", "vsock:", "fd:")


def _validate_grpc_target(target: str) -> None:
    """Validate a gRPC target address against SSRF-unsafe destinations.

    Consults the platform SSRF settings (``ssrf_allow_localhost``,
    ``ssrf_allow_private_networks``, ``ssrf_allowed_networks``,
    ``ssrf_blocked_networks``, ``ssrf_blocked_hosts``) so that gRPC
    targets follow the same rules as HTTP URLs validated by
    ``SecurityValidator.validate_url``.

    Args:
        target: gRPC target string. Accepts ``host:port``, bracketed
            ``[ipv6]:port``, and gRPC name-resolver forms ``dns:///host:port``,
            ``ipv4:host:port``, ``ipv6:host:port``. Local-only schemes
            (``unix:``, ``unix-abstract:``, ``vsock:``, ``fd:``) are always
            rejected because they bypass the network-level SSRF model.

    Raises:
        GrpcServiceError: If the target uses a forbidden scheme or resolves to a blocked address.
    """
    if not target:
        raise GrpcServiceError("Empty gRPC target address")

    # Local-only schemes bypass the IP-based SSRF model entirely; reject outright.
    lowered = target.lower()
    for scheme in _GRPC_DISALLOWED_SCHEMES:
        if lowered.startswith(scheme):
            raise GrpcServiceError(f"gRPC target scheme '{scheme.rstrip(':')}' is not permitted")

    # Strip recognised gRPC name-resolver scheme prefixes so the host check below sees a bare host:port.
    for scheme_prefix in ("dns:///", "dns://", "dns:", "ipv4:", "ipv6:"):
        if lowered.startswith(scheme_prefix):
            target = target[len(scheme_prefix) :]
            break

    # Extract host (strip port). Bracketed IPv6 literals: ``[::1]:50051``.
    if target.startswith("["):
        end = target.find("]")
        if end < 0:
            raise GrpcServiceError(f"Malformed bracketed gRPC target: {target!r}")
        host = target[1:end]
    else:
        host = target.rsplit(":", 1)[0].strip("[]")
    if not host:
        raise GrpcServiceError("Empty gRPC target address")

    # Reserved / multicast IP literals are unconditionally blocked. SecurityValidator._validate_ssrf
    # only checks blocked-networks / localhost / private; it does not flag is_reserved/is_multicast,
    # so this guard runs before delegation to keep the original gRPC-validator semantics. Loopback is
    # excluded because Python flags ``::1`` as both is_loopback AND is_reserved; loopback policy is
    # handled by SecurityValidator below via ssrf_allow_localhost.
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None and not addr.is_loopback and (addr.is_reserved or addr.is_multicast):
        raise GrpcServiceError(f"gRPC target address '{host}' is blocked (reserved/multicast)")

    # Delegate the hostname/IP-network/DNS-resolution policy to the shared SecurityValidator
    # so gRPC and HTTP follow the same SSRF rules and a hostname like ``metadata.google.internal``
    # is resolved before being allowed through.
    # First-Party
    from mcpgateway.common.validators import SecurityValidator  # pylint: disable=import-outside-toplevel

    if getattr(settings, "ssrf_protection_enabled", True):
        try:
            SecurityValidator._validate_ssrf(host, "gRPC target")  # pylint: disable=protected-access
        except ValueError as exc:
            raise GrpcServiceError(str(exc)) from exc


def _validate_tls_path(path_str: str, label: str = "TLS path") -> Path:
    """Validate that a TLS cert/key path is within allowed directories.

    Args:
        path_str: The file path to validate.
        label: Label for error messages.

    Returns:
        Resolved Path object.

    Raises:
        GrpcServiceError: If the path escapes allowed directories.
    """
    resolved = Path(path_str).resolve()
    # Allow only paths under /certs/, /etc/ssl/, /etc/pki/, or the CWD/certs dir
    allowed_prefixes = (
        Path("/certs").resolve(),
        Path("/etc/ssl").resolve(),
        Path("/etc/pki").resolve(),
        Path.cwd().joinpath("certs").resolve(),
    )
    if not any(resolved.is_relative_to(prefix) for prefix in allowed_prefixes):
        raise GrpcServiceError(f"{label} '{path_str}' is outside allowed certificate directories")
    return resolved
