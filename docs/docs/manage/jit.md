# Just-in-Time (JIT) Access

Just-in-Time (JIT) access provides temporary privilege elevation with approval workflows, automatic expiration, and full audit trails. It enforces least-privilege principles by ensuring elevated access is granted only when needed and for the shortest duration necessary.

---

## Overview

JIT access allows users to request temporary elevated roles for specific tasks such as incident response. An admin approves or rejects the request, and access automatically expires after the specified duration.
```
┌─────────────────────────────────────────────────────────────┐
│                    JIT Access Flow                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   User → Request → Pending → Admin Approve → Active        │
│                            ↘ Admin Reject  → Rejected      │
│                                                             │
│   Active → Expires (auto) → Expired                        │
│   Active → User/Admin Revoke → Revoked                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Grant Statuses

| Status | Description |
|--------|-------------|
| `pending` | Request submitted, awaiting admin approval |
| `active` | Approved and access window is open |
| `expired` | Access window has passed automatically |
| `revoked` | Manually revoked before expiry |
| `rejected` | Rejected by admin |

---

## API Endpoints

### Request JIT Access
```bash
POST /jit
Authorization: Bearer <token>

{
  "requested_role": "incident-responder",
  "justification": "INC-1234: Production database issue",
  "duration_hours": 2,
  "ticket_url": "https://jira.example.com/INC-1234"
}
```

### List All Grants (Admin)
```bash
GET /jit?status=pending
Authorization: Bearer <admin-token>
```

### List My Grants
```bash
GET /jit/mine
Authorization: Bearer <token>
```

### Get Grant by ID
```bash
GET /jit/{grant_id}
Authorization: Bearer <token>
```

### Approve a Grant (Admin)
```bash
POST /jit/{grant_id}/approve
Authorization: Bearer <admin-token>

{
  "note": "Approved for INC-1234"
}
```

### Reject a Grant (Admin)
```bash
POST /jit/{grant_id}/reject
Authorization: Bearer <admin-token>

{
  "reason": "No active incident found"
}
```

### Revoke a Grant
```bash
POST /jit/{grant_id}/revoke
Authorization: Bearer <token>

{
  "reason": "Incident resolved"
}
```

---

## Grant Schema
```json
{
  "id": "jit-uuid",
  "requester_email": "developer@example.com",
  "requested_role": "incident-responder",
  "justification": "INC-1234: Production database issue",
  "duration_hours": 2,
  "ticket_url": "https://jira.example.com/INC-1234",
  "status": "active",
  "approved_by": "admin@example.com",
  "approved_at": "2026-01-15T10:00:00Z",
  "starts_at": "2026-01-15T10:00:00Z",
  "expires_at": "2026-01-15T12:00:00Z",
  "revoked_by": null,
  "revoke_reason": null,
  "reject_reason": null,
  "note": "Approved for INC-1234",
  "created_at": "2026-01-15T09:55:00Z",
  "updated_at": "2026-01-15T10:00:00Z"
}
```

---

## Compliance

JIT access supports the following compliance requirements:

| Standard | Control | How JIT Helps |
|----------|---------|---------------|
| NIST SP 800-53 | AC-6 Least Privilege | Temporary elevation instead of standing access |
| FedRAMP | AC-6 | Demonstrable least privilege with audit trail |
| HIPAA | Access Control | Time-limited access with justification |

---

## Related

- [RBAC Configuration](rbac.md)
- [Audit Logging](logging.md)
- [Teams](teams.md)
