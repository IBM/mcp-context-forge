# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_check_schema_at_head.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for ``mcpgateway.utils.check_schema_at_head``.

The module is the gateway pod's K8s startup-probe entrypoint — it runs
every five seconds and its exit code determines whether a pod is allowed
to serve traffic. The contract this module exists to pin:

  * exit 0  ⇔  ``alembic_at_head`` returned True
  * exit 1  ⇔  ``alembic_at_head`` returned False
  * exit 1  ⇔  any exception inside the try/except is swallowed and
                logged at WARNING (operator-visible at the project's
                default log level)
  * ``engine.dispose()`` is called on every code path

A regression here either fails open (probe returns 0 with no schema —
gateway pods reach Ready against an empty DB and 500 on the first
request) or fails closed forever (an exception propagates with a non-1
exit code that K8s might re-classify). Neither is acceptable; both are
silent. These tests are the truth-table that catches such regressions
at PR time rather than in production pod logs.
"""

# Standard
import logging
from unittest.mock import MagicMock, Mock, patch

# First-Party
import mcpgateway.utils.check_schema_at_head as check_schema_at_head


def _build_mock_engine_with_connect():
    """Return a MagicMock engine whose ``connect()`` works as a context manager.

    The probe's ``with engine.connect() as conn:`` pattern requires
    ``__enter__``/``__exit__`` on whatever ``engine.connect()`` returns.
    MagicMock supplies both by default; this helper just wires the
    yielded connection to a plain Mock so tests can assert on it if they
    want to.
    """
    mock_engine = MagicMock()
    mock_conn = Mock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_engine.connect.return_value.__exit__.return_value = False
    return mock_engine


class TestMain:
    """Truth-table for ``check_schema_at_head.main()``.

    Each test patches the three symbols ``main()`` reaches for
    (``create_engine``, ``make_alembic_cfg``, ``alembic_at_head``) at the
    point they're imported into ``check_schema_at_head`` — that way we
    never touch a real database, the tests run in milliseconds, and they
    pin the wrapper's contract without coupling to any specific engine
    or Alembic implementation detail.
    """

    def test_returns_0_when_schema_at_head(self):
        """Happy path: alembic_at_head True → exit 0; engine disposed once."""
        mock_engine = _build_mock_engine_with_connect()

        with patch.object(check_schema_at_head, "create_engine", return_value=mock_engine):
            with patch.object(check_schema_at_head, "make_alembic_cfg", return_value=Mock()):
                with patch.object(check_schema_at_head, "alembic_at_head", return_value=True):
                    assert check_schema_at_head.main() == 0

        mock_engine.dispose.assert_called_once()

    def test_returns_1_when_schema_not_at_head(self):
        """Probe says no → exit 1 (K8s holds the pod 0/1 until next tick)."""
        mock_engine = _build_mock_engine_with_connect()

        with patch.object(check_schema_at_head, "create_engine", return_value=mock_engine):
            with patch.object(check_schema_at_head, "make_alembic_cfg", return_value=Mock()):
                with patch.object(check_schema_at_head, "alembic_at_head", return_value=False):
                    assert check_schema_at_head.main() == 1

        mock_engine.dispose.assert_called_once()

    def test_returns_1_on_engine_connect_error(self):
        """``engine.connect()`` raising (DB unreachable, bad URL, network
        partition) must be caught and exit 1, not propagate. K8s relies on
        the probe being deterministic on the failure path."""
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = OSError("connection refused")

        with patch.object(check_schema_at_head, "create_engine", return_value=mock_engine):
            with patch.object(check_schema_at_head, "make_alembic_cfg", return_value=Mock()):
                assert check_schema_at_head.main() == 1

        mock_engine.dispose.assert_called_once()

    def test_returns_1_on_probe_exception(self):
        """``alembic_at_head`` itself raising (e.g., corrupt alembic_version
        row) must be caught and exit 1. The helper's own ``except`` returns
        False, but a defensive test pins ``main()``'s outer ``except`` too —
        a future refactor that drops the helper's broad-except would otherwise
        pass through unnoticed."""
        mock_engine = _build_mock_engine_with_connect()

        with patch.object(check_schema_at_head, "create_engine", return_value=mock_engine):
            with patch.object(check_schema_at_head, "make_alembic_cfg", return_value=Mock()):
                with patch.object(
                    check_schema_at_head,
                    "alembic_at_head",
                    side_effect=RuntimeError("boom"),
                ):
                    assert check_schema_at_head.main() == 1

        mock_engine.dispose.assert_called_once()

    def test_logs_warning_on_exception(self, caplog):
        """Probe-failure path must emit at WARNING so it's visible at the
        project's default ``LOG_LEVEL=INFO`` (most chart deployments).
        DEBUG would render the failure invisible to operators — the same
        observability concern H1 fixed in ``alembic_at_head``."""
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = OSError("connection refused")

        with patch.object(check_schema_at_head, "create_engine", return_value=mock_engine):
            with patch.object(check_schema_at_head, "make_alembic_cfg", return_value=Mock()):
                with caplog.at_level(logging.WARNING, logger="mcpgateway.check_schema_at_head"):
                    check_schema_at_head.main()

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("schema-at-head probe failed" in r.message for r in warnings), f"Expected WARNING containing 'schema-at-head probe failed' from check_schema_at_head; got: {[r.message for r in caplog.records]}"
