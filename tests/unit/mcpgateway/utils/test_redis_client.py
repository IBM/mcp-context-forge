# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_redis_client.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the centralized Redis client factory.
"""

# Standard
import builtins
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.redis_client import (
    _build_ssl_kwargs,
    _get_async_parser_class,
    _is_hiredis_available,
    _reset_client,
    _validate_ssl_settings,
    close_redis_client,
    get_redis_client,
    get_redis_client_sync,
    get_redis_parser_info,
    is_redis_available,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_client_state():
    """Reset client state before and after each test."""
    _reset_client()
    yield
    _reset_client()


# ---------------------------------------------------------------------------
# Tests for get_redis_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_redis_client_returns_none_when_cache_not_redis():
    """get_redis_client returns None when cache_type is not redis."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "memory"
        mock_settings.redis_url = "redis://localhost:6379"

        client = await get_redis_client()

        assert client is None


@pytest.mark.asyncio
async def test_get_redis_client_returns_none_when_no_redis_url():
    """get_redis_client returns None when redis_url is not set."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = None

        client = await get_redis_client()

        assert client is None


@pytest.mark.asyncio
async def test_get_redis_client_returns_none_when_redis_not_installed():
    """get_redis_client returns None when redis.asyncio is not available."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "redis.asyncio":
                raise ImportError("No module named 'redis.asyncio'")
            return real_import(name, globals, locals, fromlist, level)

        # Simulate import error for redis.asyncio
        with patch.dict("sys.modules", {"redis.asyncio": None}):
            with patch("builtins.__import__", side_effect=fake_import):
                _reset_client()  # Force re-initialization
                client = await get_redis_client()
                assert client is None


@pytest.mark.asyncio
async def test_get_redis_client_creates_client_on_first_call():
    """get_redis_client creates client with correct settings on first call."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "auto"
        mock_settings.redis_ssl = False

        with patch("redis.asyncio.from_url", return_value=mock_redis) as mock_from_url:
            client = await get_redis_client()

            assert client is mock_redis
            # Verify from_url was called with expected kwargs (parser_class may vary)
            mock_from_url.assert_called_once()
            call_kwargs = mock_from_url.call_args[1]
            assert call_kwargs["decode_responses"] is True
            assert call_kwargs["max_connections"] == 10
            assert call_kwargs["socket_timeout"] == 5.0
            assert call_kwargs["socket_connect_timeout"] == 5.0
            assert call_kwargs["retry_on_timeout"] is True
            assert call_kwargs["health_check_interval"] == 30
            assert call_kwargs["encoding"] == "utf-8"
            assert call_kwargs["single_connection_client"] is False
            mock_redis.ping.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_redis_client_returns_cached_client():
    """get_redis_client returns cached client on subsequent calls."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "auto"
        mock_settings.redis_ssl = False

        with patch("redis.asyncio.from_url", return_value=mock_redis) as mock_from_url:
            client1 = await get_redis_client()
            client2 = await get_redis_client()

            assert client1 is client2
            # from_url should only be called once
            mock_from_url.assert_called_once()


@pytest.mark.asyncio
async def test_get_redis_client_returns_none_on_connection_error():
    """get_redis_client returns None when connection fails."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis not reachable"))

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "auto"
        mock_settings.redis_ssl = False

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            client = await get_redis_client()

            assert client is None


# ---------------------------------------------------------------------------
# Tests for close_redis_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_redis_client_closes_active_client():
    """close_redis_client closes active client and resets state."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.aclose = AsyncMock()

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "auto"
        mock_settings.redis_ssl = False

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await get_redis_client()
            await close_redis_client()

            mock_redis.aclose.assert_awaited_once()

            # Verify state was reset
            assert get_redis_client_sync() is None


@pytest.mark.asyncio
async def test_close_redis_client_handles_no_client():
    """close_redis_client handles case when no client exists."""
    # Should not raise any errors
    await close_redis_client()


@pytest.mark.asyncio
async def test_close_redis_client_handles_close_error():
    """close_redis_client handles errors during close gracefully."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.aclose = AsyncMock(side_effect=Exception("Close failed"))

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "auto"
        mock_settings.redis_ssl = False

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await get_redis_client()
            # Should not raise
            await close_redis_client()


# ---------------------------------------------------------------------------
# Tests for is_redis_available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_redis_available_returns_true_when_connected():
    """is_redis_available returns True when Redis is connected and responds to ping."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "auto"
        mock_settings.redis_ssl = False

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            result = await is_redis_available()

            assert result is True


