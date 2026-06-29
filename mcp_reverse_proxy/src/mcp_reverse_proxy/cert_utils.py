# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/cert_utils.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Certificate utilities for MCP reverse proxy transports.
"""

# Standard
import os


def load_cert_data(cert: str) -> str:
    """Load certificate data from file path or return as-is if already PEM content.

    This handles certificates from config.json which can be either file paths or PEM content.
    CLI arguments are pre-loaded by the CLI layer.

    Args:
        cert: Either a file path to a certificate or PEM-encoded certificate content.

    Returns:
        PEM-encoded certificate content as string.

    Raises:
        FileNotFoundError: If cert is a file path but file doesn't exist.
        ValueError: If cert content is invalid.
    """
    # First check if it's already PEM content (most reliable indicator)
    if '-----BEGIN CERTIFICATE-----' in cert:
        return cert

    # Not PEM content, treat as file path
    cert_path = os.path.expanduser(cert)
    if not os.path.isfile(cert_path):
        raise FileNotFoundError(f"Certificate file not found: {cert_path}")

    with open(cert_path, 'r', encoding='utf-8') as f:
        cert_data = f.read()

    # Validate it looks like PEM content
    if '-----BEGIN CERTIFICATE-----' not in cert_data:
        raise ValueError(f"Certificate file does not contain valid PEM data: {cert_path}")

    return cert_data
