#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive SQLite testing and diagnostics for ContextForge.

This script combines:
1. System diagnostics (like diagnose_sqlite.sh)
2. Direct SQLite access tests
3. SQLAlchemy engine tests with ContextForge settings

Usage:
    python3 scripts/test_sqlite.py [options]

Options:
    --db-path PATH        Database file path (default: mcp.db)
    --database-url URL    Database URL (overrides --db-path)
    --skip-diagnostics    Skip system diagnostics
    --skip-sqlite         Skip direct SQLite tests
    --skip-sqlalchemy     Skip SQLAlchemy tests
    --verbose             Show detailed output
"""

import argparse
import os
import sys
import sqlite3
import subprocess
import platform


# Colors for output
class Colors:
    GREEN = "\033[0;32m"
    RED = "\033[0;31m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"  # No Color


def print_status(message, success=True):
    """Print status with color coding."""
    color = Colors.GREEN if success else Colors.RED
    symbol = "✓" if success else "✗"
    print(f"{color}{symbol}{Colors.NC} {message}")


def print_warning(message):
    """Print warning message."""
    print(f"{Colors.YELLOW}⚠{Colors.NC} {message}")


def print_info(message):
    """Print info message."""
    print(f"{Colors.BLUE}ℹ{Colors.NC} {message}")


def run_command(cmd, capture_output=True, timeout=30):
    """Run a shell command safely."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=capture_output, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


