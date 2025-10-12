# -*- coding: utf-8 -*-
"""Data validation utilities."""

import logging
from typing import Any, Dict, List

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


class DataValidator:
    """Validate generated data integrity."""

    def __init__(self, db: Session, logger: logging.Logger):
        """Initialize validator.

        Args:
            db: Database session
            logger: Logger instance
        """
        self.db = db
        self.logger = logger
        self.results = {}

    def validate_all(self) -> Dict[str, Any]:
        """Run all validation checks.

        Returns:
            Dictionary of validation results
        """
        self.logger.info("Starting data validation...")

        checks = [
            ("Foreign Keys", self.check_foreign_keys),
            ("Orphaned Records", self.check_orphaned_records),
            ("Required Fields", self.check_required_fields),
            ("Email Formats", self.check_email_formats),
        ]

        all_passed = True
        for name, check_func in checks:
            self.logger.info(f"Running check: {name}")
            result = check_func()
            self.results[name] = result

            if not result.get("passed", False):
                all_passed = False
                self.logger.warning(f"Check failed: {name}")
            else:
                self.logger.info(f"Check passed: {name}")

        self.results["all_passed"] = all_passed
        return self.results

    def check_foreign_keys(self) -> Dict[str, Any]:
        """Check foreign key integrity.

        Returns:
            Check results
        """
        try:
            # This is database-specific, but works for SQLite and PostgreSQL
            result = self.db.execute(text("PRAGMA foreign_key_check;"))
            violations = result.fetchall()

            return {
                "passed": len(violations) == 0,
                "violations": len(violations),
                "details": [str(v) for v in violations[:10]],  # First 10
            }
        except Exception as e:
            self.logger.error(f"Foreign key check failed: {e}")
            return {
                "passed": False,
                "error": str(e),
            }

    def check_orphaned_records(self) -> Dict[str, Any]:
        """Check for orphaned records (records with invalid foreign keys).

        Returns:
            Check results
        """
        orphans = []

        try:
            # Check EmailTeamMember for orphaned records
            result = self.db.execute(text("""
                SELECT COUNT(*) FROM email_team_members etm
                LEFT JOIN email_users eu ON etm.user_email = eu.email
                WHERE eu.email IS NULL
            """))
            team_member_orphans = result.scalar()
            if team_member_orphans > 0:
                orphans.append(f"EmailTeamMember: {team_member_orphans} orphans")

            # Check Tool for orphaned gateways
            result = self.db.execute(text("""
                SELECT COUNT(*) FROM tools t
                LEFT JOIN gateways g ON t.gateway_id = g.id
                WHERE t.gateway_id IS NOT NULL AND g.id IS NULL
            """))
            tool_orphans = result.scalar()
            if tool_orphans > 0:
                orphans.append(f"Tool: {tool_orphans} orphans")

            return {
                "passed": len(orphans) == 0,
                "orphans_found": len(orphans),
                "details": orphans,
            }
        except Exception as e:
            self.logger.error(f"Orphan check failed: {e}")
            return {
                "passed": False,
                "error": str(e),
            }

    def check_required_fields(self) -> Dict[str, Any]:
        """Check that required fields are not NULL.

        Returns:
            Check results
        """
        issues = []

        try:
            # Check EmailUser required fields
            result = self.db.execute(text("""
                SELECT COUNT(*) FROM email_users
                WHERE email IS NULL OR full_name IS NULL OR password_hash IS NULL
            """))
            user_issues = result.scalar()
            if user_issues > 0:
                issues.append(f"EmailUser: {user_issues} records with NULL required fields")

            # Check EmailTeam required fields
            result = self.db.execute(text("""
                SELECT COUNT(*) FROM email_teams
                WHERE name IS NULL OR created_by IS NULL
            """))
            team_issues = result.scalar()
            if team_issues > 0:
                issues.append(f"EmailTeam: {team_issues} records with NULL required fields")

            return {
                "passed": len(issues) == 0,
                "issues_found": len(issues),
                "details": issues,
            }
        except Exception as e:
            self.logger.error(f"Required fields check failed: {e}")
            return {
                "passed": False,
                "error": str(e),
            }

    def check_email_formats(self) -> Dict[str, Any]:
        """Check email format validity.

        Returns:
            Check results
        """
        try:
            # Simple check: email should contain @
            result = self.db.execute(text("""
                SELECT COUNT(*) FROM email_users
                WHERE email NOT LIKE '%@%'
            """))
            invalid_emails = result.scalar()

            return {
                "passed": invalid_emails == 0,
                "invalid_count": invalid_emails,
            }
        except Exception as e:
            self.logger.error(f"Email format check failed: {e}")
            return {
                "passed": False,
                "error": str(e),
            }

    def get_table_counts(self) -> Dict[str, int]:
        """Get row counts for all tables.

        Returns:
            Dictionary of table name to row count
        """
        counts = {}

        try:
            # Get list of tables
            inspector = inspect(self.db.bind)
            tables = inspector.get_table_names()

            for table in tables:
                result = self.db.execute(text(f"SELECT COUNT(*) FROM {table}"))
                counts[table] = result.scalar()
        except Exception as e:
            self.logger.error(f"Failed to get table counts: {e}")

        return counts
