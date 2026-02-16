#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/test_storage_models.py
Copyright: 2026
SPDX-License-Identifier: Apache-2.0
Authors: Yaser
"""

# First-Party
from plugins.source_scanner.storage.models import FindingRecord, ScanRecord


def test_scan_record_repr_includes_short_commit() -> None:
    record = ScanRecord(repo_url="https://example.com/repo.git", commit_sha="abcdef1234567890")

    result = repr(record)

    assert "commit=abcdef12" in result
    assert "repo=https://example.com/repo.git" in result


def test_scan_record_table_columns_include_expected_fields() -> None:
    columns = {column.name for column in ScanRecord.__table__.columns}

    assert "repo_url" in columns
    assert "commit_sha" in columns
    assert "created_at" in columns
    assert "blocked" in columns


def test_finding_record_repr_includes_key_fields() -> None:
    finding = FindingRecord(
        scan_id=1,
        scanner="semgrep",
        severity="ERROR",
        rule_id="rule.id",
        message="Issue found",
    )

    result = repr(finding)

    assert "scanner=semgrep" in result
    assert "rule=rule.id" in result
    assert "severity=ERROR" in result


def test_finding_record_has_dedup_unique_constraint() -> None:
    constraint_names = {constraint.name for constraint in FindingRecord.__table__.constraints if constraint.name}

    assert "uq_finding_scan_dedup" in constraint_names
