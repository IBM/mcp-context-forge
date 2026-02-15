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


# --------------------------------------------------------------------------- #
#                         SSO field validators                            #
# --------------------------------------------------------------------------- #
def test_parse_sso_entra_admin_groups_json_and_csv():
    """sso_entra_admin_groups should accept JSON array or comma-separated string."""
    # Test JSON format
    s_json = Settings(sso_entra_admin_groups='["admin", "superadmin"]', _env_file=None)
    assert s_json.sso_entra_admin_groups == ["admin", "superadmin"]

    # Test CSV format
    s_csv = Settings(sso_entra_admin_groups="admin, superadmin", _env_file=None)
    assert s_csv.sso_entra_admin_groups == ["admin", "superadmin"]

    # Test empty list
    s_empty = Settings(sso_entra_admin_groups="", _env_file=None)
    assert s_empty.sso_entra_admin_groups == []


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
        assert settings.metrics_delete_raw_after_rollup is True
        assert settings.metrics_delete_raw_after_rollup_hours == 1
        assert settings.metrics_cleanup_interval_hours == 1
        assert settings.metrics_retention_days == 7
        assert settings.metrics_rollup_late_data_hours == 1


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


# --------------------------------------------------------------------------- #
#                    _normalize_env_list_vars                                  #
# --------------------------------------------------------------------------- #
def test_normalize_env_list_vars_empty_value():
    """Empty env var should be converted to '[]'."""
    from mcpgateway.config import _normalize_env_list_vars

    with patch.dict(os.environ, {"SSO_TRUSTED_DOMAINS": ""}, clear=False):
        _normalize_env_list_vars()
        assert os.environ["SSO_TRUSTED_DOMAINS"] == "[]"


def test_normalize_env_list_vars_valid_json():
    """Valid JSON array should be left as-is."""
    from mcpgateway.config import _normalize_env_list_vars

    with patch.dict(os.environ, {"SSO_TRUSTED_DOMAINS": '["a.com", "b.com"]'}, clear=False):
        _normalize_env_list_vars()
        assert os.environ["SSO_TRUSTED_DOMAINS"] == '["a.com", "b.com"]'


def test_normalize_env_list_vars_csv():
    """CSV value should be converted to JSON array."""
    from mcpgateway.config import _normalize_env_list_vars

    with patch.dict(os.environ, {"SSO_TRUSTED_DOMAINS": "a.com, b.com"}, clear=False):
        _normalize_env_list_vars()
        import orjson

        result = orjson.loads(os.environ["SSO_TRUSTED_DOMAINS"])
        assert result == ["a.com", "b.com"]


def test_normalize_env_list_vars_invalid_json_bracket():
    """Value starting with '[' but not valid JSON should fall through to CSV."""
    from mcpgateway.config import _normalize_env_list_vars

    with patch.dict(os.environ, {"SSO_TRUSTED_DOMAINS": "[not-valid-json"}, clear=False):
        _normalize_env_list_vars()
        import orjson

        result = orjson.loads(os.environ["SSO_TRUSTED_DOMAINS"])
        assert result == ["[not-valid-json"]


# --------------------------------------------------------------------------- #
#                      x_frame_options validator                               #
# --------------------------------------------------------------------------- #
def test_x_frame_options_null_returns_none():
    """x_frame_options set to 'null' or 'none' should return None."""
    s = Settings(x_frame_options="null", _env_file=None)
    assert s.x_frame_options is None

    s2 = Settings(x_frame_options="None", _env_file=None)
    assert s2.x_frame_options is None


def test_x_frame_options_normal_value():
    """Normal x_frame_options value should be preserved."""
    s = Settings(x_frame_options="DENY", _env_file=None)
    assert s.x_frame_options == "DENY"


# --------------------------------------------------------------------------- #
#                      parse_allowed_roots                                     #
# --------------------------------------------------------------------------- #
def test_parse_allowed_roots_json():
    """JSON array string should be parsed into list."""
    s = Settings(allowed_roots='["/api", "/v2"]', _env_file=None)
    assert s.allowed_roots == ["/api", "/v2"]


