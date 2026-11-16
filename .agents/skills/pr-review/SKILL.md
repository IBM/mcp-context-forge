---
name: pr-review
description: Review a PR, branch, or diff in this repository. Use before you create or update a PR, when a branch is ready for review, or before you post `gh pr review`. Defines the procedure, finding format, severity levels, blocking criteria, and tone.
---

# PR Review

A review reports every issue as a finding the author can act on. A review changes no files.

## Rebase on origin/main

1. Run `git fetch origin`.
2. Run `git rebase origin/main`.

If the rebase hits conflicts, resolve them. When both sides changed the same logic substantively, ask the user which side wins. Resolve `.secrets.baseline` conflicts with the `secret-detection` skill.

## Gather Context

1. **Diff**: Collect all changes between `origin/main` and HEAD, plus staged and unstaged working-tree changes. Treat them as one unit. Staging status is never a finding.
2. **PR metadata**: When a PR exists, read the description, review comments, and linked issues (`gh pr view`, `gh pr view --comments`, `gh issue view N`).
3. **Scope**: Compare the PR description against the linked issues. Partial coverage of an issue is acceptable when the PR says so. Unstated gaps and scope drift are findings.
4. **Conventions**: Read `AGENTS.md` and `CONTRIBUTING.md`. Use their linter and test commands exactly.

## Review Order

Review the diff in this order. Severity comes from *Blocking Criteria* below, not from the category.

1. Security: injection, leaked secrets, auth gaps, OWASP top 10, Layer 1 / Layer 2 violations.
2. Correctness: logic errors, edge cases, mismatch with linked issues.
3. Test coverage: changed code has tests, including deny-path tests for security changes.
4. Linter compliance: run project linters on touched files and report violations. Do not fix them (see *Optional Lint Auto-Fix*).
5. Performance: N+1 queries, unnecessary allocations, bottlenecks.
6. Redundancy: duplicated logic, copy-paste patterns, shared-utility opportunities.
7. Design: structural quality (see *Design Guidance*).
8. Consistency: adherence to documented conventions.
9. Alembic migrations (conditional): idempotence, reversibility, cross-database compatibility, `batch_alter_table` for SQLite. Apply the `alembic-migrations` skill.

## Optional Lint Auto-Fix

Never auto-fix formatting during a review. A reviewer who edits the reviewed code changes the PR under review. Report `black`, `isort`, `autoflake`, pylint, bandit, and mypy findings for the author to address. Include the exact command and output.

Run the auto-fix only when the user explicitly asks for it, for example a local developer who reviews their own branch. Fix files the PR touched only. Never run formatters on the whole codebase. That pollutes the diff.

```bash
PY_FILES="$(git diff --diff-filter=d --name-only origin/main -- '*.py')"
if [ -n "$PY_FILES" ]; then
  make autoflake isort black TARGET="$PY_FILES"
fi
```

Run the linters again to check the fixes. Report the fix as a minor finding, for example "Auto-fixed: ran autoflake/isort/black on N files".

## Design Guidance

### Structure and modularity

- **Single-responsibility violations**: Name each responsibility and suggest a split.
- **God functions**: More than 50 lines of logic or more than 3 levels of nesting. Name the extraction points.
- **Long parameter lists**: More than 5 parameters often means a missing config object or dataclass.
- **Tight coupling**: Modules that reach into each other's internals. Suggest an interface boundary.
- **Deep nesting**: Suggest early returns, guard clauses, or extracted helpers.

### Polymorphism

Long `if`/`elif`/`else` chains often want polymorphic dispatch. Look for these in changed code and adjacent code:

- **Type-switching conditionals**, for example `if transport == "sse": ... elif transport == "websocket": ...`. Suggest an ABC or Protocol with one implementation per variant.
- **Behavior chosen by enum or string**. Suggest Strategy or Template Method.
- **Scattered object creation**. Suggest a factory method or registry.
- **Simple dispatch**. A `dict[key, callable]` table is a good intermediate step.
- **Copy-paste behavior across classes**. Suggest a `Protocol` or mixin.
- **Missing abstract parents**. Classes with a shared interface and no common base need an ABC with `@abstractmethod`.

### Missing abstractions

- A pattern repeated at 3 or more call sites needs a shared utility or base class.
- A data class whose related logic lives in other modules needs that logic moved next to the data.

## Second Opinions

After your own review, run these tools as background tasks. If a tool is missing or fails, skip it and note the reduced coverage.

- `codex exec review --base origin/main`
- `git diff origin/main..HEAD | bob "Review this diff for correctness, security, and design quality. Be specific about line-level issues."`

Attribute each finding to its source. Resolve contradictions.

## Finding Format

Write each finding as a compact block that reads well in a GitHub comment:

```markdown
**severity** · `path:line`
Problem: what is wrong and why it matters.
Fix: the concrete change.
```

Use short sentences. Add detail only when the problem or fix needs it. Make each fix concrete: name the method to extract, the class to create, the interface to define. "Consider refactoring" is not a fix. The delivery channel (file, agent toolkit, `gh pr review`) is per-PR. Ask the user which channel applies before you post externally.

## Severity

| Severity | Meaning | Disposition |
|----------|---------|-------------|
| blocking | Meets a blocking criterion with evidence in the diff or linked artifacts | Merge gate. No waiver |
| functionally-impacting | Affects behavior or maintainability, below the blocking bar | Fix before merge unless the PR documents a waiver |
| suggestion | A better way exists. Optional | May be deferred |
| minor | Polish | May be deferred |

## Blocking Criteria

A finding is blocking if and only if it meets one of these criteria with evidence in the diff or linked artifacts. If there is no evidence, the finding is not blocking:

1. Correctness bug in changed code, reachable in real use (includes data loss).
2. Security regression, or a security-sensitive change without deny-path regression tests (unauthenticated, wrong team, insufficient permission, feature disabled).
3. Violates a documented Security Invariant or design decision (see *Authentication & RBAC Overview* and *Synchronous SQLAlchemy in Async Handlers* in `AGENTS.md`).
4. Breaks a consumer contract unflagged: HTTP API, environment variables or their defaults, database schema, Helm values, MCP/A2A wire behavior.
5. Adds or changes a model without a matching Alembic migration.
6. The PR does not deliver what it claims.

When severity stays ambiguous after investigation, mark the finding blocking and name the missing evidence. The next pass resolves it.

Not blocking: style and naming (Ruff owns these), the sync-SQLAlchemy-in-async pattern, doc polish, test-count aesthetics.

## Output

```markdown
# PR Review: [branch-name]

## Summary
[1-2 sentences: what changed, whether it meets the PR and issue goals]

## Findings
[one block per finding, grouped blocking, functionally-impacting, suggestion, minor]

## Recommendation
[Exactly ONE of: "Ready to merge" | "Ready after addressing findings" | "Needs significant rework"]
[1 sentence of justification]
```

## Rules

- Change no files. Report every finding for the author. Run the lint auto-fix only on explicit user request.
- Never mention AI or coding assistants in any output.

## Tone

Courteous by structure, direct by sentence. Lead with what works. State severity so the author knows what must change. Write as a respectful senior colleague: direct about problems, never harsh, never hedged. Prose follows *Agent Prose* in `AGENTS.md`. Before you post, rewrite the summary, findings, and recommendation with the `asd-ste100` skill in STE-flavored mode. Done when each sentence is 25 words or fewer, active, and keeps every severity and hedge.
