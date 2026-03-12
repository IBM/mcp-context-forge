---
name: sprint-plan
description: Based on the current contents of the project issues, plan a series of sprints to address the issues.
---
# Sprint Planning Regeneration Guide

Instructions for Claude Code to regenerate the sprint planning worksheets in this directory.
This process is expected to run roughly monthly.

## Prerequisites

- `gh` CLI authenticated with access to IBM/mcp-context-forge
- Python 3.11+ available
- Access to the full open issue list (currently ~661 issues)

## Overview

The process produces four artifacts:

1. **sprint-plan.csv** — Master issue inventory with sprint assignments and effort estimates
2. **epic-categories.csv** — Epic inventory with child issue rollup
3. **label-fixes.csv** — Label/title consistency audit
4. **milestone-sprint-matrix.csv** — Milestone vs sprint cross-reference

## Step-by-Step Process

### Step 1: Fetch All Open Issues

```bash
gh issue list --repo IBM/mcp-context-forge --state open --limit 1000 \
  --json number,title,labels,milestone \
  > /tmp/all_issues.json
```

Important: The default limit is 30. Always set `--limit` high enough to capture all open issues. Verify the count matches what GitHub reports.

### Step 2: Fetch Milestones

```bash
gh api repos/IBM/mcp-context-forge/milestones --paginate \
  --jq '.[] | [.number, .title, .open_issues, .closed_issues] | @tsv'
```

Note: The `!=` operator in jq requires escaping in zsh. Use Python to filter null milestones from JSON rather than jq `select()` with negation.

### Step 3: Classify Each Issue

#### 3a. Issue Type (from title tags)

| Title Pattern | Type |
|---------------|------|
| `[EPIC]` in title OR `epic` label | Epic |
| `[BUG]` in title OR `bug` label | Bug |
| `[FEATURE]` or `[ENHANCEMENT]` in title | Feature |
| `[PERFORMANCE]` in title | Performance |
| `[TESTING]` or `[CHORE][TESTING]` in title | Testing |
| `[CHORE]` in title | Chore |
| `[DOCS]` or `[README]` or `[QUICK-START]` in title | Docs |
| Default | Feature |

Priority: Epic > Bug > Performance > Testing > Chore > Docs > Feature.
If multiple tags match, use the highest priority type.

#### 3b. MoSCoW Priority (from labels)

Look for these exact label strings: `MUST`, `SHOULD`, `COULD`, `WOULD`.
If none found, mark as empty/unset.

#### 3c. Epic Category

Assign each issue to exactly one of these 12 categories based on title tags and labels:

| # | Category | Matching signals |
|---|----------|-----------------|
| 1 | Security & Auth | `[AUTH]`, `[SECURITY]`, `[SSO]`, `[RBAC]`, `[COMPLIANCE]`, `security` label |
| 2 | Admin UI & Frontend | `[UI]`, `[CATALOG]`, `frontend` label, `ui` label |
| 3 | Protocol & Transport | `[PROTOCOL]`, `[API]`, `[A2A]`, `[RUNTIME]`, `[INTEGRATION]`, `mcp-protocol` label |
| 4 | Performance & Database | `[PERFORMANCE]`, `[DB]`, `[DATABASE]`, `[RUST]`, `performance` label, `database` label |
| 5 | Plugins & Extensions | `[PLUGIN]`, `[PLUGINS]`, `plugins` label |
| 6 | DevOps & Infrastructure | `[HELM]`, `[DOCKER]`, `[CICD]`, `[K8S]`, `[DEPLOYMENT]`, `devops` label |
| 7 | Observability & Monitoring | `[OBSERVABILITY]`, `[LOGGING]`, `observability` label |
| 8 | SaaS Readiness | `[COMPLIANCE]` (when SaaS-specific), SaaS-related billing/metering |
| 9 | Client Integration | `wxo` label, `client-*` labels, `ica` label |
| 10 | Testing & QA | `[TESTING]`, `testing` label, `manual-testing` label |
| 11 | Documentation & Samples | `[DOCS]`, `[README]`, `[QUICK-START]`, `documentation` label |
| 12 | AI & Discovery | `[AI]`, `[SEARCH]`, AI/ML/semantic keywords |

Priority order when multiple match: Client Integration (9) > Security (1) > Protocol (3) > Performance (4) > Plugins (5) > UI (2) > Observability (7) > SaaS (8) > Testing (10) > DevOps (6) > Docs (11) > AI (12).

### Step 4: Sprint Priority Assignment

| Priority | Criteria |
|----------|----------|
| P0 | Has `wxo` label, or any `client-*` label, or `ica` label |
| P1 | SaaS enablement: security hardening, compliance, auth, billing, multi-tenancy |
| P2 | A2A/LLM gateway: protocol compliance, transport, A2A features |
| P3 | Platform quality: performance, database, observability, bug fixes |
| P4 | Developer experience: DevOps, testing infrastructure, documentation, CI/CD |
| P5 | Nice-to-have: COULD/WOULD items without higher priority signals |

### Step 5: Sprint Assignment

| Sprint | Rule |
|--------|------|
| Sprint 1 | P0 + MUST |
| Sprint 2 | P0 remaining + P1 MUST |
| Sprint 3 | P1 SHOULD + P2 MUST (theme: Protocol & Compliance) |
| Sprint 4 | P2 SHOULD + P3 MUST (theme: Performance, DB, Testing & UI Infrastructure) |
| Sprint 5A | P3 SHOULD bugs + performance items |
| Sprint 5B | P3 SHOULD testing items |
| Sprint 5C | P3 SHOULD features + epics (theme: Security Hardening) |
| Sprint 6 | P4 SHOULD (theme: DevOps, Docs & Polish) |
| Backlog | Everything else (COULD, WOULD, P5) |