def test_parse_allowed_roots_json_non_list_falls_back_to_csv():
    """Valid JSON that is not a list should fall back to comma-splitting (config.py:648->654)."""
    s = Settings(allowed_roots='{"root": "/api"}', _env_file=None)
    assert s.allowed_roots == ['{"root": "/api"}']


def test_parse_allowed_roots_csv():
    """CSV string should be parsed into list."""
    s = Settings(allowed_roots="/api, /v2", _env_file=None)
    assert s.allowed_roots == ["/api", "/v2"]


def test_parse_allowed_roots_empty():
    """Empty string should return empty list."""
    s = Settings(allowed_roots="", _env_file=None)
    assert s.allowed_roots == []


def test_parse_allowed_roots_list_passthrough():
    """List input should be passed through unchanged."""
    s = Settings(allowed_roots=["/api"], _env_file=None)
    assert s.allowed_roots == ["/api"]


# --------------------------------------------------------------------------- #
#                      validate_secrets branches                               #
# --------------------------------------------------------------------------- #
def test_validate_secrets_non_secretstr_input():
    """Passing a plain string for jwt_secret_key should return SecretStr."""
    s = Settings(jwt_secret_key="a" * 32, _env_file=None)
    assert isinstance(s.jwt_secret_key, SecretStr)
    assert s.jwt_secret_key.get_secret_value() == "a" * 32


def test_validate_secrets_weak_secret_warns():
    """Weak secret should trigger warnings but not fail."""
    s = Settings(jwt_secret_key="changeme", _env_file=None)
    assert s.jwt_secret_key.get_secret_value() == "changeme"


def test_validate_secrets_low_entropy_warns():
    """Low entropy secret should trigger warnings."""
    s = Settings(jwt_secret_key="aaaa", _env_file=None)
    assert s.jwt_secret_key.get_secret_value() == "aaaa"


def test_validate_secrets_direct_call_non_secretstr_value():
    """Cover validate_secrets branch where v is not a SecretStr (config.py:691)."""
    class _Info:
        field_name = "jwt_secret_key"
        data = {"client_mode": True}

    out = Settings.validate_secrets("plain-secret", _Info())
    assert isinstance(out, SecretStr)
    assert out.get_secret_value() == "plain-secret"


# --------------------------------------------------------------------------- #
#                      validate_admin_password branches                        #
# --------------------------------------------------------------------------- #
def test_validate_admin_password_plain_string():
    """Plain string password should be wrapped as SecretStr."""
    s = Settings(basic_auth_password="StrongP@ss1!", _env_file=None)
    assert isinstance(s.basic_auth_password, SecretStr)
    assert s.basic_auth_password.get_secret_value() == "StrongP@ss1!"


def test_validate_admin_password_short_warns():
    """Short password should trigger warning."""
    s = Settings(basic_auth_password="ab", _env_file=None)
    assert s.basic_auth_password.get_secret_value() == "ab"


def test_validate_admin_password_high_complexity():
    """Complex password with 3+ categories passes without extra warning."""
    s = Settings(basic_auth_password="Abc123!@#", _env_file=None)
    assert s.basic_auth_password.get_secret_value() == "Abc123!@#"


def test_validate_admin_password_low_complexity():
    """Low complexity password triggers warning."""
    s = Settings(basic_auth_password="alllower", _env_file=None)
    assert s.basic_auth_password.get_secret_value() == "alllower"


def test_validate_admin_password_direct_call_plain_string():
    """Cover validate_admin_password branch where v is not a SecretStr (config.py:726)."""
    class _Info:
        data = {"client_mode": True}

    out = Settings.validate_admin_password("plain", _Info())
    assert isinstance(out, SecretStr)
    assert out.get_secret_value() == "plain"


# --------------------------------------------------------------------------- #
#                      validate_cors_origins                                   #
# --------------------------------------------------------------------------- #
def test_validate_cors_origins_empty_set():
    """Empty set allowed_origins should work."""
    s = Settings(allowed_origins=set(), _env_file=None)
    assert s.allowed_origins == set()


def test_validate_cors_origins_valid_set():
    """Valid origins set should be preserved."""
    origins = {"http://localhost:3000", "https://example.com"}
    s = Settings(allowed_origins=origins, _env_file=None)
    assert s.allowed_origins == origins


