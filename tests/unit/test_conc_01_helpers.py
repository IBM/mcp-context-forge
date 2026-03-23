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
_Case = _mod._Case
DEFAULT_CASES = _mod.DEFAULT_CASES


# ---------------------------------------------------------------------------
# _env_bool
# ---------------------------------------------------------------------------
class TestEnvBool:
    """Tests for _env_bool helper."""

    def test_returns_default_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env_bool("CONC_MISSING_VAR", True) is True
            assert _env_bool("CONC_MISSING_VAR", False) is False

    def test_truthy_values(self):
        for val in ("1", "true", "yes", "on", "TRUE", "Yes", "ON", " 1 ", " true "):
            with patch.dict(os.environ, {"CONC_DB_CHECK": val}, clear=False):
                assert _env_bool("CONC_DB_CHECK", False) is True, f"Expected True for {val!r}"

    def test_falsy_values(self):
        for val in ("0", "false", "no", "off", "", "random"):
            with patch.dict(os.environ, {"CONC_DB_CHECK": val}, clear=False):
                assert _env_bool("CONC_DB_CHECK", True) is False, f"Expected False for {val!r}"


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
            assert cfg["base_url"] == "http://127.0.0.1:8000"
            assert cfg["name_prefix"] == "conc-gw"
            assert cfg["gateway_url"] == "http://127.0.0.1:9000/sse"
            assert cfg["db_check_default"] is True
            assert cfg["db_path"] == "mcp.db"
            assert cfg["database_url"] == ""
            assert cfg["cases_filter"] == ""
            assert cfg["timeout_override"] == ""

    def test_overrides_from_env(self):
        env = {
            "CONC_TOKEN": "tok",
            "CONC_BASE_URL": "https://gw.example.com/",
            "CONC_NAME_PREFIX": "my-gw",
            "CONC_GATEWAY_URL": "https://backend.example.com/sse",
            "CONC_DB_CHECK": "0",
            "CONC_DB_PATH": "/tmp/test.db",
            "DATABASE_URL": "postgresql+psycopg://user:pass@host/db",
            "CONC_CASES": "api_smoke_20",
            "CONC_TIMEOUT_OVERRIDE": "30",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = _build_config()
            assert cfg["base_url"] == "https://gw.example.com"  # trailing slash stripped
            assert cfg["name_prefix"] == "my-gw"
            assert cfg["gateway_url"] == "https://backend.example.com/sse"
            assert cfg["db_check_default"] is False
            assert cfg["db_path"] == "/tmp/test.db"
            assert cfg["database_url"] == "postgresql+psycopg://user:pass@host/db"
            assert cfg["cases_filter"] == "api_smoke_20"
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


# ---------------------------------------------------------------------------
# _db_mode
# ---------------------------------------------------------------------------
class TestDbMode:
    """Tests for _db_mode helper."""

    def test_postgresql_standard(self):
        assert _db_mode("postgresql://user:pass@host/db") == "postgres"

    def test_postgresql_psycopg(self):
        assert _db_mode("postgresql+psycopg://user:pass@host/db") == "postgres"

    def test_sqlite_empty(self):
        assert _db_mode("") == "sqlite"

    def test_sqlite_path(self):
        assert _db_mode("sqlite:///./mcp.db") == "sqlite"

    def test_sqlite_other(self):
        assert _db_mode("mysql://user:pass@host/db") == "sqlite"


# ---------------------------------------------------------------------------
# _normalize_pg_dsn
# ---------------------------------------------------------------------------
class TestNormalizePgDsn:
    """Tests for _normalize_pg_dsn helper."""

    def test_strips_psycopg_driver(self):
        result = _normalize_pg_dsn("postgresql+psycopg://user:pass@host:5432/db")
        assert result == "postgresql://user:pass@host:5432/db"

    def test_preserves_standard_dsn(self):
        dsn = "postgresql://user:pass@host:5432/db"
        assert _normalize_pg_dsn(dsn) == dsn

    def test_preserves_non_postgresql_dsn(self):
        dsn = "sqlite:///./mcp.db"
        assert _normalize_pg_dsn(dsn) == dsn


# ---------------------------------------------------------------------------
# _Case dataclass
# ---------------------------------------------------------------------------
class TestCaseDataclass:
    """Tests for _Case frozen dataclass."""

    def test_case_is_frozen(self):
        case = _Case(name="test", n=10, timeout_sec=5, db_check=False)
        with pytest.raises(AttributeError):
            case.n = 20  # type: ignore[misc]

    def test_case_fields(self):
        case = _Case(name="api_smoke_20", n=20, timeout_sec=10, db_check=False)
        assert case.name == "api_smoke_20"
        assert case.n == 20
        assert case.timeout_sec == 10
        assert case.db_check is False


# ---------------------------------------------------------------------------
# DEFAULT_CASES
# ---------------------------------------------------------------------------
class TestDefaultCases:
    """Tests for DEFAULT_CASES list."""

    def test_has_three_cases(self):
        assert len(DEFAULT_CASES) == 3

    def test_case_names(self):
        names = [c.name for c in DEFAULT_CASES]
        assert names == ["api_smoke_20", "api_100", "api_db_100"]

    def test_smoke_case(self):
        case = DEFAULT_CASES[0]
        assert case.n == 20
        assert case.db_check is False

    def test_api_100_case(self):
        case = DEFAULT_CASES[1]
        assert case.n == 100
        assert case.db_check is False

    def test_api_db_100_case(self):
        case = DEFAULT_CASES[2]
        assert case.n == 100
        assert case.db_check is True
