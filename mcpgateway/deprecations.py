# -*- coding: utf-8 -*-
"""Shared deprecation metadata for runtime warnings."""

DEPRECATION_EFFECTIVE_DATE = "2026-06-11"
DEPRECATION_HEADER_DATE = "@1781136000"
DEPRECATION_DOC_URL = "https://ibm.github.io/mcp-context-forge/deprecations/"
SUNSET_DATE = "2026-07-07"
SUNSET_HEADER_DATE = "Tue, 07 Jul 2026 00:00:00 GMT"
DEPRECATION_LINK_VALUE = f'<{DEPRECATION_DOC_URL}>; rel="deprecation"; type="text/html"'
DEPRECATION_RESPONSE_HEADERS = {
    "Deprecation": DEPRECATION_HEADER_DATE,
    "Sunset": SUNSET_HEADER_DATE,
    "Link": DEPRECATION_LINK_VALUE,
}

RUST_MCP_RUNTIME_DEPRECATION_MESSAGE = (
    "The Rust MCP runtime sidecar is deprecated as of 2026-06-11 and will sunset on 2026-07-07. "
    "Use the default Python MCP transport path. See https://ibm.github.io/mcp-context-forge/deprecations/."
)
RUST_A2A_RUNTIME_DEPRECATION_MESSAGE = (
    "The Rust A2A runtime sidecar is deprecated as of 2026-06-11 and will sunset on 2026-07-07. "
    "Use the default Python A2A invocation path. See https://ibm.github.io/mcp-context-forge/deprecations/."
)
VALIDATION_MIDDLEWARE_DEPRECATION_MESSAGE = (
    "ValidationMiddleware is deprecated as of 2026-06-11 and will sunset on 2026-07-07. "
    "Use endpoint-level Pydantic validation and existing protocol-specific validation. "
    "See https://ibm.github.io/mcp-context-forge/deprecations/."
)
