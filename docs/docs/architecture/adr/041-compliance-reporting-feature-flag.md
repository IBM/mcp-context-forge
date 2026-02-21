# ADR-0041: Feature-Flagged Compliance Reporting Module

- *Status:* Accepted
- *Date:* 2026-02-18
- *Deciders:* Mihai Criveti

## Context

Compliance reporting requirements (audit viewer enhancements, compliance dashboard, evidence exports) were introduced as overlapping epics. The gateway already had foundational audit/security logging, but no dedicated compliance API surface and no configuration guardrail to enable the feature selectively by environment.

Key requirements:

- Enable compliance workflows without forcing all installations to expose them.
- Provide consistent configuration across runtime, `.env`, Docker Compose, and Helm.
- Keep compliance scope explicit for operators (framework set, export limits, schedule hint).
- Provide operator-facing explainability for score interpretation and evidence gaps.

## Decision

Introduce a dedicated compliance module controlled by a feature flag:

- `MCPGATEWAY_COMPLIANCE_ENABLED` (default: `false`)
- `MCPGATEWAY_COMPLIANCE_FRAMEWORKS` (default: `soc2,gdpr,hipaa,iso27001`)
- `MCPGATEWAY_COMPLIANCE_REPORT_SCHEDULE` (default: `disabled`)
- `MCPGATEWAY_COMPLIANCE_MAX_EXPORT_ROWS` (default: `5000`)

Behavior:

- When disabled, compliance routes (`/api/compliance/*`) are not registered.
- Admin UI compliance controls are hidden when the feature is disabled.
- Evidence export size is clamped by `MCPGATEWAY_COMPLIANCE_MAX_EXPORT_ROWS`.
- Compliance framework scoring uses only configured framework identifiers.
- Dashboard responses include score model metadata, control-level evidence, and missing-signal limitations.
- Compliance UI export flow should guide users when raw datasets are empty due filters or disabled telemetry sources.

## Consequences

### Positive

- Safer rollout: feature can be enabled per environment.
- Predictable operations: one set of flags across local, Compose, and Helm deployments.
- Better guardrails: large compliance exports are bounded by config.

### Negative

- Additional config surface for operators to manage.
- `MCPGATEWAY_COMPLIANCE_REPORT_SCHEDULE` is currently a schedule hint, not a built-in scheduler.

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| Always-on compliance endpoints | Increases default attack surface and operational cost for deployments that do not need compliance features. |
| Reuse only existing `/api/logs/*` routes | Did not provide framework reporting/dashboard semantics or evidence dataset exports. |
| Hardcoded framework list with no config | Prevented operator control over which frameworks appear in compliance posture outputs. |

## Related

- [Compliance Reporting](../../manage/compliance-reporting.md)
- [Configuration Reference](../../manage/configuration.md#compliance-reporting)
