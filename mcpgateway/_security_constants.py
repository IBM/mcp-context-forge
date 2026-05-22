# -*- coding: utf-8 -*-
"""Stdlib-only security constants shared between config.py and init_secrets.py.

Must not import pydantic or any other mcpgateway module; init_secrets.py
imports this before mcpgateway.config is loaded.
"""

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
