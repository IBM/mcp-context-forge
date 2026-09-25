# Deprecations

This page is the registry of deprecated interfaces. Each row carries the
deprecation date, the earliest removal, the migration path, and the current
status.

Rows sort by deprecation date, then earliest removal. Rows without dates sort
last.

The lifecycle rules live in the
[deprecation policy](development/deprecation-policy.md).

## Pending deprecations

{{ read_yaml('tables/deprecations-pending.yaml') }}

The 2026-06-11 deprecations predate the policy. They used a 26-day window.

## Removed

{{ read_yaml('tables/deprecations-removed.yaml') }}

## Documentation gaps

- The `deprecated` lifecycle flag on tools (#4829) and LLM models has no
  user-facing documentation.
