# Compliance Reporting

MCP Gateway includes an optional compliance reporting module that builds evidence from:

- Audit trail entries (`audit_trails`)
- Permission audit checks (`permission_audit_log`)
- Security events (`security_events`)

When enabled, the Admin UI exposes a dedicated **Compliance** section with:

- Compliance dashboard summaries
- Framework-level scoring views
- User activity timelines
- Evidence export controls (JSON/CSV)

## Feature Flag

Compliance reporting is disabled by default.

```bash
MCPGATEWAY_COMPLIANCE_ENABLED=true
```

If disabled, `/api/compliance/*` endpoints are not registered and compliance controls are hidden in the Admin UI.

## Configuration

```bash
# Enable/disable compliance module
MCPGATEWAY_COMPLIANCE_ENABLED=false

# Frameworks used for scoring/reporting (CSV or JSON array)
MCPGATEWAY_COMPLIANCE_FRAMEWORKS=soc2,gdpr,hipaa,iso27001

# Scheduling hint for recurring reports
MCPGATEWAY_COMPLIANCE_REPORT_SCHEDULE=disabled

# Hard cap for export size
MCPGATEWAY_COMPLIANCE_MAX_EXPORT_ROWS=5000
```

Supported framework identifiers:

- `soc2`
- `gdpr`
- `hipaa`
- `iso27001`

## Telemetry Prerequisites

Compliance scoring and export quality depend on telemetry capture settings:

- `AUDIT_TRAIL_ENABLED=true` for rich `audit_logs` evidence
- `PERMISSION_AUDIT_ENABLED=true` for `access_control` evidence
- `SECURITY_LOGGING_ENABLED=true` for `security_events` evidence

If these are disabled or have no events in the selected period, dashboard confidence drops and raw evidence exports can be empty.

## Score Model

All control and framework scores are on a `0-100` scale.

- **Framework score**: arithmetic mean of its control scores
- **Compliant**: `>= 85`
- **Needs Attention**: `>= 70 and < 85`
- **At Risk**: `< 70`

The dashboard now surfaces:

- Per-control descriptions and evidence signals
- Missing evidence indicators
- Confidence level (`high`, `medium`, `low`) based on telemetry coverage
- Limitations when required telemetry sources are disabled or empty

## Framework Control Mapping

| Framework | Control Signals (examples) |
|-----------|----------------------------|
| SOC 2 | Access control, audit log integrity, incident response, change tracking |
| GDPR | Data-access traceability, least privilege, security monitoring, retention readiness |
| HIPAA | PHI access logging, access control, security event resolution, encryption posture |
| ISO 27001 | Access management, operations monitoring, incident management, continuous improvement |

## API Endpoints

All compliance routes require `admin.security_audit` permission.

- `GET /api/compliance/frameworks`
- `GET /api/compliance/dashboard`
- `GET /api/compliance/frameworks/{framework}`
- `GET /api/compliance/user-activity/{user_identifier}`
- `GET /api/compliance/evidence/export`

## Evidence Export Datasets

Use `dataset` in `/api/compliance/evidence/export`:

- `audit_logs`
- `access_control`
- `security_events`
- `compliance_summary`
- `encryption_status`
- `user_activity` (requires `user_identifier`)

Use `format=json` or `format=csv`.

Dataset prerequisites:

- `audit_logs`: requires audit trail telemetry to be enabled and populated
- `access_control`: requires permission audit telemetry to be enabled and populated
- `security_events`: requires security event logging to be enabled and populated
- `compliance_summary`: computed scores; usually available when compliance is enabled
- `encryption_status`: configuration snapshot; always available
- `user_activity`: requires `user_identifier` plus matching events

## Notes

- Compliance scoring is heuristic and intended for operational visibility, not as a legal attestation by itself.
- Export limits are always clamped by `MCPGATEWAY_COMPLIANCE_MAX_EXPORT_ROWS`.
- Scheduling is currently a configuration hint (`MCPGATEWAY_COMPLIANCE_REPORT_SCHEDULE`) for external job orchestration.

## Troubleshooting Empty Exports

If an export returns no rows:

1. Expand the date range (default lookback is recent activity only).
2. Verify telemetry toggles (`AUDIT_TRAIL_ENABLED`, `PERMISSION_AUDIT_ENABLED`, `SECURITY_LOGGING_ENABLED`).
3. Remove restrictive filters (`framework`, `user_identifier`, `severity`, etc.).
4. For `user_activity`, provide a concrete user email/ID and ensure recent activity exists.
