# -*- coding: utf-8 -*-
"""JWT Claims Extraction Plugin Package.

Location: ./mcpgateway/plugins/jwt_claims_extraction/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Plugin for extracting JWT claims and metadata for downstream authorization.
"""

from mcpgateway.plugins.jwt_claims_extraction.plugin import JwtClaimsExtractionPlugin

__all__ = [
    "JwtClaimsExtractionPlugin",
]
