# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/env_deprecation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Warn about deprecated and removed environment variables at startup.
"""

# Future
from __future__ import annotations

# Standard
from fnmatch import fnmatch
import logging
import os
from typing import Mapping, Optional, Sequence

# First-Party
from mcpgateway.config import EnvDeprecation

logger = logging.getLogger(__name__)

DEPRECATED_ENVS: Sequence[EnvDeprecation] = ()
REMOVED_ENVS: Sequence[EnvDeprecation] = (
    EnvDeprecation(
        "MCP_SESSION_POOL_*",
        "The upstream MCP session pool was removed in #4205. UpstreamSessionRegistry manages upstream sessions, one per downstream session and gateway, and has no pool settings. Remove these variables from your environment, Helm values, or compose files.",
    ),
)


def warn_deprecated_envs(env: Optional[Mapping[str, str]] = None) -> None:
    """Check environment variables and log warnings for removed or deprecated items.

    Args:
        env: Optional mapping of environment variables to check. Defaults to ``os.environ``.
    """
    env_vars = os.environ if env is None else env

    for item in REMOVED_ENVS:
        matched = sorted(name for name in env_vars if fnmatch(name.upper(), item.pattern.upper()))
        if matched:
            logger.warning(
                "Ignoring removed environment variables: %s. %s",
                ", ".join(matched),
                item.message,
            )

    for item in DEPRECATED_ENVS:
        matched = sorted(name for name in env_vars if fnmatch(name.upper(), item.pattern.upper()))
        if matched:
            logger.warning(
                "Environment variables are deprecated: %s. %s",
                ", ".join(matched),
                item.message,
            )
