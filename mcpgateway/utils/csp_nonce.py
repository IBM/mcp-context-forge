# -*- coding: utf-8 -*-
"""CSP nonce helper utilities.

Provides a standalone helper for retrieving CSP nonces from request state,
separated from mcpgateway.main to avoid cyclic import issues.
"""

# Standard
import logging

# Third-Party
from starlette.requests import Request

logger = logging.getLogger(__name__)


def get_csp_nonce_from_request(request: Request) -> str:
    """
    Retrieve the CSP nonce from the request state.

    Used in templates to add nonce attributes to inline scripts.

    Args:
        request: The FastAPI/Starlette Request object. Can be None in test contexts.

    Returns:
        The CSP nonce string, or empty string if not available.
    """
    if request is None:
        logger.debug("CSP nonce requested with None request")
        return ""
    nonce = getattr(request.state, "csp_nonce", "")
    if not nonce:
        logger.warning("CSP nonce missing from request.state — inline scripts may be blocked by CSP")
    return nonce
