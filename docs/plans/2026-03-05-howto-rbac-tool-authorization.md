# How-To: RBAC Tool Authorization — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a new "How-To Guides" documentation section and its first guide covering RBAC configuration for tool access in virtual servers.

**Architecture:** Four new files wired into the existing MkDocs Material site via awesome-pages `.pages` files. One edit to the top-level `.pages` to add the nav entry.

**Tech Stack:** MkDocs Material, awesome-pages plugin, pymdownx.tabbed for API/UI tabs, admonitions

**Design doc:** `docs/plans/2026-03-05-howto-rbac-tool-authorization-design.md`

---

## Task 1: Create howto directory and .pages nav file

**Files:**
- Create: `docs/docs/howto/.pages`

**Step 1: Create the directory and .pages file**

```yaml
nav:
  - index.md
  - rbac-tool-authorization.md
```

**Step 2: Verify directory exists**

Run: `ls docs/docs/howto/.pages`
Expected: file listed

**Step 3: Commit**

```bash
git add docs/docs/howto/.pages
git commit -s -m "docs: add howto section skeleton with .pages nav"
```

---

## Task 2: Wire howto into top-level navigation

**Files:**
- Modify: `docs/docs/.pages` — add howto entry between tutorials and best-practices

**Step 1: Edit .pages**

Current content (lines 12-14):
```yaml
  - "📖 Tutorials": tutorials
  - "⭐ Best Practices": best-practices
  - "❓ FAQ": faq
```

Insert new line between tutorials and best-practices:
```yaml
  - "📖 Tutorials": tutorials
  - "📝 How-To Guides": howto
  - "⭐ Best Practices": best-practices
  - "❓ FAQ": faq
```

**Step 2: Verify the edit**

Run: `grep -n howto docs/docs/.pages`
Expected: line containing `"📝 How-To Guides": howto`

**Step 3: Commit**

```bash
git add docs/docs/.pages
git commit -s -m "docs: add How-To Guides to top-level navigation"
```

---

## Task 3: Create howto/index.md landing page

**Files:**
- Create: `docs/docs/howto/index.md`

**Step 1: Write index.md**

Content should be a brief introduction to the how-to section (5-10 lines), explaining that how-to guides are task-oriented walkthroughs for specific operational goals, distinct from tutorials (learning-oriented) and reference docs (information-oriented). Include a bullet list linking to available guides — currently just the RBAC tool authorization guide.

Key points to include:
- One-sentence description of what how-to guides are
- Distinguish from tutorials and reference docs
- Link to `rbac-tool-authorization.md` with a one-line summary

Match the tone and structure of `docs/docs/tutorials/index.md` (brief intro, links to guides). No emojis in the body.

**Step 2: Verify renders**

Run: `head -5 docs/docs/howto/index.md`
Expected: title and intro paragraph visible

**Step 3: Commit**

```bash
git add docs/docs/howto/index.md
git commit -s -m "docs: add how-to section landing page"
```

---

## Task 4: Write rbac-tool-authorization.md

**Files:**
- Create: `docs/docs/howto/rbac-tool-authorization.md`

This is the main deliverable. Synthesize from these source documents (all read earlier in the conversation — do NOT re-read unless you need to verify a specific detail):

- `docs/docs/manage/rbac.md` — roles, permissions, token scoping model, troubleshooting
- `docs/docs/architecture/multitenancy.md` — visibility levels, two-layer security model
- `docs/docs/manage/securing.md` — permission-scoped tokens, server-scoped tokens
- `docs/docs/manage/teams.md` — team creation and SSO mapping

### Section-by-section content specification

**Title:** `# Authorize Tools in a Virtual Server Using RBAC`

**Introductory paragraph (3-4 sentences):**
State what this guide covers: configuring RBAC so that specific users can list and/or execute tools exposed through a virtual server, while others are restricted. Mention the scenario: an analytics team with data-query tools, a `db-migrate` tool that should be restricted, and a viewer role that can browse but not execute.

**Prerequisites section:**
Use an admonition block (`!!! info "Prerequisites"`). List:
- A running ContextForge instance with `AUTH_REQUIRED=true`
- At least one team created (link to `../manage/teams.md`)
- At least one user with team membership
- A virtual server with registered gateway(s) and tools
- Link to quickstart/deployment docs for anyone starting from scratch

**Section: How the Two-Layer Model Applies to Tools**
5-6 sentences explaining:
- Layer 1 (token scoping): the `teams` JWT claim controls which tools a user can *see* based on the tool's `visibility` and `team_id`
- Layer 2 (RBAC): role permissions (`tools.read`, `tools.execute`) control which *actions* the user can perform
- Both layers must pass for a tool call to succeed
- Include this compact ASCII diagram from the multitenancy doc (simplified):

```
Request → Token Scoping (Can see this tool?) → RBAC Check (Can execute?) → Tool runs
```

