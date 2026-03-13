# -*- coding: utf-8 -*-
"""
Location: ./plugins/security_clearance/models.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Katia Neli

Bell-LaPadula MAC - SQLAlchemy ORM Models (Phase 2).
"""
from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mcpgateway.db import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SCLevel(Base):
    """Livelli di clearance nominali, es. PUBLIC=0, SECRET=3."""

    __tablename__ = "sc_levels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    numeric_value: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)


class SCUserClearance(Base):
    """Clearance assegnata per singolo utente."""

    __tablename__ = "sc_user_clearances"
    __table_args__ = (
        Index("ix_sc_user_clearances_user_tenant", "user_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    clearance_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    granted_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)


class SCTeamClearance(Base):
    """Clearance assegnata per team."""

    __tablename__ = "sc_team_clearances"
    __table_args__ = (
        Index("ix_sc_team_clearances_team_tenant", "team_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    clearance_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    granted_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)


class SCToolClassification(Base):
    """Livello minimo richiesto per invocare un tool."""

    __tablename__ = "sc_tool_classifications"
    __table_args__ = (
        Index("ix_sc_tool_classifications_tool_server", "tool_name", "server_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    server_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    classification_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)


class SCServerClassification(Base):
    """Livello minimo richiesto per un intero server MCP."""

    __tablename__ = "sc_server_classifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    server_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    classification_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)


class SCClearanceAuditLog(Base):
    """Audit trail immutabile di ogni decisione di accesso."""

    __tablename__ = "sc_clearance_audit_log"
    __table_args__ = (
        Index("ix_sc_audit_user_ts", "user_id", "timestamp"),
        Index("ix_sc_audit_tenant_ts", "tenant_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, index=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_clearance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)    # tool | resource | prompt
    resource_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    resource_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)          # ALLOW | DENY
    violation_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    hook: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    extra: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class SCDynamicRule(Base):
    """Override dinamici e regole context-sensitive a runtime."""

    __tablename__ = "sc_dynamic_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)    # override | deny | allow
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False) # user | team | role
    subject_id: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    clearance_override: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)