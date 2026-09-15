# Team Management

ContextForge organizes users into teams so you can scope access and group operational responsibilities. While first-class UI for team administration is evolving, teams are already referenced across SSO guides and configuration for mapping identities to gateway-scoped groups.

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
OKTA_GROUP_MAPPING={"ContextForge Admins": "admin-team-uuid", "ContextForge Users": "user-team-uuid"}
```

### IBM Security Verify (Groups) → Team

```bash
# Map ISV groups to gateway team IDs
IBM_VERIFY_GROUP_MAPPING={"CN=Developers,OU=Groups": "dev-team-uuid", "CN=Administrators,OU=Groups": "admin-team-uuid"}
```

---

## Team Name Validation

Team names are validated against a strict character pattern to prevent XSS attacks and ensure consistent display across the UI.

### Allowed Characters

Team names may only contain:

- Letters (a-z, A-Z)
- Numbers (0-9)
- Spaces
- Underscores (`_`)
- Periods (`.`)
- Dashes (`-`)

**Pattern:** `^[a-zA-Z0-9_.\-\s]+$`

### Rejected Characters

The following characters are **not allowed** in team names:

- Ampersand (`&`)
- Apostrophe (`'`)
- Forward slash (`/`)
- Angle brackets (`<`, `>`)
- Quotation marks (`"`)
- Any HTML or script content

### Examples

| Team Name | Valid? | Reason |
|-----------|--------|--------|
| `Engineering Team` | ✅ | Letters and space |
| `Dev_Team-2024.v1` | ✅ | Allowed special chars |
| `R&D Team` | ❌ | Ampersand not allowed |
| `O'Connor's Team` | ❌ | Apostrophe not allowed |
| `Team <Alpha>` | ❌ | Angle brackets not allowed |

### Migrating Existing Teams

If you have existing teams with names containing restricted characters, you'll need to update them before they can be modified via the API or Admin UI.

#### Option 1: SQL Migration (Recommended)

Find affected teams:

```sql
-- SQLite
SELECT id, name FROM email_teams
WHERE name GLOB '*[^a-zA-Z0-9_. -]*';

-- PostgreSQL
SELECT id, name FROM email_teams
WHERE name !~ '^[a-zA-Z0-9_.\- ]+$';
```

Update team names manually or via script:

```sql
-- Example: Replace & with 'and'
UPDATE email_teams SET name = REPLACE(name, '&', 'and')
WHERE name LIKE '%&%';
```

#### Option 2: Python Migration Script

```python
import re
from mcpgateway.db import get_db, EmailTeam

VALID_PATTERN = re.compile(r'^[a-zA-Z0-9_.\-\s]+$')

def sanitize_name(name: str) -> str:
    """Replace invalid characters."""
    name = name.replace('&', 'and')
    return re.sub(r'[^a-zA-Z0-9_.\-\s]', '-', name)

def migrate_team_names():
    db = next(get_db())
    teams = db.query(EmailTeam).all()
    for team in teams:
        if not VALID_PATTERN.match(team.name):
            old_name = team.name
            team.name = sanitize_name(team.name)
            print(f"Migrated: '{old_name}' -> '{team.name}'")
    db.commit()

if __name__ == "__main__":
    migrate_team_names()
```

---

## Listing and Searching Teams

The `GET /v1/teams/` endpoint returns the teams visible to the caller.

| Query parameter | Type | Default | Description |
|----------------|------|---------|-------------|
| `skip` | int | `0` | Number of teams to skip (offset-based pagination). |
| `limit` | int | `50` | Maximum teams to return (capped by `PAGINATION_MAX_PAGE_SIZE`). |
| `cursor` | string | – | Opaque cursor for cursor-based pagination. |
| `include_pagination` | bool | `false` | When `true`, response includes `nextCursor` instead of `total`. |
| `search_query` | string | – | Case-insensitive substring filter on name, slug, or description (max 500 chars). |

**Visibility rules:**

- **Platform admins** see all non-personal teams plus their own personal team. `search_query` is applied server-side via SQL.
- **Regular users** see only teams they belong to. `search_query` filters the result locally.

```bash
# List your teams
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/v1/teams/" | jq '.teams[].name'

# Search by name, slug, or description
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/v1/teams/?search_query=engineering" | jq '.teams[].name'

# Paginate with offset
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/v1/teams/?skip=50&limit=25" | jq '.'

# Cursor-based pagination
CURSOR=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/v1/teams/?include_pagination=true" | jq -r '.nextCursor')
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/v1/teams/?include_pagination=true&cursor=$CURSOR" | jq '.'
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