@pytest.mark.asyncio
async def test_is_redis_available_returns_false_when_disabled():
    """is_redis_available returns False when Redis is disabled."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "memory"
        mock_settings.redis_url = "redis://localhost:6379"

        result = await is_redis_available()

        assert result is False


@pytest.mark.asyncio
async def test_is_redis_available_returns_false_when_ping_fails():
    """is_redis_available returns False when ping fails."""
    mock_redis = AsyncMock()
    # First ping succeeds (initialization), second fails (availability check)
    mock_redis.ping = AsyncMock(side_effect=[True, ConnectionError("Ping failed")])

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "auto"
        mock_settings.redis_ssl = False

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            result = await is_redis_available()

            assert result is False


# ---------------------------------------------------------------------------
# Tests for get_redis_client_sync
# ---------------------------------------------------------------------------


def test_get_redis_client_sync_returns_none_before_init():
    """get_redis_client_sync returns None before initialization."""
    result = get_redis_client_sync()

    assert result is None


@pytest.mark.asyncio
async def test_get_redis_client_sync_returns_cached_client():
    """get_redis_client_sync returns cached client after initialization."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "auto"
        mock_settings.redis_ssl = False

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await get_redis_client()

            sync_client = get_redis_client_sync()

            assert sync_client is mock_redis


# ---------------------------------------------------------------------------
# Tests for _reset_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_client_clears_state():
    """_reset_client clears initialized state."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "auto"
        mock_settings.redis_ssl = False

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await get_redis_client()
            assert get_redis_client_sync() is mock_redis

            _reset_client()

            assert get_redis_client_sync() is None
            assert get_redis_parser_info() is None


# ---------------------------------------------------------------------------
# Tests for parser selection (ADR-026)
# ---------------------------------------------------------------------------


def test_get_async_parser_class_python_mode():
    """_get_async_parser_class returns AsyncRESP2Parser for python mode."""
    parser_class, parser_info = _get_async_parser_class("python")

    assert parser_class is not None
    assert "AsyncRESP2Parser" in parser_info or "pure-Python" in parser_info


def test_get_async_parser_class_auto_mode():
    """_get_async_parser_class returns appropriate parser for auto mode."""
    parser_class, parser_info = _get_async_parser_class("auto")

    # In auto mode, parser_class is None (let redis-py decide)
    assert parser_class is None
    # Parser info should indicate auto-detection
    assert "auto-detected" in parser_info


def test_get_async_parser_class_hiredis_mode_when_available():
    """_get_async_parser_class returns None for hiredis mode (let redis-py auto-detect)."""
    if _is_hiredis_available():
        parser_class, parser_info = _get_async_parser_class("hiredis")
        # For async, we let redis-py auto-detect (parser_class is None)
        assert parser_class is None
        assert "AsyncHiredisParser" in parser_info
        assert "C extension" in parser_info
    else:
        # If hiredis is not installed, test that it raises ImportError
        with pytest.raises(ImportError) as exc_info:
            _get_async_parser_class("hiredis")
        assert "hiredis" in str(exc_info.value)


def test_get_redis_parser_info_before_init():
    """get_redis_parser_info returns None before initialization."""
    result = get_redis_parser_info()
    assert result is None


@pytest.mark.asyncio
async def test_get_redis_client_with_parser_setting():
    """get_redis_client respects redis_parser setting."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "auto"
        mock_settings.redis_ssl = False

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            client = await get_redis_client()

            assert client is mock_redis
            # Parser info should be set after initialization
            parser_info = get_redis_parser_info()
            assert parser_info is not None
            assert "auto-detected" in parser_info


def test_is_hiredis_available_true_when_module_present(monkeypatch):
    monkeypatch.setitem(sys.modules, "hiredis", object())
    assert _is_hiredis_available() is True


def test_get_async_parser_class_auto_prefers_hiredis_when_available(monkeypatch):
    monkeypatch.setattr("mcpgateway.utils.redis_client._is_hiredis_available", lambda: True)
    parser_class, parser_info = _get_async_parser_class("auto")
    assert parser_class is None
    assert "auto-detected" in parser_info
    assert "C extension" in parser_info


def test_get_async_parser_class_hiredis_forced_when_available(monkeypatch):
    monkeypatch.setattr("mcpgateway.utils.redis_client._is_hiredis_available", lambda: True)
    parser_class, parser_info = _get_async_parser_class("hiredis")
    assert parser_class is None
    assert "AsyncHiredisParser" in parser_info


@pytest.mark.asyncio
async def test_get_redis_client_sets_parser_class_when_python_parser_selected():
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "python"
        mock_settings.redis_ssl = False

        with patch("redis.asyncio.from_url", return_value=mock_redis) as mock_from_url:
            client = await get_redis_client()

            assert client is mock_redis
            mock_from_url.assert_called_once()
            call_kwargs = mock_from_url.call_args[1]
            assert call_kwargs["parser_class"] is not None