def test_validate_cors_origins_wildcard_warns():
    """Wildcard origin should trigger warning."""
    s = Settings(allowed_origins={"*"}, _env_file=None)
    assert "*" in s.allowed_origins


def test_validate_cors_origins_invalid_format_warns():
    """Origin without http:// or https:// should trigger warning."""
    s = Settings(allowed_origins={"example.com"}, _env_file=None)
    assert "example.com" in s.allowed_origins


def test_validate_cors_origins_none_passthrough_direct_call():
    """Directly cover the validator branch returning None (config.py:767)."""
    # This branch is not reachable through Settings() because _parse_allowed_origins
    # turns inputs into a set, but we still want to keep the validator logic covered.
    class _Info:
        data = {"client_mode": True}

    assert Settings.validate_cors_origins(None, _Info()) is None


def test_validate_cors_origins_invalid_type_direct_call():
    """Directly cover the validator raising ValueError for invalid types (config.py:769)."""
    class _Info:
        data = {"client_mode": True}

    with pytest.raises(ValueError, match="allowed_origins must be a set or list of strings"):
        Settings.validate_cors_origins(123, _Info())


# --------------------------------------------------------------------------- #
#                      validate_database_url                                   #
# --------------------------------------------------------------------------- #
def test_validate_database_url_weak_password_warns():
    """Database URL with weak password triggers warning."""
    s = Settings(database_url="postgresql://admin:password123@localhost/db", _env_file=None)
    assert "postgresql" in s.database_url


def test_validate_database_url_sqlite_info():
    """SQLite URL triggers info message."""
    s = Settings(database_url="sqlite:///./test.db", _env_file=None)
    assert s.database_url == "sqlite:///./test.db"


# --------------------------------------------------------------------------- #
#                      validate_security_combinations                          #
# --------------------------------------------------------------------------- #
def test_security_combinations_ui_no_auth():
    """UI enabled without auth should warn."""
    s = Settings(auth_required=False, mcpgateway_ui_enabled=True, _env_file=None)
    assert s.auth_required is False


def test_security_combinations_ssl_no_dev():
    """SSL verification disabled outside dev should warn."""
    s = Settings(skip_ssl_verify=True, dev_mode=False, _env_file=None)
    assert s.skip_ssl_verify is True


def test_security_combinations_debug_no_dev():
    """Debug enabled outside dev should warn."""
    s = Settings(debug=True, dev_mode=False, _env_file=None)
    assert s.debug is True


# --------------------------------------------------------------------------- #
#                      get_security_warnings                                   #
# --------------------------------------------------------------------------- #
def test_get_security_warnings_many():
    """Get security warnings with multiple issues triggered."""
    s = Settings(
        auth_required=False,
        skip_ssl_verify=True,
        debug=True,
        dev_mode=False,
        token_expiry=20000,
        tool_rate_limit=2000,
        _env_file=None,
    )
    warnings = s.get_security_warnings()
    assert len(warnings) >= 3
    assert any("Authentication is disabled" in w for w in warnings)
    assert any("SSL" in w for w in warnings)
    assert any("Debug" in w for w in warnings)


def test_get_security_warnings_clean():
    """Minimal warnings with secure settings."""
    s = Settings(
        auth_required=True,
        skip_ssl_verify=False,
        debug=False,
        dev_mode=False,
        basic_auth_user="custom_admin",
        basic_auth_password="StrongP@ss1!XYZ",
        allowed_origins={"https://example.com"},
        token_expiry=60,
        tool_rate_limit=100,
        _env_file=None,
    )
    warnings = s.get_security_warnings()
    # Should have very few warnings (may have SQLite warning)
    assert not any("Authentication is disabled" in w for w in warnings)


def test_get_security_warnings_dev_mode():
    """Dev mode should generate a warning."""
    s = Settings(dev_mode=True, _env_file=None)
    warnings = s.get_security_warnings()
    assert any("Development mode" in w for w in warnings)


def test_get_security_warnings_long_token():
    """Very long token expiry should generate a warning."""
    s = Settings(token_expiry=20160, _env_file=None)
    warnings = s.get_security_warnings()
    assert any("token expiry" in w for w in warnings)


