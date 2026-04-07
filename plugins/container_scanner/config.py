#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/container_scanner/config.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Configuration models for the ContainerScannerPlugin.

All values are loaded from the gateway plugin config dict, not from environment
variables directly. Registry credentials are referenced by env-var name and
resolved at runtime by auth_resolver.py.

"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import List, Literal, Optional

# Third-Party
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


def _parse_registry_host(ref: str) -> str:
    """Extract the registry host from a Docker image reference or registry URL.

    A segment is treated as a registry host when it contains a dot, is "localhost",
    or has a colon followed only by digits (a port number).  A colon followed by
    non-digits is a tag separator on an implicit docker.io image (e.g. "python:3.12-slim").

    Args:
        ref: An image reference (e.g., "ghcr.io/org/app:v1") or registry URL
            (e.g., "gcr.io/my-project"). Path components beyond the host are ignored.

    Returns:
        The registry hostname (and optional port), e.g. "ghcr.io" or "registry:5000".
        Returns "docker.io" when no explicit registry host is present.
    """
    first = ref.split("/")[0]
    # Strip tag/port to isolate the bare hostname for dot and localhost checks
    # e.g. "python:3.12-slim" → hostname_part="python"; "localhost:5000" → "localhost"
    hostname_part = first.split(":")[0]
    if "." in hostname_part or hostname_part == "localhost":
        return first
    # Colon is a port only when followed exclusively by digits (e.g. "registry:5000")
    colon_idx = first.find(":")
    if colon_idx != -1 and first[colon_idx + 1 :].isdigit():
        return first
    return "docker.io"


class RegistryConfig(BaseModel):
    """Per-registry authentication configuration.

    Credentials are stored as the *names* of environment variables,
    not the secret values themselves. auth_resolver.py resolves them
    at scan time via os.environ.

    Attributes:
        url: Registry URL prefix (e.g., "ghcr.io", "gcr.io/my-project").
        auth_type: Authentication mechanism — "token" or "basic".
        token_env: Env var name holding a bearer/token credential (token auth).
        username_env: Env var name holding the username (basic auth).
        password_env: Env var name holding the password (basic auth).
    """

    url: str
    auth_type: Literal["token", "basic"]
    token_env: Optional[str] = None
    username_env: Optional[str] = None
    password_env: Optional[str] = None

    @model_validator(mode="after")
    def validate_auth_fields(self) -> "RegistryConfig":
        if self.auth_type == "token":
            if not self.token_env:
                raise ValueError(f"Registry '{self.url}': auth_type 'token' requires token_env.")
            unused = [name for name, val in [("username_env", self.username_env), ("password_env", self.password_env)] if val]
            if unused:
                logger.warning(f"Registry '{self.url}': auth_type 'token' ignores {' and '.join(unused)}.")
        elif self.auth_type == "basic":
            missing = [name for name, val in [("username_env", self.username_env), ("password_env", self.password_env)] if not val]
            if missing:
                raise ValueError(f"Registry '{self.url}': auth_type 'basic' requires {' and '.join(missing)}.")
            if self.token_env:
                logger.warning(f"Registry '{self.url}': auth_type 'basic' ignores token_env.")
        return self


class ScannerConfig(BaseModel):
    """Top-level configuration for the ContainerScannerPlugin.

    Attributes:
        scanner: Which scanner CLI to use.
        severity_threshold: Minimum severity level that triggers a finding.
            Vulnerabilities below this threshold are silently dropped.
        fail_on_unfixed: If True, unfixed vulnerabilities still count as violations.
        ignore_cves: CVE IDs to suppress regardless of severity.
        timeout_seconds: Hard timeout for the scanner subprocess.
        mode: Plugin enforcement mode — "enforce" blocks deployment,
            "audit" logs but allows, "disabled" skips the plugin entirely.
        cache_enabled: Whether digest-based result caching is active.
        cache_ttl_hours: How long cached results are considered valid.
        registries: Per-registry authentication configuration.
        on_scan_error: Behaviour when the scanner subprocess fails.
            "fail_closed" blocks deployment (safe default);
            "fail_open" allows deployment and records the error.
    """

    scanner: Literal["trivy", "grype"] = "trivy"
    severity_threshold: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = "HIGH"
    fail_on_unfixed: bool = False
    ignore_cves: List[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=300, gt=0)
    mode: Literal["enforce", "audit", "disabled"] = "enforce"
    cache_enabled: bool = True
    cache_ttl_hours: int = Field(default=24, gt=0)
    registries: List[RegistryConfig] = Field(default_factory=list)
    on_scan_error: Literal["fail_closed", "fail_open"] = "fail_closed"

    def registry_for(self, image_ref: str) -> Optional[RegistryConfig]:
        """Return the first registry config whose host matches the image reference.

        Args:
            image_ref: Full image reference (e.g., "ghcr.io/org/app:v1").

        Returns:
            Matching RegistryConfig, or None if the registry is public / unconfigured.
        """
        image_host = _parse_registry_host(image_ref)
        for reg in self.registries:
            if image_host == _parse_registry_host(reg.url):
                return reg
        return None
