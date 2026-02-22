# -*- coding: utf-8 -*-
"""Tests for CORS configuration logic in app.py."""

# Standard
import importlib
import logging
import os
import sys
from unittest.mock import patch

# Third-Party
from starlette.middleware.cors import CORSMiddleware

# Re-use the fake credentials already set in conftest.py (module-level os.environ).
_TEST_ENV_BASE = {
    "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", "sk-fake-test-000"),  # noqa: S105
    "MCPGATEWAY_BEARER_TOKEN": os.environ.get("MCPGATEWAY_BEARER_TOKEN", "tok-fake-test"),  # noqa: S105
}

_APP_MODULE = "agent_runtimes.langchain_agent.app"


def _reload_app(env_overrides: dict) -> object:
    """Reimport app module with given environment variables to trigger CORS setup."""
    env = {**_TEST_ENV_BASE, **env_overrides}
    with patch.dict(os.environ, env, clear=True):
        # __init__.py shadows the attribute ``agent_runtimes.langchain_agent.app``
        # with the FastAPI object.  Grab the real module from sys.modules (placed
        # there by Python's import machinery) or import it fresh.
        mod = sys.modules.get(_APP_MODULE)
        if mod is None:
            mod = importlib.import_module(_APP_MODULE)
        else:
            mod = importlib.reload(mod)
        return mod


def _get_cors_middleware(app):
    """Extract CORS middleware from app middleware stack, if present."""
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            return mw
    return None


class TestCorsDisabledByDefault:
    """When CORS_ORIGINS is unset or empty, no CORS middleware should be added."""

    def test_cors_disabled_when_empty(self):
        """CORS middleware is not added when CORS_ORIGINS is empty."""
        mod = _reload_app({"CORS_ORIGINS": ""})
        assert _get_cors_middleware(mod.app) is None

    def test_cors_disabled_when_unset(self):
        """CORS middleware is not added when CORS_ORIGINS is not set."""
        mod = _reload_app({})
        assert _get_cors_middleware(mod.app) is None


class TestCorsWithExplicitOrigins:
    """When CORS_ORIGINS lists specific origins, those are configured."""

    def test_single_origin(self):
        """Single origin is parsed and applied."""
        mod = _reload_app({"CORS_ORIGINS": "http://localhost:3000"})
        mw = _get_cors_middleware(mod.app)
        assert mw is not None
        assert mw.kwargs["allow_origins"] == ["http://localhost:3000"]

    def test_multiple_origins(self):
        """Comma-separated origins are parsed correctly."""
        mod = _reload_app({"CORS_ORIGINS": "http://localhost:3000,https://example.com"})
        mw = _get_cors_middleware(mod.app)
        assert mw is not None
        assert mw.kwargs["allow_origins"] == ["http://localhost:3000", "https://example.com"]

    def test_credentials_enabled_with_explicit_origins(self):
        """Credentials can be enabled with explicit (non-wildcard) origins."""
        mod = _reload_app({"CORS_ORIGINS": "http://localhost:3000", "CORS_CREDENTIALS": "true"})
        mw = _get_cors_middleware(mod.app)
        assert mw is not None
        assert mw.kwargs["allow_credentials"] is True


class TestCorsWildcardSafety:
    """When CORS_ORIGINS=*, credentials must be forced off."""

    def test_wildcard_without_credentials(self):
        """Wildcard origin works when credentials are not requested."""
        mod = _reload_app({"CORS_ORIGINS": "*"})
        mw = _get_cors_middleware(mod.app)
        assert mw is not None
        assert mw.kwargs["allow_origins"] == ["*"]
        assert mw.kwargs["allow_credentials"] is False

    def test_wildcard_forces_credentials_off(self):
        """Wildcard + credentials=true results in credentials being disabled."""
        mod = _reload_app({"CORS_ORIGINS": "*", "CORS_CREDENTIALS": "true"})
        mw = _get_cors_middleware(mod.app)
        assert mw is not None
        assert mw.kwargs["allow_origins"] == ["*"]
        assert mw.kwargs["allow_credentials"] is False

    def test_wildcard_credentials_warning(self, caplog):
        """Warning is logged when wildcard + credentials is detected."""
        with caplog.at_level(logging.WARNING):
            _reload_app({"CORS_ORIGINS": "*", "CORS_CREDENTIALS": "true"})
        assert "unsafe" in caplog.text.lower()


class TestCorsWildcardMixed:
    """Wildcard mixed with other origins must still trigger the safety guard."""

    def test_wildcard_with_other_origins_normalizes(self):
        """'*,https://example.com' collapses to ['*'] and disables credentials."""
        mod = _reload_app({"CORS_ORIGINS": "*,https://example.com", "CORS_CREDENTIALS": "true"})
        mw = _get_cors_middleware(mod.app)
        assert mw is not None
        assert mw.kwargs["allow_origins"] == ["*"]
        assert mw.kwargs["allow_credentials"] is False

    def test_wildcard_trailing_comma(self):
        """'*,' collapses to ['*'] and disables credentials."""
        mod = _reload_app({"CORS_ORIGINS": "*,", "CORS_CREDENTIALS": "true"})
        mw = _get_cors_middleware(mod.app)
        assert mw is not None
        assert mw.kwargs["allow_origins"] == ["*"]
        assert mw.kwargs["allow_credentials"] is False

    def test_wildcard_mixed_without_credentials(self):
        """'*,https://example.com' without credentials still normalizes to ['*']."""
        mod = _reload_app({"CORS_ORIGINS": "*,https://example.com"})
        mw = _get_cors_middleware(mod.app)
        assert mw is not None
        assert mw.kwargs["allow_origins"] == ["*"]
        assert mw.kwargs["allow_credentials"] is False


class TestCorsOnlyCommas:
    """Edge case: CORS_ORIGINS containing only commas should not add middleware."""

    def test_only_commas(self):
        """CORS_ORIGINS=',,' should not add CORS middleware (parsed to empty list)."""
        mod = _reload_app({"CORS_ORIGINS": ",,,"})
        assert _get_cors_middleware(mod.app) is None
