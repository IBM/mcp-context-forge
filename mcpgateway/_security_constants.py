# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/_security_constants.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Stdlib-only security constants shared between config.py and init_secrets.py.

Must not import pydantic or any other mcpgateway module; init_secrets.py
imports this before mcpgateway.config is loaded.
"""

# Standard
import math

MIN_SECRET_LENGTH: int = 32
MIN_ENTROPY: float = 3.5


def calculate_entropy(text: str) -> float:
    """Calculate Shannon entropy to detect low-randomness secrets.

    Args:
        text (str): The secret string to evaluate.

    Returns:
        float: The calculated entropy score.
    """
    if not text:
        return 0.0
    probabilities = [text.count(c) / len(text) for c in set(text)]
    return -sum(p * math.log2(p) for p in probabilities)


WEAK_VALUES: tuple[str, ...] = (
    "my-test-key",
    "my-test-key-but-now-longer-than-32-bytes",
    "my-test-salt",
    "changeme",
    "secret",
    "password",
    "test-secret",
    "my-secret",
    "12345678",
)
