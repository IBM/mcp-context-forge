# Issue #2225 Implementation: Policy Audit Trail and Decision Logging

## Overview

Implementation of audit logging for IBM MCP Context Forge policy decisions, aligned with GitHub issue #2225:
https://github.com/IBM/mcp-context-forge/issues/2225

## Implementation Status

Requirements from the GitHub issue have been implemented and tested.

### User Stories Implemented

**US-1: Security Analyst - Query Access Decisions**
- Full query API with filtering by subject, resource, decision, time range
- REST API endpoints for querying (GET and POST)

**US-2: Security Team - Export to SIEM**
- Splunk HEC integration
- Elasticsearch integration
- Generic webhook support
- Batch processing for performance

## Deliverables

### Core Components

| File | Purpose |
|------|---------|
| `mcpgateway/services/policy_decision_service.py` | Decision logging service (SQLAlchemy) |
| `mcpgateway/services/siem_export_service.py` | SIEM exporters and batching |
| `mcpgateway/routers/policy_decisions_api.py` | REST API endpoints |
| `mcpgateway/common/policy_audit.py` | PolicyDecision ORM model |
| `mcpgateway/alembic/versions/373c8cc5e13a_add_policy_decisions_migration.py` | Database migration |

## Features

### Decision Logging
- Comprehensive audit records with full context
- Subject details (email, roles, teams, clearance)
- Resource details (type, server, classification)
- Context (IP, user agent, MFA status, time)
- Policy evaluation details with explanations
- Request correlation IDs
- Gateway node tracking
- Duration metrics

### Database Storage
- SQLAlchemy ORM with SQLite/PostgreSQL support
- Indexed queries for performance
- Time-range queries
- Multi-field filtering
- Pagination support
- Statistics calculation

### SIEM Integration
- Splunk HTTP Event Collector
  - Proper time formatting
  - Structured event data
  - Batch support
- Elasticsearch
  - @timestamp field
  - Bulk API support
  - Document indexing
- Generic Webhook
  - JSON payload
  - Configurable endpoint
  - Batch support

### REST API
- Query decisions (GET)
- Query decisions (POST for complex queries)
- Get statistics
- OpenAPI documentation
- Health check endpoint (unauthenticated for monitoring)

### Configuration
- Enable/disable logging per decision type (`policy_audit_log_allowed`, `policy_audit_log_denied`)
- SIEM configuration
- Batch processing settings

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              Policy Engine (Cedar/OPA/MAC/RBAC)             │
│  - Evaluates access requests                                │
│  - Makes allow/deny decisions                               │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  v
┌─────────────────────────────────────────────────────────────┐
│     PolicyDecisionService (policy_decision_service.py)      │
│  - Receives decision events                                 │
│  - Enriches with context                                    │
│  - Routes to storage and SIEM                               │
└──────────────┬─────────────┬──────────────┬────────────────┘
               │             │              │
       ┌───────v──────┐ ┌───v─────┐ ┌─────v──────┐
       │   Database   │ │  SIEM   │ │  REST API  │
       │  (SQLAlchemy │ │ Batch   │ │  (FastAPI) │
       │  ORM)        │ │Processor│ │            │
       └──────────────┘ └────┬────┘ └────────────┘
                             │
                    ┌────────┴────────┐
                    v                 v
          ┌──────────────┐  ┌──────────────┐
          │   Splunk     │  │Elasticsearch │
          │     HEC      │  │   / Webhook  │
          └──────────────┘  └──────────────┘
```

## Schema (from Issue #2225)

```json
{
  "id": "decision-uuid",
  "timestamp": "2024-01-15T10:30:00Z",
  "request_id": "req-12345",
  "gateway_node": "gateway-1",

  "subject": {
    "type": "user",
    "id": "user-uuid",
    "email": "user@example.com",
    "roles": ["developer"],
    "teams": ["engineering"],
    "clearance_level": 2
  },

  "action": "tools.invoke",
  "resource": {
    "type": "tool",
    "id": "db-query",
    "server": "production-db",
    "classification": 4
  },

  "decision": "deny",
  "reason": "Insufficient clearance level",

  "matching_policies": [
    {
      "id": "mac-policy-1",
      "name": "production-data-access",
      "engine": "mac",
      "result": "deny",
      "explanation": "User clearance (2) < Resource classification (4)"
    }
  ],

  "context": {
    "ip_address": "10.0.0.50",
    "user_agent": "claude-desktop/1.0",
    "mfa_verified": true,
    "time_of_day": "10:30"
  },

  "duration_ms": 5
}
```

## Usage

### REST API

```bash
# Query decisions (requires admin auth)
GET /api/policy-decisions/decisions?subject_email=user@example.com&decision=deny&limit=50

# Get statistics (requires admin auth)
GET /api/policy-decisions/statistics?start_time=2024-01-01T00:00:00Z

# Health check (no auth required)
GET /api/policy-decisions/health
```

### SIEM Configuration

Set the following environment variables to enable SIEM export:

```bash
POLICY_AUDIT_ENABLED=true
SIEM_ENABLED=true
SIEM_TYPE=splunk           # or elasticsearch, webhook
SIEM_ENDPOINT=https://splunk.example.com:8088
SPLUNK_HEC_TOKEN=your-token
SIEM_BATCH_SIZE=100
SIEM_FLUSH_INTERVAL=5
```

## Key Design Decisions

1. **Schema Alignment**: Matches GitHub issue #2225 schema
2. **SQLAlchemy Integration**: Uses existing gateway ORM infrastructure
3. **Modular Design**: Separate concerns (service, SIEM, API)
4. **SIEM Formats**: Industry-standard formats (Splunk HEC, Elasticsearch)
5. **Batch Processing**: Efficient SIEM forwarding with batching
6. **Per-decision toggles**: `policy_audit_log_allowed` and `policy_audit_log_denied` settings

## Production Considerations

### Security
- Store audit logs in tamper-proof location
- Encrypt logs at rest and in transit
- Restrict access to audit logs
- Use strong authentication for SIEM endpoints

### Performance
- Use connection pooling for database
- Batch SIEM exports (default: 100 events)
- Index database for common queries
- Consider partitioning for large datasets

### Scalability
- Use PostgreSQL for production
- Use message queue for high-throughput scenarios
- Implement log archival and compression
- Consider distributed logging for multi-node deployments

### Compliance
- Configure retention per compliance framework
- Regular backup of audit logs
- Audit log integrity checks

---

**Issue**: [#2225 - Policy audit trail and decision logging](https://github.com/IBM/mcp-context-forge/issues/2225)
