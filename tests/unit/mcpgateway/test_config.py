# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_config.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test the configuration module.
Author: Mihai Criveti
"""

# Standard
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic import SecretStr

# Third-Party
# Third-party
import pytest

# First-Party
from mcpgateway.config import (
    get_settings,
    Settings,
)


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

    assert [str(u) for u in s_json.federation_peers] == ["https://gw1/", "https://gw2/"]
    assert [str(u) for u in s_csv.federation_peers] == ["https://gw3/", "https://gw4/"]


# --------------------------------------------------------------------------- #
#                          database / CORS helpers                            #
# --------------------------------------------------------------------------- #
def test_database_settings_sqlite_and_non_sqlite(tmp_path: Path) -> None:
    """connect_args differs for sqlite vs everything else."""
    # sqlite -> check_same_thread flag present
    db_file = tmp_path / "foo" / "bar.db"
    url = f"sqlite:///{db_file}"
    s_sqlite = Settings(database_url=url)
    assert s_sqlite.database_settings["connect_args"] == {"check_same_thread": False}

    # non-sqlite -> empty connect_args
    s_pg = Settings(database_url="postgresql://u:p@db/test")
    assert s_pg.database_settings["connect_args"] == {}


def test_validate_database_creates_missing_parent(tmp_path: Path) -> None:
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
    """cors_settings property returns CORS configuration based on cors_enabled flag."""
    # Test with cors_enabled = True (default)
    s_enabled = Settings(cors_enabled=True, _env_file=None)
    result = s_enabled.cors_settings
    assert result["allow_methods"] == ["*"]
    assert result["allow_headers"] == ["*"]
    assert result["allow_credentials"] is True
    assert s_enabled.allowed_origins.issubset(set(result["allow_origins"]))

    # Test with cors_enabled = False
    s_disabled = Settings(cors_enabled=False, _env_file=None)
    result = s_disabled.cors_settings
    assert result == {}  # Empty dict when disabled


# --------------------------------------------------------------------------- #
#                           get_settings LRU cache                            #
# --------------------------------------------------------------------------- #
@patch("mcpgateway.config.Settings")
def test_get_settings_is_lru_cached(mock_settings):
    """Constructor must run only once regardless of repeated calls."""
    get_settings.cache_clear()

    try:
        inst1 = MagicMock()
        inst1.validate_transport.return_value = None
        inst1.validate_database.return_value = None

        inst2 = MagicMock()
        mock_settings.side_effect = [inst1, inst2]

        assert get_settings() is inst1
        assert get_settings() is inst1  # cached
        assert mock_settings.call_count == 1
    finally:
        get_settings.cache_clear()


# --------------------------------------------------------------------------- #
#                       Keep the user-supplied baseline                       #
# --------------------------------------------------------------------------- #
def test_settings_default_values():
    dummy_env = {
        "JWT_SECRET_KEY": "x" * 32,  # required, at least 32 chars
        "AUTH_ENCRYPTION_SECRET": "dummy-secret",
        "APP_DOMAIN": "http://localhost",
    }

    with patch.dict(os.environ, dummy_env, clear=True):
        settings = Settings(_env_file=None)

        assert settings.app_name == "MCP_Gateway"
        assert settings.host == "127.0.0.1"
        assert settings.port == 4444
        assert settings.database_url == "sqlite:///./mcp.db"
        assert settings.basic_auth_user == "admin"
        assert settings.basic_auth_password == SecretStr("changeme")
        assert settings.auth_required is True
        assert settings.jwt_secret_key.get_secret_value() == "x" * 32
        assert settings.auth_encryption_secret.get_secret_value() == "dummy-secret"
        assert str(settings.app_domain) == "http://localhost/"


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


# --------------------------------------------------------------------------- #
#                          Response Compression                               #
# --------------------------------------------------------------------------- #
def test_compression_default_values():
    """Test that compression settings have correct defaults."""
    s = Settings(_env_file=None)
    assert s.compression_enabled is True
    assert s.compression_minimum_size == 500
    assert s.compression_gzip_level == 6
    assert s.compression_brotli_quality == 4
    assert s.compression_zstd_level == 3


def test_compression_custom_values():
    """Test that compression settings can be customized."""
    s = Settings(
        compression_enabled=False,
        compression_minimum_size=1000,
        compression_gzip_level=9,
        compression_brotli_quality=11,
        compression_zstd_level=22,
        _env_file=None,
    )
    assert s.compression_enabled is False
    assert s.compression_minimum_size == 1000
    assert s.compression_gzip_level == 9
    assert s.compression_brotli_quality == 11
    assert s.compression_zstd_level == 22


def test_compression_minimum_size_validation():
    """Test that compression_minimum_size validates >= 0."""
    # Valid: 0 is allowed (compress all responses)
    s = Settings(compression_minimum_size=0, _env_file=None)
    assert s.compression_minimum_size == 0

    # Invalid: negative values should fail
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        Settings(compression_minimum_size=-1, _env_file=None)
    assert "greater than or equal to 0" in str(exc_info.value).lower()


def test_compression_gzip_level_validation():
    """Test that gzip level validates 1-9 range."""
    from pydantic import ValidationError

    # Valid range
    for level in [1, 6, 9]:
        s = Settings(compression_gzip_level=level, _env_file=None)
        assert s.compression_gzip_level == level

    # Invalid: below range
    with pytest.raises(ValidationError) as exc_info:
        Settings(compression_gzip_level=0, _env_file=None)
    assert "greater than or equal to 1" in str(exc_info.value).lower()

    # Invalid: above range
    with pytest.raises(ValidationError) as exc_info:
        Settings(compression_gzip_level=10, _env_file=None)
    assert "less than or equal to 9" in str(exc_info.value).lower()


def test_compression_brotli_quality_validation():
    """Test that brotli quality validates 0-11 range."""
    from pydantic import ValidationError

    # Valid range
    for quality in [0, 4, 11]:
        s = Settings(compression_brotli_quality=quality, _env_file=None)
        assert s.compression_brotli_quality == quality

    # Invalid: below range
    with pytest.raises(ValidationError) as exc_info:
        Settings(compression_brotli_quality=-1, _env_file=None)
    assert "greater than or equal to 0" in str(exc_info.value).lower()

    # Invalid: above range
    with pytest.raises(ValidationError) as exc_info:
        Settings(compression_brotli_quality=12, _env_file=None)
    assert "less than or equal to 11" in str(exc_info.value).lower()


def test_compression_zstd_level_validation():
    """Test that zstd level validates 1-22 range."""
    from pydantic import ValidationError

    # Valid range
    for level in [1, 3, 22]:
        s = Settings(compression_zstd_level=level, _env_file=None)
        assert s.compression_zstd_level == level

    # Invalid: below range
    with pytest.raises(ValidationError) as exc_info:
        Settings(compression_zstd_level=0, _env_file=None)
    assert "greater than or equal to 1" in str(exc_info.value).lower()

    # Invalid: above range
    with pytest.raises(ValidationError) as exc_info:
        Settings(compression_zstd_level=23, _env_file=None)
    assert "less than or equal to 22" in str(exc_info.value).lower()