@pytest.mark.asyncio
async def test_get_redis_client_parser_configuration_error_returns_none():
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "hiredis"
        mock_settings.redis_ssl = False

        with patch("mcpgateway.utils.redis_client._get_async_parser_class", side_effect=ImportError("no hiredis")):
            with patch("redis.asyncio.from_url", return_value=mock_redis) as mock_from_url:
                client = await get_redis_client()

                assert client is None
                mock_from_url.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for _build_ssl_kwargs
# ---------------------------------------------------------------------------


def test_build_ssl_kwargs_returns_empty_dict_when_ssl_disabled():
    """_build_ssl_kwargs returns {} when redis_ssl is False (line 55)."""
    mock_settings = MagicMock()
    mock_settings.redis_ssl = False

    result = _build_ssl_kwargs(mock_settings)

    assert result == {}


def test_build_ssl_kwargs_sets_ca_certs_when_provided():
    """_build_ssl_kwargs sets ssl_ca_certs when redis_ssl_ca_certs is provided (line 109)."""
    mock_settings = MagicMock()
    mock_settings.redis_ssl = True
    mock_settings.redis_ssl_ca_certs = "/some/ca.crt"
    mock_settings.redis_ssl_certfile = None
    mock_settings.redis_ssl_keyfile = None
    mock_settings.redis_ssl_check_hostname = True

    with patch("mcpgateway.utils.redis_client._validate_ssl_settings"):
        result = _build_ssl_kwargs(mock_settings)

    assert result["ssl_ca_certs"] == "/some/ca.crt"
    assert "ssl_certfile" not in result
    assert "ssl_keyfile" not in result


def test_build_ssl_kwargs_sets_certfile_when_provided():
    """_build_ssl_kwargs sets ssl_certfile when redis_ssl_certfile is provided (line 111)."""
    mock_settings = MagicMock()
    mock_settings.redis_ssl = True
    mock_settings.redis_ssl_ca_certs = None
    mock_settings.redis_ssl_certfile = "/some/client.crt"
    mock_settings.redis_ssl_keyfile = None
    mock_settings.redis_ssl_check_hostname = True

    with patch("mcpgateway.utils.redis_client._validate_ssl_settings"):
        result = _build_ssl_kwargs(mock_settings)

    assert result["ssl_certfile"] == "/some/client.crt"
    assert "ssl_ca_certs" not in result
    assert "ssl_keyfile" not in result


def test_build_ssl_kwargs_sets_keyfile_when_provided():
    """_build_ssl_kwargs sets ssl_keyfile when redis_ssl_keyfile is provided (line 113)."""
    mock_settings = MagicMock()
    mock_settings.redis_ssl = True
    mock_settings.redis_ssl_ca_certs = None
    mock_settings.redis_ssl_certfile = None
    mock_settings.redis_ssl_keyfile = "/some/client.key"
    mock_settings.redis_ssl_check_hostname = True

    with patch("mcpgateway.utils.redis_client._validate_ssl_settings"):
        result = _build_ssl_kwargs(mock_settings)

    assert result["ssl_keyfile"] == "/some/client.key"
    assert "ssl_ca_certs" not in result
    assert "ssl_certfile" not in result


def test_build_ssl_kwargs_sets_no_hostname_check_when_check_hostname_false():
    """_build_ssl_kwargs sets ssl_cert_reqs and ssl_check_hostname when check_hostname is False (lines 68-69)."""
    mock_settings = MagicMock()
    mock_settings.redis_ssl = True
    mock_settings.redis_ssl_ca_certs = None
    mock_settings.redis_ssl_certfile = None
    mock_settings.redis_ssl_keyfile = None
    mock_settings.redis_ssl_check_hostname = False

    result = _build_ssl_kwargs(mock_settings)

    assert result["ssl_cert_reqs"] == "none"
    assert result["ssl_check_hostname"] is False


# ---------------------------------------------------------------------------
# Tests for _validate_ssl_settings
# ---------------------------------------------------------------------------


def test_validate_ssl_settings_passes_when_all_paths_none():
    """_validate_ssl_settings passes silently when no cert paths are configured."""
    mock_settings = MagicMock()
    mock_settings.redis_ssl_ca_certs = None
    mock_settings.redis_ssl_certfile = None
    mock_settings.redis_ssl_keyfile = None
    # Should not raise
    _validate_ssl_settings(mock_settings)


def test_validate_ssl_settings_raises_when_ca_certs_file_missing():
    """_validate_ssl_settings raises ValueError when ca_certs path doesn't exist on disk."""
    mock_settings = MagicMock()
    mock_settings.redis_ssl_ca_certs = "/nonexistent/ca.crt"
    mock_settings.redis_ssl_certfile = None
    mock_settings.redis_ssl_keyfile = None

    with pytest.raises(ValueError, match="CA certificate.*not found"):
        _validate_ssl_settings(mock_settings)


