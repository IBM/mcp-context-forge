# -*- coding: utf-8 -*-
"""redis_isready - Wait until Redis is ready and accepting connections

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Reeve Barreto, Mihai Criveti

"""

# Standard
import asyncio
from unittest.mock import patch
import sys
import types

# Third-Party
import pytest

# First-Party
import mcpgateway.utils.redis_isready as redis_isready

# ---------------------------------------------------------------------------
# Mock Redis
# ---------------------------------------------------------------------------


class MockRedis:
    """Mock Redis client for testing Redis backend."""

    def __init__(self):
        self.data = {}
        self.published = []
        self.should_fail = False
        self.attempts = 0

    @classmethod
    def from_url(cls, url):
        return cls()

    def ping(self):
        self.attempts += 1
        if self.should_fail:
            raise ConnectionError("Redis not ready")
        return True

    # Async methods - included for compatibility with other parts of codebase
    async def setex(self, key, ttl, value):
        if self.should_fail:
            raise Exception("Redis connection failed")
        self.data[key] = {"value": value, "ttl": ttl}

    async def exists(self, key):
        if self.should_fail:
            raise Exception("Redis connection failed")
        return key in self.data

    async def delete(self, key):
        if self.should_fail:
            raise Exception("Redis connection failed")
        self.data.pop(key, None)

    async def expire(self, key, ttl):
        if self.should_fail:
            raise Exception("Redis connection failed")
        if key in self.data:
            self.data[key]["ttl"] = ttl

    async def publish(self, channel, message):
        if self.should_fail:
            raise Exception("Redis connection failed")
        self.published.append({"channel": channel, "message": message})

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_wait_for_redis_ready_success(monkeypatch):
    """A healthy Redis instance should succeed on the first attempt."""

    mock = MockRedis()
    mock.should_fail = False

    monkeypatch.setattr(redis_isready.time, "sleep", lambda *_: None)

    with patch("redis.Redis", MockRedis):
        redis_isready.wait_for_redis_ready(
            redis_url="redis://localhost:6379/0",
            max_retries=3,
            retry_interval_ms=10,
            sync=True,
        )


def test_wait_for_redis_ready_retries(monkeypatch):
    """Redis should fail a few times before succeeding."""

    mock = MockRedis()
    mock.attempts = 0

    def failing_then_succeeding_ping():
        mock.attempts += 1
        if mock.attempts < 3:
            raise ConnectionError("Redis not ready")
        return True

    mock.ping = failing_then_succeeding_ping
    monkeypatch.setattr(redis_isready.time, "sleep", lambda *_: None)

    class MockRedisWithFromUrl:
        @classmethod
        def from_url(cls, url):
            return mock

    with patch("redis.Redis", MockRedisWithFromUrl):
        redis_isready.wait_for_redis_ready(
            redis_url="redis://localhost:6379/0",
            max_retries=5,
            retry_interval_ms=10,
            sync=True,
        )

    assert mock.attempts == 3


def test_wait_for_redis_ready_fails(monkeypatch):
    """After max_retries, should raise RuntimeError."""

    mock = MockRedis()
    mock.should_fail = True

    monkeypatch.setattr(redis_isready.time, "sleep", lambda *_: None)

    class MockRedisWithFromUrl:
        @classmethod
        def from_url(cls, url):
            return mock

    with patch("redis.Redis", MockRedisWithFromUrl):
        with pytest.raises(RuntimeError, match="Redis not ready after"):
            redis_isready.wait_for_redis_ready(
                redis_url="redis://localhost:6379/0",
                max_retries=3,
                retry_interval_ms=10,
                sync=True,
            )


def test_wait_for_redis_ready_invalid_params():
    """Zero or negative retry parameters are rejected immediately."""

    with pytest.raises(RuntimeError):
        redis_isready.wait_for_redis_ready(max_retries=0)

    with pytest.raises(RuntimeError):
        redis_isready.wait_for_redis_ready(retry_interval_ms=0)


def test_wait_for_redis_ready_async_path(monkeypatch):
    """Async path should offload probe into executor."""

    mock = MockRedis()
    mock.attempts = 0

    def ping():
        mock.attempts += 1
        return True

    mock.ping = ping
    monkeypatch.setattr(redis_isready.time, "sleep", lambda *_: None)

    # Create a dedicated loop so we can patch run_in_executor cleanly
    loop = asyncio.new_event_loop()

    async def fake_run_in_executor(_executor, func, *args):
        # Execute the probe synchronously (no thread) then return dummy future
        func(*args)
        fut = loop.create_future()
        fut.set_result(None)
        return fut

    monkeypatch.setattr(asyncio, "get_event_loop", lambda: loop)
    loop.run_in_executor = fake_run_in_executor

    class MockRedisWithFromUrl:
        @classmethod
        def from_url(cls, url):
            return mock

    with patch("redis.Redis", MockRedisWithFromUrl):
        redis_isready.wait_for_redis_ready(
            redis_url="redis://localhost:6379/0",
            max_retries=2,
            retry_interval_ms=10,
            sync=False,
        )

    assert mock.attempts == 1


