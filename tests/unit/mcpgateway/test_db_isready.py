# -*- coding: utf-8 -*-
"""Module Description.
Location: ./tests/unit/mcpgateway/test_db_isready.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""
# Standard
import asyncio
import sys

# Third-Party
import pytest

# First-Party
# Import the module under test after patching where necessary
import mcpgateway.utils.db_isready as db_isready

# ---------------------------------------------------------------------------
# Helper test doubles
# ---------------------------------------------------------------------------


class _DummyConn:
    """A no-op DBAPI connection that always succeeds on ``execute``."""

    def execute(self, _):
        return 1  # pragma: no cover

    # Context-manager support -------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyEngine:
    """Mimics the minimal SQLAlchemy *Engine* interface needed by db_isready."""

    def __init__(self, succeed_after: int = 1):
        self._attempts = 0
        self._succeed_after = max(1, succeed_after)

    def connect(self):
        # Import inside the method so SQLAlchemy is only required when tests run
        # Third-Party
        from sqlalchemy.exc import OperationalError  # pylint: disable=C0415

        self._attempts += 1
        if self._attempts < self._succeed_after:
            raise OperationalError("SELECT 1", {}, Exception("boom"))
        return _DummyConn()

    # Expose attempts for assertions
    @property
    def attempts(self):  # noqa: D401 - simple accessor
        return self._attempts


# ---------------------------------------------------------------------------
# Unit-tests - utilities first, then public API
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql://alice:secret@db/mydb",
        "error password=reallys3cret param=value",
    ],
)
def test_sanitize_masks_sensitive_parts(raw):
    """Anything that looks like credentials must be replaced by ***."""

    redacted = db_isready._sanitize(raw)

    # The replacement text must contain at least one asterisk block signalling masking
    assert "***" in redacted

    # And **no** piece of the original secret text may survive
    assert "secret" not in redacted
    assert "reallys3cret" not in redacted


@pytest.mark.parametrize(
    "url, expected",
    [
        ("sqlite:///:memory:", ":memory:"),  # SQLAlchemy represents memory DB with literal string
        ("postgresql://u:p@db.example.com:5432/mcp", "db.example.com:5432/mcp"),
    ],
)
def test_format_target_variants(url, expected):
    """_format_target should create concise human readable targets."""

    assert db_isready._format_target(db_isready.make_url(url)) == expected


def test_wait_for_db_ready_success(monkeypatch):
    """A healthy database should succeed on the first attempt."""

    dummy = _DummyEngine(succeed_after=1)

    def _fake_create_engine(_url, **kwargs):
        _fake_create_engine.kwargs = kwargs  # type: ignore[attr-defined]
        return dummy

    monkeypatch.setattr(db_isready, "create_engine", _fake_create_engine)
    monkeypatch.setattr(db_isready.time, "sleep", lambda *_: None)

    db_isready.wait_for_db_ready(
        database_url="postgresql://user:pw@localhost:5432/mcp",
        max_tries=3,
        interval=0.001,
        timeout=1,
        sync=True,
    )

    assert dummy.attempts == 1
    assert _fake_create_engine.kwargs["connect_args"]["connect_timeout"] == 1  # type: ignore[attr-defined]


def test_wait_for_db_ready_retries_then_succeeds(monkeypatch):
    """OperationalError should trigger retries until the connection works."""

    dummy = _DummyEngine(succeed_after=3)
    monkeypatch.setattr(db_isready, "create_engine", lambda *_a, **_k: dummy)
    monkeypatch.setattr(db_isready.time, "sleep", lambda *_: None)

    db_isready.wait_for_db_ready(
        database_url="postgresql://u:p@db/mcp",
        max_tries=5,
        interval=0.0001,
        timeout=2,
        sync=True,
    )

    assert dummy.attempts == 3


def test_wait_for_db_ready_exhausts_and_raises(monkeypatch):
    """After *max_tries* failures the helper must raise RuntimeError."""

    dummy = _DummyEngine(succeed_after=999)
    monkeypatch.setattr(db_isready, "create_engine", lambda *_a, **_k: dummy)
    monkeypatch.setattr(db_isready.time, "sleep", lambda *_: None)

    with pytest.raises(RuntimeError, match="Database not ready after 3 attempts"):
        db_isready.wait_for_db_ready(
            database_url="sqlite:///tmp.db",
            max_tries=3,
            interval=0.001,
            timeout=1,
            sync=True,
        )
    assert dummy.attempts == 3


def test_wait_for_db_ready_invalid_parameters():
    """Zero or negative timing parameters are rejected immediately."""

    with pytest.raises(RuntimeError):
        db_isready.wait_for_db_ready(max_tries=0)
    with pytest.raises(RuntimeError):
        db_isready.wait_for_db_ready(interval=0)
    with pytest.raises(RuntimeError):
        db_isready.wait_for_db_ready(timeout=0)


def test_wait_for_db_ready_async_path(monkeypatch):
    """Async path should off-load probe into executor without blocking."""

    dummy = _DummyEngine(succeed_after=1)
    monkeypatch.setattr(db_isready, "create_engine", lambda *_a, **_k: dummy)
    monkeypatch.setattr(db_isready.time, "sleep", lambda *_: None)

    # Create a dedicated loop so we can patch run_in_executor cleanly
    loop = asyncio.new_event_loop()

    async def _fake_run_in_executor(_executor, func, *args):  # noqa: D401
        # Execute the probe synchronously (no thread) then return dummy future
        func(*args)
        fut = loop.create_future()
        fut.set_result(None)
        return fut

    loop.run_in_executor = _fake_run_in_executor  # type: ignore[assignment]
    monkeypatch.setattr(asyncio, "get_event_loop", lambda: loop)

    db_isready.wait_for_db_ready(
        database_url="postgresql://u:p@db/mcp",
        max_tries=2,
        interval=0.001,
        timeout=1,
        sync=False,
    )

    assert dummy.attempts == 1
    loop.close()


def test_parse_cli_roundtrip(monkeypatch):
    """All CLI flags should be parsed into the expected Namespace values."""

    argv = [
        "db_isready.py",
        "--database-url",
        "postgresql://u:p@db/mcp",
        "--max-tries",
        "7",
        "--interval",
        "0.5",
        "--timeout",
        "3",
        "--log-level",
        "DEBUG",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    ns = db_isready._parse_cli()
    assert ns.database_url == "postgresql://u:p@db/mcp"
    assert ns.max_tries == 7
    assert ns.interval == 0.5
    assert ns.timeout == 3
    assert ns.log_level == "DEBUG"
