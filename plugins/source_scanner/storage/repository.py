#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/source_scanner/storage/repository.py

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Arnav

Repository layer for Source Scanner persistence.

Provides CRUD access to ScanRecord and FindingRecord.
Currently uses SQLAlchemy; designed for incremental integration.
"""

# Standard
# from datetime import datetime, timezone
from typing import List, Optional

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from plugins.source_scanner.storage.models import FindingRecord, ScanRecord
from plugins.source_scanner.types import Finding

#


class ScanRepository:
    """Repository for accessing and storing scan records."""

    def __init__(self, db: Session):
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy database session.
        """
        self.db = db

    def create_scan(
        self,
        repo_url: str,
        ref: Optional[str],
        commit_sha: Optional[str],
        languages: List[str],
        findings: List[Finding],
        blocked: bool,
        block_reason: Optional[str],
    ) -> ScanRecord:
        """Persist a completed scan to the database.

        Creates a ScanRecord with associated FindingRecords. Deduplication
        is handled via unique constraint on (scan_id, dedup_key).

        Args:
            repo_url: Git repository URL.
            ref: Branch/tag/commit reference (user input).
            commit_sha: Resolved commit SHA.
            languages: List of detected languages.
            findings: Normalized findings from scanners.
            blocked: Policy decision result.
            block_reason: Reason for block if applicable.

        Returns:
            ScanRecord object with findings attached.
        """
        # Count findings by severity for summary stats
        error_count = sum(1 for f in findings if f.severity == "ERROR")
        warning_count = sum(1 for f in findings if f.severity == "WARNING")
        info_count = sum(1 for f in findings if f.severity == "INFO")

        # Create ScanRecord with metadata
        scan = ScanRecord(
            repo_url=repo_url,
            ref=ref,
            commit_sha=commit_sha,
            languages=",".join(languages) if languages else None,
            blocked=blocked,
            block_reason=block_reason,
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
        )
        self.db.add(scan)
        self.db.flush()  # Get scan ID without committing yet

        # Create FindingRecords for each finding
        for finding in findings:
            key_tuple = finding.dedup_key()  # dedup_key() returns a tuple

            # Serialize tuple to a string for the DB column
            dedup_key: str = "|".join([str(x) for x in key_tuple])

            finding_record = FindingRecord(
                scan_id=scan.id,
                scanner=finding.scanner,
                severity=finding.severity,
                rule_id=finding.rule_id,
                message=finding.message,
                file_path=finding.file_path,
                line=finding.line,
                column=finding.column,
                code_snippet=finding.code_snippet,
                help_url=finding.help_url,
                dedup_key=dedup_key,
            )
            self.db.add(finding_record)

        # Commit all changes at once
        self.db.commit()
        return scan

    def get_scan_by_id(self, scan_id: int) -> Optional[ScanRecord]:
        """Retrieve a scan record by ID.

        Args:
            scan_id: Primary key of the scan.

        Returns:
            ScanRecord if found, None otherwise.
        """
        return self.db.query(ScanRecord).filter(ScanRecord.id == scan_id).first()

    def get_findings_for_scan(self, scan_id: int) -> List[FindingRecord]:
        """Retrieve all findings for a given scan.

        Args:
            scan_id: Primary key of the scan.

        Returns:
            List of FindingRecord objects, ordered by severity then file_path.
        """
        # Severity order: ERROR > WARNING > INFO
        severity_order = {"ERROR": 0, "WARNING": 1, "INFO": 2}

        findings = self.db.query(FindingRecord).filter(FindingRecord.scan_id == scan_id).all()

        # Sort by severity first, then by file_path
        findings.sort(key=lambda f: (severity_order.get(getattr(f, "severity", ""), 3), getattr(f, "file_path", "") or ""))

        # findings.sort(key=lambda f: (severity_order.get(f.severity, 3), f.file_path or ""))
        return findings

    def get_latest_scan_for_commit(
        self,
        repo_url: str,
        commit_sha: str,
    ) -> Optional[ScanRecord]:
        """Retrieve the most recent scan for a given commit SHA.

        Args:
            repo_url: Git repository URL.
            commit_sha: Commit hash.

        Returns:
            Most recent ScanRecord if found, None otherwise.
        """
        return (
            self.db.query(ScanRecord)
            .filter(
                ScanRecord.repo_url == repo_url,
                ScanRecord.commit_sha == commit_sha,
            )
            .order_by(ScanRecord.created_at.desc())
            .first()
        )

    def get_scans_for_repo(
        self,
        repo_url: str,
        limit: int = 10,
        offset: int = 0,
    ) -> List[ScanRecord]:
        """Retrieve recent scans for a repository with pagination.

        Args:
            repo_url: Git repository URL.
            limit: Maximum number of results to return.
            offset: Number of results to skip.

        Returns:
            List of ScanRecord objects ordered by creation time (newest first).
        """
        return self.db.query(ScanRecord).filter(ScanRecord.repo_url == repo_url).order_by(ScanRecord.created_at.desc()).offset(offset).limit(limit).all()

    def get_findings_by_severity(
        self,
        scan_id: int,
        severity: str,
    ) -> List[FindingRecord]:
        """Retrieve findings of a specific severity for a scan.

        Args:
            scan_id: Primary key of the scan.
            severity: Severity level (ERROR|WARNING|INFO).

        Returns:
            List of FindingRecord objects matching the severity.
        """
        return (
            self.db.query(FindingRecord)
            .filter(
                FindingRecord.scan_id == scan_id,
                FindingRecord.severity == severity,
            )
            .order_by(FindingRecord.file_path)
            .all()
        )

    def delete_scan(self, scan_id: int) -> bool:
        """Delete a scan and all its associated findings.

        Args:
            scan_id: Primary key of the scan to delete.

        Returns:
            True if scan was deleted, False if not found.
        """
        scan = self.db.query(ScanRecord).filter(ScanRecord.id == scan_id).first()
        if not scan:
            return False

        self.db.delete(scan)  # Cascade delete handles findings
        self.db.commit()
        return True
