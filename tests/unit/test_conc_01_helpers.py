"""Unit tests for CONC-01 gateway parallel-create helper functions."""

# Future
from __future__ import annotations

# Standard
import importlib.util
import os
from pathlib import Path
import sys
from unittest.mock import patch

# Third-Party
import pytest

# ---------------------------------------------------------------------------
# Import the manual test module by path (it has no __init__.py).
# ---------------------------------------------------------------------------
_MODULE_PATH = Path(__file__).resolve().parents[2] / "tests" / "manual" / "concurrency" / "conc_01_gateways_parallel_create_pg_redis.py"
_spec = importlib.util.spec_from_file_location("conc_01_gateways_parallel_create_pg_redis", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_env_bool = _mod._env_bool
_build_config = _mod._build_config
_db_mode = _mod._db_mode
_normalize_pg_dsn = _mod._normalize_pg_dsn


# ---------------------------------------------------------------------------
# _env_bool
# ---------------------------------------------------------------------------
class TestEnvBool:
    """Tests for _env_bool helper."""

    def test_returns_default_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env_bool("CONC_MISSING_VAR", True) is True

    def test_returns_false_default_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env_bool("CONC_MISSING_VAR", False) is False

    def test_returns_true_for_1(self):
        with patch.dict(os.environ, {"CONC_FLAG": "1"}, clear=False):
            assert _env_bool("CONC_FLAG", False) is True

    def test_returns_true_for_true(self):
        with patch.dict(os.environ, {"CONC_FLAG": "true"}, clear=False):
            assert _env_bool("CONC_FLAG", False) is True

    def test_returns_true_for_yes(self):
        with patch.dict(os.environ, {"CONC_FLAG": "yes"}, clear=False):
            assert _env_bool("CONC_FLAG", False) is True

    def test_returns_true_for_on(self):
        with patch.dict(os.environ, {"CONC_FLAG": "on"}, clear=False):
            assert _env_bool("CONC_FLAG", False) is True

    def test_returns_false_for_0(self):
        with patch.dict(os.environ, {"CONC_FLAG": "0"}, clear=False):
            assert _env_bool("CONC_FLAG", True) is False

    def test_returns_false_for_false(self):
        with patch.dict(os.environ, {"CONC_FLAG": "false"}, clear=False):
            assert _env_bool("CONC_FLAG", True) is False

    def test_returns_false_for_no(self):
        with patch.dict(os.environ, {"CONC_FLAG": "no"}, clear=False):
            assert _env_bool("CONC_FLAG", True) is False

    def test_returns_false_for_off(self):
        with patch.dict(os.environ, {"CONC_FLAG": "off"}, clear=False):
            assert _env_bool("CONC_FLAG", True) is False

    def test_strips_whitespace(self):
        with patch.dict(os.environ, {"CONC_FLAG": "  true  "}, clear=False):
            assert _env_bool("CONC_FLAG", False) is True

    def test_case_insensitive(self):
        with patch.dict(os.environ, {"CONC_FLAG": "TRUE"}, clear=False):
            assert _env_bool("CONC_FLAG", False) is True


# ---------------------------------------------------------------------------
# _build_config
# ---------------------------------------------------------------------------
class TestBuildConfig:
    """Tests for _build_config helper."""

    def test_raises_when_token_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="CONC_TOKEN is required"):
                _build_config()

    def test_raises_when_token_empty(self):
        with patch.dict(os.environ, {"CONC_TOKEN": ""}, clear=True):
            with pytest.raises(ValueError, match="CONC_TOKEN is required"):
                _build_config()

    def test_raises_when_token_whitespace(self):
        with patch.dict(os.environ, {"CONC_TOKEN": "   "}, clear=True):
            with pytest.raises(ValueError, match="CONC_TOKEN is required"):
                _build_config()

    def test_returns_defaults_with_valid_token(self):
        env = {"CONC_TOKEN": "tok123"}
        with patch.dict(os.environ, env, clear=True):
            cfg = _build_config()
            assert cfg["token"] == "tok123"
            assert cfg["base_url"] == "http://localhost:8000"
            assert cfg["name_prefix"] == "conc-gw"
            assert cfg["gateway_url"] == "http://127.0.0.1:9000/sse"
            assert cfg["db_path"] == "mcp.db"
            assert cfg["database_url"] == ""
            assert cfg["cases_filter"] == ""
            assert cfg["timeout_override"] == ""

    def test_overrides_from_env(self):
        env = {
            "CONC_TOKEN": "tok",
            "CONC_BASE_URL": "http://localhost:9000/",
            "CONC_NAME_PREFIX": "my-gw",
            "CONC_GATEWAY_URL": "http://127.0.0.1:9001/sse",
            "CONC_DB_PATH": "custom.db",
            "DATABASE_URL": "postgresql://localhost/mydb",
            "CONC_CASES": "api_smoke_20,api_100",
            "CONC_TIMEOUT_OVERRIDE": "30",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = _build_config()
            assert cfg["base_url"] == "http://localhost:9000"  # trailing slash stripped
            assert cfg["name_prefix"] == "my-gw"
            assert cfg["gateway_url"] == "http://127.0.0.1:9001/sse"
            assert cfg["db_path"] == "custom.db"
            assert cfg["database_url"] == "postgresql://localhost/mydb"
            assert cfg["cases_filter"] == "api_smoke_20,api_100"
            assert cfg["timeout_override"] == "30"

    def test_empty_name_prefix_falls_back(self):
        env = {"CONC_TOKEN": "tok", "CONC_NAME_PREFIX": "  "}
        with patch.dict(os.environ, env, clear=True):
            cfg = _build_config()
            assert cfg["name_prefix"] == "conc-gw"

    def test_empty_db_path_falls_back(self):
        env = {"CONC_TOKEN": "tok", "CONC_DB_PATH": "  "}
        with patch.dict(os.environ, env, clear=True):
            cfg = _build_config()
            assert cfg["db_path"] == "mcp.db"

    def test_db_check_default_true(self):
        env = {"CONC_TOKEN": "tok"}
        with patch.dict(os.environ, env, clear=True):
            cfg = _build_config()
            assert cfg["db_check_default"] is True

    def test_db_check_default_disabled(self):
        env = {"CONC_TOKEN": "tok", "CONC_DB_CHECK": "0"}
        with patch.dict(os.environ, env, clear=True):
            cfg = _build_config()
            assert cfg["db_check_default"] is False


# ---------------------------------------------------------------------------
# _db_mode
# ---------------------------------------------------------------------------
class TestDbMode:
    """Tests for _db_mode helper."""

    def test_postgres_url(self):
        assert _db_mode("postgresql://user:pass@localhost/db") == "postgres"

    def test_postgres_psycopg_url(self):
        assert _db_mode("postgresql+psycopg://user:pass@localhost/db") == "postgres"

    def test_sqlite_fallback_for_sqlite_url(self):
        assert _db_mode("sqlite:///./mcp.db") == "sqlite"

    def test_sqlite_fallback_for_empty_string(self):
        assert _db_mode("") == "sqlite"

    def test_sqlite_fallback_for_unknown_scheme(self):
        assert _db_mode("mysql://user:pass@localhost/db") == "sqlite"


# ---------------------------------------------------------------------------
# _normalize_pg_dsn
# ---------------------------------------------------------------------------
class TestNormalizePgDsn:
    """Tests for _normalize_pg_dsn helper."""

    def test_strips_psycopg_prefix(self):
        dsn = "postgresql+psycopg://user:pass@localhost:5432/db"
        assert _normalize_pg_dsn(dsn) == "postgresql://user:pass@localhost:5432/db"

    def test_passthrough_plain_postgresql(self):
        dsn = "postgresql://user:pass@localhost:5432/db"
        assert _normalize_pg_dsn(dsn) == dsn

    def test_passthrough_other_url(self):
        dsn = "sqlite:///./mcp.db"
        assert _normalize_pg_dsn(dsn) == dsn
