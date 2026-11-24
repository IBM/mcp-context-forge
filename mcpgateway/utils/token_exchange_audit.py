# -*- coding: utf-8 -*-
# mcpgateway/utils/token_exchange_audit.py
"""Location: ./mcpgateway/utils/token_exchange_audit.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Structured audit logging for RFC 8693 token exchange. Never logs raw tokens.
"""

# Standard
import logging
from typing import Optional

# First-Party
from mcpgateway.services.structured_logger import get_structured_logger

# Module logger. IMPORTANT (L2): do NOT set propagate=False here — the event must reach the
# application's configured handlers via propagation to the root logger. The structured
# payload is attached as `extra={"token_exchange": ...}` so log-record-based consumers
# (e.g. caplog in tests) can index it.
logger = logging.getLogger("mcpgateway.audit.token_exchange")

# Separate DB-backed structured logger: the stdlib `logger` above has no handler that
# persists to StructuredLogEntry, so the DB audit trail is written explicitly here.
_db_logger = get_structured_logger("token_exchange")


def audit_token_exchange(
    *,
    user_email: Optional[str],
    gateway_id: str,
    target_audience: Optional[str],
    success: bool,
    expires_in: Optional[int],
    upstream: Optional[str],
    error: Optional[str],
    latency_ms: Optional[int],
    correlation_id: Optional[str] = None,  # L3: tie the event to the originating request
    request_id: Optional[str] = None,
    purpose: str = "invocation",
    mode: str = "impersonation",
) -> None:
    """Emit a structured audit event for one token exchange attempt.

    Records principal claims and outcome only — never the subject, actor, or
    exchanged token material. ``correlation_id``/``request_id`` link the event to
    the request for forensic correlation (Story 3).

    Args:
        user_email: Principal the token was requested for, or ``None`` for a service token.
        gateway_id: Gateway identifier.
        target_audience: Requested audience, if any.
        success: Whether the token request succeeded.
        expires_in: Lifetime of the issued token in seconds, if known.
        upstream: Gateway display name or upstream identifier.
        error: Sanitized failure reason, or ``None`` on success.
        latency_ms: Token request latency in milliseconds.
        correlation_id: Correlation identifier of the originating request.
        request_id: Request identifier of the originating request.
        purpose: ``invocation`` for a per-user exchange, ``discovery`` for the discovery credential.
        mode: ``impersonation`` or ``delegation`` (RFC 8693 ``actor_token`` sent).
    """
    event = {
        "event": "token-exchange",
        "purpose": purpose,
        "mode": mode,
        "user_email": user_email,
        "gateway_id": gateway_id,
        "target_audience": target_audience,
        "success": success,
        "exchanged_token_expires_in": expires_in,
        "upstream": upstream,
        "latency_ms": latency_ms,
        "error": error,
        "correlation_id": correlation_id,
        "request_id": request_id,
    }
    if success:
        logger.info(
            "token-exchange succeeded purpose=%s mode=%s user=%s gateway=%s audience=%s",
            purpose,
            mode,
            user_email,
            gateway_id,
            target_audience,
            extra={"token_exchange": event},
        )
    else:
        logger.warning(
            "token-exchange failed purpose=%s mode=%s user=%s gateway=%s audience=%s error=%s",
            purpose,
            mode,
            user_email,
            gateway_id,
            target_audience,
            error,
            extra={"token_exchange": event},
        )

    _db_logger.log(
        "INFO" if success else "WARNING",
        f"token-exchange {'succeeded' if success else 'failed'} for gateway {gateway_id}",
        user_email=user_email,
        correlation_id=correlation_id,
        request_id=request_id,
        is_security_event=True,
        custom_fields=event,
    )