class SQLiteDiagnostics:
    """System diagnostics for SQLite issues."""

    def __init__(self, db_path="mcp.db", verbose=False):
        self.db_path = db_path
        self.verbose = verbose
        self.is_macos = platform.system() == "Darwin"
        self.issues = []
        self.recommendations = []

    def run_all_diagnostics(self):
        """Run comprehensive diagnostics."""
        print(f"{Colors.BLUE}=== SQLite System Diagnostics ==={Colors.NC}")
        print(f"Database: {self.db_path}")
        print(f"Platform: {platform.system()} {platform.release()}")
        print(f"Working directory: {os.getcwd()}")
        print(f"User: {os.getenv('USER', 'unknown')}")
        print()

        self.check_file_system()
        self.check_sqlite_versions()
        self.check_system_resources()
        self.check_database_health()
        self.check_processes()
        self.check_environment()

        if self.is_macos:
            self.check_macos_specific()

        self.print_summary()

    def check_file_system(self):
        """Check file system status."""
        print(f"{Colors.BLUE}=== File System Checks ==={Colors.NC}")

        if os.path.exists(self.db_path):
            stat_info = os.stat(self.db_path)
            print(f"File size: {stat_info.st_size} bytes")
            print(f"Permissions: {oct(stat_info.st_mode)}")

            # Check file type
            success, output, _ = run_command(f"file {self.db_path}")
            if success:
                print(f"File type: {output}")
                if "SQLite" not in output:
                    self.issues.append("Database file is not recognized as SQLite format")

            print_status("Database file exists")
        else:
            print_status("Database file missing", False)
            self.issues.append(f"Database file {self.db_path} does not exist")

        # Check WAL files
        wal_files = [f for f in [f"{self.db_path}-wal", f"{self.db_path}-shm", f"{self.db_path}-journal"] if os.path.exists(f)]
        if wal_files:
            print_warning(f"WAL/Journal files present: {wal_files}")
            self.issues.append("WAL/Journal files may indicate unclean shutdown")
            self.recommendations.append("Remove WAL files: rm -f mcp.db-wal mcp.db-shm mcp.db-journal")
        else:
            print_status("No WAL/Journal files")

        # Check disk space
        success, output, _ = run_command("df -h .")
        if success:
            print(f"Disk space:\n{output}")
            # Parse disk usage
            lines = output.split("\n")
            if len(lines) > 1:
                usage_line = lines[1].split()
                if len(usage_line) >= 4:
                    usage_percent = usage_line[4].rstrip("%")
                    try:
                        if int(usage_percent) > 90:
                            self.issues.append(f"Disk usage high: {usage_percent}%")
                    except ValueError:
                        pass
        print()

    def check_sqlite_versions(self):
        """Check SQLite version compatibility."""
        print(f"{Colors.BLUE}=== SQLite Version Checks ==={Colors.NC}")

        # System SQLite
        success, output, _ = run_command("sqlite3 --version")
        if success:
            print(f"System SQLite: {output}")
            print_status("sqlite3 command available")
        else:
            print_status("sqlite3 command not found", False)
            self.issues.append("sqlite3 command line tool not available")

        # Python SQLite
        try:
            import sqlite3 as sqlite_module

            print(f"Python SQLite: {sqlite_module.sqlite_version}")
            print(f"Python sqlite3 module: {sqlite_module.version}")
            print_status("Python SQLite module working")
        except ImportError:
            print_status("Python SQLite module not available", False)
            self.issues.append("Python sqlite3 module not available")

        if self.is_macos:
            # Check for Homebrew SQLite
            success, output, _ = run_command("/opt/homebrew/bin/sqlite3 --version")
            if success:
                print(f"Homebrew SQLite: {output}")
            else:
                print_warning("Homebrew SQLite not installed")
                self.recommendations.append("Update SQLite on macOS: brew install sqlite3 && brew link --force sqlite3")

        print()

    def check_system_resources(self):
        """Check system resource limits."""
        print(f"{Colors.BLUE}=== System Resource Checks ==={Colors.NC}")

        # ulimit checks
        success, output, _ = run_command("ulimit -n")
        if success:
            fd_limit = int(output)
            print(f"File descriptor limit: {fd_limit}")
            if fd_limit < 1024:
                self.issues.append(f"Low file descriptor limit: {fd_limit}")
                self.recommendations.append("Increase file limits: ulimit -n 4096")
            else:
                print_status("File descriptor limit OK")

        success, output, _ = run_command("ulimit -u")
        if success:
            proc_limit = int(output)
            print(f"Process limit: {proc_limit}")
            if proc_limit < 512:
                self.issues.append(f"Low process limit: {proc_limit}")

        print()

    def check_database_health(self):
        """Check database integrity and accessibility."""
        print(f"{Colors.BLUE}=== Database Health Checks ==={Colors.NC}")

        if not os.path.exists(self.db_path):
            print_status("Database file does not exist", False)
            return

        try:
            # Integrity check
            conn = sqlite3.connect(self.db_path, timeout=10)
            cursor = conn.execute("PRAGMA integrity_check;")
            result = cursor.fetchone()[0]
            if result == "ok":
                print_status("Database integrity OK")
            else:
                print_status(f"Database integrity issues: {result}", False)
                self.issues.append("Database integrity check failed")

            # Locking mode
            cursor = conn.execute("PRAGMA locking_mode;")
            lock_mode = cursor.fetchone()[0]
            print(f"Locking mode: {lock_mode}")

            # Journal mode
            cursor = conn.execute("PRAGMA journal_mode;")
            journal_mode = cursor.fetchone()[0]
            print(f"Journal mode: {journal_mode}")

            # List tables
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]
            print(f"Tables found: {len(tables)}")
            if self.verbose:
                print(f"  {', '.join(tables)}")

            # Check for multitenancy tables
            multitenancy_tables = ["email_users", "email_teams", "email_team_members"]
            found_mt_tables = [t for t in tables if t in multitenancy_tables]
            if found_mt_tables:
                print_info(f"Multitenancy tables found: {found_mt_tables} (v0.7.0+)")
            else:
                print_info("No multitenancy tables (v0.6.0 or earlier)")

            # Test basic queries
            if "gateways" in tables:
                cursor = conn.execute("SELECT COUNT(*) FROM gateways;")
                count = cursor.fetchone()[0]
                print(f"Gateway records: {count}")
                print_status("Database queries working")

            conn.close()

        except sqlite3.OperationalError as e:
            print_status(f"Database access failed: {e}", False)
            self.issues.append(f"SQLite operational error: {e}")
            if "disk I/O error" in str(e):
                self.recommendations.append("Check file permissions and disk space")
            elif "database is locked" in str(e):
                self.recommendations.append("Kill processes using database: pkill -f mcpgateway")
        except Exception as e:
            print_status(f"Database test failed: {e}", False)
            self.issues.append(f"Database error: {e}")

        print()

    def check_processes(self):
        """Check for processes that might lock the database."""
        print(f"{Colors.BLUE}=== Process Checks ==={Colors.NC}")

        # Check for ContextForge processes
        success, output, _ = run_command("pgrep -f 'mcpgateway|gunicorn'")
        if success and output:
            print_warning("ContextForge processes running:")
            success, ps_output, _ = run_command("ps aux | grep -E '(mcpgateway|gunicorn)' | grep -v grep")
            if success:
                print(ps_output)
            self.recommendations.append("Consider stopping processes: pkill -f mcpgateway")
        else:
            print_status("No ContextForge processes running")

        # Check for database locks (if lsof available)
        if os.path.exists(self.db_path):
            success, output, _ = run_command(f"lsof {self.db_path}")
            if success and output:
                print_warning("Processes using database file:")
                print(output)
            else:
                print_status("No processes using database file")

        print()

    def check_environment(self):
        """Check environment configuration."""
        print(f"{Colors.BLUE}=== Environment Configuration ==={Colors.NC}")

        env_vars = {
            "DATABASE_URL": os.getenv("DATABASE_URL", "not set"),
            "DB_POOL_SIZE": os.getenv("DB_POOL_SIZE", "not set (default: 10)"),
            "DB_MAX_OVERFLOW": os.getenv("DB_MAX_OVERFLOW", "not set (default: 5)"),
            "DB_POOL_TIMEOUT": os.getenv("DB_POOL_TIMEOUT", "not set (default: 30)"),
            "TMPDIR": os.getenv("TMPDIR", "not set"),
        }

        for key, value in env_vars.items():
            print(f"{key}: {value}")

        # Check .env file
        if os.path.exists(".env"):
            print_status(".env file present")
            with open(".env", "r") as f:
                content = f.read()
                if "DATABASE_URL" in content:
                    print_info("DATABASE_URL configured in .env")
                else:
                    print_warning("DATABASE_URL not found in .env")
        else:
            print_warning(".env file not found")

        print()

    def check_macos_specific(self):
        """macOS-specific checks."""
        print(f"{Colors.BLUE}=== macOS Specific Checks ==={Colors.NC}")

        # Check for quarantine attributes
        if os.path.exists(self.db_path):
            success, output, _ = run_command(f"xattr -l {self.db_path}")
            if success and "com.apple.quarantine" in output:
                print_warning("Database has quarantine attributes")
                self.recommendations.append(f"Remove quarantine: xattr -d com.apple.quarantine {self.db_path}")
            else:
                print_status("No quarantine attributes")

        # Check directory location
        cwd = os.getcwd()
        if any(folder in cwd for folder in ["/Desktop", "/Documents", "/Downloads"]):
            print_warning(f"Running in sandboxed directory: {cwd}")
            self.recommendations.append("Move to ~/Developer/ or similar non-sandboxed directory")
        else:
            print_status("Directory location OK")

        # Check Python version
        success, output, _ = run_command("which python3")
        if success:
            print(f"Python location: {output}")
            if "/opt/homebrew" in output:
                print_status("Using Homebrew Python")
            else:
                print_info("Using system Python")
                self.recommendations.append("Consider using Homebrew Python: brew install python3")

        print()

    def print_summary(self):
        """Print diagnostic summary."""
        print(f"{Colors.BLUE}=== Diagnostic Summary ==={Colors.NC}")

        if not self.issues:
            print_status("No issues detected")
        else:
            print(f"{Colors.RED}Issues found:{Colors.NC}")
            for issue in self.issues:
                print(f"  - {issue}")

        if self.recommendations:
            print(f"{Colors.YELLOW}Recommendations:{Colors.NC}")
            for rec in self.recommendations:
                print(f"  - {rec}")

        print()