def test_validate_ssl_settings_raises_when_certfile_missing():
    """_validate_ssl_settings raises ValueError when certfile path doesn't exist on disk."""
    mock_settings = MagicMock()
    mock_settings.redis_ssl_ca_certs = None
    mock_settings.redis_ssl_certfile = "/nonexistent/client.crt"
    mock_settings.redis_ssl_keyfile = None

    with pytest.raises(ValueError, match="client certificate.*not found"):
        _validate_ssl_settings(mock_settings)


def test_validate_ssl_settings_raises_when_keyfile_missing():
    """_validate_ssl_settings raises ValueError when keyfile path doesn't exist on disk."""
    mock_settings = MagicMock()
    mock_settings.redis_ssl_ca_certs = None
    mock_settings.redis_ssl_certfile = None
    mock_settings.redis_ssl_keyfile = "/nonexistent/client.key"

    with pytest.raises(ValueError, match="private key.*not found"):
        _validate_ssl_settings(mock_settings)


def test_validate_ssl_settings_raises_on_invalid_ca_cert(tmp_path):
    """_validate_ssl_settings raises ValueError when CA cert file exists but content is invalid."""
    ca_cert = tmp_path / "ca.crt"
    ca_cert.write_text("not a valid certificate")

    mock_settings = MagicMock()
    mock_settings.redis_ssl_ca_certs = str(ca_cert)
    mock_settings.redis_ssl_certfile = None
    mock_settings.redis_ssl_keyfile = None

    with pytest.raises(ValueError, match="Invalid CA certificate"):
        _validate_ssl_settings(mock_settings)


def test_validate_ssl_settings_raises_on_invalid_cert_key_pair(tmp_path):
    """_validate_ssl_settings raises ValueError when cert/key pair files exist but content is invalid."""
    certfile = tmp_path / "client.crt"
    keyfile = tmp_path / "client.key"
    certfile.write_text("not a valid cert")
    keyfile.write_text("not a valid key")

    mock_settings = MagicMock()
    mock_settings.redis_ssl_ca_certs = None
    mock_settings.redis_ssl_certfile = str(certfile)
    mock_settings.redis_ssl_keyfile = str(keyfile)

    with pytest.raises(ValueError, match="Invalid client certificate/key"):
        _validate_ssl_settings(mock_settings)


def test_validate_ssl_settings_collects_multiple_errors():
    """_validate_ssl_settings reports all missing files in one ValueError, not just the first."""
    mock_settings = MagicMock()
    mock_settings.redis_ssl_ca_certs = "/bad/ca.crt"
    mock_settings.redis_ssl_certfile = "/bad/client.crt"
    mock_settings.redis_ssl_keyfile = "/bad/client.key"

    with pytest.raises(ValueError) as exc_info:
        _validate_ssl_settings(mock_settings)

    msg = str(exc_info.value)
    assert "CA certificate" in msg
    assert "client certificate" in msg
    assert "private key" in msg


@pytest.mark.asyncio
async def test_get_redis_client_returns_none_on_ssl_misconfiguration():
    """get_redis_client returns None (with ERROR log) when SSL config raises ValueError."""
    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "auto"

        with patch(
            "mcpgateway.utils.redis_client._build_ssl_kwargs",
            side_effect=ValueError("Redis SSL misconfiguration:\n  - CA certificate (REDIS_SSL_CA_CERTS) file not found: '/bad/ca.crt'"),
        ):
            with patch("redis.asyncio.from_url") as mock_from_url:
                client = await get_redis_client()

                assert client is None
                mock_from_url.assert_not_called()


@pytest.mark.asyncio
async def test_get_redis_client_warns_when_rediss_url_but_ssl_disabled(caplog):
    """get_redis_client emits WARNING when rediss:// URL is used but REDIS_SSL=false."""
    # Standard
    import logging

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with patch("mcpgateway.config.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "rediss://localhost:6380"
        mock_settings.redis_decode_responses = True
        mock_settings.redis_max_connections = 10
        mock_settings.redis_socket_timeout = 5.0
        mock_settings.redis_socket_connect_timeout = 5.0
        mock_settings.redis_retry_on_timeout = True
        mock_settings.redis_health_check_interval = 30
        mock_settings.redis_parser = "auto"
        mock_settings.redis_ssl = False

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.redis_client"):
                client = await get_redis_client()

    assert client is mock_redis
    assert any("rediss://" in r.message and "REDIS_SSL=false" in r.message for r in caplog.records)
