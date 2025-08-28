# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/models_email_only.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Email-Only User Models.
Clean email-based identity system without username complexity.
"""

# Standard
from datetime import datetime
from typing import Dict, List, Optional
import uuid

# Third-Party
import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

# First-Party
from mcpgateway.db import Base, utc_now


class EmailUser(Base):
    """
    Email-only user model - clean implementation without username.

    Core identity fields:
    - email: Primary identifier and login credential
    - password_hash: Argon2id hashed password
    - full_name: Optional display name
    - is_admin: Admin privileges flag
    """

    __tablename__ = "email_users"

    # Core Identity (4 essential fields)
    email: Mapped[str] = mapped_column(String(255), primary_key=True, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Essential Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Authentication & Security
    auth_provider: Mapped[str] = mapped_column(String(50), default="local")
    password_hash_type: Mapped[str] = mapped_column(String(20), default="argon2id")
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Personal Team Reference
    personal_team_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("email_teams.id"), nullable=True)

    # Relationships
    personal_team: Mapped[Optional["EmailTeam"]] = relationship("EmailTeam", back_populates="owner", foreign_keys=[personal_team_id])
    team_memberships: Mapped[List["EmailTeamMember"]] = relationship("EmailTeamMember", back_populates="user", foreign_keys="EmailTeamMember.user_email")
    api_tokens: Mapped[List["EmailApiToken"]] = relationship("EmailApiToken", back_populates="user", cascade="all, delete-orphan")
    auth_events: Mapped[List["EmailAuthEvent"]] = relationship("EmailAuthEvent", back_populates="user", cascade="all, delete-orphan")

    @property
    def display_name(self) -> str:
        """Get display name for UI (full_name or email prefix)."""
        return self.full_name or self.email.split("@")[0]

    @property
    def short_name(self) -> str:
        """Get short name for compact displays."""
        if self.full_name:
            return self.full_name.split()[0]  # First name only
        return self.email.split("@")[0]

    @property
    def username(self) -> str:
        """Backward compatibility property."""
        return self.email  # For any legacy code that expects username


class EmailTeam(Base):
    """
    Email-based team model for clean email-only architecture.
    """

    __tablename__ = "email_teams"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Email-based ownership
    created_by: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=False)

    # Team Type and Settings
    is_personal: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility: Mapped[str] = mapped_column(String(20), default="private")  # 'private', 'public'
    auto_join: Mapped[bool] = mapped_column(Boolean, default=False)
    max_members: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    owner: Mapped[Optional["EmailUser"]] = relationship("EmailUser", back_populates="personal_team", foreign_keys=[created_by])
    members: Mapped[List["EmailTeamMember"]] = relationship("EmailTeamMember", back_populates="team", cascade="all, delete-orphan")
    invitations: Mapped[List["EmailTeamInvitation"]] = relationship("EmailTeamInvitation", back_populates="team", cascade="all, delete-orphan")


class EmailTeamMember(Base):
    """
    Email-based team membership.
    """

    __tablename__ = "email_team_members"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str] = mapped_column(String, ForeignKey("email_teams.id", ondelete="CASCADE"), nullable=False)
    user_email: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="member")  # 'owner', 'admin', 'member'
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    invited_by: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=True)

    # Relationships
    team: Mapped["EmailTeam"] = relationship("EmailTeam", back_populates="members")
    user: Mapped["EmailUser"] = relationship("EmailUser", back_populates="team_memberships", foreign_keys=[user_email])
    invited_by_user: Mapped[Optional["EmailUser"]] = relationship("EmailUser", foreign_keys=[invited_by])

    # Unique constraint for team membership
    __table_args__ = (sa.UniqueConstraint("team_id", "user_email", name="uq_email_team_user_membership"),)


class EmailTeamInvitation(Base):
    """
    Email-based team invitations.
    """

    __tablename__ = "email_team_invitations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str] = mapped_column(String, ForeignKey("email_teams.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)  # Email to invite
    role: Mapped[str] = mapped_column(String(50), default="member")
    invited_by: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=False)

    # Invitation Management
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=True)

    token: Mapped[Optional[str]] = mapped_column(String(500), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    team: Mapped["EmailTeam"] = relationship("EmailTeam", back_populates="invitations")
    invited_by_user: Mapped["EmailUser"] = relationship("EmailUser", foreign_keys=[invited_by])
    accepted_by_user: Mapped[Optional["EmailUser"]] = relationship("EmailUser", foreign_keys=[accepted_by])


class EmailApiToken(Base):
    """
    Email-based API tokens with enhanced scoping.
    """

    __tablename__ = "email_api_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_email: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    jti: Mapped[str] = mapped_column(String, unique=True, nullable=False, default=lambda: str(uuid.uuid4()))

    # Token Scoping (#282 - Per-Virtual-Server API Keys)
    server_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Null = global scope
    resource_scopes: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)  # ['tools.read', 'resources.write']
    ip_restrictions: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)  # ['192.168.1.0/24']
    time_restrictions: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)  # Business hours, etc.

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Status and Metadata
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Relationships
    user: Mapped["EmailUser"] = relationship("EmailUser", back_populates="api_tokens")


class EmailAuthEvent(Base):
    """
    Email-based authentication events for audit logging.
    """

    __tablename__ = "email_auth_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("email_users.email", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    user: Mapped[Optional["EmailUser"]] = relationship("EmailUser", back_populates="auth_events")


class TrustedDomain(Base):
    """
    Trusted domains for auto-approval and SSO integration.
    """

    __tablename__ = "trusted_domains"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)  # '@ibm.com'
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=True)
    sso_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # 'github', 'google', 'ibm_verify'

    # Metadata
    created_by: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Configuration
    settings: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)  # Provider-specific settings


class UserRegistration(Base):
    """
    Pending user registrations awaiting approval.
    """

    __tablename__ = "user_registrations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Null for SSO
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    auth_provider: Mapped[str] = mapped_column(String(50), default="local")

    # Approval Workflow
    status: Mapped[str] = mapped_column(String(20), default="pending_approval")  # 'pending_approval', 'approved', 'rejected'
    domain: Mapped[str] = mapped_column(String(255), nullable=False)

    # Timestamps
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("email_users.email"), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # SSO Data (if applicable)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    external_profile: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)


class EmailVerification(Base):
    """
    Email verification tokens.
    """

    __tablename__ = "email_verifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    verification_token: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PasswordReset(Base):
    """
    Password reset tokens.
    """

    __tablename__ = "password_resets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_email: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email", ondelete="CASCADE"), nullable=False)
    reset_token: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SSOProvider(Base):
    """
    SSO provider configurations.
    """

    __tablename__ = "sso_providers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)  # 'github', 'google', 'ibm_verify'
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)  # 'GitHub', 'Google Workspace'
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'oauth2', 'oidc'
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # OAuth/OIDC Configuration
    client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_secret_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    authorization_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    token_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    userinfo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    issuer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # For OIDC

    # Provider Settings
    configuration: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)
    attribute_mapping: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)
    trusted_domains: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class UserExternalProfile(Base):
    """
    External SSO profile data linked to email users.
    """

    __tablename__ = "user_external_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_email: Mapped[str] = mapped_column(String(255), ForeignKey("email_users.email", ondelete="CASCADE"), nullable=False)
    provider_id: Mapped[str] = mapped_column(String, ForeignKey("sso_providers.id", ondelete="CASCADE"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    profile_data: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    last_sync: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