class SQLiteDirectTest:
    """Direct SQLite database access tests."""

    def __init__(self, db_path="mcp.db", verbose=False):
        self.db_path = db_path
        self.verbose = verbose

    def run_tests(self):
        """Run direct SQLite tests."""
        print(f"{Colors.BLUE}=== Direct SQLite Tests ==={Colors.NC}")

        if not os.path.exists(self.db_path):
            print_status(f"Database file '{self.db_path}' does not exist", False)
            return False

        test_table = "mcpgateway_direct_test"
        conn = None

        try:
            # Test basic connection
            conn = sqlite3.connect(self.db_path, timeout=30)
            print_status("Connection successful")

            # Test basic query
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            table_names = [t[0] for t in tables]
            print_status(f"Found {len(tables)} tables")
            if self.verbose:
                print(f"  Tables: {table_names}")

            # Test multitenancy tables (v0.7.0)
            multitenancy_tables = ["email_users", "email_teams", "email_team_members"]
            found_mt_tables = [t for t in table_names if t in multitenancy_tables]
            if found_mt_tables:
                print_info(f"Multitenancy tables found: {found_mt_tables}")
            else:
                print_info("No multitenancy tables found (v0.6.0 or earlier)")

            # Test read operations on main tables
            if "gateways" in table_names:
                cursor = conn.execute("SELECT COUNT(*) FROM gateways;")
                count = cursor.fetchone()[0]
                print_status(f"Gateway table read successful: {count} records")

            # Test write operation
            test_table = "mcpgateway_direct_test"
            conn.execute(f"CREATE TABLE IF NOT EXISTS {test_table} (id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            conn.execute(f"INSERT INTO {test_table} (id) VALUES (?)", (1,))
            conn.commit()
            print_status("Write operation successful")

            # Test transaction
            cursor = conn.execute(f"SELECT COUNT(*) FROM {test_table}")
            count = cursor.fetchone()[0]
            print_status(f"Transaction test successful: {count} test records")

            print_status("All direct SQLite tests passed")
            return True

        except sqlite3.OperationalError as e:
            print_status(f"SQLite Operational Error: {e}", False)
            if "disk I/O error" in str(e):
                print("  → This is likely a file system or permissions issue")
                print("  → Try: ls -la mcp.db && df -h .")
            elif "database is locked" in str(e):
                print("  → Another process may have the database open")
                print("  → Try: lsof mcp.db && pkill -f mcpgateway")
            elif "no such table" in str(e):
                print("  → Database schema may not be initialized")
                print("  → Try: python3 -m mcpgateway.bootstrap_db")
            return False

        except Exception as e:
            print_status(f"Database test failed: {e}", False)
            return False

        finally:
            # Always cleanup test table and connection
            if conn:
                try:
                    conn.execute(f"DROP TABLE IF EXISTS {test_table}")
                    conn.commit()
                    conn.close()
                except Exception:
                    pass  # Ignore cleanup errors


class SQLAlchemyTest:
    """SQLAlchemy engine tests using ContextForge settings."""

    def __init__(self, database_url=None, verbose=False):
        self.database_url = database_url or os.getenv("DATABASE_URL", "sqlite:///./mcp.db")
        self.verbose = verbose

    def run_tests(self):
        """Run SQLAlchemy tests."""
        print(f"{Colors.BLUE}=== SQLAlchemy Engine Tests ==={Colors.NC}")
        print(f"Database URL: {self.database_url}")

        try:
            from sqlalchemy import create_engine, text, inspect

            # Create engine with ContextForge settings
            engine = create_engine(
                self.database_url,
                pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
                max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
                pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
                pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "3600")),
                echo=self.verbose,  # Show SQL queries if verbose
            )

            print_status("Engine created successfully")

            # Test connection
            with engine.connect() as conn:
                print_status("Connection established")

                # Test table inspection
                inspector = inspect(engine)
                tables = inspector.get_table_names()
                print_status(f"Found {len(tables)} tables")

                if self.verbose:
                    print(f"  Tables: {tables}")

                # Test basic query
                if "gateways" in tables:
                    result = conn.execute(text("SELECT COUNT(*) FROM gateways"))
                    count = result.scalar()
                    print_status(f"Gateway query successful: {count} records")

                    # Test more complex query
                    try:
                        result = conn.execute(
                            text("""
                            SELECT gateways.name, gateways.enabled, gateways.reachable
                            FROM gateways
                            LIMIT 5
                        """)
                        )
                        rows = result.fetchall()
                        print_status(f"Complex query successful: {len(rows)} gateway records")

                        if self.verbose:
                            for row in rows[:3]:  # Show first 3
                                print(f"  - {row[0]}: enabled={row[1]}, reachable={row[2]}")

                    except Exception as e:
                        print_warning(f"Complex query failed (might be schema issue): {e}")

                # Test multitenancy tables (v0.7.0)
                multitenancy_tables = ["email_users", "email_teams", "email_team_members"]
                found_mt_tables = [t for t in tables if t in multitenancy_tables]

                if found_mt_tables:
                    print_info(f"Multitenancy tables found: {found_mt_tables}")

                    # Test user query
                    if "email_users" in tables:
                        result = conn.execute(text("SELECT COUNT(*) FROM email_users"))
                        user_count = result.scalar()
                        print_status(f"Email users query successful: {user_count} users")

                    # Test team query
                    if "email_teams" in tables:
                        result = conn.execute(text("SELECT COUNT(*) FROM email_teams"))
                        team_count = result.scalar()
                        print_status(f"Email teams query successful: {team_count} teams")
                else:
                    print_info("No multitenancy tables found (v0.6.0 database or earlier)")

                # Test write operation
                test_table = "mcpgateway_sqlalchemy_test"
                conn.execute(text(f"CREATE TABLE IF NOT EXISTS {test_table} (id INTEGER, test_data TEXT)"))
                conn.execute(text(f"INSERT INTO {test_table} (id, test_data) VALUES (:id, :data)"), {"id": 1, "data": "test"})
                conn.commit()
                print_status("Write operation successful")

                # Cleanup
                conn.execute(text(f"DROP TABLE IF EXISTS {test_table}"))
                conn.commit()

                print_status("All SQLAlchemy tests passed")

            return True

        except ImportError:
            print_status("SQLAlchemy not available", False)
            print("  → Install with: pip install sqlalchemy")
            return False

        except Exception as e:
            print_status(f"SQLAlchemy test failed: {e}", False)

            # Specific error handling
            error_str = str(e)
            if "disk I/O error" in error_str:
                print("  → File system or permissions issue")
                print("  → Try: ls -la mcp.db && df -h .")
            elif "database is locked" in error_str:
                print("  → Database locked by another process")
                print("  → Try: lsof mcp.db && pkill -f mcpgateway")
            elif "no such table" in error_str:
                print("  → Database not initialized or migration needed")
                print("  → Try: python3 -m mcpgateway.bootstrap_db")
            elif "pool timeout" in error_str:
                print("  → Connection pool exhausted")
                print("  → Try increasing DB_POOL_SIZE and DB_POOL_TIMEOUT in .env")

            return False


