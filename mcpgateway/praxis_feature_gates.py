"""Request-time gates for staged Praxis configuration delivery."""

from typing import Final

from fastapi import HTTPException, status

from mcpgateway.config import settings

PRAXIS_FEATURE_DISABLED: Final = "praxis_feature_disabled"


def require_praxis_artifact_delivery() -> None:
    """Reject publication and artifact access while delivery is disabled."""
    if not settings.praxis_artifact_delivery_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, PRAXIS_FEATURE_DISABLED)


def require_praxis_activation() -> None:
    """Reject reports unless the complete activation chain is enabled."""
    if not settings.praxis_artifact_delivery_enabled or not settings.praxis_activation_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, PRAXIS_FEATURE_DISABLED)


__all__ = ("PRAXIS_FEATURE_DISABLED", "require_praxis_activation", "require_praxis_artifact_delivery")
