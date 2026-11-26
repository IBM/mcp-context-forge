# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/env_deprecation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Warn about deprecated and removed environment variables at startup.
"""

# Standard
from fnmatch import fnmatch
import logging
import os
from typing import Collection, Optional

# Third-Party
from dotenv import dotenv_values


logger = logging.getLogger(__name__)

DEPRECATED_ENVS = [
    ("EXPOSE_ERROR_DETAILS", "Ignored: error responses are always sanitized. Remove it from your configuration."),
]
REMOVED_ENVS = [
    (
        "MCP_SESSION_POOL_*",
        "UpstreamSessionRegistry (mcpgateway/services/upstream_session_registry.py) replaced the upstream MCP session pool in #4205. "
        "Remove these variables from your environment, Helm values, or compose files.",
    ),
]


def warn_deprecated_envs(env: Optional[Collection[str]] = None) -> None:
    """Check environment variables and log warnings for removed or deprecated items.

    Args:
        env: Optional collection of variable names. Defaults to the process environment and ``.env``.
    """
    env_vars = {name.upper() for name in (*os.environ, *dotenv_values(".env", interpolate=False))} if env is None else env

    for pattern, message in REMOVED_ENVS:
        matched = sorted(name for name in env_vars if fnmatch(name.upper(), pattern.upper()))
        if matched:
            logger.warning(
                "Ignoring removed environment variables: %s. %s",
                ", ".join(matched),
                message,
            )

    for pattern, message in DEPRECATED_ENVS:
        matched = sorted(name for name in env_vars if fnmatch(name.upper(), pattern.upper()))
        if matched:
            logger.warning(
                "Environment variables are deprecated: %s. %s",
                ", ".join(matched),
                message,
            )
