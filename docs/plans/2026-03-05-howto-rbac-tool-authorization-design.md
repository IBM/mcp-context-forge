# Design: How-To Guide — Authorize Tools with RBAC in a Virtual Server

**Date:** 2026-03-05
**Status:** Approved

## Goal

Create a task-oriented how-to guide that walks operators through configuring RBAC
to control which users can list and execute tools on a virtual server. This is the
first document in a new top-level "How-To Guides" documentation section.

## Navigation Changes

- New directory: `docs/docs/howto/`
- New top-level nav entry in `docs/docs/.pages`: "How-To Guides" between
  "Tutorials" and "Best Practices"
- `howto/.pages` listing `index.md` and `rbac-tool-authorization.md`
- `howto/index.md` — landing page with brief intro and links to guides

## Scenario

An analytics team needs `tools.read` + `tools.execute` on data-query tools but
must not execute the `db-migrate` tool on the production virtual server. A viewer
role can list tools but not run them.

## Guide Structure (rbac-tool-authorization.md)

1. **Prerequisites** — running instance, auth enabled, at least one team and user.
   Admonition blocks link to quickstart/teams/securing for setup-from-scratch.

2. **Understand the Two-Layer Model** — 5-6 sentence recap of token scoping
   (Layer 1: visibility) and RBAC (Layer 2: actions). Compact diagram. Links to
   full RBAC reference.

3. **Step 1: Set Tool Visibility** — configure `visibility` on tools/server to
   `team` or `public`. Tabbed for API/CLI vs Admin UI.

4. **Step 2: Assign an RBAC Role** — assign `developer` or `viewer` to users for
   the owning team. Brief mention of custom roles with link to bootstrap reference.
   Tabbed.

5. **Step 3: Generate a Scoped Token** — create team-scoped JWT. Tabbed for CLI
   vs Admin UI.

6. **Step 4: Verify Access** — curl calls confirming developer can list+execute,
   viewer can list only, neither sees other teams' tools.

7. **Troubleshooting** — 3-4 common failure modes with fixes. Links to RBAC
   reference troubleshooting.

## Conventions

- Both API/CLI and Admin UI paths via `pymdownx.tabbed` content blocks
- Admonitions (`!!! tip`, `!!! warning`) matching existing docs style
- Realistic but not reproducible scenario (option 2)
- Target audience: both newcomers (via prerequisite callouts) and experienced
  operators (scannable steps)
- ~250-350 lines of markdown
- No emojis in guide body; emoji only in `.pages` nav label per convention

## Source Documents

Synthesized from:
- `docs/docs/manage/rbac.md` — roles, permissions, token scoping, troubleshooting
- `docs/docs/architecture/multitenancy.md` — visibility levels, two-layer model
- `docs/docs/manage/securing.md` — permission-scoped tokens, server-scoped tokens
- `docs/docs/manage/teams.md` — team creation and mapping