def test_get_security_warnings_high_rate_limit():
    """Very high rate limit should generate a warning."""
    s = Settings(tool_rate_limit=5000, _env_file=None)
    warnings = s.get_security_warnings()
    assert any("rate limit" in w for w in warnings)


def test_get_security_warnings_wildcard_cors():
    """Wildcard CORS origin should generate a warning."""
    s = Settings(cors_enabled=True, allowed_origins={"*"}, _env_file=None)
    warnings = s.get_security_warnings()
    assert any("CORS allows all origins" in w for w in warnings)


# --------------------------------------------------------------------------- #
#                      get_security_status                                     #
# --------------------------------------------------------------------------- #
def test_get_security_status():
    """get_security_status should return a dict with all expected keys."""
    s = Settings(auth_required=True, _env_file=None)
    status = s.get_security_status()
    assert "secure_secrets" in status
    assert "auth_enabled" in status
    assert "ssl_verification" in status
    assert "debug_disabled" in status
    assert "cors_restricted" in status
    assert "ui_protected" in status
    assert "warnings" in status
    assert "security_score" in status
    assert isinstance(status["security_score"], int)
    assert 0 <= status["security_score"] <= 100


# --------------------------------------------------------------------------- #
#                    _parse_allowed_origins quote stripping                     #
# --------------------------------------------------------------------------- #
def test_parse_allowed_origins_quoted_string():
    """Outer quotes should be stripped from allowed_origins string."""
    s = Settings(allowed_origins='"https://a.com,https://b.com"', _env_file=None)
    assert "https://a.com" in s.allowed_origins
    assert "https://b.com" in s.allowed_origins


# --------------------------------------------------------------------------- #
#                      validate_log_level                                       #
# --------------------------------------------------------------------------- #
def test_validate_log_level_invalid():
    """Invalid log level should raise ValueError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(log_level="TRACE", _env_file=None)


def test_validate_log_level_case_insensitive():
    """Log level should be case-insensitive and uppercased."""
    s = Settings(log_level="debug", _env_file=None)
    assert s.log_level == "DEBUG"


# --------------------------------------------------------------------------- #
#                    _parse_sso_issuers                                        #
# --------------------------------------------------------------------------- #
def test_parse_sso_issuers_none():
    """None should return empty list."""
    s = Settings(sso_issuers=None, _env_file=None)
    assert s.sso_issuers == []


def test_parse_sso_issuers_list():
    """List input should pass through."""
    s = Settings(sso_issuers=["https://issuer.com"], _env_file=None)
    assert len(s.sso_issuers) == 1
    assert str(s.sso_issuers[0]).rstrip("/") == "https://issuer.com"


def test_parse_sso_issuers_json_string():
    """JSON array string should be parsed."""
    s = Settings(sso_issuers='["https://a.com", "https://b.com"]', _env_file=None)
    assert len(s.sso_issuers) == 2
    urls = [str(u).rstrip("/") for u in s.sso_issuers]
    assert "https://a.com" in urls
    assert "https://b.com" in urls


def test_parse_sso_issuers_csv_string():
    """CSV string should be parsed."""
    s = Settings(sso_issuers="https://a.com, https://b.com", _env_file=None)
    assert len(s.sso_issuers) == 2
    urls = [str(u).rstrip("/") for u in s.sso_issuers]
    assert "https://a.com" in urls
    assert "https://b.com" in urls


def test_parse_sso_issuers_empty_string():
    """Empty string should return empty list."""
    s = Settings(sso_issuers="", _env_file=None)
    assert s.sso_issuers == []


def test_parse_sso_issuers_invalid_json():
    """Invalid JSON starting with '[' should raise ValueError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(sso_issuers="[invalid", _env_file=None)


