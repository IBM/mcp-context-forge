---
name: pr-review
description: >-
  Review code changes for quality, security, correctness, and design. Use when
  a feature branch is ready for review, before creating or updating a pull
  request, when asked to check code quality, review changes, look at a diff,
  or verify a branch is merge-ready. Also triggers on phrases like "review my
  code", "what do you think of these changes", or "is this ready to merge".
---

# PR Review

A review-only skill. **Do not modify any files** — produce a report the author
uses to make their own changes.

## Gather context

1. **Diff** — Collect all changes between `origin/main` and HEAD, plus any
   staged/unstaged working-tree changes. This is the review scope. Treat
   all of these changes as a single unit — assume everything will be
   committed before merge. Do not report on git staging status (uncommitted,
   unstaged, etc.) as a finding.

2. **PR metadata** — If a PR exists (`gh pr view`), read the description,
   review comments (`gh pr view --comments`), and linked issues
   (`gh issue view N`) to understand requirements and prior feedback.

3. **Project conventions** — Read `AGENTS.md`, `CONTRIBUTING.md`, or
   `CLAUDE.md` if present. These are authoritative for linter commands, test
   commands, and coding conventions — use their commands exactly.

## Review checklist

Review the diff in priority order. Report all findings for human review.

| # | Category | Severity | Focus |
|---|----------|----------|-------|
| 1 | Security | Blocking | Injection, leaked secrets, auth gaps, OWASP top 10 |
| 2 | Correctness | Blocking | Logic errors, edge cases, mismatch with linked issues |
| 3 | Test coverage | Blocking | Differential coverage — verify changed code has tests |
| 4 | Linter compliance | Blocking | Run project linters on touched files; report findings with exact commands |
| 5 | Performance | High | N+1 queries, unnecessary allocations, bottlenecks |
| 6 | Redundancy | High | Duplicated logic, copy-paste patterns, shared-utility opportunities |
| 7 | Design | High | Structural quality — see guidance below |
| 8 | Consistency | Medium | Adherence to documented conventions |
| 9 | Alembic migrations | Conditional | Idempotence, reversibility, cross-DB compat, `batch_alter_table` for SQLite |

## Design review guidance

### Structure and modularity

- **Single-responsibility violations** — functions or classes doing more than
  one thing. Name what each responsibility is and suggest how to split.
- **God functions** — functions with >50 lines of logic or >3 levels of
  nesting. Identify extraction points.
- **Long parameter lists** — >5 parameters often indicate a missing config
  object or dataclass.
- **Tight coupling** — modules reaching into each other's internals. Suggest
  interface boundaries.
- **Deep nesting** — suggest early returns, guard clauses, or extracted helpers.

### Object-oriented design and polymorphism

This codebase tends toward long if/elif/else chains where polymorphic dispatch
would be cleaner. **Actively look for these opportunities** in changed code and
in code adjacent to changes:

- **Type-switching conditionals** — e.g., `if transport == "sse": ... elif
  transport == "websocket": ...`. Suggest an ABC or Protocol with concrete
  implementations per variant.
- **Conditional behavior by enum/string** — functions branching on a type field.
  Suggest the Strategy or Template Method pattern.
- **Scattered object creation** — conditionals that construct different objects
  by type. Suggest a factory method or registry pattern.
- **Dict-dispatch** — for simpler cases where class hierarchies are overkill,
  `dict[key, callable]` dispatch tables are a good stepping stone.
- **Copy-paste behavior across classes** — suggest a `Protocol` (structural
  subtyping) or mixin.
- **Missing abstract parents** — when classes share an interface but lack a
  common base, suggest an `ABC` with `@abstractmethod`.

### Missing abstractions

- **Repeated patterns** across 3+ call sites → shared utility or base class.
- **Data bags with scattered behavior** — pure data classes whose related logic
  lives in other modules. The behavior should live with the data.

## Second opinions

After your own review, attempt to run these tools as background tasks. If a
tool is not installed or fails, skip it and note the reduced coverage.

- `codex exec review --base origin/main`
- `git diff origin/main..HEAD | bob "Review this diff for correctness, security, and design quality. Be specific about line-level issues."`

Attribute findings to their source and resolve contradictions.

## Output format

```markdown
# PR Review: [branch-name]

## Summary
[1-2 sentence overview: what changed, whether it meets PR/issue goals]

## Findings

### Blocking
| File:Line | Category | Issue | Suggestion |
|-----------|----------|-------|------------|

### High
| File:Line | Category | Issue | Suggestion |
|-----------|----------|-------|------------|

### Medium
| File:Line | Category | Issue | Suggestion |
|-----------|----------|-------|------------|

## Recommendation
[Pick exactly ONE: "Ready to merge" | "Ready after addressing findings" | "Needs significant rework"]
[1 sentence justification]
```

## Rules

- **Do not modify any files.** Report findings for the author to address.
- Never mention Claude, Claude Code, or AI in any output.
- Include exact linter commands and output so the author can reproduce.
- Make suggestions concrete — name the method to extract, the class to create,
  the interface to define. "Consider refactoring" is not actionable.
