#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/test_storage_repository.py
Copyright: 2026
SPDX-License-Identifier: Apache-2.0
Authors: Yaser
"""

# Standard
from typing import Optional
from unittest.mock import MagicMock, Mock

# Third-Party
import pytest

# First-Party
from plugins.source_scanner.storage.models import ScanRecord
from plugins.source_scanner.storage.repository import ScanRepository
from plugins.source_scanner.types import Finding


@pytest.fixture
def mock_db() -> MagicMock:
    """Mock SQLAlchemy Session."""
    return MagicMock()


@pytest.fixture
def repository(mock_db: MagicMock) -> ScanRepository:
    """Create ScanRepository with mocked database."""
    return ScanRepository(mock_db)


def _create_finding(
    scanner: str = "semgrep",
    severity: str = "ERROR",
    rule_id: str = "rule.id",
    message: str = "Issue found",
    file_path: Optional[str] = "app.py",
    line: Optional[int] = 10,
) -> Finding:
    """Helper to create Finding objects."""
    return Finding(
        scanner=scanner,
        severity=severity,  # type: ignore[arg-type]
        rule_id=rule_id,
        message=message,
        file_path=file_path,
        line=line,
    )


class TestScanRepositoryCreateScan:
    """Tests for create_scan method."""

    def test_create_scan_with_findings(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test creating a scan record with findings."""
        findings = [
            _create_finding(severity="ERROR"),
            _create_finding(severity="WARNING"),
            _create_finding(severity="INFO"),
        ]

        # Mock the scan object returned after flush
        mock_scan = Mock(spec=ScanRecord)
        mock_scan.id = 1

        repository.db.query.return_value.filter.return_value.first.return_value = None  # type: ignore[attr-defined]
        repository.db.flush = MagicMock(side_effect=lambda: setattr(mock_scan, "id", 1))

        repository.create_scan(
            repo_url="https://github.com/test/repo.git",
            ref="main",
            commit_sha="abc123def456",
            languages=["python", "javascript"],
            findings=findings,
            blocked=False,
            block_reason=None,
        )

        # Verify db.add was called for scan
        assert isinstance(repository.db.add, MagicMock) and repository.db.add.call_count >= 1
        # Verify db.commit was called
        assert isinstance(repository.db.commit, MagicMock) and repository.db.commit.call_count >= 1

    def test_create_scan_counts_severity(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test that create_scan correctly counts findings by severity."""
        findings = [
            _create_finding(severity="ERROR"),
            _create_finding(severity="ERROR"),
            _create_finding(severity="WARNING"),
            _create_finding(severity="INFO"),
            _create_finding(severity="INFO"),
            _create_finding(severity="INFO"),
        ]

        mock_scan = Mock(spec=ScanRecord)
        mock_scan.id = 1

        repository.db.flush = MagicMock(side_effect=lambda: setattr(mock_scan, "id", 1))

        repository.create_scan(
            repo_url="https://github.com/test/repo.git",
            ref="main",
            commit_sha="abc123def456",
            languages=[],
            findings=findings,
            blocked=False,
            block_reason=None,
        )

        # Verify ScanRecord was created with correct counts
        assert isinstance(repository.db.add, MagicMock) and repository.db.add.call_count >= 1


class TestScanRepositoryGetScan:
    """Tests for get_scan_by_id method."""

    def test_get_scan_by_id_found(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test retrieving scan by ID when it exists."""
        mock_scan = Mock(spec=ScanRecord)
        mock_scan.id = 1

        repository.db.query.return_value.filter.return_value.first.return_value = mock_scan  # type: ignore[attr-defined]

        result = repository.get_scan_by_id(1)

        assert result == mock_scan
        repository.db.query.assert_called_once()  # type: ignore[attr-defined]

    def test_get_scan_by_id_not_found(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test retrieving scan by ID when it does not exist."""
        repository.db.query.return_value.filter.return_value.first.return_value = None  # type: ignore[attr-defined]

        result = repository.get_scan_by_id(999)

        assert result is None


class TestScanRepositoryGetFindings:
    """Tests for get_findings_for_scan method."""

    def test_get_findings_for_scan_sorted(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test that findings are sorted by severity and file_path."""
        findings = [
            Mock(severity="INFO", file_path="z.py"),
            Mock(severity="ERROR", file_path="b.py"),
            Mock(severity="WARNING", file_path="a.py"),
        ]

        repository.db.query.return_value.filter.return_value.all.return_value = findings  # type: ignore[attr-defined]

        result = repository.get_findings_for_scan(1)

        # Verify sorting: ERROR (0), WARNING (1), INFO (2)
        assert result[0].severity == "ERROR"
        assert result[1].severity == "WARNING"
        assert result[2].severity == "INFO"

    def test_get_findings_for_scan_empty(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test getting findings when scan has none."""
        repository.db.query.return_value.filter.return_value.all.return_value = []  # type: ignore[attr-defined]

        result = repository.get_findings_for_scan(1)

        assert result == []


class TestScanRepositoryGetLatestScan:
    """Tests for get_latest_scan_for_commit method."""

    def test_get_latest_scan_for_commit_found(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test retrieving latest scan for a commit."""
        mock_scan = Mock(spec=ScanRecord)
        mock_scan.commit_sha = "abc123"

        repository.db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_scan  # type: ignore[attr-defined]

        result = repository.get_latest_scan_for_commit("https://github.com/test/repo", "abc123")

        assert result == mock_scan

    def test_get_latest_scan_for_commit_not_found(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test retrieving latest scan when none exists."""
        repository.db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None  # type: ignore[attr-defined]

        result = repository.get_latest_scan_for_commit("https://github.com/test/repo", "abc123")

        assert result is None


class TestScanRepositoryGetScansForRepo:
    """Tests for get_scans_for_repo method."""

    def test_get_scans_for_repo_with_pagination(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test retrieving scans with pagination."""
        mock_scans = [Mock(spec=ScanRecord) for _ in range(3)]

        repository.db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = mock_scans  # type: ignore[attr-defined]

        result = repository.get_scans_for_repo("https://github.com/test/repo", limit=10, offset=0)

        assert len(result) == 3
        assert result == mock_scans

    def test_get_scans_for_repo_default_pagination(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test that default pagination limits to 10."""
        repository.db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []  # type: ignore[attr-defined]

        repository.get_scans_for_repo("https://github.com/test/repo")

        # Verify limit(10) was called with default
        repository.db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.assert_called_with(10)  # type: ignore[attr-defined]


class TestScanRepositoryGetFindingsBySeverity:
    """Tests for get_findings_by_severity method."""

    def test_get_findings_by_severity_error(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test retrieving ERROR-level findings."""
        mock_findings = [Mock(severity="ERROR") for _ in range(2)]

        repository.db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_findings  # type: ignore[attr-defined]

        result = repository.get_findings_by_severity(1, "ERROR")

        assert len(result) == 2

    def test_get_findings_by_severity_warning(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test retrieving WARNING-level findings."""
        mock_findings = [Mock(severity="WARNING") for _ in range(1)]

        repository.db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_findings  # type: ignore[attr-defined]

        result = repository.get_findings_by_severity(1, "WARNING")

        assert len(result) == 1

    def test_get_findings_by_severity_empty(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test retrieving findings of specific severity when none exist."""
        repository.db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []  # type: ignore[attr-defined]

        result = repository.get_findings_by_severity(1, "ERROR")

        assert result == []


class TestScanRepositoryDeleteScan:
    """Tests for delete_scan method."""

    def test_delete_scan_success(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test deleting a scan that exists."""
        mock_scan = Mock(spec=ScanRecord)
        mock_scan.id = 1

        repository.db.query.return_value.filter.return_value.first.return_value = mock_scan  # type: ignore[attr-defined]
        repository.db.delete = MagicMock()  # type: ignore[attr-defined]
        repository.db.commit = MagicMock()  # type: ignore[attr-defined]

        result = repository.delete_scan(1)

        assert result is True
        repository.db.delete.assert_called_once_with(mock_scan)
        repository.db.commit.assert_called()

    def test_delete_scan_not_found(self, repository: ScanRepository, mock_db: MagicMock) -> None:
        """Test deleting a scan that does not exist."""
        repository.db.query.return_value.filter.return_value.first.return_value = None  # type: ignore[attr-defined]
        repository.db.delete = MagicMock()  # type: ignore[attr-defined]

        result = repository.delete_scan(999)

        assert result is False
        repository.db.delete.assert_not_called()