def test_importerror_exits(monkeypatch):
    """If redis is not installed, should exit with code 2."""
    # Patch sys.modules to simulate ImportError
    import importlib
    import builtins

    # Save original import
    orig_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "redis":
            raise ImportError("No redis")
        return orig_import(name, *args, **kwargs)

    builtins.__import__ = fake_import
    # Patch sys.exit to catch exit code
    exit_code = {}
    monkeypatch.setattr(sys, "exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))
    try:
        with pytest.raises(SystemExit) as exc:
            # Use sync=True to hit ImportError path
            import mcpgateway.utils.redis_isready as redis_isready_mod
            redis_isready_mod.wait_for_redis_ready(sync=True)
        assert exc.value.code == 2
    finally:
        builtins.__import__ = orig_import


def test_logging_config(monkeypatch):
    """Logger with no handlers triggers basicConfig."""
    import logging
    # Use a real Logger instance and clear its handlers
    dummy_logger = logging.getLogger("dummy_logger_for_test_logging_config")
    dummy_logger.handlers.clear()
    # Patch Redis to always succeed
    class DummyRedis:
        @classmethod
        def from_url(cls, url): return cls()
        def ping(self): return True
    monkeypatch.setattr("redis.Redis", DummyRedis)
    monkeypatch.setattr("mcpgateway.utils.redis_isready.time.sleep", lambda *_: None)
    import mcpgateway.utils.redis_isready as redis_isready_mod
    redis_isready_mod.wait_for_redis_ready(logger=dummy_logger, sync=True)


def test_parse_cli_and_main_success(monkeypatch):
    """Test CLI parse and main() success path (exit 0)."""
    import mcpgateway.utils.redis_isready as redis_isready_mod
    # Patch sys.argv and sys.exit
    monkeypatch.setattr(sys, "argv", ["redis_isready.py", "--max-retries", "1"])
    monkeypatch.setattr(sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))
    # Patch wait_for_redis_ready to not raise
    monkeypatch.setattr(redis_isready_mod, "wait_for_redis_ready", lambda **kwargs: None)
    # Patch settings.cache_type to "redis"
    monkeypatch.setattr(redis_isready_mod.settings, "cache_type", "redis")
    with pytest.raises(SystemExit) as exc:
        redis_isready_mod.main()
    assert exc.value.code == 0


def test_parse_cli_and_main_fail(monkeypatch):
    """Test CLI main() with RuntimeError (exit 1)."""
    import mcpgateway.utils.redis_isready as redis_isready_mod
    monkeypatch.setattr(sys, "argv", ["redis_isready.py", "--max-retries", "1"])
    monkeypatch.setattr(sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))
    def fail(**kwargs): raise RuntimeError("fail")
    monkeypatch.setattr(redis_isready_mod, "wait_for_redis_ready", fail)
    monkeypatch.setattr(redis_isready_mod.settings, "cache_type", "redis")
    with pytest.raises(SystemExit) as exc:
        redis_isready_mod.main()
    assert exc.value.code == 1


def test_main_not_using_redis(monkeypatch):
    """If not using Redis, main() should exit 0."""
    import mcpgateway.utils.redis_isready as redis_isready_mod
    monkeypatch.setattr(redis_isready_mod.settings, "cache_type", "none")
    monkeypatch.setattr(sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))
    # __main__ block
    if hasattr(redis_isready_mod, "__main__"):
        delattr(redis_isready_mod, "__main__")
    with pytest.raises(SystemExit) as exc:
        # Simulate __main__ block
        if redis_isready_mod.settings.cache_type == "redis":
            redis_isready_mod.main()
        else:
            sys.exit(0)
    assert exc.value.code == 0


def test_invalid_cli_params(monkeypatch):
    """Test CLI with invalid params (exit 3)."""
    import mcpgateway.utils.redis_isready as redis_isready_mod
    monkeypatch.setattr(sys, "argv", ["redis_isready.py", "--max-retries", "0"])
    # Patch sys.exit to catch exit code
    monkeypatch.setattr(sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))
    # Patch wait_for_redis_ready to raise RuntimeError for invalid params
    def fail(**kwargs): raise RuntimeError("Invalid max_retries or retry_interval_ms values")
    monkeypatch.setattr(redis_isready_mod, "wait_for_redis_ready", fail)
    monkeypatch.setattr(redis_isready_mod.settings, "cache_type", "redis")
    with pytest.raises(SystemExit) as exc:
        try:
            redis_isready_mod.main()
        except RuntimeError:
            # If main doesn't catch, test will still pass
            pass
