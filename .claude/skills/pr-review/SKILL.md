---
name: pr-review
description: Use when a feature branch is ready for code review, needs rebasing onto main, or before creating/updating a pull request. Also use when asked to review changes, check code quality, or verify a branch is merge-ready.
---

# PR Review

Review all changes between `main` and the current branch HEAD, plus any staged
and unstaged working-tree changes.

## Setup

1. **Rebase** — Unless the user says otherwise, fetch `origin` and rebase onto
   `origin/main`, resolving conflicts. If the branch has Alembic migrations,
   run `alembic heads` after rebase — if multiple heads exist, update
   `down_revision` to restore a single linear history.

2. **Gather context** — If a PR exists (`gh pr view`):
   - PR description, title, review comments (`gh pr view --comments`)
   - Linked issues (`gh issue view N`) to understand requirements
   If no PR exists, review from the diff alone.

3. **Read project docs** — Check for `AGENTS.md`, `CONTRIBUTING.md`,
   `CLAUDE.md`. These are authoritative for test commands, linter config, and
   conventions — use their commands exactly, not generic substitutes.

## Review checklist

Review the diff in priority order. Fix blocking issues directly when
straightforward; flag issues that need human judgment.

| # | Category | Severity | Focus |
|---|----------|----------|-------|
| 1 | Security | Blocking | Injection, leaked secrets, auth gaps, OWASP top 10 |
| 2 | Correctness | Blocking | Logic errors, edge cases, mismatch with linked issues |
| 3 | Test coverage | Blocking | 100% differential coverage — verify changed code has tests |
| 4 | Linter compliance | Blocking | Run project linters on touched files; resolve all findings |
| 5 | Performance | High | N+1 queries, unnecessary allocations, bottlenecks |
| 6 | Code quality | Medium | Redundancy, over-complexity, code smells |
| 7 | Consistency | Medium | Follow documented conventions; suggest undocumented ones |
| 8 | Alembic migrations | Conditional | Idempotence, reversibility, cross-DB compat, data safety, `batch_alter_table` for SQLite |

## Second opinions

After your own review, run available second-opinion tools in parallel as
background tasks. If a tool is missing from `$PATH` or fails, skip it and note
reduced coverage.

- **Codex**: `codex exec review --base origin/main`
- **Bob**: Pipe the diff inline — `git diff origin/main..HEAD | bob "Review this
  diff for correctness, security, and code quality. Be specific about
  line-level issues."` Tailor the prompt to the PR content.

Attribute findings to their source (Claude/Codex/Bob) and resolve contradictions.

## Output format

```markdown
# PR Review: [branch-name]

## Summary
[1-2 sentence overview: what changed, whether it meets PR/issue goals]

## Findings
| # | Severity | Category | File:Line | Issue | Source |
|---|----------|----------|-----------|-------|--------|

## Fixes Applied
[Issues fixed directly, with commit refs]

## Remaining Issues
[Issues needing human decision or outside scope]

## Recommendation
Pick exactly ONE: Ready to merge | Ready after fixing remaining issues | Needs significant rework
```

## Rules

- Never mention Claude, Claude Code, or AI in commits or PR text.
- Never push unless explicitly asked.
- Sign commits with `git commit -s`. Verify Git author matches `gh auth status`.
- Create new commits rather than amending existing ones when rebasing or fixing.
- After fix-up commits, re-run linters and tests to confirm no regressions.