- Link to full RBAC reference: `../manage/rbac.md`

**Step 1: Set Tool Visibility**
Explain that tools inherit visibility from how they're registered, and that visibility must match the user's token scope. Walk through setting a tool's visibility to `team` so team members can see it.

Use tabbed content:

```
=== "API / CLI"

    curl -X PATCH with Authorization header, setting visibility to "team"

=== "Admin UI"

    1. Navigate to Tools
    2. Select the tool
    3. Change Visibility to "Team"
    4. Save
```

Include a `!!! tip` noting that `public` visibility makes the tool visible to all authenticated users, while `team` restricts to team members.

**Step 2: Assign an RBAC Role**
Explain the three relevant built-in roles and their tool permissions:

| Role | `tools.read` | `tools.execute` |
|------|:---:|:---:|
| `viewer` | Yes | No |
| `developer` | Yes | Yes |
| `team_admin` | Yes | Yes |

Show how to assign a role. Tabbed content:

```
=== "API / CLI"

    POST /admin/users/{email}/roles with role_name and scope_id (team UUID)

=== "Admin UI"

    1. Navigate to Users
    2. Select the user
    3. Assign role for the team
```

Include a `!!! note` about custom roles — mention `MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_ENABLED` and link to the "Bootstrap Custom Roles" section in `../manage/rbac.md#bootstrap-custom-roles`.

**Step 3: Generate a Scoped Token**
Show how to create a team-scoped API token. Tabbed content:

```
=== "API / CLI"

    python3 -m mcpgateway.utils.create_jwt_token \
      --data '{"sub":"analyst@example.com","is_admin":false,"teams":["<analytics-team-uuid>"],"token_use":"api"}' \
      --exp 60 \
      --secret $JWT_SECRET_KEY

=== "Admin UI"

    1. Navigate to Tokens
    2. Click Create Token
    3. Select the analytics team
    4. Set expiration
    5. Copy the generated token
```

Include a `!!! warning` about tokens created without selecting a team defaulting to public-only access.

**Step 4: Verify Access**
Provide three curl examples showing expected outcomes:

1. **Developer lists tools** — `GET /tools` with developer's token → sees team tools
2. **Developer executes a tool** — `POST /tools/{tool_name}/execute` → 200 success
3. **Viewer executes a tool** — same call with viewer's token → 403 forbidden
4. **Either user lists tools on another team's server** — → tools not in response

Use a `!!! tip` noting they can decode the JWT to inspect claims: `echo "$TOKEN" | cut -d. -f2 | base64 -d | jq .`

**Troubleshooting section:**
Brief table or definition list covering:

| Symptom | Cause | Fix |
|---------|-------|-----|
| Tool not visible (404 or empty list) | Token missing `teams` claim or wrong team UUID | Decode JWT and verify `teams` includes the tool's `team_id` |
| 403 on tool execution | User has `viewer` role (no `tools.execute`) | Assign `developer` or `team_admin` role |
| Admin token seeing only public tools | Token has `teams: []` (explicit empty) | Use `teams: null` with `is_admin: true` for admin bypass |
| Tool visible but execution returns 500 | Upstream gateway unreachable | Check gateway health via `GET /gateways/{id}` |

Link to the full troubleshooting section: `../manage/rbac.md#troubleshooting`

**Related Documentation section (footer):**
Bulleted links to:
- [RBAC Configuration](../manage/rbac.md)
- [Team Management](../manage/teams.md)
- [Security Configuration](../manage/securing.md)
- [Multi-Tenancy Architecture](../architecture/multitenancy.md)

### Quality checks

After writing the file:
- Verify no broken relative links by checking that target files exist
- Verify tabbed syntax uses `=== "Tab Name"` with 4-space indented content
- Verify admonition syntax uses `!!! type "Title"` with 4-space indented content
- Target length: 250-350 lines

**Step 2: Commit**

```bash
git add docs/docs/howto/rbac-tool-authorization.md
git commit -s -m "docs: add RBAC tool authorization how-to guide"
```

---

## Task 5: Final verification and squash-ready commit

**Step 1: Verify all files exist**

Run: `find docs/docs/howto -type f | sort`
Expected:
```
docs/docs/howto/.pages
docs/docs/howto/index.md
docs/docs/howto/rbac-tool-authorization.md
```

**Step 2: Verify nav wiring**

Run: `grep howto docs/docs/.pages`
Expected: `"📝 How-To Guides": howto`

**Step 3: Verify relative links resolve**

Run: `grep -oP '\(\.\..*?\)' docs/docs/howto/rbac-tool-authorization.md | sort -u`
Then verify each target file exists under `docs/docs/`.

**Step 4: Review git log**

Run: `git log --oneline -5`
Expected: 4 commits from this plan (tasks 1-4)
