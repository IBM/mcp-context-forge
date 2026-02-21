# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/compliance_report_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Compliance reporting and evidence export service.
"""

# flake8: noqa: DAR101, DAR201, DAR401
# pylint: disable=not-callable

# Standard
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Third-Party
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import AuditTrail, PermissionAuditLog, SecurityEvent

SUPPORTED_FRAMEWORKS: Tuple[str, ...] = ("soc2", "gdpr", "hipaa", "iso27001")

FRAMEWORK_DISPLAY_NAMES: Dict[str, str] = {
    "soc2": "SOC 2",
    "gdpr": "GDPR",
    "hipaa": "HIPAA",
    "iso27001": "ISO 27001",
}

SCORE_THRESHOLDS: Dict[str, float] = {
    "compliant": 85.0,
    "needs_attention": 70.0,
}

CONTROL_METADATA: Dict[str, Dict[str, str]] = {
    "access_control": {
        "display_name": "Access Control",
        "description": "Measures denied-permission ratio; fewer denied checks indicates tighter role alignment.",
        "calculation": "100 - (denied_permissions / total_permission_checks * 100)",
    },
    "least_privilege": {
        "display_name": "Least Privilege",
        "description": "Tracks denied permission checks as a proxy for over-scoped role requests.",
        "calculation": "100 - (denied_permissions / total_permission_checks * 100)",
    },
    "access_management": {
        "display_name": "Access Management",
        "description": "Evaluates access decision outcomes to detect drift from intended RBAC boundaries.",
        "calculation": "100 - (denied_permissions / total_permission_checks * 100)",
    },
    "audit_log_integrity": {
        "display_name": "Audit Log Integrity",
        "description": "Evaluates how often auditable operations are captured without failed outcomes.",
        "calculation": "100 - (failed_audit_events / total_audit_events * 100)",
    },
    "operations_monitoring": {
        "display_name": "Operations Monitoring",
        "description": "Checks whether operational events are captured consistently in audit trails.",
        "calculation": "100 - (failed_audit_events / total_audit_events * 100)",
    },
    "incident_response": {
        "display_name": "Incident Response",
        "description": "Measures unresolved security event backlog within the selected period.",
        "calculation": "100 - (unresolved_security_events / total_security_events * 100)",
    },
    "security_event_resolution": {
        "display_name": "Security Event Resolution",
        "description": "Tracks closure rate for security events that impact protected workloads.",
        "calculation": "100 - (unresolved_security_events / total_security_events * 100)",
    },
    "incident_management": {
        "display_name": "Incident Management",
        "description": "Assesses incident closure discipline over recorded security events.",
        "calculation": "100 - (unresolved_security_events / total_security_events * 100)",
    },
    "change_tracking": {
        "display_name": "Change Tracking",
        "description": "Validates that create/update/delete operations are represented in audit evidence.",
        "calculation": "100 if change events exist, otherwise 45",
    },
    "data_access_traceability": {
        "display_name": "Data Access Traceability",
        "description": "Checks for auditable read/access/export events needed for accountability workflows.",
        "calculation": "100 if data-access events exist, otherwise 50",
    },
    "security_monitoring": {
        "display_name": "Security Monitoring",
        "description": "Uses high-risk threat score rate to indicate active monitoring quality.",
        "calculation": "100 - (high_risk_security_events / total_security_events * 100)",
    },
    "retention_readiness": {
        "display_name": "Retention Readiness",
        "description": "Reflects whether non-zero log retention is configured for compliance evidence preservation.",
        "calculation": "100 if LOG_RETENTION_DAYS > 0, otherwise 50",
    },
    "phi_access_logging": {
        "display_name": "PHI Access Logging",
        "description": "Checks for confidential/restricted classification events as PHI evidence signals.",
        "calculation": "100 if confidential/restricted audit events exist, otherwise 40",
    },
    "encryption_posture": {
        "display_name": "Encryption Posture",
        "description": "Reflects whether TLS verification is enforced for downstream calls.",
        "calculation": "100 when SKIP_SSL_VERIFY=false, otherwise 35",
    },
    "continuous_improvement": {
        "display_name": "Continuous Improvement",
        "description": "Checks whether telemetry exists to support periodic control review and tuning.",
        "calculation": "100 when audit/security events exist, otherwise 40",
    },
}

EXPORT_DATASET_METADATA: Dict[str, Dict[str, Any]] = {
    "audit_logs": {
        "display_name": "Audit Logs",
        "required_signals": ("audit_trail",),
        "description": "Detailed CRUD and admin action trail from audit_trails.",
    },
    "access_control": {
        "display_name": "Access Control",
        "required_signals": ("permission_audit",),
        "description": "RBAC decision evidence from permission_audit_log.",
    },
    "security_events": {
        "display_name": "Security Events",
        "required_signals": ("security_events",),
        "description": "Security detections and resolution state from security_events.",
    },
    "compliance_summary": {
        "display_name": "Compliance Summary",
        "required_signals": (),
        "description": "Computed per-framework scoring summary for the selected period.",
    },
    "encryption_status": {
        "display_name": "Encryption Status",
        "required_signals": (),
        "description": "Point-in-time encryption and TLS posture snapshot.",
    },
    "user_activity": {
        "display_name": "User Activity",
        "required_signals": ("audit_trail", "permission_audit", "security_events"),
        "description": "Merged user timeline across audit, permission, and security sources.",
    },
}

_DEFAULT_LOOKBACK_DAYS = 30


@dataclass
class ComplianceMetrics:
    """Aggregated metrics used for compliance scoring."""

    audit_total: int = 0
    audit_success: int = 0
    audit_failed: int = 0
    audit_requires_review: int = 0
    audit_confidential_events: int = 0
    audit_change_events: int = 0
    audit_data_access_events: int = 0
    permission_total: int = 0
    permission_granted: int = 0
    permission_denied: int = 0
    security_total: int = 0
    security_unresolved: int = 0
    security_high: int = 0
    security_critical: int = 0
    security_high_risk: int = 0


class ComplianceReportService:
    """Service for compliance dashboard, framework reports, and evidence exports."""

    def normalize_frameworks(self, frameworks: Optional[Sequence[str]]) -> List[str]:
        """Normalize requested frameworks to supported values."""
        configured = settings.mcpgateway_compliance_frameworks or list(SUPPORTED_FRAMEWORKS)
        configured_set = {item for item in configured if item in SUPPORTED_FRAMEWORKS}
        configured_frameworks = [item for item in configured if item in configured_set]
        if not configured_frameworks:
            configured_frameworks = list(SUPPORTED_FRAMEWORKS)

        if not frameworks:
            return configured_frameworks

        normalized: List[str] = []
        for framework in frameworks:
            value = (framework or "").strip().lower()
            if value in configured_set and value not in normalized:
                normalized.append(value)

        return normalized or configured_frameworks

    def resolve_time_range(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> Tuple[datetime, datetime]:
        """Return a timezone-aware reporting window."""
        now = datetime.now(timezone.utc)
        resolved_end = self._ensure_utc(end_time) or now
        resolved_start = self._ensure_utc(start_time) or (resolved_end - timedelta(days=_DEFAULT_LOOKBACK_DAYS))
        if resolved_start > resolved_end:
            raise ValueError("start_time cannot be after end_time")
        return resolved_start, resolved_end

    def build_dashboard(
        self,
        db: Session,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        frameworks: Optional[Sequence[str]] = None,
        trend_days: int = 14,
    ) -> Dict[str, Any]:
        """Build compliance dashboard payload."""
        start_ts, end_ts = self.resolve_time_range(start_time, end_time)
        selected_frameworks = self.normalize_frameworks(frameworks)
        metrics = self._collect_metrics(db=db, start_time=start_ts, end_time=end_ts)
        data_sources = self._build_data_source_status(metrics)

        framework_cards = [self._build_framework_summary(name=framework, metrics=metrics) for framework in selected_frameworks]
        overall_score = round(sum(item["score"] for item in framework_cards) / len(framework_cards), 2) if framework_cards else 0.0

        return {
            "generated_at": datetime.now(timezone.utc),
            "period": {"start_time": start_ts, "end_time": end_ts},
            "overall_score": overall_score,
            "overall_status": self._status_for_score(overall_score),
            "overview": {
                "audit_events": metrics.audit_total,
                "audit_failures": metrics.audit_failed,
                "review_required": metrics.audit_requires_review,
                "permission_checks": metrics.permission_total,
                "permission_denied": metrics.permission_denied,
                "security_events": metrics.security_total,
                "security_unresolved": metrics.security_unresolved,
                "security_high_risk": metrics.security_high_risk,
            },
            "frameworks": framework_cards,
            "trend": self._build_daily_trend(db=db, start_time=start_ts, end_time=end_ts, trend_days=trend_days),
            "policy_violations": self._build_policy_violations(metrics),
            "score_model": self._build_score_model(),
            "data_sources": data_sources,
            "limitations": self._build_dashboard_limitations(data_sources=data_sources),
            "export_datasets": self._build_export_dataset_status(metrics=metrics, framework_count=len(framework_cards)),
        }

    def build_framework_report(
        self,
        framework: str,
        db: Session,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Build a detailed framework-specific report."""
        normalized_framework = (framework or "").strip().lower()
        if normalized_framework not in SUPPORTED_FRAMEWORKS:
            raise ValueError(f"Unsupported framework: {framework}")

        start_ts, end_ts = self.resolve_time_range(start_time, end_time)
        metrics = self._collect_metrics(db=db, start_time=start_ts, end_time=end_ts)
        summary = self._build_framework_summary(name=normalized_framework, metrics=metrics)
        data_sources = self._build_data_source_status(metrics)

        return {
            "generated_at": datetime.now(timezone.utc),
            "framework": normalized_framework,
            "framework_display_name": FRAMEWORK_DISPLAY_NAMES.get(normalized_framework, normalized_framework.upper()),
            "period": {"start_time": start_ts, "end_time": end_ts},
            "summary": summary,
            "evidence": {
                "audit_actions": self._audit_action_breakdown(db=db, start_time=start_ts, end_time=end_ts),
                "resource_types": self._audit_resource_breakdown(db=db, start_time=start_ts, end_time=end_ts),
                "security_severity": self._security_severity_breakdown(db=db, start_time=start_ts, end_time=end_ts),
                "denied_permissions": self._denied_permission_breakdown(db=db, start_time=start_ts, end_time=end_ts),
            },
            "recommendations": self._build_recommendations(framework=normalized_framework, metrics=metrics),
            "score_model": self._build_score_model(),
            "data_sources": data_sources,
            "limitations": self._build_dashboard_limitations(data_sources=data_sources),
        }

    def build_user_activity_timeline(
        self,
        user_identifier: str,
        db: Session,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 500,
    ) -> Dict[str, Any]:
        """Build a user activity timeline grouped by inferred session."""
        if not user_identifier:
            raise ValueError("user_identifier is required")

        start_ts, end_ts = self.resolve_time_range(start_time, end_time)
        safe_limit = max(1, min(limit, settings.mcpgateway_compliance_max_export_rows))

        audit_rows = (
            db.execute(
                select(AuditTrail)
                .where(
                    and_(
                        AuditTrail.timestamp >= start_ts,
                        AuditTrail.timestamp <= end_ts,
                        or_(AuditTrail.user_id == user_identifier, AuditTrail.user_email == user_identifier),
                    )
                )
                .order_by(desc(AuditTrail.timestamp))
                .limit(safe_limit)
            )
            .scalars()
            .all()
        )

        permission_rows = (
            db.execute(
                select(PermissionAuditLog)
                .where(and_(PermissionAuditLog.timestamp >= start_ts, PermissionAuditLog.timestamp <= end_ts, PermissionAuditLog.user_email == user_identifier))
                .order_by(desc(PermissionAuditLog.timestamp))
                .limit(safe_limit)
            )
            .scalars()
            .all()
        )

        security_rows = (
            db.execute(
                select(SecurityEvent)
                .where(
                    and_(
                        SecurityEvent.timestamp >= start_ts,
                        SecurityEvent.timestamp <= end_ts,
                        or_(SecurityEvent.user_id == user_identifier, SecurityEvent.user_email == user_identifier),
                    )
                )
                .order_by(desc(SecurityEvent.timestamp))
                .limit(safe_limit)
            )
            .scalars()
            .all()
        )

        events: List[Dict[str, Any]] = []

        for row in audit_rows:
            event_ts = self._ensure_utc(row.timestamp) or datetime.now(timezone.utc)
            events.append(
                {
                    "timestamp": event_ts,
                    "source": "audit",
                    "action": row.action,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "resource_name": row.resource_name,
                    "success": row.success,
                    "severity": None,
                    "ip_address": row.client_ip,
                    "user_agent": row.user_agent,
                    "session_id": self._session_id(event_ts, row.correlation_id, row.client_ip, row.user_agent),
                    "correlation_id": row.correlation_id,
                    "details": {"requires_review": row.requires_review, "data_classification": row.data_classification},
                }
            )

        for row in permission_rows:
            event_ts = self._ensure_utc(row.timestamp) or datetime.now(timezone.utc)
            events.append(
                {
                    "timestamp": event_ts,
                    "source": "permission",
                    "action": f"permission_check:{row.permission}",
                    "resource_type": row.resource_type or "permission",
                    "resource_id": row.resource_id,
                    "resource_name": None,
                    "success": bool(row.granted),
                    "severity": None,
                    "ip_address": row.ip_address,
                    "user_agent": row.user_agent,
                    "session_id": self._session_id(event_ts, None, row.ip_address, row.user_agent),
                    "correlation_id": None,
                    "details": {"team_id": row.team_id, "granted": row.granted},
                }
            )

        for row in security_rows:
            event_ts = self._ensure_utc(row.timestamp) or datetime.now(timezone.utc)
            events.append(
                {
                    "timestamp": event_ts,
                    "source": "security",
                    "action": row.event_type,
                    "resource_type": row.category,
                    "resource_id": None,
                    "resource_name": None,
                    "success": row.resolved,
                    "severity": row.severity,
                    "ip_address": row.client_ip,
                    "user_agent": row.user_agent,
                    "session_id": self._session_id(event_ts, row.correlation_id, row.client_ip, row.user_agent),
                    "correlation_id": row.correlation_id,
                    "details": {"threat_score": row.threat_score, "resolved": row.resolved, "description": row.description},
                }
            )

        events.sort(key=lambda item: item["timestamp"], reverse=True)
        events = events[:safe_limit]

        sessions: Dict[str, Dict[str, Any]] = {}
        for event in events:
            session_id = event["session_id"]
            session = sessions.get(session_id)
            if session is None:
                session = {
                    "session_id": session_id,
                    "start_time": event["timestamp"],
                    "end_time": event["timestamp"],
                    "event_count": 0,
                    "sources": set(),
                }
                sessions[session_id] = session

            session["event_count"] += 1
            session["sources"].add(event["source"])
            if event["timestamp"] < session["start_time"]:
                session["start_time"] = event["timestamp"]
            if event["timestamp"] > session["end_time"]:
                session["end_time"] = event["timestamp"]

        session_list = sorted(
            (
                {
                    "session_id": value["session_id"],
                    "start_time": value["start_time"],
                    "end_time": value["end_time"],
                    "event_count": value["event_count"],
                    "sources": sorted(value["sources"]),
                }
                for value in sessions.values()
            ),
            key=lambda item: item["end_time"],
            reverse=True,
        )

        return {
            "generated_at": datetime.now(timezone.utc),
            "user_identifier": user_identifier,
            "period": {"start_time": start_ts, "end_time": end_ts},
            "total_events": len(events),
            "sessions": session_list,
            "events": events,
        }

    def build_export_rows(
        self,
        dataset: str,
        db: Session,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 5000,
        user_identifier: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        success: Optional[bool] = None,
        severity: Optional[str] = None,
        granted: Optional[bool] = None,
        frameworks: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Build rows for evidence export datasets."""
        start_ts, end_ts = self.resolve_time_range(start_time, end_time)
        safe_limit = max(1, min(limit, settings.mcpgateway_compliance_max_export_rows))
        dataset_name = (dataset or "").strip().lower()

        if dataset_name == "audit_logs":
            return self._export_audit_logs(
                db=db,
                start_time=start_ts,
                end_time=end_ts,
                limit=safe_limit,
                user_identifier=user_identifier,
                action=action,
                resource_type=resource_type,
                success=success,
            )
        if dataset_name == "access_control":
            return self._export_access_control(
                db=db,
                start_time=start_ts,
                end_time=end_ts,
                limit=safe_limit,
                user_identifier=user_identifier,
                granted=granted,
            )
        if dataset_name == "security_events":
            return self._export_security_events(
                db=db,
                start_time=start_ts,
                end_time=end_ts,
                limit=safe_limit,
                user_identifier=user_identifier,
                severity=severity,
                resolved=success,
            )
        if dataset_name == "compliance_summary":
            dashboard = self.build_dashboard(db=db, start_time=start_ts, end_time=end_ts, frameworks=frameworks)
            return [
                {
                    "framework": card["framework"],
                    "framework_display_name": card["framework_display_name"],
                    "score": card["score"],
                    "status": card["status"],
                    "confidence": card.get("confidence", "unknown"),
                    "control_count": len(card["controls"]),
                    "low_scoring_control_count": len(card.get("low_scoring_controls", [])),
                    "missing_evidence_count": len(card.get("missing_evidence", [])),
                    "missing_evidence": card.get("missing_evidence", []),
                    "period_start_time": dashboard["period"]["start_time"],
                    "period_end_time": dashboard["period"]["end_time"],
                }
                for card in dashboard["frameworks"]
            ]
        if dataset_name == "encryption_status":
            return [
                {
                    "captured_at": datetime.now(timezone.utc),
                    "transport_tls_verification_enabled": not settings.skip_ssl_verify,
                    "grpc_tls_enabled_by_default": settings.mcpgateway_grpc_tls_enabled,
                    "smtp_tls_enabled": settings.smtp_use_tls,
                    "smtp_ssl_enabled": settings.smtp_use_ssl,
                    "auth_encryption_secret_is_default": settings.auth_encryption_secret.get_secret_value() == "my-test-salt",
                }
            ]
        if dataset_name == "user_activity":
            if not user_identifier:
                raise ValueError("user_identifier is required for user_activity export")
            timeline = self.build_user_activity_timeline(
                user_identifier=user_identifier,
                db=db,
                start_time=start_ts,
                end_time=end_ts,
                limit=safe_limit,
            )
            return timeline["events"]

        raise ValueError(f"Unsupported dataset: {dataset}")

    def _build_framework_summary(self, name: str, metrics: ComplianceMetrics) -> Dict[str, Any]:
        """Build a framework card with score, evidence, and remediation guidance."""
        controls = self._framework_controls(name=name, metrics=metrics)
        score = round(sum(controls.values()) / len(controls), 2) if controls else 0.0
        rounded_controls = {key: round(value, 2) for key, value in controls.items()}
        control_details = [self._build_control_detail(control=control, score=value, metrics=metrics) for control, value in rounded_controls.items()]
        missing_evidence = [item["gap"] for item in control_details if item["missing_evidence"] and item["gap"]]
        low_scoring_controls = [
            {
                "control": item["control"],
                "display_name": item["display_name"],
                "score": item["score"],
            }
            for item in control_details
            if item["score"] < SCORE_THRESHOLDS["compliant"]
        ]

        return {
            "framework": name,
            "framework_display_name": FRAMEWORK_DISPLAY_NAMES.get(name, name.upper()),
            "score": score,
            "status": self._status_for_score(score),
            "controls": rounded_controls,
            "control_details": control_details,
            "low_scoring_controls": low_scoring_controls,
            "missing_evidence": missing_evidence,
            "score_explanation": "Framework score is the arithmetic mean of control scores (0-100 scale).",
            "confidence": self._score_confidence(control_details),
            "recommended_next_steps": self._framework_next_steps(control_details),
        }

    def _framework_controls(self, name: str, metrics: ComplianceMetrics) -> Dict[str, float]:
        """Return control scores for the requested framework."""
        access_score = self._inverse_rate_score(
            numerator=metrics.permission_denied,
            denominator=metrics.permission_total,
            no_data_score=50.0,
        )
        audit_integrity_score = self._inverse_rate_score(
            numerator=metrics.audit_failed,
            denominator=metrics.audit_total,
            no_data_score=50.0,
        )
        incident_resolution_score = self._inverse_rate_score(
            numerator=metrics.security_unresolved,
            denominator=metrics.security_total,
            no_data_score=50.0,
        )
        monitoring_score = self._inverse_rate_score(
            numerator=metrics.security_high_risk,
            denominator=metrics.security_total,
            no_data_score=50.0,
        )

        if name == "soc2":
            return {
                "access_control": access_score,
                "audit_log_integrity": audit_integrity_score,
                "incident_response": incident_resolution_score,
                "change_tracking": 100.0 if metrics.audit_change_events > 0 else 45.0,
            }
        if name == "gdpr":
            return {
                "data_access_traceability": 100.0 if metrics.audit_data_access_events > 0 else 50.0,
                "least_privilege": access_score,
                "security_monitoring": monitoring_score,
                "retention_readiness": 100.0 if settings.log_retention_days > 0 else 50.0,
            }
        if name == "hipaa":
            return {
                "phi_access_logging": 100.0 if metrics.audit_confidential_events > 0 else 40.0,
                "access_control": access_score,
                "security_event_resolution": incident_resolution_score,
                "encryption_posture": 100.0 if not settings.skip_ssl_verify else 35.0,
            }
        if name == "iso27001":
            return {
                "access_management": access_score,
                "operations_monitoring": audit_integrity_score,
                "incident_management": incident_resolution_score,
                "continuous_improvement": 100.0 if (metrics.audit_total + metrics.security_total) > 0 else 40.0,
            }
        return {}

    def _build_control_detail(self, control: str, score: float, metrics: ComplianceMetrics) -> Dict[str, Any]:
        """Build a normalized control detail record for UI/report rendering."""
        metadata = CONTROL_METADATA.get(control, {})
        evidence, missing_evidence, gap = self._control_signal(control=control, metrics=metrics)
        return {
            "control": control,
            "display_name": metadata.get("display_name", control.replace("_", " ").title()),
            "score": round(score, 2),
            "description": metadata.get("description", "Compliance control score."),
            "calculation": metadata.get("calculation", "Derived from telemetry evidence."),
            "evidence": evidence,
            "missing_evidence": missing_evidence,
            "gap": gap,
        }

    def _control_signal(self, control: str, metrics: ComplianceMetrics) -> Tuple[str, bool, Optional[str]]:
        """Map a control to evidence text, missing-signal flag, and remediation gap."""
        access_controls = {"access_control", "least_privilege", "access_management"}
        audit_controls = {"audit_log_integrity", "operations_monitoring"}
        incident_controls = {"incident_response", "security_event_resolution", "incident_management"}

        if control in access_controls:
            evidence = f"{metrics.permission_denied} denied of {metrics.permission_total} permission checks"
            missing = metrics.permission_total == 0
            gap = (
                "No permission audit evidence in range. Enable PERMISSION_AUDIT_ENABLED=true."
                if missing
                else (f"{metrics.permission_denied} denied checks should be reviewed for role/scope drift." if metrics.permission_denied > 0 else None)
            )
            return evidence, missing, gap

        if control in audit_controls:
            evidence = f"{metrics.audit_failed} failed of {metrics.audit_total} audit events"
            missing = metrics.audit_total == 0
            gap = (
                "No audit trail evidence in range. Enable AUDIT_TRAIL_ENABLED=true."
                if missing
                else (f"{metrics.audit_failed} failed audit events need remediation." if metrics.audit_failed > 0 else None)
            )
            return evidence, missing, gap

        if control in incident_controls:
            evidence = f"{metrics.security_unresolved} unresolved of {metrics.security_total} security events"
            missing = metrics.security_total == 0
            gap = (
                "No security event evidence in range. Enable SECURITY_LOGGING_ENABLED=true."
                if missing
                else (f"{metrics.security_unresolved} security events remain unresolved." if metrics.security_unresolved > 0 else None)
            )
            return evidence, missing, gap

        if control == "change_tracking":
            evidence = f"{metrics.audit_change_events} create/update/delete events captured"
            missing = metrics.audit_change_events == 0
            gap = "No create/update/delete audit events observed. Verify change operations are logged." if missing else None
            return evidence, missing, gap

        if control == "data_access_traceability":
            evidence = f"{metrics.audit_data_access_events} read/access/export events captured"
            missing = metrics.audit_data_access_events == 0
            gap = "No data-access audit events observed. Verify read/export operations are logged." if missing else None
            return evidence, missing, gap

        if control == "security_monitoring":
            evidence = f"{metrics.security_high_risk} high-risk events of {metrics.security_total} security events"
            missing = metrics.security_total == 0
            gap = (
                "No security events available for monitoring quality checks."
                if missing
                else (f"{metrics.security_high_risk} high-risk events require triage and closure." if metrics.security_high_risk > 0 else None)
            )
            return evidence, missing, gap

        if control == "retention_readiness":
            evidence = f"log_retention_days={settings.log_retention_days}"
            missing = settings.log_retention_days <= 0
            gap = "Set LOG_RETENTION_DAYS to a positive value for retention evidence." if missing else None
            return evidence, missing, gap

        if control == "phi_access_logging":
            evidence = f"{metrics.audit_confidential_events} confidential/restricted audit events"
            missing = metrics.audit_confidential_events == 0
            gap = "No confidential/restricted audit events observed. Ensure PHI resources are classified and accessed through auditable flows." if missing else None
            return evidence, missing, gap

        if control == "encryption_posture":
            evidence = f"skip_ssl_verify={settings.skip_ssl_verify}"
            missing = bool(settings.skip_ssl_verify)
            gap = "TLS verification is disabled (SKIP_SSL_VERIFY=true)." if missing else None
            return evidence, missing, gap

        if control == "continuous_improvement":
            total_events = metrics.audit_total + metrics.security_total
            evidence = f"{total_events} total audit/security events"
            missing = total_events == 0
            gap = "No audit/security telemetry captured; continuous improvement loops cannot be evidenced." if missing else None
            return evidence, missing, gap

        return "No evidence details available", False, None

    @staticmethod
    def _framework_next_steps(control_details: Sequence[Dict[str, Any]]) -> List[str]:
        """Derive de-duplicated remediation steps from control gaps."""
        steps: List[str] = []
        for item in control_details:
            gap = item.get("gap")
            if gap and gap not in steps:
                steps.append(str(gap))
        return steps[:5]

    @staticmethod
    def _score_confidence(control_details: Sequence[Dict[str, Any]]) -> str:
        """Estimate confidence level based on missing-evidence density."""
        if not control_details:
            return "low"
        missing_count = sum(1 for item in control_details if item.get("missing_evidence"))
        if missing_count == 0:
            return "high"
        if missing_count <= max(1, len(control_details) // 2):
            return "medium"
        return "low"

    @staticmethod
    def _build_score_model() -> Dict[str, Any]:
        """Return metadata describing score scale, method, and status thresholds."""
        return {
            "scale": "0-100",
            "method": "Each framework score is an arithmetic mean of control scores.",
            "status_thresholds": {
                "compliant": f">= {int(SCORE_THRESHOLDS['compliant'])}",
                "needs_attention": f">= {int(SCORE_THRESHOLDS['needs_attention'])} and < {int(SCORE_THRESHOLDS['compliant'])}",
                "at_risk": f"< {int(SCORE_THRESHOLDS['needs_attention'])}",
            },
        }

    def _build_data_source_status(self, metrics: ComplianceMetrics) -> List[Dict[str, Any]]:
        """Return telemetry source readiness and event volume status."""
        return [
            {
                "source": "audit_trail",
                "display_name": "Audit Trail",
                "enabled": bool(settings.audit_trail_enabled),
                "event_count": metrics.audit_total,
                "description": "Backs audit-focused controls and audit_logs exports.",
            },
            {
                "source": "permission_audit",
                "display_name": "Permission Audit",
                "enabled": bool(settings.permission_audit_enabled),
                "event_count": metrics.permission_total,
                "description": "Backs access-control controls and access_control exports.",
            },
            {
                "source": "security_events",
                "display_name": "Security Events",
                "enabled": bool(settings.security_logging_enabled),
                "event_count": metrics.security_total,
                "description": "Backs incident controls and security_events exports.",
            },
        ]

    @staticmethod
    def _build_dashboard_limitations(data_sources: Sequence[Dict[str, Any]]) -> List[str]:
        """Summarize known dashboard limitations from disabled or empty sources."""
        limitations: List[str] = []
        for item in data_sources:
            if not item.get("enabled"):
                limitations.append(f"{item.get('display_name', item.get('source'))} capture is disabled.")
            elif int(item.get("event_count", 0)) == 0:
                limitations.append(f"No {item.get('display_name', item.get('source'))} events were captured in the selected window.")
        return limitations

    @staticmethod
    def _build_export_dataset_status(metrics: ComplianceMetrics, framework_count: int) -> List[Dict[str, Any]]:
        """Return dataset metadata with estimated row counts for export UX."""
        estimated_rows = {
            "audit_logs": metrics.audit_total,
            "access_control": metrics.permission_total,
            "security_events": metrics.security_total,
            "compliance_summary": framework_count,
            "encryption_status": 1,
            "user_activity": None,
        }
        return [
            {
                "dataset": dataset,
                "display_name": meta["display_name"],
                "description": meta["description"],
                "required_signals": list(meta["required_signals"]),
                "estimated_rows": estimated_rows.get(dataset),
            }
            for dataset, meta in EXPORT_DATASET_METADATA.items()
        ]

    @staticmethod
    def _status_for_score(score: float) -> str:
        """Map numeric score to compliance status bucket."""
        if score >= SCORE_THRESHOLDS["compliant"]:
            return "compliant"
        if score >= SCORE_THRESHOLDS["needs_attention"]:
            return "needs_attention"
        return "at_risk"

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        """Safely compute a ratio with zero-denominator protection."""
        if denominator <= 0:
            return 0.0
        return numerator / denominator

    @classmethod
    def _inverse_rate_score(
        cls,
        numerator: int,
        denominator: int,
        no_data_score: float = 50.0,
    ) -> float:
        """Convert a bad-event ratio into a 0-100 score where lower ratio is better."""
        if denominator <= 0:
            return no_data_score
        return 100.0 - (cls._ratio(numerator, denominator) * 100.0)

    @staticmethod
    def _ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
        """Normalize datetime values to timezone-aware UTC."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _count(db: Session, stmt) -> int:
        """Execute a count/select scalar statement and normalize to int."""
        return int(db.execute(stmt).scalar() or 0)

    def _collect_metrics(self, db: Session, start_time: datetime, end_time: datetime) -> ComplianceMetrics:
        """Aggregate audit, permission, and security metrics for a reporting window."""
        audit_window = and_(AuditTrail.timestamp >= start_time, AuditTrail.timestamp <= end_time)
        permission_window = and_(PermissionAuditLog.timestamp >= start_time, PermissionAuditLog.timestamp <= end_time)
        security_window = and_(SecurityEvent.timestamp >= start_time, SecurityEvent.timestamp <= end_time)

        return ComplianceMetrics(
            audit_total=self._count(db, select(func.count(AuditTrail.id)).where(audit_window)),
            audit_success=self._count(db, select(func.count(AuditTrail.id)).where(and_(audit_window, AuditTrail.success.is_(True)))),
            audit_failed=self._count(db, select(func.count(AuditTrail.id)).where(and_(audit_window, AuditTrail.success.is_(False)))),
            audit_requires_review=self._count(db, select(func.count(AuditTrail.id)).where(and_(audit_window, AuditTrail.requires_review.is_(True)))),
            audit_confidential_events=self._count(
                db,
                select(func.count(AuditTrail.id)).where(
                    and_(
                        audit_window,
                        AuditTrail.data_classification.in_(["confidential", "restricted"]),
                    )
                ),
            ),
            audit_change_events=self._count(
                db,
                select(func.count(AuditTrail.id)).where(
                    and_(
                        audit_window,
                        func.lower(AuditTrail.action).in_(["create", "update", "delete"]),
                    )
                ),
            ),
            audit_data_access_events=self._count(
                db,
                select(func.count(AuditTrail.id)).where(
                    and_(
                        audit_window,
                        func.lower(AuditTrail.action).in_(["read", "access", "export"]),
                    )
                ),
            ),
            permission_total=self._count(db, select(func.count(PermissionAuditLog.id)).where(permission_window)),
            permission_granted=self._count(db, select(func.count(PermissionAuditLog.id)).where(and_(permission_window, PermissionAuditLog.granted.is_(True)))),
            permission_denied=self._count(db, select(func.count(PermissionAuditLog.id)).where(and_(permission_window, PermissionAuditLog.granted.is_(False)))),
            security_total=self._count(db, select(func.count(SecurityEvent.id)).where(security_window)),
            security_unresolved=self._count(db, select(func.count(SecurityEvent.id)).where(and_(security_window, SecurityEvent.resolved.is_(False)))),
            security_high=self._count(db, select(func.count(SecurityEvent.id)).where(and_(security_window, SecurityEvent.severity.in_(["HIGH", "CRITICAL"])))),
            security_critical=self._count(db, select(func.count(SecurityEvent.id)).where(and_(security_window, SecurityEvent.severity == "CRITICAL"))),
            security_high_risk=self._count(
                db,
                select(func.count(SecurityEvent.id)).where(and_(security_window, SecurityEvent.threat_score >= settings.security_threat_score_alert)),
            ),
        )

    def _build_daily_trend(self, db: Session, start_time: datetime, end_time: datetime, trend_days: int) -> List[Dict[str, Any]]:
        """Build daily audit/permission/security trend data for charts."""
        if trend_days <= 0:
            return []

        end_day = end_time.astimezone(timezone.utc).date()
        start_day = max(start_time.astimezone(timezone.utc).date(), end_day - timedelta(days=trend_days - 1))
        trend_start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)

        audit_rows = db.execute(
            select(func.date(AuditTrail.timestamp).label("day"), func.count(AuditTrail.id).label("count"))
            .where(and_(AuditTrail.timestamp >= trend_start, AuditTrail.timestamp <= end_time))
            .group_by(func.date(AuditTrail.timestamp))
        ).all()
        permission_rows = db.execute(
            select(func.date(PermissionAuditLog.timestamp).label("day"), func.count(PermissionAuditLog.id).label("count"))
            .where(
                and_(
                    PermissionAuditLog.timestamp >= trend_start,
                    PermissionAuditLog.timestamp <= end_time,
                    PermissionAuditLog.granted.is_(False),
                )
            )
            .group_by(func.date(PermissionAuditLog.timestamp))
        ).all()
        security_rows = db.execute(
            select(func.date(SecurityEvent.timestamp).label("day"), func.count(SecurityEvent.id).label("count"))
            .where(and_(SecurityEvent.timestamp >= trend_start, SecurityEvent.timestamp <= end_time))
            .group_by(func.date(SecurityEvent.timestamp))
        ).all()

        audit_map = {str(row.day): int(row.count) for row in audit_rows}
        permission_map = {str(row.day): int(row.count) for row in permission_rows}
        security_map = {str(row.day): int(row.count) for row in security_rows}

        trend: List[Dict[str, Any]] = []
        current_day: date = start_day
        while current_day <= end_day:
            day_key = current_day.isoformat()
            trend.append(
                {
                    "date": day_key,
                    "audit_events": audit_map.get(day_key, 0),
                    "permission_denied": permission_map.get(day_key, 0),
                    "security_events": security_map.get(day_key, 0),
                }
            )
            current_day = current_day + timedelta(days=1)

        return trend

    @staticmethod
    def _session_id(
        timestamp: datetime,
        correlation_id: Optional[str],
        ip_address: Optional[str],
        user_agent: Optional[str],
    ) -> str:
        """Derive a stable synthetic session identifier for timeline grouping."""
        if correlation_id:
            return f"corr:{correlation_id}"

        fingerprint = hashlib.sha256(f"{ip_address or '-'}|{user_agent or '-'}".encode("utf-8")).hexdigest()[:10]
        hour_bucket = timestamp.astimezone(timezone.utc).strftime("%Y%m%d%H")
        return f"session:{hour_bucket}:{fingerprint}"

    def _audit_action_breakdown(self, db: Session, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
        """Return top audit actions with counts for framework evidence."""
        rows = db.execute(
            select(func.lower(AuditTrail.action).label("action"), func.count(AuditTrail.id).label("count"))
            .where(and_(AuditTrail.timestamp >= start_time, AuditTrail.timestamp <= end_time))
            .group_by(func.lower(AuditTrail.action))
            .order_by(func.count(AuditTrail.id).desc())
            .limit(20)
        ).all()
        return [{"action": row.action, "count": int(row.count)} for row in rows]

    def _audit_resource_breakdown(self, db: Session, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
        """Return top audit resource types with counts for evidence summaries."""
        rows = db.execute(
            select(AuditTrail.resource_type.label("resource_type"), func.count(AuditTrail.id).label("count"))
            .where(and_(AuditTrail.timestamp >= start_time, AuditTrail.timestamp <= end_time))
            .group_by(AuditTrail.resource_type)
            .order_by(func.count(AuditTrail.id).desc())
            .limit(20)
        ).all()
        return [{"resource_type": row.resource_type, "count": int(row.count)} for row in rows]

    def _security_severity_breakdown(self, db: Session, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
        """Return security event counts grouped by severity."""
        rows = db.execute(
            select(SecurityEvent.severity.label("severity"), func.count(SecurityEvent.id).label("count"))
            .where(and_(SecurityEvent.timestamp >= start_time, SecurityEvent.timestamp <= end_time))
            .group_by(SecurityEvent.severity)
            .order_by(func.count(SecurityEvent.id).desc())
        ).all()
        return [{"severity": row.severity, "count": int(row.count)} for row in rows]

    def _denied_permission_breakdown(self, db: Session, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
        """Return denied permission counts grouped by permission key."""
        rows = db.execute(
            select(PermissionAuditLog.permission.label("permission"), func.count(PermissionAuditLog.id).label("count"))
            .where(
                and_(
                    PermissionAuditLog.timestamp >= start_time,
                    PermissionAuditLog.timestamp <= end_time,
                    PermissionAuditLog.granted.is_(False),
                )
            )
            .group_by(PermissionAuditLog.permission)
            .order_by(func.count(PermissionAuditLog.id).desc())
            .limit(20)
        ).all()
        return [{"permission": row.permission, "count": int(row.count)} for row in rows]

    @staticmethod
    def _build_policy_violations(metrics: ComplianceMetrics) -> List[Dict[str, Any]]:
        """Build policy violation summaries from aggregate metrics."""
        violations: List[Dict[str, Any]] = []

        if metrics.security_unresolved > 0:
            violations.append(
                {
                    "policy_id": "security.unresolved_events",
                    "severity": "high",
                    "message": f"{metrics.security_unresolved} security events remain unresolved",
                }
            )
        if metrics.permission_denied > 0:
            violations.append(
                {
                    "policy_id": "access.denied_checks",
                    "severity": "medium",
                    "message": f"{metrics.permission_denied} permission checks were denied",
                }
            )
        if metrics.audit_requires_review > 0:
            violations.append(
                {
                    "policy_id": "audit.review_required",
                    "severity": "medium",
                    "message": f"{metrics.audit_requires_review} audit events require manual review",
                }
            )

        return violations

    @staticmethod
    def _build_recommendations(framework: str, metrics: ComplianceMetrics) -> List[str]:
        """Build framework-aware remediation recommendations."""
        recommendations: List[str] = []
        if metrics.security_unresolved > 0:
            recommendations.append("Resolve outstanding security events and document remediation actions.")
        if metrics.permission_denied > 0:
            recommendations.append("Review denied permission checks to validate least-privilege policy coverage.")
        if metrics.audit_requires_review > 0:
            recommendations.append("Complete manual review workflow for flagged audit events.")
        if framework == "hipaa" and metrics.audit_confidential_events == 0:
            recommendations.append("Tag PHI-related resources with confidential/restricted classification for explicit audit evidence.")
        if framework == "gdpr" and metrics.audit_data_access_events == 0:
            recommendations.append("Increase data-access event logging coverage for GDPR accountability evidence.")
        return recommendations

    def _export_audit_logs(
        self,
        db: Session,
        start_time: datetime,
        end_time: datetime,
        limit: int,
        user_identifier: Optional[str],
        action: Optional[str],
        resource_type: Optional[str],
        success: Optional[bool],
    ) -> List[Dict[str, Any]]:
        """Export normalized audit trail rows with optional filters."""
        conditions = [AuditTrail.timestamp >= start_time, AuditTrail.timestamp <= end_time]
        if user_identifier:
            conditions.append(or_(AuditTrail.user_id == user_identifier, AuditTrail.user_email == user_identifier))
        if action:
            conditions.append(func.lower(AuditTrail.action) == action.lower())
        if resource_type:
            conditions.append(AuditTrail.resource_type == resource_type)
        if success is not None:
            conditions.append(AuditTrail.success.is_(success))

        rows = db.execute(select(AuditTrail).where(and_(*conditions)).order_by(desc(AuditTrail.timestamp)).limit(limit)).scalars().all()

        return [
            {
                "timestamp": row.timestamp,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "resource_name": row.resource_name,
                "user_id": row.user_id,
                "user_email": row.user_email,
                "team_id": row.team_id,
                "client_ip": row.client_ip,
                "request_method": row.request_method,
                "request_path": row.request_path,
                "success": row.success,
                "requires_review": row.requires_review,
                "data_classification": row.data_classification,
                "correlation_id": row.correlation_id,
            }
            for row in rows
        ]

    def _export_access_control(
        self,
        db: Session,
        start_time: datetime,
        end_time: datetime,
        limit: int,
        user_identifier: Optional[str],
        granted: Optional[bool],
    ) -> List[Dict[str, Any]]:
        """Export permission-audit evidence rows with optional filters."""
        conditions = [PermissionAuditLog.timestamp >= start_time, PermissionAuditLog.timestamp <= end_time]
        if user_identifier:
            conditions.append(PermissionAuditLog.user_email == user_identifier)
        if granted is not None:
            conditions.append(PermissionAuditLog.granted.is_(granted))

        rows = db.execute(select(PermissionAuditLog).where(and_(*conditions)).order_by(desc(PermissionAuditLog.timestamp)).limit(limit)).scalars().all()

        return [
            {
                "timestamp": row.timestamp,
                "user_email": row.user_email,
                "permission": row.permission,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "team_id": row.team_id,
                "granted": row.granted,
                "ip_address": row.ip_address,
                "user_agent": row.user_agent,
            }
            for row in rows
        ]

    def _export_security_events(
        self,
        db: Session,
        start_time: datetime,
        end_time: datetime,
        limit: int,
        user_identifier: Optional[str],
        severity: Optional[str],
        resolved: Optional[bool],
    ) -> List[Dict[str, Any]]:
        """Export security-event evidence rows with optional filters."""
        conditions = [SecurityEvent.timestamp >= start_time, SecurityEvent.timestamp <= end_time]
        if user_identifier:
            conditions.append(or_(SecurityEvent.user_id == user_identifier, SecurityEvent.user_email == user_identifier))
        if severity:
            conditions.append(SecurityEvent.severity == severity.upper())
        if resolved is not None:
            conditions.append(SecurityEvent.resolved.is_(resolved))

        rows = db.execute(select(SecurityEvent).where(and_(*conditions)).order_by(desc(SecurityEvent.timestamp)).limit(limit)).scalars().all()

        return [
            {
                "timestamp": row.timestamp,
                "event_type": row.event_type,
                "severity": row.severity,
                "category": row.category,
                "description": row.description,
                "user_id": row.user_id,
                "user_email": row.user_email,
                "client_ip": row.client_ip,
                "resolved": row.resolved,
                "threat_score": row.threat_score,
                "correlation_id": row.correlation_id,
            }
            for row in rows
        ]


_compliance_report_service: Optional[ComplianceReportService] = None


def get_compliance_report_service() -> ComplianceReportService:
    """Get singleton compliance report service."""
    global _compliance_report_service  # pylint: disable=global-statement
    if _compliance_report_service is None:
        _compliance_report_service = ComplianceReportService()
    return _compliance_report_service
