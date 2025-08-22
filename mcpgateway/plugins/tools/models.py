# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/tools/models.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

MCP Plugins CLI models for schema validation.
This module defines models for schema validation.
"""

# Standard

# Third-Party
from pydantic import BaseModel


class InstallManifestPackage(BaseModel):
    """
    A single install manifest record containing the specification of what plugin
    packages and dependencies to be installed from a repository.
    """

    package: str
    repository: str
    extras: list[str] | None = None


class InstallManifest(BaseModel):
    """
    An install manifest containing a list of records describing what plugin
    packages and dependencies to be installed.
    """

    packages: list[InstallManifestPackage]