def main():
    """Main function with argument parsing."""
    parser = argparse.ArgumentParser(description="Comprehensive SQLite testing and diagnostics for ContextForge", formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument("--db-path", default="mcp.db", help="Database file path (default: mcp.db)")
    parser.add_argument("--database-url", help="Database URL (overrides --db-path)")
    parser.add_argument("--skip-diagnostics", action="store_true", help="Skip system diagnostics")
    parser.add_argument("--skip-sqlite", action="store_true", help="Skip direct SQLite tests")
    parser.add_argument("--skip-sqlalchemy", action="store_true", help="Skip SQLAlchemy tests")
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")

    args = parser.parse_args()

    print(f"{Colors.BLUE}ContextForge SQLite Test Suite{Colors.NC}")
    print("=" * 50)

    all_passed = True

    # Run diagnostics
    if not args.skip_diagnostics:
        diagnostics = SQLiteDiagnostics(args.db_path, args.verbose)
        diagnostics.run_all_diagnostics()
        if diagnostics.issues:
            all_passed = False

    # Run direct SQLite tests
    if not args.skip_sqlite:
        sqlite_test = SQLiteDirectTest(args.db_path, args.verbose)
        if not sqlite_test.run_tests():
            all_passed = False

    # Run SQLAlchemy tests
    if not args.skip_sqlalchemy:
        database_url = args.database_url
        if not database_url and args.db_path != "mcp.db":
            database_url = f"sqlite:///{args.db_path}"

        sqlalchemy_test = SQLAlchemyTest(database_url, args.verbose)
        if not sqlalchemy_test.run_tests():
            all_passed = False

    print("=" * 50)
    if all_passed:
        print_status("All tests completed successfully")
        print("\n✓ SQLite database is working correctly with ContextForge")
    else:
        print_status("Some tests failed or issues detected", False)
        print("\nTroubleshooting recommendations:")
        print("1. Review the diagnostic output above")
        print("2. Check the SQLite troubleshooting section in MIGRATION-0.7.0.md")
        print("3. Ensure proper file permissions and disk space")
        print("4. Kill any hanging ContextForge processes")
        print("5. Remove WAL files if database was corrupted")

        if platform.system() == "Darwin":
            print("6. Update SQLite on macOS: brew install sqlite3 && brew link --force sqlite3")

        sys.exit(1)


if __name__ == "__main__":
    main()
