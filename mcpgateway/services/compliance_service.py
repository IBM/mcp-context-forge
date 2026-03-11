# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/compliance_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Compliance Report Generator Service.

This module provides automated compliance report generation for FedRAMP Moderate,
HIPAA, and SOC2 Type II frameworks. Evidence is collected from audit logs,
user/role inventory, and configuration snapshots stored in the gateway.
"""

# Standard
import csv
import io
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import AuditTrail, EmailUser, SessionLocal, UserRole

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ComplianceFramework(str, Enum):
    """Supported compliance frameworks."""

    FEDRAMP_MODERATE = "fedramp_moderate"
    FEDRAMP_HIGH = "fedramp_high"
    HIPAA = "hipaa"
    SOC2_TYPE2 = "soc2_type2"


class ControlStatus(str, Enum):
    """Compliance control implementation status."""

    IMPLEMENTED = "implemented"
    PARTIAL = "partial"
    NOT_IMPLEMENTED = "not_implemented"
    NOT_APPLICABLE = "not_applicable"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ComplianceControl:
    """Definition of a compliance control requirement.

    Attributes:
        id: Control identifier (e.g. AC-2, 164.312(a)(1), CC6.1)
        title: Short title of the control
        description: Full description of what the control requires
        framework: Compliance framework this control belongs to
        evidence_sources: List of evidence source labels
    """

    id: str
    title: str
    description: str
    framework: ComplianceFramework
    evidence_sources: List[str] = field(default_factory=list)


@dataclass
class ControlEvidence:
    """Evidence collected for a single compliance control.

    Attributes:
        control_id: ID of the control being assessed
        status: Implementation status
        evidence: Human-readable evidence summary
        artifacts: Raw artifact data collected during evidence gathering
        findings: List of findings or observations
        recommendations: List of recommended remediation actions
    """

    control_id: str
    status: ControlStatus
    evidence: str
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    findings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class ComplianceReport:
    """Full compliance report for a given framework and time period.

    Attributes:
        id: Unique report identifier
        framework: Compliance framework assessed
        period_start: Start of the assessment period
        period_end: End of the assessment period
        generated_at: Timestamp when the report was generated
        controls: List of control evidence objects
        summary: Aggregated counts and metadata
    """

    id: str
    framework: ComplianceFramework
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    controls: List[ControlEvidence] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Control definitions
# ---------------------------------------------------------------------------

_FEDRAMP_MODERATE_CONTROLS: List[ComplianceControl] = [
    ComplianceControl(
        id="AC-2",
        title="Account Management",
        description="The organization manages information system accounts, including establishing, activating, modifying, reviewing, disabling, and removing accounts.",
        framework=ComplianceFramework.FEDRAMP_MODERATE,
        evidence_sources=["user_inventory", "audit_logs"],
    ),
    ComplianceControl(
        id="AC-3",
        title="Access Enforcement",
        description="The information system enforces approved authorizations for logical access to information and system resources.",
        framework=ComplianceFramework.FEDRAMP_MODERATE,
        evidence_sources=["role_inventory", "config_snapshot"],
    ),
    ComplianceControl(
        id="AC-6",
        title="Least Privilege",
        description="The organization employs the principle of least privilege, allowing only authorized accesses for users which are necessary to accomplish assigned tasks.",
        framework=ComplianceFramework.FEDRAMP_MODERATE,
        evidence_sources=["role_inventory", "user_inventory"],
    ),
    ComplianceControl(
        id="AU-2",
        title="Audit Events",
        description="The organization determines that the information system is capable of auditing events and coordinates the security audit function with other organizations.",
        framework=ComplianceFramework.FEDRAMP_MODERATE,
        evidence_sources=["audit_logs", "config_snapshot"],
    ),
    ComplianceControl(
        id="AU-3",
        title="Content of Audit Records",
        description="The information system generates audit records containing sufficient information to establish what events occurred, the sources of the events, and the outcomes.",
        framework=ComplianceFramework.FEDRAMP_MODERATE,
        evidence_sources=["audit_logs"],
    ),
    ComplianceControl(
        id="AU-6",
        title="Audit Review",
        description="The organization reviews and analyzes information system audit records for indications of inappropriate or unusual activity.",
        framework=ComplianceFramework.FEDRAMP_MODERATE,
        evidence_sources=["audit_logs"],
    ),
]

_FEDRAMP_HIGH_CONTROLS: List[ComplianceControl] = [
    ComplianceControl(
        id="AC-2",
        title="Account Management",
        description="Enhanced account management with automated review and enforcement of account lifecycle policies.",
        framework=ComplianceFramework.FEDRAMP_HIGH,
        evidence_sources=["user_inventory", "audit_logs"],
    ),
    ComplianceControl(
        id="AC-3",
        title="Access Enforcement",
        description="Mandatory access controls enforced at the information system level with cryptographic mechanisms.",
        framework=ComplianceFramework.FEDRAMP_HIGH,
        evidence_sources=["role_inventory", "config_snapshot"],
    ),
    ComplianceControl(
        id="AC-6",
        title="Least Privilege",
        description="Least privilege enforced with just-in-time access provisioning and automated revocation.",
        framework=ComplianceFramework.FEDRAMP_HIGH,
        evidence_sources=["role_inventory", "user_inventory"],
    ),
    ComplianceControl(
        id="AU-2",
        title="Audit Events",
        description="Comprehensive audit event coverage with real-time alerting on security-relevant events.",
        framework=ComplianceFramework.FEDRAMP_HIGH,
        evidence_sources=["audit_logs", "config_snapshot"],
    ),
    ComplianceControl(
        id="AU-3",
        title="Content of Audit Records",
        description="Audit records include session, connection, transaction, or activity duration with full chain of custody.",
        framework=ComplianceFramework.FEDRAMP_HIGH,
        evidence_sources=["audit_logs"],
    ),
    ComplianceControl(
        id="AU-6",
        title="Audit Review",
        description="Automated mechanisms integrate audit review, analysis, and reporting with real-time alerting.",
        framework=ComplianceFramework.FEDRAMP_HIGH,
        evidence_sources=["audit_logs"],
    ),
]

_HIPAA_CONTROLS: List[ComplianceControl] = [
    ComplianceControl(
        id="164.312(a)(1)",
        title="Access Controls",
        description="Implement technical policies and procedures for electronic information systems that maintain ePHI to allow access only to those persons or software programs that have been granted access rights.",
        framework=ComplianceFramework.HIPAA,
        evidence_sources=["user_inventory", "role_inventory", "config_snapshot"],
    ),
    ComplianceControl(
        id="164.312(b)",
        title="Audit Controls",
        description="Implement hardware, software, and/or procedural mechanisms that record and examine activity in information systems that contain or use ePHI.",
        framework=ComplianceFramework.HIPAA,
        evidence_sources=["audit_logs", "config_snapshot"],
    ),
    ComplianceControl(
        id="164.312(c)(1)",
        title="Integrity",
        description="Implement policies and procedures to protect ePHI from improper alteration or destruction.",
        framework=ComplianceFramework.HIPAA,
        evidence_sources=["audit_logs", "config_snapshot"],
    ),
]

_SOC2_CONTROLS: List[ComplianceControl] = [
    ComplianceControl(
        id="CC6.1",
        title="Logical Access Controls",
        description="The entity implements logical access security software, infrastructure, and architectures over protected information assets to protect them from security events.",
        framework=ComplianceFramework.SOC2_TYPE2,
        evidence_sources=["user_inventory", "role_inventory", "config_snapshot"],
    ),
    ComplianceControl(
        id="CC6.2",
        title="New Access",
        description="Prior to issuing system credentials and granting system access, the entity registers and authorizes new internal and external users.",
        framework=ComplianceFramework.SOC2_TYPE2,
        evidence_sources=["user_inventory", "audit_logs"],
    ),
    ComplianceControl(
        id="CC6.3",
        title="Access Removal",
        description="The entity removes access to protected information assets when appropriate (e.g., user termination, role changes).",
        framework=ComplianceFramework.SOC2_TYPE2,
        evidence_sources=["user_inventory", "audit_logs"],
    ),
    ComplianceControl(
        id="CC7.2",
        title="Monitor",
        description="The entity monitors system components and the operation of those components for anomalies that are indicative of malicious acts.",
        framework=ComplianceFramework.SOC2_TYPE2,
        evidence_sources=["audit_logs", "config_snapshot"],
    ),
]

_CONTROLS_BY_FRAMEWORK: Dict[ComplianceFramework, List[ComplianceControl]] = {
    ComplianceFramework.FEDRAMP_MODERATE: _FEDRAMP_MODERATE_CONTROLS,
    ComplianceFramework.FEDRAMP_HIGH: _FEDRAMP_HIGH_CONTROLS,
    ComplianceFramework.HIPAA: _HIPAA_CONTROLS,
    ComplianceFramework.SOC2_TYPE2: _SOC2_CONTROLS,
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ComplianceService:
    """Service for generating compliance reports.

    Collects evidence from audit logs, user/role inventory, and configuration
    snapshots, then assembles structured reports for FedRAMP, HIPAA, and SOC2.
    Reports are stored in-memory (class-level) since they are ephemeral artifacts.
    """

    _reports: Dict[str, ComplianceReport] = {}

    def __init__(self) -> None:
        """Initialize compliance service."""

    # ------------------------------------------------------------------
    # Evidence collectors
    # ------------------------------------------------------------------

    def collect_user_role_evidence(self, db: Session, framework: ComplianceFramework, control_id: str) -> Dict[str, Any]:
        """Collect user and role evidence from the database.

        Queries EmailUser and UserRole tables to gather account inventory
        evidence relevant to access control and least-privilege controls.

        Args:
            db: SQLAlchemy database session
            framework: Compliance framework being assessed
            control_id: Control ID for which evidence is collected

        Returns:
            Dict containing user count, active users, admin users, role assignments
        """
        try:
            users = list(db.execute(select(EmailUser)).scalars().all())
            active_count = sum(1 for u in users if getattr(u, "is_active", False))
            admin_count = sum(1 for u in users if getattr(u, "is_admin", False))

            role_assignments = list(db.execute(select(UserRole)).scalars().all())
            active_roles = sum(1 for r in role_assignments if getattr(r, "is_active", False))

            return {
                "total_users": len(users),
                "active_users": active_count,
                "admin_users": admin_count,
                "total_role_assignments": len(role_assignments),
                "active_role_assignments": active_roles,
                "control_id": control_id,
                "framework": framework.value,
            }
        except Exception as exc:
            logger.warning("Failed to collect user/role evidence for %s: %s", control_id, exc)
            return {"error": str(exc), "control_id": control_id}

    def collect_audit_log_evidence(self, db: Session, start: datetime, end: datetime, control_id: str) -> Dict[str, Any]:
        """Collect audit log evidence for the assessment period.

        Queries the AuditTrail table to count events, check coverage,
        and surface high-risk events within the period.

        Args:
            db: SQLAlchemy database session
            start: Start of the assessment period
            end: End of the assessment period
            control_id: Control ID for which evidence is collected

        Returns:
            Dict with event counts, coverage indicators, and sample events
        """
        try:
            query = select(AuditTrail).where(AuditTrail.timestamp >= start, AuditTrail.timestamp <= end)
            entries = list(db.execute(query).scalars().all())

            success_count = sum(1 for e in entries if getattr(e, "success", True))
            failure_count = len(entries) - success_count
            review_count = sum(1 for e in entries if getattr(e, "requires_review", False))

            resource_types = list({getattr(e, "resource_type", "unknown") for e in entries})

            return {
                "total_events": len(entries),
                "success_events": success_count,
                "failure_events": failure_count,
                "review_required_events": review_count,
                "resource_types_covered": resource_types,
                "audit_enabled": settings.audit_trail_enabled,
                "control_id": control_id,
            }
        except Exception as exc:
            logger.warning("Failed to collect audit log evidence for %s: %s", control_id, exc)
            return {"error": str(exc), "control_id": control_id, "audit_enabled": getattr(settings, "audit_trail_enabled", False)}

    def collect_config_snapshot(self, control_id: str) -> Dict[str, Any]:
        """Collect relevant configuration settings as evidence.

        Reads non-sensitive settings values to demonstrate that security
        controls are configured in the system.

        Args:
            control_id: Control ID for which the snapshot is taken

        Returns:
            Dict with relevant configuration settings
        """
        return {
            "control_id": control_id,
            "auth_required": getattr(settings, "auth_required", True),
            "audit_trail_enabled": getattr(settings, "audit_trail_enabled", False),
            "require_token_expiration": getattr(settings, "require_token_expiration", True),
            "require_jti": getattr(settings, "require_jti", True),
            "require_user_in_db": getattr(settings, "require_user_in_db", False),
            "app_name": getattr(settings, "app_name", "ContextForge"),
        }

    # ------------------------------------------------------------------
    # Status determination
    # ------------------------------------------------------------------

    def _determine_status(self, control: ComplianceControl, artifacts: List[Dict[str, Any]]) -> tuple[ControlStatus, List[str], List[str]]:
        """Determine control status based on collected artifacts.

        Args:
            control: The compliance control being assessed
            artifacts: List of evidence artifacts collected

        Returns:
            Tuple of (status, findings, recommendations)
        """
        findings: List[str] = []
        recommendations: List[str] = []

        # Merge all artifact data for analysis
        merged: Dict[str, Any] = {}
        for a in artifacts:
            merged.update(a)

        # Check audit trail enablement
        audit_enabled = merged.get("audit_enabled", False)
        if "audit_logs" in control.evidence_sources and not audit_enabled:
            findings.append("Audit trail logging is not enabled.")
            recommendations.append("Enable AUDIT_TRAIL_ENABLED in configuration to satisfy audit control requirements.")

        # Check auth requirement
        auth_required = merged.get("auth_required", True)
        if "config_snapshot" in control.evidence_sources and not auth_required:
            findings.append("Authentication is not required (AUTH_REQUIRED=false).")
            recommendations.append("Set AUTH_REQUIRED=true to enforce access controls.")

        # Check token expiration
        require_expiry = merged.get("require_token_expiration", True)
        if "config_snapshot" in control.evidence_sources and not require_expiry:
            findings.append("Token expiration is not required.")
            recommendations.append("Enable REQUIRE_TOKEN_EXPIRATION for stronger session management.")

        # Check user inventory
        total_users = merged.get("total_users", 0)
        admin_users = merged.get("admin_users", 0)
        if "user_inventory" in control.evidence_sources:
            if total_users == 0:
                findings.append("No users found in the system.")
            if admin_users > 5:
                findings.append(f"High number of admin users detected: {admin_users}.")
                recommendations.append("Review and reduce the number of admin accounts to enforce least privilege.")

        # Determine status
        if not findings:
            return ControlStatus.IMPLEMENTED, findings, recommendations
        if len(findings) >= 2 or not audit_enabled:
            return ControlStatus.PARTIAL, findings, recommendations
        return ControlStatus.PARTIAL, findings, recommendations

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_report(self, db: Session, framework: ComplianceFramework, period_start: datetime, period_end: datetime) -> ComplianceReport:
        """Generate a full compliance report for the given framework and period.

        Iterates through all control definitions for the framework, collects
        evidence per control, determines status, and assembles the report.

        Args:
            db: SQLAlchemy database session
            framework: Compliance framework to assess
            period_start: Start of the assessment period (UTC)
            period_end: End of the assessment period (UTC)

        Returns:
            ComplianceReport with evidence for all controls
        """
        controls_defs = _CONTROLS_BY_FRAMEWORK.get(framework, [])
        evidence_list: List[ControlEvidence] = []

        for ctrl in controls_defs:
            artifacts: List[Dict[str, Any]] = []

            if "user_inventory" in ctrl.evidence_sources or "role_inventory" in ctrl.evidence_sources:
                artifacts.append(self.collect_user_role_evidence(db, framework, ctrl.id))
            if "audit_logs" in ctrl.evidence_sources:
                artifacts.append(self.collect_audit_log_evidence(db, period_start, period_end, ctrl.id))
            if "config_snapshot" in ctrl.evidence_sources:
                artifacts.append(self.collect_config_snapshot(ctrl.id))

            status, findings, recommendations = self._determine_status(ctrl, artifacts)

            evidence = f"Control {ctrl.id} ({ctrl.title}) assessed for period {period_start.date()} to {period_end.date()}."
            if findings:
                evidence += " Findings: " + "; ".join(findings)

            evidence_list.append(
                ControlEvidence(
                    control_id=ctrl.id,
                    status=status,
                    evidence=evidence,
                    artifacts=artifacts,
                    findings=findings,
                    recommendations=recommendations,
                )
            )

        # Build summary
        status_counts: Dict[str, int] = {s.value: 0 for s in ControlStatus}
        for ev in evidence_list:
            status_counts[ev.status.value] += 1

        summary: Dict[str, Any] = {
            "framework": framework.value,
            "total_controls": len(evidence_list),
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            **status_counts,
        }

        report = ComplianceReport(
            id=str(uuid.uuid4()),
            framework=framework,
            period_start=period_start,
            period_end=period_end,
            generated_at=datetime.now(timezone.utc),
            controls=evidence_list,
            summary=summary,
        )

        # Store in-memory
        ComplianceService._reports[report.id] = report
        logger.info("Generated compliance report %s for framework %s", report.id, framework.value)
        return report

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_json(self, report: ComplianceReport) -> str:
        """Serialise a compliance report to a JSON string.

        Args:
            report: ComplianceReport to serialise

        Returns:
            JSON string representation of the report
        """

        def _default(obj: Any) -> Any:
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, Enum):
                return obj.value
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        data = asdict(report)
        return json.dumps(data, default=_default, indent=2)

    def export_csv(self, report: ComplianceReport) -> str:
        """Serialise a compliance report to a CSV string.

        Each row corresponds to one control evidence entry.

        Args:
            report: ComplianceReport to serialise

        Returns:
            CSV string with one header row and one row per control
        """
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["report_id", "framework", "period_start", "period_end", "generated_at", "control_id", "status", "evidence", "findings", "recommendations"])

        for ctrl_ev in report.controls:
            writer.writerow(
                [
                    report.id,
                    report.framework.value,
                    report.period_start.isoformat(),
                    report.period_end.isoformat(),
                    report.generated_at.isoformat(),
                    ctrl_ev.control_id,
                    ctrl_ev.status.value,
                    ctrl_ev.evidence,
                    "; ".join(ctrl_ev.findings),
                    "; ".join(ctrl_ev.recommendations),
                ]
            )

        return output.getvalue()

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    def list_reports(self, db: Optional[Session] = None) -> List[ComplianceReport]:
        """List all stored compliance reports.

        Args:
            db: Unused; kept for interface consistency with DB-backed services

        Returns:
            List of stored ComplianceReport objects
        """
        return list(ComplianceService._reports.values())

    def get_report(self, db: Optional[Session] = None, report_id: str = "") -> Optional[ComplianceReport]:
        """Retrieve a stored compliance report by ID.

        Args:
            db: Unused; kept for interface consistency with DB-backed services
            report_id: Report UUID to look up

        Returns:
            ComplianceReport if found, None otherwise
        """
        return ComplianceService._reports.get(report_id)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_compliance_service: Optional[ComplianceService] = None


def get_compliance_service() -> ComplianceService:
    """Get or create the singleton ComplianceService instance.

    Returns:
        ComplianceService singleton
    """
    global _compliance_service  # pylint: disable=global-statement
    if _compliance_service is None:
        _compliance_service = ComplianceService()
    return _compliance_service
