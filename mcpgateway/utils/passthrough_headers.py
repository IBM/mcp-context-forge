from typing import Dict
from sqlalchemy.orm import Session
import logging

from mcpgateway.config import settings
from mcpgateway.models import GlobalConfig
from mcpgateway.db import Gateway as DbGateway

logger = logging.getLogger(__name__)


from typing import Optional


def get_passthrough_headers(request_headers: Dict[str, str], base_headers: Dict[str, str], db: Session, gateway: Optional[DbGateway] = None) -> Dict[str, str]:
    """Get headers that should be passed through to the target gateway.

    Args:
        request_headers: Headers from the incoming request
        base_headers: Base headers that should always be included
        gateway: Target gateway (optional)
        db: Database session for global config lookup

    Returns:
        Dict of headers that should be passed through
    """
    passthrough_headers = base_headers.copy()

    # Get global passthrough headers first
    global_config = db.query(GlobalConfig).first()
    allowed_headers = global_config.passthrough_headers if global_config else settings.default_passthrough_headers

    # Gateway specific headers override global config
    if gateway:
        if gateway.passthrough_headers is not None:
            allowed_headers = gateway.passthrough_headers

    # Get auth headers to check for conflicts
    base_headers_keys = {key.lower(): key for key in passthrough_headers.keys()}

    # Copy allowed headers from request
    if request_headers and allowed_headers:
        for header_name in allowed_headers:
            header_value = request_headers.get(header_name.lower())
            if header_value:

                header_lower = header_name.lower()
                # Skip if header would conflict with existing auth headers
                if header_lower in base_headers_keys:
                    logger.warning(f"Skipping {header_name} header passthrough as it conflicts with pre-defined headers")
                    continue

                # Skip if header would conflict with gateway auth
                if gateway:
                    if gateway.auth_type == "basic" and header_lower == "authorization":
                        logger.warning(f"Skipping Authorization header passthrough due to basic auth configuration on gateway {gateway.name}")
                        continue
                    if gateway.auth_type == "bearer" and header_lower == "authorization":
                        logger.warning(f"Skipping Authorization header passthrough due to bearer auth configuration on gateway {gateway.name}")
                        continue

                passthrough_headers[header_name] = header_value
            else:
                logger.warning(f"Header {header_name} not found in request headers, skipping passthrough")

    return passthrough_headers
