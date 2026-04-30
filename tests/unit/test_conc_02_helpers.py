# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_conc_02_helpers.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for CONC-02 gateway read-during-write helper functions.
"""

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
_MODULE_PATH = Path(__file__).resolve().parents[2] / "tests" / "manual" / "concurrency" / "conc_02_gateways_read_during_write.py"
_spec = importlib.util.spec_from_file_location("conc_02_gateways_read_during_write", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_env_int = _mod._env_int
_build_config = _mod._build_config
_is_valid_read_payload = _mod._is_valid_read_payload


# ---------------------------------------------------------------------------
# _env_int
# ---------------------------------------------------------------------------
class TestEnvInt:
    """Tests for _env_int helper."""

    def test_returns_default_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env_int("CONC_MISSING_VAR", 42) == 42

    def test_returns_default_when_env_empty(self):
        with patch.dict(os.environ, {"CONC_EMPTY": ""}, clear=False):
            assert _env_int("CONC_EMPTY", 7) == 7

    def test_returns_default_when_env_whitespace(self):
        with patch.dict(os.environ, {"CONC_WS": "   "}, clear=False):
            assert _env_int("CONC_WS", 7) == 7

    def test_parses_valid_int(self):
        with patch.dict(os.environ, {"CONC_VAL": "10"}, clear=False):
            assert _env_int("CONC_VAL", 1) == 10

    def test_parses_int_with_whitespace(self):
        with patch.dict(os.environ, {"CONC_VAL": "  15  "}, clear=False):
            assert _env_int("CONC_VAL", 1) == 15

    def test_raises_on_non_integer(self):
        with patch.dict(os.environ, {"CONC_BAD": "abc"}, clear=False):
            with pytest.raises(ValueError, match="must be an integer"):
                _env_int("CONC_BAD", 1)

    def test_raises_on_zero(self):
        with patch.dict(os.environ, {"CONC_ZERO": "0"}, clear=False):
            with pytest.raises(ValueError, match="must be > 0"):
                _env_int("CONC_ZERO", 1)

    def test_raises_on_negative(self):
        with patch.dict(os.environ, {"CONC_NEG": "-5"}, clear=False):
            with pytest.raises(ValueError, match="must be > 0"):
                _env_int("CONC_NEG", 1)


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
            assert cfg["duration_sec"] == 20
            assert cfg["reader_workers"] == 5
            assert cfg["writer_workers"] == 1
            assert cfg["req_timeout_sec"] == 20

    def test_overrides_from_env(self):
        env = {
            "CONC_TOKEN": "tok",
            "CONC_BASE_URL": "https://gw.example.com/",
            "CONC_NAME_PREFIX": "my-gw",
            "CONC_GATEWAY_URL": "https://backend.example.com/sse",
            "CONC_RW_DURATION_SEC": "30",
            "CONC_RW_READERS": "10",
            "CONC_RW_WRITERS": "3",
            "CONC_RW_TIMEOUT_SEC": "60",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = _build_config()
            assert cfg["base_url"] == "https://gw.example.com"  # trailing slash stripped
            assert cfg["name_prefix"] == "my-gw"
            assert cfg["gateway_url"] == "https://backend.example.com/sse"
            assert cfg["duration_sec"] == 30
            assert cfg["reader_workers"] == 10
            assert cfg["writer_workers"] == 3
            assert cfg["req_timeout_sec"] == 60

    def test_empty_name_prefix_falls_back(self):
        env = {"CONC_TOKEN": "tok", "CONC_NAME_PREFIX": "  "}
        with patch.dict(os.environ, env, clear=True):
            cfg = _build_config()
            assert cfg["name_prefix"] == "conc-gw"

    def test_propagates_env_int_errors(self):
        env = {"CONC_TOKEN": "tok", "CONC_RW_DURATION_SEC": "not-a-number"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="must be an integer"):
                _build_config()


# ---------------------------------------------------------------------------
# _is_valid_read_payload
# ---------------------------------------------------------------------------
class TestIsValidReadPayload:
    """Tests for _is_valid_read_payload helper."""

    def test_valid_http_url(self):
        payload = {"id": "abc", "name": "gw1", "url": "http://localhost:9000/sse"}
        ok, reason = _is_valid_read_payload(payload)
        assert ok is True
        assert reason == "ok"

    def test_valid_https_url(self):
        payload = {"id": "abc", "name": "gw1", "url": "https://api.example.com/sse"}
        ok, reason = _is_valid_read_payload(payload)
        assert ok is True
        assert reason == "ok"

    def test_non_dict_payload(self):
        ok, reason = _is_valid_read_payload("not a dict")
        assert ok is False
        assert "payload_type=str" in reason

    def test_none_payload(self):
        ok, reason = _is_valid_read_payload(None)
        assert ok is False
        assert "payload_type=NoneType" in reason

    def test_list_payload(self):
        ok, reason = _is_valid_read_payload([1, 2])
        assert ok is False
        assert "payload_type=list" in reason

    def test_missing_id(self):
        ok, reason = _is_valid_read_payload({"name": "gw", "url": "http://x"})
        assert ok is False
        assert "missing_field=id" in reason

    def test_missing_name(self):
        ok, reason = _is_valid_read_payload({"id": "1", "url": "http://x"})
        assert ok is False
        assert "missing_field=name" in reason

    def test_missing_url(self):
        ok, reason = _is_valid_read_payload({"id": "1", "name": "gw"})
        assert ok is False
        assert "missing_field=url" in reason

    def test_url_not_string(self):
        ok, reason = _is_valid_read_payload({"id": "1", "name": "gw", "url": 12345})
        assert ok is False
        assert "invalid_url" in reason

    def test_url_no_scheme(self):
        ok, reason = _is_valid_read_payload({"id": "1", "name": "gw", "url": "ftp://x"})
        assert ok is False
        assert "invalid_url" in reason

    def test_url_empty_string(self):
        ok, reason = _is_valid_read_payload({"id": "1", "name": "gw", "url": ""})
        assert ok is False
        assert "invalid_url" in reason

    def test_extra_fields_ignored(self):
        payload = {"id": "1", "name": "gw", "url": "http://x", "extra": "stuff", "tags": []}
        ok, reason = _is_valid_read_payload(payload)
        assert ok is True
        assert reason == "ok"
