# -*- coding: utf-8 -*-
"""Test the configuration module.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Author: Mihai Criveti
"""

# Standard
import json
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

# First-Party
from mcpgateway.config import (
    extract_using_jq,
    get_settings,
    jsonpath_modifier,
    Settings,
)

# Third-Party
from fastapi import HTTPException

# Third-party
import pytest


# --------------------------------------------------------------------------- #
#                          Settings field parsers                             #
# --------------------------------------------------------------------------- #
def test_parse_allowed_origins_json_and_csv():
    """Validator should accept JSON array *or* comma-separated string."""
    s_json = Settings(allowed_origins='["https://a.com", "https://b.com"]')
    assert s_json.allowed_origins == {"https://a.com", "https://b.com"}

    s_csv = Settings(allowed_origins="https://x.com , https://y.com")
    assert s_csv.allowed_origins == {"https://x.com", "https://y.com"}


def test_parse_federation_peers_json_and_csv():
    peers_json = '["https://gw1", "https://gw2"]'
    peers_csv = "https://gw3, https://gw4"

    s_json = Settings(federation_peers=peers_json)
    s_csv = Settings(federation_peers=peers_csv)

    assert s_json.federation_peers == ["https://gw1", "https://gw2"]
    assert s_csv.federation_peers == ["https://gw3", "https://gw4"]


# --------------------------------------------------------------------------- #
#                          database / CORS helpers                            #
# --------------------------------------------------------------------------- #
def test_database_settings_sqlite_and_non_sqlite(tmp_path: Path):
    """connect_args differs for sqlite vs everything else."""
    # sqlite -> check_same_thread flag present
    db_file = tmp_path / "foo" / "bar.db"
    url = f"sqlite:///{db_file}"
    s_sqlite = Settings(database_url=url)
    assert s_sqlite.database_settings["connect_args"] == {"check_same_thread": False}

    # non-sqlite -> empty connect_args
    s_pg = Settings(database_url="postgresql://u:p@db/test")
    assert s_pg.database_settings["connect_args"] == {}


def test_validate_database_creates_missing_parent(tmp_path: Path):
    db_file = tmp_path / "newdir" / "db.sqlite"
    url = f"sqlite:///{db_file}"
    s = Settings(database_url=url, _env_file=None)

    # Parent shouldn't exist yet
    assert not db_file.parent.exists()
    s.validate_database()
    # Now it *must* exist
    assert db_file.parent.exists()


def test_validate_transport_accepts_and_rejects():
    Settings(transport_type="http").validate_transport()  # should not raise

    with pytest.raises(ValueError):
        Settings(transport_type="bogus").validate_transport()


def test_cors_settings_branches():
    """cors_settings property depends on dynamically present cors_enabled flag."""
    s = Settings(_env_file=None)

    # With flag missing -> AttributeError when property accessed
    with pytest.raises(AttributeError):
        _ = s.cors_settings

    # Manually inject the flag then verify dictionary
    object.__setattr__(s, "cors_enabled", True)
    result = s.cors_settings
    assert result["allow_methods"] == ["*"]
    assert s.allowed_origins.issubset(set(result["allow_origins"]))


# --------------------------------------------------------------------------- #
#                               extract_using_jq                              #
# --------------------------------------------------------------------------- #
def test_extract_using_jq_happy_path():
    data = {"a": 123}

    with patch("mcpgateway.config.jq.all", return_value=[123]) as mock_jq:
        out = extract_using_jq(data, ".a")
        mock_jq.assert_called_once_with(".a", data)
        assert out == [123]


def test_extract_using_jq_short_circuits_and_errors():
    # Empty filter returns data unmodified
    orig = {"x": "y"}
    assert extract_using_jq(orig) is orig

    # Non-JSON string
    assert extract_using_jq("this isn't json", ".foo") == ["Invalid JSON string provided."]

    # Unsupported input type
    assert extract_using_jq(42, ".foo") == ["Input data must be a JSON string, dictionary, or list."]


# --------------------------------------------------------------------------- #
#                               jsonpath_modifier                             #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def sample_people() -> List[Dict[str, Any]]:
    return [
        {"name": "Ada", "id": 1},
        {"name": "Bob", "id": 2},
    ]


def test_jsonpath_modifier_basic_match(sample_people):
    # Pull out names directly
    names = jsonpath_modifier(sample_people, "$[*].name")
    assert names == ["Ada", "Bob"]

    # Same query but with a mapping
    mapped = jsonpath_modifier(sample_people, "$[*]", mappings={"n": "$.name"})
    assert mapped == [{"n": "Ada"}, {"n": "Bob"}]


def test_jsonpath_modifier_single_dict_collapse():
    person = {"name": "Zoe", "id": 10}
    out = jsonpath_modifier(person, "$")
    assert out == person  # single-item dict collapses to dict, not list


def test_jsonpath_modifier_invalid_expressions(sample_people):
    with pytest.raises(HTTPException):
        jsonpath_modifier(sample_people, "$[")  # invalid main expr

    with pytest.raises(HTTPException):
        jsonpath_modifier(sample_people, "$[*]", mappings={"bad": "$["})  # invalid mapping expr


# --------------------------------------------------------------------------- #
#                           get_settings LRU cache                            #
# --------------------------------------------------------------------------- #
@patch("mcpgateway.config.Settings")
def test_get_settings_is_lru_cached(mock_settings):
    """Constructor must run only once regardless of repeated calls."""
    get_settings.cache_clear()

    inst1 = MagicMock()
    inst1.validate_transport.return_value = None
    inst1.validate_database.return_value = None

    inst2 = MagicMock()
    mock_settings.side_effect = [inst1, inst2]

    assert get_settings() is inst1
    assert get_settings() is inst1  # cached
    assert mock_settings.call_count == 1


# --------------------------------------------------------------------------- #
#                       Keep the user-supplied baseline                       #
# --------------------------------------------------------------------------- #
def test_settings_default_values():
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings(_env_file=None)

        assert settings.app_name == "MCP_Gateway"
        assert settings.host == "127.0.0.1"
        assert settings.port == 4444
        assert settings.database_url == "sqlite:///./mcp.db"
        assert settings.basic_auth_user == "admin"
        assert settings.basic_auth_password == "changeme"
        assert settings.auth_required is True


def test_api_key_property():
    settings = Settings(basic_auth_user="u", basic_auth_password="p")
    assert settings.api_key == "u:p"


def test_supports_transport_properties():
    s_all = Settings(transport_type="all")
    assert (s_all.supports_http, s_all.supports_websocket, s_all.supports_sse) == (True, True, True)

    s_http = Settings(transport_type="http")
    assert (s_http.supports_http, s_http.supports_websocket, s_http.supports_sse) == (True, False, False)

    s_ws = Settings(transport_type="ws")
    assert (s_ws.supports_http, s_ws.supports_websocket, s_ws.supports_sse) == (False, True, False)
