# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_main_entrypoint.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for mcpgateway.__main__ startup entry point.
"""

import importlib

import pytest


class TestMainEntrypoint:
    """Verify __main__.py behaviour under different secret conditions."""

    def test_main_does_not_call_ensure_env_file_secrets(self, monkeypatch):
        """After cleanup, __main__.main() must not call ensure_env_file_secrets."""
        called = []

        def fake_ensure(**kwargs):
            called.append("called")
            return {}

        monkeypatch.setattr(
            "mcpgateway.scripts.init_secrets.ensure_env_file_secrets",
            fake_ensure,
        )
        monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)

        import mcpgateway.__main__ as entrypoint

        importlib.reload(entrypoint)
        entrypoint.main()

        assert called == [], "ensure_env_file_secrets must not be called after cleanup"

    def test_uvicorn_called_with_app_string(self, monkeypatch):
        """uvicorn.run must be called with 'mcpgateway.main:app'."""
        uvicorn_calls: list[tuple] = []

        def fake_uvicorn_run(*args, **kwargs):
            uvicorn_calls.append((args, kwargs))

        monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)

        import mcpgateway.__main__ as entrypoint

        importlib.reload(entrypoint)
        entrypoint.main()

        assert len(uvicorn_calls) == 1
        args, kwargs = uvicorn_calls[0]
        assert args[0] == "mcpgateway.main:app"
