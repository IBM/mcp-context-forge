#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/source_scanner/storage/models.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Arnav

SQLAlchemy ORM models for Source Scanner persistence layer.

Note: This module defines the persistence layer for storing scan results and findings.
Currently, it is used internally by the repository layer.
Full integration with admin UI / caching / deployment hooks will be added in follow-up PRs.
"""

# Standard
#
from datetime import datetime, timezone

# Third-Party
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, Mapped, mapped_column, relationship

Base = declarative_base()


class ScanRecord(Base):
    """ORM model for scan records."""

    __tablename__ = "source_scanner_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    repo_url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    languages: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    block_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    info_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    findings: Mapped[list["FindingRecord"]] = relationship("FindingRecord", back_populates="scan", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_scan_commit_created", "commit_sha", "created_at"),
        Index("idx_scan_repo_created", "repo_url", "created_at"),
    )

    def __repr__(self) -> str:
        commit_val = getattr(self, "commit_sha", None)
        commit_display: str | None = commit_val[:8] if commit_val else None
        return f"<ScanRecord(id={self.id}, repo={self.repo_url}, commit={commit_display})>"


class FindingRecord(Base):
    """ORM model for individual findings within a scan."""

    __tablename__ = "source_scanner_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scan_id: Mapped[int] = mapped_column(Integer, ForeignKey("source_scanner_scans.id"), nullable=False, index=True)
    scanner: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(256), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column: Mapped[int | None] = mapped_column(Integer, nullable=True)
    code_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    help_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    scan: Mapped["ScanRecord"] = relationship("ScanRecord", back_populates="findings")

    __table_args__ = (
        UniqueConstraint("scan_id", "dedup_key", name="uq_finding_scan_dedup"),
        Index("idx_finding_severity", "severity"),
    )

    def __repr__(self) -> str:
        return f"<FindingRecord(id={self.id}, scanner={self.scanner}, rule={self.rule_id}, severity={self.severity})>"
