# -*- coding: utf-8 -*-
"""Unit tests for mcpgateway.utils.db_isready."""

# Standard
from types import SimpleNamespace
from unittest.mock import Mock

# Third-Party
import pytest

# First-Party
import mcpgateway.utils.db_isready as db_isready


class DummyLogger:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.debugs: list[str] = []
        self.errors: list[str] = []

    def info(self, msg: str) -> None:
        self.infos.append(msg)

    def debug(self, msg: str) -> None:
        self.debugs.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    @property
    def handlers(self) -> list[object]:
        # Non-empty so wait_for_db_ready skips logging.basicConfig (covers that branch).
        return [object()]


class FakeOperationalError(Exception):
    pass


class FakeConn:
    def __init__(self, execute_side_effect: Exception | None = None) -> None:
        self._execute_side_effect = execute_side_effect
        self.executed: list[object] = []

    def __enter__(self) -> "FakeConn":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: object) -> int:
        self.executed.append(query)
        if self._execute_side_effect:
            raise self._execute_side_effect
        return 1


class FakeEngine:
    def __init__(self, connect_side_effects: list[Exception] | None = None, has_dispose: bool = True) -> None:
        self._connect_side_effects = list(connect_side_effects or [])
        self.disposed = False
        if has_dispose:
            self.dispose = self._dispose  # type: ignore[assignment]

    def connect(self) -> FakeConn:
        if self._connect_side_effects:
            raise self._connect_side_effects.pop(0)
        return FakeConn()

    def _dispose(self) -> None:
        self.disposed = True


def test_sanitize_redacts_credentials() -> None:
    txt = "postgresql://user:secret@localhost/db?password=hunter2"
    redacted = db_isready._sanitize(txt)
    assert "secret" not in redacted
    assert "hunter2" not in redacted
    assert "***" in redacted


def test_format_target_sqlite_and_network_targets() -> None:
    sqlite_url = SimpleNamespace(get_backend_name=lambda: "sqlite", database=":memory:")
    assert db_isready._format_target(sqlite_url) == ":memory:"

    pg_url = SimpleNamespace(get_backend_name=lambda: "postgresql", host="db", port=5432, database="app")
    assert db_isready._format_target(pg_url) == "db:5432/app"


def test_wait_for_db_ready_rejects_invalid_parameters() -> None:
    with pytest.raises(RuntimeError, match="Invalid max_tries"):
        db_isready.wait_for_db_ready(database_url="sqlite:///./mcp.db", max_tries=0, interval=1, timeout=1, logger=DummyLogger(), sync=True)


def test_wait_for_db_ready_sqlite_success_disposes_engine(monkeypatch) -> None:
    fake_url = SimpleNamespace(get_backend_name=lambda: "sqlite", database="file.db", host=None, port=None)
    fake_engine = FakeEngine()

    create_engine_mock = Mock(return_value=fake_engine)
    monkeypatch.setattr(db_isready, "make_url", Mock(return_value=fake_url))
    monkeypatch.setattr(db_isready, "create_engine", create_engine_mock)
    monkeypatch.setattr(db_isready, "text", lambda q: q)
    monkeypatch.setattr(db_isready, "OperationalError", FakeOperationalError)

    db_isready.wait_for_db_ready(database_url="sqlite:///./mcp.db", max_tries=1, interval=1, timeout=1, logger=DummyLogger(), sync=True)

    create_engine_mock.assert_called_once()
    assert fake_engine.disposed is True


def test_wait_for_db_ready_non_sqlite_retries_with_backoff_and_connect_timeout(monkeypatch) -> None:
    fake_url = SimpleNamespace(get_backend_name=lambda: "postgresql", host="localhost", port=5432, database="testdb")
    fake_engine = FakeEngine(connect_side_effects=[FakeOperationalError("fail 1")])

    create_engine_mock = Mock(return_value=fake_engine)
    sleep_mock = Mock()

    monkeypatch.setattr(db_isready, "make_url", Mock(return_value=fake_url))
    monkeypatch.setattr(db_isready, "create_engine", create_engine_mock)
    monkeypatch.setattr(db_isready, "text", lambda q: q)
    monkeypatch.setattr(db_isready, "OperationalError", FakeOperationalError)
    monkeypatch.setattr(db_isready.random, "uniform", Mock(return_value=0.0))
    monkeypatch.setattr(db_isready.time, "sleep", sleep_mock)

    db_isready.wait_for_db_ready(database_url="postgresql://localhost/testdb", max_tries=2, interval=2, timeout=7, max_backoff=30, logger=DummyLogger(), sync=True)

    # Ensure connect_timeout is set for postgres and engine is created with pooling params.
    _, kwargs = create_engine_mock.call_args
    assert kwargs["connect_args"]["connect_timeout"] == 7
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_size"] == 1
    assert kwargs["max_overflow"] == 0

    # First attempt fails -> sleeps once before retrying.
    sleep_mock.assert_called_once()
    assert fake_engine.disposed is True


