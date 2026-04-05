# -*- coding: utf-8 -*-
"""Tests for run_mutmut.py cleanup logic and results_store parameterized query.

Covers the security changes in PR #3944:
1. shutil.rmtree replacement for os.system in run_mutmut.py
2. Parameterized SQL query in results_store.cleanup_old_results
"""

# Standard
import ast
import importlib
import inspect
import sqlite3
import textwrap
from unittest.mock import call, patch

# Third-Party
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _mutmut_module(tmp_path, monkeypatch):
    """Import (or reload) run_mutmut in an isolated cwd with controlled argv."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["run_mutmut.py"])

    # First-Party
    import run_mutmut

    importlib.reload(run_mutmut)  # ensure module picks up current cwd
    return run_mutmut


@pytest.fixture
def _db_conn(tmp_path):
    """SQLite connection with the evaluation_results schema; auto-closed."""
    conn = sqlite3.connect(tmp_path / "test.db")
    conn.execute(textwrap.dedent("""\
        CREATE TABLE evaluation_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            results_id TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""))
    conn.commit()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLEANUP_SQL = """\
DELETE FROM evaluation_results
WHERE created_at < datetime('now', '-' || CAST(? AS TEXT) || ' days')
"""


def _insert_aged_row(conn, results_id: str, age_days: int):
    conn.execute(
        "INSERT INTO evaluation_results (results_id, created_at) VALUES (?, datetime('now', '-' || ? || ' days'))",
        (results_id, age_days),
    )
    conn.commit()


def _run_cleanup(conn, days_old: int = 30) -> int:
    """Execute the exact parameterized cleanup query from results_store.py."""
    cursor = conn.execute(_CLEANUP_SQL, (days_old,))
    conn.commit()
    return cursor.rowcount


# ===========================================================================
# Part 1 — run_mutmut.py: shutil.rmtree replacement
# ===========================================================================


class TestMutmutCleanup:
    """Verify shutil.rmtree replaced os.system for directory cleanup."""

    def test_existing_dirs_are_removed(self, tmp_path, _mutmut_module):
        """Both mutants/ and .mutmut-cache/ are deleted before mutant generation."""
        (tmp_path / "mutants").mkdir()
        (tmp_path / ".mutmut-cache").mkdir()
        (tmp_path / "mutants" / "file.py").write_text("x")

        with patch.object(_mutmut_module, "run_command", return_value=("", "", 1)):
            _mutmut_module.main()

        assert not (tmp_path / "mutants").exists()
        assert not (tmp_path / ".mutmut-cache").exists()

    def test_missing_dirs_do_not_raise(self, tmp_path, _mutmut_module):
        """FileNotFoundError is caught so absent directories are silently skipped."""
        assert not (tmp_path / "mutants").exists()
        assert not (tmp_path / ".mutmut-cache").exists()

        with patch.object(_mutmut_module, "run_command", return_value=("", "", 1)):
            result = _mutmut_module.main()

        assert result == 1  # returns 1 because mutants/ never appears

    def test_rmtree_called_without_ignore_errors(self, _mutmut_module):
        """shutil.rmtree is called without ignore_errors (real errors must propagate)."""
        with patch.object(_mutmut_module.shutil, "rmtree") as mock_rm:
            with patch.object(_mutmut_module, "run_command", return_value=("", "", 1)):
                _mutmut_module.main()

        # rmtree must be called without ignore_errors — only FileNotFoundError is caught
        assert mock_rm.call_args_list == [
            call("mutants"),
            call(".mutmut-cache"),
        ]

    def test_partial_dir_removal(self, tmp_path, _mutmut_module):
        """Only one of the two dirs exists; the other is a no-op."""
        (tmp_path / ".mutmut-cache").mkdir()

        with patch.object(_mutmut_module, "run_command", return_value=("", "", 1)):
            _mutmut_module.main()

        assert not (tmp_path / ".mutmut-cache").exists()

    def test_permission_error_propagates(self, tmp_path, _mutmut_module):
        """Non-FileNotFoundError exceptions (e.g. PermissionError) must not be swallowed.

        If stale directories can't actually be removed, the script must fail
        rather than silently proceeding with stale mutant data.
        """

        def rmtree_perm_error(path):
            if path == "mutants":
                raise PermissionError(f"Cannot remove {path}")

        with patch.object(_mutmut_module.shutil, "rmtree", side_effect=rmtree_perm_error):
            with patch.object(_mutmut_module, "run_command", return_value=("", "", 1)):
                with pytest.raises(PermissionError, match="Cannot remove mutants"):
                    _mutmut_module.main()


