#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/container_scanner/auth/auth_resolver.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Resolves registry credentials from environment variables and returns
scanner-compatible environment variable dicts for subprocess injection.

The resolver is intentionally stateless after construction — it reads
os.environ on every call so that credential rotation is picked up
without restarting the gateway.
"""

# Future
from __future__ import annotations

# Standard
import os

# Local
from plugins.container_scanner.config import ScannerConfig


class AuthResolver:
    """Translates RegistryConfig env-var-name fields into scanner credentials.

    Usage::

        resolver = AuthResolver(config)
        env_vars = resolver.resolve("ghcr.io/org/app:v1")
        # env_vars is injected into the scanner subprocess environment

    Args:
        config: Top-level scanner configuration containing the registries list.
    """

    _config : ScannerConfig

    def __init__(self, config: ScannerConfig) -> None:
        self._config = config


    def _resolve_env(self, var_name: str, registry_url: str) -> str:
        """Look up a required environment variable by name.

        Args:
            var_name: Name of the environment variable (e.g., "GHCR_TOKEN").
            registry_url: Registry URL used in the error message for clarity.

        Returns:
            The value of the environment variable.

        Raises:
            EnvironmentError: If the variable is not set in os.environ.
        """
        resolved_value = os.environ.get(var_name)
        if not resolved_value:
            raise EnvironmentError(f"Registry {registry_url}: required env var {var_name} is not set")

        return resolved_value


    def resolve(self, image_ref: str) -> dict[str, str]:
        """Return scanner env vars for the registry that owns *image_ref*.

        Injects credentials for both Trivy and Grype so that the runner
        does not need to know which scanner CLI is in use.

        Args:
            image_ref: Full image reference (e.g., "ghcr.io/org/app:v1").

        Returns:
            A dict of environment variable names → values to merge into the
            scanner subprocess environment.  Returns ``{}`` for public
            registries that have no matching entry in the config.

        Raises:
            EnvironmentError: If a required credential env var is not set.
        """
        reg = self._config.registry_for(image_ref)
        if not reg:
            return {}
        if reg.auth_type == "token":
            username = ""
            password = self._resolve_env(reg.token_env, reg.url)
        else:
            username = self._resolve_env(reg.username_env, reg.url)
            password = self._resolve_env(reg.password_env, reg.url)
        return {
            "TRIVY_USERNAME": username,
            "TRIVY_PASSWORD": password,
            "GRYPE_REGISTRY_AUTH_USERNAME": username,
            "GRYPE_REGISTRY_AUTH_PASSWORD": password,
        }

