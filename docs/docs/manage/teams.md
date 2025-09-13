# Team Management

MCP Gateway organizes users into teams so you can scope access and group operational responsibilities. While first-class UI for team administration is evolving, teams are already referenced across SSO guides and configuration for mapping identities to gateway-scoped groups.

---

## Concepts

- Teams: Logical groups used to organize users for access and ownership boundaries.
- Mapping: Associate external identity attributes (e.g., Okta groups, Google Groups, GitHub orgs) to gateway team IDs.
- Usage: Team IDs are used by administrative flows and planned RBAC policies.

---

## Team Mapping Examples

Use provider-specific environment variables to auto-assign users to teams on SSO login.

### GitHub Organization → Team

```bash
# Map a GitHub organization to a gateway team
GITHUB_ORG_TEAM_MAPPING={"your-github-org": "dev-team-uuid"}
```

### Google Groups → Team

```bash
# Map Google Groups to gateway team IDs
GOOGLE_GROUPS_MAPPING={"group1@yourcompany.com": "team-uuid-1", "admins@yourcompany.com": "admin-team-uuid"}
```

### Okta Groups → Team

```bash
# Map Okta groups to gateway team IDs
OKTA_GROUP_MAPPING={"MCP Gateway Admins": "admin-team-uuid", "MCP Gateway Users": "user-team-uuid"}
```

### IBM Security Verify (Groups) → Team

```bash
# Map ISV groups to gateway team IDs
IBM_VERIFY_GROUP_MAPPING={"CN=Developers,OU=Groups": "dev-team-uuid", "CN=Administrators,OU=Groups": "admin-team-uuid"}
```

---

## Operational Tips

- Generate deterministic team UUIDs and manage them via export/import or admin APIs so they're stable across environments.
- Use a small set of core teams (e.g., developers, admins, observers) to keep mappings simple.
- Test SSO login with a pilot user per provider to verify expected team assignment.

---

## Related

- [SSO Overview](sso.md)
- [RBAC Configuration](rbac.md)