class TestMutmutSecurityRegression:
    """Static checks that os.system is not reintroduced."""

    def test_os_module_not_imported(self):
        """run_mutmut.py must not import the os module."""
        # First-Party
        import run_mutmut

        source = inspect.getsource(run_mutmut)
        tree = ast.parse(source)
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_names.add(node.module.split(".")[0])
        assert "os" not in imported_names, "os module should not be imported in run_mutmut.py"

    def test_no_os_system_calls(self):
        """run_mutmut.py source must not contain os.system calls."""
        # First-Party
        import run_mutmut

        source = inspect.getsource(run_mutmut)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "os" and node.func.attr == "system":
                    pytest.fail("os.system() call found in run_mutmut.py — use shutil.rmtree instead")

    def test_shutil_is_used_for_cleanup(self):
        """run_mutmut.py must use shutil for directory removal."""
        # First-Party
        import run_mutmut

        assert hasattr(run_mutmut, "shutil"), "run_mutmut should import shutil"
        source = inspect.getsource(run_mutmut)
        assert "shutil.rmtree" in source, "shutil.rmtree should be used for directory cleanup"


# ===========================================================================
# Part 2 — results_store.py: parameterized SQL query
# ===========================================================================


class TestCleanupOldResultsSQL:
    """Test the parameterized DELETE query used by ResultsStore.cleanup_old_results."""

    def test_deletes_records_older_than_threshold(self, _db_conn):
        _insert_aged_row(_db_conn, "old-40", 40)
        _insert_aged_row(_db_conn, "old-35", 35)
        _insert_aged_row(_db_conn, "recent-10", 10)

        deleted = _run_cleanup(_db_conn, days_old=30)

        assert deleted == 2
        ids = [r[0] for r in _db_conn.execute("SELECT results_id FROM evaluation_results").fetchall()]
        assert ids == ["recent-10"]

    def test_preserves_all_when_none_old_enough(self, _db_conn):
        _insert_aged_row(_db_conn, "r1", 5)
        _insert_aged_row(_db_conn, "r2", 15)

        deleted = _run_cleanup(_db_conn, days_old=30)

        assert deleted == 0
        count = _db_conn.execute("SELECT COUNT(*) FROM evaluation_results").fetchone()[0]
        assert count == 2

    def test_default_30_days(self, _db_conn):
        _insert_aged_row(_db_conn, "old-31", 31)
        _insert_aged_row(_db_conn, "recent-29", 29)

        deleted = _run_cleanup(_db_conn)  # default days_old=30

        assert deleted == 1
        remaining = _db_conn.execute("SELECT results_id FROM evaluation_results").fetchone()[0]
        assert remaining == "recent-29"

    def test_empty_table_returns_zero(self, _db_conn):
        assert _run_cleanup(_db_conn) == 0

    def test_boundary_record_is_preserved(self, _db_conn):
        """A record at exactly days_old is NOT deleted (strict less-than)."""
        _insert_aged_row(_db_conn, "boundary-30", 30)
        _insert_aged_row(_db_conn, "over-31", 31)

        deleted = _run_cleanup(_db_conn, days_old=30)

        assert deleted == 1
        remaining = _db_conn.execute("SELECT results_id FROM evaluation_results").fetchone()[0]
        assert remaining == "boundary-30"

    def test_parameterized_query_blocks_injection(self, _db_conn):
        """Malicious string input must not delete unrelated rows.

        With parameterization, the malicious string is treated as a literal
        value for CAST(? AS TEXT).  SQLite's datetime() returns NULL for
        the resulting nonsense modifier, so the WHERE clause is never true
        and zero rows are deleted.
        """
        _insert_aged_row(_db_conn, "should-survive", 5)

        # This string would cause universal deletion in an f-string query
        malicious = "0 days') OR 1=1 --"
        deleted = _run_cleanup(_db_conn, days_old=malicious)

        assert deleted == 0, "Injection payload must not delete any rows"
        count = _db_conn.execute("SELECT COUNT(*) FROM evaluation_results").fetchone()[0]
        assert count == 1, "Parameterized query must not allow injection to delete rows"

    def test_query_matches_source_file(self):
        """The SQL pattern tested here must match what results_store.py actually uses."""
        source_path = "mcp-servers/python/mcp_eval_server/mcp_eval_server/storage/results_store.py"
        with open(source_path) as f:
            source = f.read()

        # Verify the core parameterized pattern exists in the source
        assert "CAST(? AS TEXT)" in source, "results_store.py must use CAST(? AS TEXT) parameterization"
        assert "datetime('now', '-' || CAST(? AS TEXT) || ' days')" in source, "results_store.py must use the parameterized datetime expression"
        # Verify the old f-string pattern is NOT present
        assert 'f"""' not in source or "{days_old}" not in source, "results_store.py must not use f-string SQL with days_old"
