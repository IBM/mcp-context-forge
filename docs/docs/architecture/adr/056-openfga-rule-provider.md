# ADR 056: OpenFGA rule provider for Layer-2 RBAC

- Status: Accepted
- Date: 2026-10-03
- Deciders: platform security

## Context

Layer-2 RBAC lived inline: route decorators called
`PermissionService` from 14 modules through 28 construction sites, and
the rule set existed only as role rows. Operators could not edit rules
at the capability level, and no alternate decision engine could run
without a fork of the enforcement path.

## Decision

1. **Provider seam.** `get_rule_provider(db)` in
   `mcpgateway/services/rule_provider.py` selects the Layer-2 engine
   from `RBAC_RULE_PROVIDER` (`db` default, `openfga` engine). Consumer
   modules alias the factory under the historical `PermissionService`
   name so call sites and test patch targets stay stable. Layer-1 token
   scoping (`token_scope_grants`) never passes through the seam.
2. **Editable rule catalog.** `rbac_rules` rows in the CPEX APL taxonomy
   (capability type and id, optional permission narrow, phase,
   predicate, effect, priority) apply as a deny-wins overlay around the
   role decision. The seed mirrors the built-in role matrix one-to-one
   with an explicit permission per row, so an unedited catalog changes
   no decision. `/rbac/rules` CRUD sits behind `rbac.rules.manage`.
3. **OpenFGA as engine, database as source of truth.** The gateway
   database owns identity and rules. `openfga_sync` mirrors them as
   tuples (role assignments, memberships, role-permission grants on
   type marker objects, simple entity rules as grants or blocked tuples) and
   a reconciliation loop repairs SQL-level drift. Predicates richer
   than `role.` or `team.` truthiness stay database-side because
   OpenFGA tuples carry no predicate grammar.
4. **Marker objects for type-wide grants.** OpenFGA rejects typed
   wildcards as tuple objects, so role-permission grants target the
   marker ``<type>:all``. The sync writes the markers and the provider
   queries them. A live engine check drove this rule.
5. **Fail-closed floor.** A check denies when no authority can answer
   it. Transport failures log an ERROR and fall through to the
   database provider. The check denies only when the database check
   also fails or denies. `RBAC_RULE_PROVIDER_SHADOW` runs both
   engines, enforces the db answer, and logs divergence as the
   cutover rehearsal.
6. **Domain hierarchy as the tenant abstraction.** The authorization
   model carries a `domain` type with `member` and `admin` relations.
   Capability types parent to domains and traverse through
   `tupleToUserset`. A domain maps a ContextForge team, an Entra
   group, or a Keycloak role without model changes.
7. **JWT claims as the membership authority.** Check-time requests
   carry contextual domain tuples built from the token's `teams` and
   `roles` claims. No stored user-to-domain tuples exist. Tokens
   without team claims fall back to `email_team_members` reads.
8. **Database bridge for engine denials.** A check the engine answers
   with deny, an empty permission set, or a transport failure falls
   through to the database provider before the gateway returns 403.
   The bridge covers principals whose tuples have not reconciled
   yet. Bridged answers never enter the decision cache: they track
   live role rows and heal as the engine converges.

## Consequences

- Two invariants hold by construction: Layer 1 stays outside the
  provider, and no check fails open. A denial requires both the
  engine and the database to deny or fail.
- The OpenFGA provider keeps `PermissionAuditLog` parity so Admin UI
  audit views survive the engine swap.
- Ownership and team-scoped admin semantics remain on the database
  bridge in the engine provider. The mirrored model carries no
  ownership edges.
- Every Gunicorn worker runs its own reconciliation loop. Tuple
  writes treat the already-exists and already-absent replies as
  success, so concurrent workers converge without batch failures.
  Deletes apply before writes so a tuple with a changed condition is
  rewritten in one pass.
- Domain objects in contextual tuples must satisfy the engine's
  object-id grammar. Team names with spaces or apostrophes are
  rejected at check time and the engine retries without contextual
  tuples. Domain identifiers must use engine-safe characters.
- Both providers ship indefinitely. Nothing deprecates. The flag controls
  the cutover.

## Alternatives considered

- **Patch the OpenFGA SDK into every call site.** Rejected: 318 test
  patches and 28 sites would churn, and Layer 1 would blur into the
  engine.
- **OpenFGA as the source of truth.** Rejected: alembic data
  migrations and admin tooling write SQL directly. Reconciliation from
  the gateway database keeps one authority.
- **Full predicate compilation to OpenFGA conditions.** Rejected for
  rule predicates: the APL subset covers seeded rules and full
  compilation would couple the grammar to the engine version. One
  condition is adopted: ``non_expired_grant`` enforces role-assignment
  expiry at check time, with the window stored as tuple context.