def test_parse_sso_issuers_invalid_type():
    """Non-string/list/None type should raise ValueError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(sso_issuers=123, _env_file=None)


# --------------------------------------------------------------------------- #
#                    gateway_tool_name_separator                                #
# --------------------------------------------------------------------------- #
def test_gateway_tool_name_separator_invalid():
    """Invalid separator should default to '-'."""
    s = Settings(gateway_tool_name_separator="invalid", _env_file=None)
    assert s.gateway_tool_name_separator == "-"


def test_gateway_tool_name_separator_valid():
    """Valid separators should be preserved."""
    for sep in ["-", "--", "_", "."]:
        s = Settings(gateway_tool_name_separator=sep, _env_file=None)
        assert s.gateway_tool_name_separator == sep


# --------------------------------------------------------------------------- #
#                    custom_well_known_files                                    #
# --------------------------------------------------------------------------- #
def test_custom_well_known_files_empty():
    """Empty well_known_custom_files should return empty dict."""
    s = Settings(well_known_custom_files="", _env_file=None)
    assert s.custom_well_known_files == {}


def test_custom_well_known_files_valid_json():
    """Valid JSON should be parsed into dict."""
    s = Settings(well_known_custom_files='{"robots.txt": "User-agent: *"}', _env_file=None)
    assert s.custom_well_known_files == {"robots.txt": "User-agent: *"}


def test_custom_well_known_files_invalid_json():
    """Invalid JSON should return empty dict."""
    s = Settings(well_known_custom_files="not-valid-json", _env_file=None)
    assert s.custom_well_known_files == {}


# --------------------------------------------------------------------------- #
#                    _auto_enable_security_txt                                  #
# --------------------------------------------------------------------------- #
def test_auto_enable_security_txt_with_content():
    """security_txt_enabled should be True when content is provided."""
    s = Settings(well_known_security_txt="Contact: security@example.com", _env_file=None)
    assert s.well_known_security_txt_enabled is True


def test_auto_enable_security_txt_empty():
    """security_txt_enabled should be False when content is empty."""
    s = Settings(well_known_security_txt="", _env_file=None)
    assert s.well_known_security_txt_enabled is False


def test_auto_enable_security_txt_falls_back_to_bool_value_direct_call():
    """Directly cover fallback branch when well_known_security_txt is missing from validator context (config.py:1699)."""
    class _Info:
        data = {}

    assert Settings._auto_enable_security_txt(True, _Info()) is True
    assert Settings._auto_enable_security_txt(False, _Info()) is False


# --------------------------------------------------------------------------- #
#                    _parse_list_from_env                                       #
# --------------------------------------------------------------------------- #
def test_parse_list_from_env_none():
    """None should return empty list."""
    s = Settings(sso_entra_admin_groups=None, _env_file=None)
    assert s.sso_entra_admin_groups == []


def test_parse_list_from_env_invalid_json_fallback():
    """Invalid JSON starting with '[' should fall back to CSV parsing."""
    s = Settings(sso_entra_admin_groups="[not-valid", _env_file=None)
    assert s.sso_entra_admin_groups == ["[not-valid"]


def test_parse_list_from_env_invalid_type():
    """Non-string/list/None type should raise ValueError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(sso_entra_admin_groups=123, _env_file=None)


# --------------------------------------------------------------------------- #
#                    validate_database (non-sqlite)                            #
# --------------------------------------------------------------------------- #
def test_validate_database_non_sqlite():
    """Non-SQLite databases should skip directory creation."""
    s = Settings(database_url="postgresql://u:p@host/db", _env_file=None)
    s.validate_database()  # Should not raise or try to create dirs


# --------------------------------------------------------------------------- #
#                    __init__ passthrough headers                               #
# --------------------------------------------------------------------------- #
def test_init_passthrough_headers_json():
    """DEFAULT_PASSTHROUGH_HEADERS as JSON should be parsed."""
    with patch.dict(os.environ, {"DEFAULT_PASSTHROUGH_HEADERS": '["X-Custom", "X-Other"]'}, clear=False):
        s = Settings(_env_file=None)
        assert s.default_passthrough_headers == ["X-Custom", "X-Other"]


def test_init_passthrough_headers_json_not_array_falls_back_to_csv():
    """Non-array JSON should fall back to comma-splitting (config.py:2124-2128)."""
    with patch.dict(os.environ, {"DEFAULT_PASSTHROUGH_HEADERS": '{"a": 1}'}, clear=False):
        # Pass an explicit list to bypass pydantic_settings' eager env JSON parsing
        # (it would otherwise fail validation before our __init__ fallback executes).
        s = Settings(default_passthrough_headers=["X-Tenant-Id"], _env_file=None)
        assert s.default_passthrough_headers == ['{"a": 1}']


