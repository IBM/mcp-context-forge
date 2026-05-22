"""Tests for mcpgateway.__main__ startup entry point."""
import importlib
import os
from unittest.mock import MagicMock, call, patch

import pytest


class TestMainEntrypoint:
    """Verify __main__.py behaviour under different secret conditions."""

    def test_ensure_secrets_called_before_config_import(self, tmp_path, monkeypatch):
        """ensure_env_file_secrets() must be called before mcpgateway.config is imported."""
        call_order: list[str] = []

        def fake_ensure(**kwargs):
            call_order.append("ensure")
            return {}

        def fake_uvicorn_run(*args, **kwargs):
            call_order.append("uvicorn")

        monkeypatch.setattr(
            "mcpgateway.scripts.init_secrets.ensure_env_file_secrets", fake_ensure
        )
        monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)

        # Import fresh (don't use cached module)
        import mcpgateway.__main__ as entrypoint
        importlib.reload(entrypoint)
        entrypoint.main()

        assert call_order[0] == "ensure", "ensure_env_file_secrets must run first"

    def test_generated_secrets_logged(self, tmp_path, monkeypatch, capsys):
        """If secrets were generated, a message must be printed to stdout."""

        def fake_ensure(**kwargs):
            return {"JWT_SECRET_KEY": "generated-abc", "AUTH_ENCRYPTION_SECRET": "generated-xyz"}

        def fake_uvicorn_run(*args, **kwargs):
            pass

        monkeypatch.setattr(
            "mcpgateway.scripts.init_secrets.ensure_env_file_secrets", fake_ensure
        )
        monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)

        import mcpgateway.__main__ as entrypoint
        importlib.reload(entrypoint)
        entrypoint.main()

        captured = capsys.readouterr()
        assert "JWT_SECRET_KEY" in captured.out
        assert "auto-generated" in captured.out.lower()

    def test_no_message_when_secrets_already_strong(self, tmp_path, monkeypatch, capsys):
        """No stdout noise when secrets are already strong."""

        def fake_ensure(**kwargs):
            return {}

        def fake_uvicorn_run(*args, **kwargs):
            pass

        monkeypatch.setattr(
            "mcpgateway.scripts.init_secrets.ensure_env_file_secrets", fake_ensure
        )
        monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)

        import mcpgateway.__main__ as entrypoint
        importlib.reload(entrypoint)
        entrypoint.main()

        captured = capsys.readouterr()
        assert captured.out.strip() == ""

    def test_uvicorn_called_with_app_string(self, monkeypatch):
        """uvicorn.run must be called with 'mcpgateway.main:app'."""
        uvicorn_calls: list[tuple] = []

        def fake_ensure(**kwargs):
            return {}

        def fake_uvicorn_run(*args, **kwargs):
            uvicorn_calls.append((args, kwargs))

        monkeypatch.setattr(
            "mcpgateway.scripts.init_secrets.ensure_env_file_secrets", fake_ensure
        )
        monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)

        import mcpgateway.__main__ as entrypoint
        importlib.reload(entrypoint)
        entrypoint.main()

        assert len(uvicorn_calls) == 1
        args, kwargs = uvicorn_calls[0]
        assert args[0] == "mcpgateway.main:app"
