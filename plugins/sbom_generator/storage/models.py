#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/storage/models.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo
"""

# Standard
from datetime import datetime, timezone
from uuid import uuid4

# Third-Party
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

# First-Party
from mcpgateway.db import Base


class SBOMDocumentDB(Base):
    """Database model for SBOM documents."""

    __tablename__ = "sbom_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    server_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # SBOM metadata
    format: Mapped[str] = mapped_column(String(50), nullable=False)
    spec_version: Mapped[str] = mapped_column(String(20), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Generation metadata
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    generator_tool: Mapped[str] = mapped_column(String(100), nullable=False, default="syft")
    generator_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Main component
    main_component_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    main_component_version: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Full SBOM document
    document_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_compressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Audit fields
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships - FIXED
    components: Mapped[list["SBOMComponentDB"]] = relationship("SBOMComponentDB", back_populates="sbom_document", cascade="all, delete-orphan", foreign_keys="SBOMComponentDB.sbom_document_id")

    __table_args__ = (
        Index("ix_sbom_documents_server_id_generated_at", "server_id", "generated_at"),
        Index("ix_sbom_documents_format", "format"),
        Index("ix_sbom_documents_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        """Provides a concise string representation of the SBOM document for debugging purposes."""
        return f"<SBOMDocument(id={self.id}, server_id={self.server_id}, format={self.format})>"


class SBOMComponentDB(Base):
    """Database model for SBOM components."""

    __tablename__ = "sbom_components"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sbom_document_id: Mapped[str] = mapped_column(String(36), ForeignKey("sbom_documents.id", ondelete="CASCADE"), nullable=False, index=True)

    # Component identification
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    purl: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)

    # Ecosystem and type
    ecosystem: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    component_type: Mapped[str] = mapped_column(String(50), nullable=False, default="library")

    # License information
    licenses: Mapped[str | None] = mapped_column(Text, nullable=True)

    hash_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_direct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Additional metadata
    component_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships - FIXED
    sbom_document: Mapped["SBOMDocumentDB"] = relationship("SBOMDocumentDB", back_populates="components")

    __table_args__ = (
        Index("ix_sbom_components_name_version", "name", "version"),
        Index("ix_sbom_components_sbom_doc_id_name", "sbom_document_id", "name"),
    )

    def __repr__(self) -> str:
        """Provides a concise string representation of the component for debugging purposes."""
        return f"<SBOMComponent(id={self.id}, name={self.name}, version={self.version})>"


class SBOMVulnerabilityDB(Base):
    """Database model for vulnerability tracking."""

    __tablename__ = "sbom_vulnerabilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    cve_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)

    package_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    package_ecosystem: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    affected_version_range: Mapped[str] = mapped_column(String(200), nullable=False)
    fixed_version: Mapped[str | None] = mapped_column(String(100), nullable=True)

    severity: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    cvss_score: Mapped[str | None] = mapped_column(String(10), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    references: Mapped[str | None] = mapped_column(Text, nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self) -> str:
        """Provides a concise string representation of the vulnerability for debugging purposes."""
        return f"<SBOMVulnerability(id={self.id}, cve_id={self.cve_id}, package={self.package_name})>"
