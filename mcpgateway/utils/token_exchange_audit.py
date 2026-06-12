# mcpgateway/utils/token_exchange_audit.py
"""Structured audit logging for RFC 8693 token exchange. Never logs raw tokens."""

# Standard
import logging
from typing import Optional

# Module logger. IMPORTANT (L2): do NOT set propagate=False here — the event must reach the
# application's configured handlers (incl. the structured-logging / DB sink when
# STRUCTURED_LOGGING_DATABASE_ENABLED) via propagation to the root logger. The structured
# payload is attached as `extra={"token_exchange": ...}` so structured handlers can index it.
logger = logging.getLogger("mcpgateway.audit.token_exchange")


def audit_token_exchange(
    *,
    user_email: str,
    gateway_id: str,
    target_audience: Optional[str],
    success: bool,
    expires_in: Optional[int],
    upstream: Optional[str],
    error: Optional[str],
    latency_ms: Optional[int],
    correlation_id: Optional[str] = None,  # L3: tie the event to the originating request
    request_id: Optional[str] = None,
) -> None:
    """Emit a structured audit event for one token exchange attempt.

    Records principal claims and outcome only — never the subject or exchanged
    token material. ``correlation_id``/``request_id`` link the event to the
    request for forensic correlation (Story 3).
    """
    event = {
        "event": "token-exchange",
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
            "token-exchange succeeded user=%s gateway=%s audience=%s",
            user_email,
            gateway_id,
            target_audience,
            extra={"token_exchange": event},
        )
    else:
        logger.warning(
            "token-exchange failed user=%s gateway=%s audience=%s error=%s",
            user_email,
            gateway_id,
            target_audience,
            error,
            extra={"token_exchange": event},
        )