Target capacity per sprint: ~200-270 SP. If any sprint exceeds ~300 SP, rebalance by:
1. Moving items to the next sprint that fits thematically
2. Pushing aspirational items (AI & Discovery, speculative epics) to Backlog

### Step 6: Effort Estimation

Apply effort estimates to sprint-assigned issues only (not Backlog).

#### Story Point Scale (Fibonacci)

| SP | Person-Days | Typical Use |
|----|-------------|-------------|
| 1 | 0.5 | Trivial config change, typo fix |
| 2 | 1 | Small bug fix, minor feature, single-file change |
| 3 | 1.5-2 | Standard feature, moderate bug, 2-3 file change |
| 5 | 3-4 | Multi-file feature, complex bug, new endpoint |
| 8 | 5-7 | Large feature, significant refactor, new service |
| 13 | 8-12 | Epic-sized, multi-component, new subsystem |
| 21 | 13-20 | Major epic, cross-cutting architectural change |

#### Estimation Heuristics

- **Epics**: 13 SP (Medium/Large) or 21 SP (XL). Always Low confidence.
- **Bugs**: 1-2 SP (simple), 3-5 SP (complex/multi-file), 8 SP (architectural).
- **Features**: 3 SP (standard), 5 SP (multi-component), 8 SP (large/new service).
- **Testing manual test plans**: 3 SP each (write + first-pass execution).
- **Performance**: 2-3 SP (config/index), 5 SP (refactor), 8+ SP (architectural).
- **Chores**: 2 SP (simple), 3-5 SP (moderate), 8 SP (large restructure).
- **Docs**: 2 SP (standard), 5-8 SP (comprehensive framework adoption).

Confidence levels:
- **High**: Well-scoped, clear requirements, similar past work.
- **Medium**: Reasonable scope but some unknowns.
- **Low**: Epics, architectural changes, first-of-kind work.

### Step 7: Epic-to-Issue Mapping

For non-epic issues, identify a parent epic by matching:

1. **Explicit title/label overlap**: Issue title tags match epic title tags (e.g., `[AUTH]` issue under `[EPIC][AUTH]`).
2. **Functional domain**: Issue addresses a story within the epic's scope.
3. **Label intersection**: Shared labels like `security`, `plugins`, `ui`.

Record the parent epic number and a brief justification. These mappings are **proposals** — always get approval before creating GitHub sub-issue links.

### Step 8: Label Consistency Audit

Check every issue for mismatches between title tags and labels:

| Title Tag | Expected Label |
|-----------|---------------|
| `[EPIC]` | `epic` |
| `[BUG]` | `bug` |
| `[FEATURE]` or `[ENHANCEMENT]` | `enhancement` |
| `[CHORE]` | `chore` |
| `[UI]` | `ui` |
| `[SECURITY]` or `[AUTH]` or `[COMPLIANCE]` | `security` |
| `[PLUGIN]` or `[PLUGINS]` | `plugins` |
| `[PERFORMANCE]` | `performance` |
| `[DB]` or `[DATABASE]` | `database` |
| `[OBSERVABILITY]` | `observability` |
| `[PROTOCOL]` | `mcp-protocol` |

Also flag the reverse: labels present without matching title tags. And flag issues with no labels at all.

### Step 9: Milestone-Sprint Matrix

Cross-reference GitHub milestone assignments against sprint assignments. Produce two matrices:
- **Story Points matrix**: Milestone (rows) x Sprint (columns), cell = total SP.
- **Issue Count matrix**: Same structure, cell = number of issues.

Include a `(No milestone)` row and `TOTAL` row/column.

### Step 10: Generate README.md

Update the README.md in this directory with:
- File listing and descriptions
- Column definitions for each CSV
- Sprint summary table with themes and SP totals
- Key observations for each worksheet
- Milestone summary

## Known Pitfalls

1. **`gh issue list` default limit is 30.** Always use `--limit 1000` or higher.
2. **jq `!=` requires escaping in zsh.** Use Python for null filtering instead of `select(.field != null)`.
3. **Large JSON output may exceed tool limits.** Use TSV or process with Python scripts instead of trying to read raw JSON.
4. **Backlog items should not have effort estimates.** Clear SP/Person-Days/Confidence/Notes when moving items to Backlog.
5. **Epic detection is dual-source.** Check both `[EPIC]` in title AND `epic` label — some epics only have one or the other (which is itself a label-fix finding).
6. **Sprint 5 splitting.** If any sprint exceeds ~300 SP after initial assignment, split by type: bugs+performance (A), testing (B), features+epics (C).
7. **Thematic coherence matters.** When rebalancing, keep sprint themes intact rather than just leveling SP counts. Ask the user for theme preferences.

## Verification Checklist

After regeneration, verify:

- [ ] Total issue count matches `gh issue list --state open` count
- [ ] All sprint SP totals are in the 150-280 SP range (except Sprint 1 which may be smaller)
- [ ] No Backlog items have story point values
- [ ] Every epic appears in epic-categories.csv
- [ ] Milestone matrix row totals match milestone open issue counts
- [ ] Label fixes CSV has no duplicate rows (same issue + same fix)
- [ ] README.md sprint summary table matches actual CSV data