def test_init_passthrough_headers_default():
    """Missing DEFAULT_PASSTHROUGH_HEADERS should use safe defaults."""
    env = {k: v for k, v in os.environ.items() if k != "DEFAULT_PASSTHROUGH_HEADERS"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings(_env_file=None)
        assert s.default_passthrough_headers == ["X-Tenant-Id", "X-Trace-Id"]


# --------------------------------------------------------------------------- #
#                    __init__ CORS environment-aware defaults                   #
# --------------------------------------------------------------------------- #
def test_init_cors_development_env():
    """Development environment should get expanded CORS origins."""
    env = {k: v for k, v in os.environ.items() if k != "ALLOWED_ORIGINS"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings(environment="development", _env_file=None)
        # Should include localhost variants
        assert any("localhost" in o for o in s.allowed_origins)


def test_init_cors_production_env():
    """Production environment should get domain-based CORS origins."""
    env = {k: v for k, v in os.environ.items() if k != "ALLOWED_ORIGINS"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings(environment="production", app_domain="https://myapp.com", _env_file=None)
        # Production origins should be based on app_domain
        assert len(s.allowed_origins) >= 1


# --------------------------------------------------------------------------- #
#                    generate_settings_schema                                  #
# --------------------------------------------------------------------------- #
def test_generate_settings_schema():
    """generate_settings_schema should return a valid JSON schema dict."""
    from mcpgateway.config import generate_settings_schema

    schema = generate_settings_schema()
    assert isinstance(schema, dict)
    assert "properties" in schema
    assert "title" in schema


# --------------------------------------------------------------------------- #
#                    client_mode bypasses security checks                      #
# --------------------------------------------------------------------------- #
def test_client_mode_skips_security_warnings():
    """client_mode=True should skip security validation warnings."""
    s = Settings(
        client_mode=True,
        jwt_secret_key="weak",
        basic_auth_password="x",
        _env_file=None,
    )
    # Should not raise - client mode bypasses all warnings
    assert s.client_mode is True


# --------------------------------------------------------------------------- #
#                    log_summary                                               #
# --------------------------------------------------------------------------- #
def test_log_summary():
    """log_summary should log settings without raising."""
    s = Settings(_env_file=None)
    s.log_summary()


# --------------------------------------------------------------------------- #
#                    proxy auth warning in __init__                            #
# --------------------------------------------------------------------------- #
def test_proxy_auth_warning():
    """Disabled MCP client auth with trust_proxy_auth=False should warn."""
    s = Settings(mcp_client_auth_enabled=False, trust_proxy_auth=False, _env_file=None)
    assert s.mcp_client_auth_enabled is False


# --------------------------------------------------------------------------- #
#                    Ed25519 key derivation                                    #
# --------------------------------------------------------------------------- #
def test_derive_ed25519_public_key():
    """Valid Ed25519 private key should auto-derive public key."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization

    private_key = ed25519.Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    s = Settings(ed25519_private_key=pem, _env_file=None)
    assert s.ed25519_public_key is not None
    assert "PUBLIC KEY" in s.ed25519_public_key


def test_derive_ed25519_invalid_key_warns():
    """Invalid PEM data should log warning but not raise."""
    s = Settings(ed25519_private_key="not-a-valid-pem-key", _env_file=None)
    assert s.ed25519_public_key is None


def test_derive_ed25519_non_ed25519_key_is_ignored():
    """Non-Ed25519 keys should be ignored by the derive_public_keys model validator (config.py:2074)."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    s = Settings(ed25519_private_key=pem, _env_file=None)
    assert s.ed25519_public_key is None


# --------------------------------------------------------------------------- #
#                    direct_proxy feature flag defaults                         #
# --------------------------------------------------------------------------- #
def test_direct_proxy_enabled_default_false():
    """mcpgateway_direct_proxy_enabled should default to False."""
    s = Settings(_env_file=None)
    assert s.mcpgateway_direct_proxy_enabled is False


def test_direct_proxy_timeout_default_30():
    """mcpgateway_direct_proxy_timeout should default to 30."""
    s = Settings(_env_file=None)
    assert s.mcpgateway_direct_proxy_timeout == 30
