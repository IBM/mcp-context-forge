# RBAC Configuration

Role-based access control (RBAC) defines which actions users or teams can perform in MCP Gateway. This document outlines the model, current capabilities, and the roadmap toward finer-grained controls.

---

## Model

- Subjects: users authenticated via SSO or basic/JWT
- Grouping: subjects can belong to one or more gateway teams
- Roles: admin, maintainer, viewer (initial baseline); future: per-entity scoped roles
- Resources: servers, tools, prompts, resources, gateway settings

---

## Current State

- Authentication and administrative endpoints are protected; production deployments should enable auth and use JWTs for API calls.
- Team mapping on SSO login allows grouping users into stable teams that can be referenced by policy.
- Visibility per server and composition via virtual servers provide pragmatic control of what tools are exposed to clients.

---

## Planned Enhancements

- Fine-grained roles for create/update/delete vs. read-only per resource type.
- Policy definitions that bind roles to teams and/or individual users.
- UI flows for assigning roles to teams and auditing access.

---

## Recommended Practices

- Start with three tiers of access:
  - Admin: full management access
  - Maintainer: manage servers, tools, prompts and configurations
  - Viewer: read-only access and metrics
- Use SSO group-to-team mappings to automate membership and reduce manual changes.
- Keep virtual servers scoped per project/team so client-facing exposure is intentional.

---

## Related

- [Team Management](teams.md)
- [Security Features](../architecture/security-features.md)
- [Configuration Reference](configuration.md)