def test_wait_for_db_ready_last_attempt_failure_does_not_sleep(monkeypatch) -> None:
    fake_url = SimpleNamespace(get_backend_name=lambda: "postgresql", host="localhost", port=None, database=None)
    fake_engine = FakeEngine(connect_side_effects=[FakeOperationalError("fail always")])

    sleep_mock = Mock()

    monkeypatch.setattr(db_isready, "make_url", Mock(return_value=fake_url))
    monkeypatch.setattr(db_isready, "create_engine", Mock(return_value=fake_engine))
    monkeypatch.setattr(db_isready, "text", lambda q: q)
    monkeypatch.setattr(db_isready, "OperationalError", FakeOperationalError)
    monkeypatch.setattr(db_isready.time, "sleep", sleep_mock)

    with pytest.raises(RuntimeError, match="Database not ready"):
        db_isready.wait_for_db_ready(database_url="postgresql://localhost/testdb", max_tries=1, interval=2, timeout=1, logger=DummyLogger(), sync=True)

    sleep_mock.assert_not_called()
    assert fake_engine.disposed is True


def test_wait_for_db_ready_async_path_uses_event_loop(monkeypatch) -> None:
    fake_url = SimpleNamespace(get_backend_name=lambda: "sqlite", database="file.db", host=None, port=None)
    fake_engine = FakeEngine()

    class FakeLoop:
        def __init__(self) -> None:
            self.run_until_complete_called = False
            self.run_in_executor_called = False

        def run_in_executor(self, executor, func):  # noqa: ANN001
            self.run_in_executor_called = True
            func()
            return object()

        def run_until_complete(self, fut):  # noqa: ANN001
            self.run_until_complete_called = True
            return fut

    loop = FakeLoop()

    monkeypatch.setattr(db_isready, "make_url", Mock(return_value=fake_url))
    monkeypatch.setattr(db_isready, "create_engine", Mock(return_value=fake_engine))
    monkeypatch.setattr(db_isready, "text", lambda q: q)
    monkeypatch.setattr(db_isready, "OperationalError", FakeOperationalError)
    monkeypatch.setattr(db_isready.asyncio, "get_event_loop", Mock(return_value=loop))

    db_isready.wait_for_db_ready(database_url="sqlite:///./mcp.db", max_tries=1, interval=1, timeout=1, logger=DummyLogger(), sync=False)

    assert loop.run_in_executor_called is True
    assert loop.run_until_complete_called is True
    assert fake_engine.disposed is True


def test_wait_for_db_ready_async_path_without_dispose(monkeypatch) -> None:
    fake_url = SimpleNamespace(get_backend_name=lambda: "sqlite", database="file.db", host=None, port=None)
    fake_engine = FakeEngine(has_dispose=False)

    class FakeLoop:
        def run_in_executor(self, executor, func):  # noqa: ANN001
            func()
            return object()

        def run_until_complete(self, fut):  # noqa: ANN001
            return fut

    monkeypatch.setattr(db_isready, "make_url", Mock(return_value=fake_url))
    monkeypatch.setattr(db_isready, "create_engine", Mock(return_value=fake_engine))
    monkeypatch.setattr(db_isready, "text", lambda q: q)
    monkeypatch.setattr(db_isready, "OperationalError", FakeOperationalError)
    monkeypatch.setattr(db_isready.asyncio, "get_event_loop", Mock(return_value=FakeLoop()))

    db_isready.wait_for_db_ready(database_url="sqlite:///./mcp.db", max_tries=1, interval=1, timeout=1, logger=DummyLogger(), sync=False)


def test_wait_for_db_ready_does_not_require_dispose_method(monkeypatch) -> None:
    fake_url = SimpleNamespace(get_backend_name=lambda: "sqlite", database="file.db", host=None, port=None)
    fake_engine = FakeEngine(has_dispose=False)

    monkeypatch.setattr(db_isready, "make_url", Mock(return_value=fake_url))
    monkeypatch.setattr(db_isready, "create_engine", Mock(return_value=fake_engine))
    monkeypatch.setattr(db_isready, "text", lambda q: q)
    monkeypatch.setattr(db_isready, "OperationalError", FakeOperationalError)

    db_isready.wait_for_db_ready(database_url="sqlite:///./mcp.db", max_tries=1, interval=1, timeout=1, logger=DummyLogger(), sync=True)
    assert getattr(fake_engine, "disposed", False) is False


def test_parse_cli_defaults_and_custom_values(monkeypatch) -> None:
    monkeypatch.setattr(db_isready.sys, "argv", ["db_isready.py"])
    args = db_isready._parse_cli()
    assert args.database_url == db_isready.DEFAULT_DB_URL
    assert args.max_tries == db_isready.DEFAULT_MAX_TRIES
    assert args.interval == db_isready.DEFAULT_INTERVAL
    assert args.timeout == db_isready.DEFAULT_TIMEOUT
    assert args.log_level == db_isready.DEFAULT_LOG_LEVEL

    monkeypatch.setattr(
        db_isready.sys,
        "argv",
        [
            "db_isready.py",
            "--database-url",
            "postgresql://localhost/test",
            "--max-tries",
            "5",
            "--interval",
            "1.5",
            "--timeout",
            "10",
            "--log-level",
            "DEBUG",
        ],
    )
    args = db_isready._parse_cli()
    assert args.database_url == "postgresql://localhost/test"
    assert args.max_tries == 5
    assert args.interval == 1.5
    assert args.timeout == 10
    assert args.log_level == "DEBUG"
