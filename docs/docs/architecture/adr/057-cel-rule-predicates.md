# ADR 057: CEL rule predicates

- Status: Accepted
- Date: 2026-10-06
- Deciders: platform security

## Context

ADR 056 shipped the rule catalog with a hand-written predicate grammar.
The grammar copied a subset of the CPEX Agent Policy Language. It
covered equality, ordering, membership, existence, and Boolean joins.

Three problems emerged:

1. The grammar could not express a prefix check. Operators wrote long
   alternation lists to deny every `US/` timezone one by one.
2. The grammar shared no syntax with the engine. OpenFGA conditions
   are CEL expressions, so a catalog predicate could not move into an
   authorization model without a rewrite.
3. Every new operator needed bespoke parser and evaluator code. The
   parser, not policy need, set the grammar's ceiling.

The grammar had not reached `main`; it lived only in the open review
stack. No released deployment stored APL predicates.

## Decision

1. **Predicates are CEL expressions.** `rule_predicate.py` compiles
   and evaluates predicates through the `celpy` interpreter
   (the cloud-custodian pure-Python CEL implementation). The public
   surface keeps its names: `parse_predicate`,
   `evaluate_predicate`, and `PredicateSyntaxError`.
2. **The attribute families stay.** Predicates bind `subject.id`,
   `authenticated`, `token.is_admin`, `role.<name>`, `team.<id>`, and
   `args.<name>`. A predicate reads the same values it read before.
3. **Expressions match OpenFGA condition syntax.** Comparisons,
   `&&`, `||`, `in`, `startsWith`, `endsWith`, `matches`, and `size`
   work. A predicate can move between the catalog and an OpenFGA
   condition without a rewrite, subject to the typed-parameter rules
   of the target model.
4. **Evaluation fails closed.** A missing attribute is false. An
   evaluation error is false. An allow rule without a match grants
   nothing. A deny rule without a match leaves the base decision in
   force.
5. **Validation runs a canary.** Parse time evaluates the expression
   against empty families. The canary rejects an undeclared top-level
   identifier with 422 before the rule is stored. A missing member
   inside a bound family stays legal, because optional attributes are
   normal.
6. **`contains` is rejected.** `celpy` returns false for true
   substring matches. A rule that used `contains` would silently stop
   matching, so the API rejects it and points to
   `matches('.*<text>.*')`.
7. **Numeric header values coerce explicitly.** Mirrored header
   values arrive as strings. Write `int(args.depth) > 2` for them.
   Body arguments keep their native types.
8. **The annotator collects references from the text.** The
   `x-mcp-header` annotator learns its parameter names from
   `args.<name>` references in the expression text. It strips string
   literals first, so a quoted name never counts as a reference.

## Consequences

- Prefix, suffix, regex, and list tests work in one line. The
  timezone demo rule collapsed from a 20-term alternation to
  `args.target_timezone.startsWith('US/')`.
- `cel-python` is a runtime dependency of the enforcement path. The
  compile cache bounds interpreter cost: each predicate text compiles
  once per process, capped at 512 entries.
- The interpreter, not our parser, owns grammar edge cases. Its
  `contains` defect is one such case; the validation layer rejects
  that one form rather than patching the interpreter.
- The model-sync subject mapping reads the plain `role.<name>` and
  `team.<name>` forms from the expression text. Richer predicates
  evaluate gateway-side only, as in ADR 056.
- A predicate that must move into an OpenFGA condition should compare
  against values of the declared parameter types. The gateway binds
  header strings; the engine binds typed parameters.

## Alternatives considered

- **Extend the APL grammar with a prefix operator.** Rejected: each
  operator stays bespoke and the dialect keeps drifting from the
  engine.
- **Adopt the full CPEX Agent Policy Language.** Rejected: no
  maintained Python interpreter exists, and the language exceeds the
  catalog's need.
- **Compile predicates into OpenFGA conditions.** Rejected, as in
  ADR 056: rule CRUD would rewrite the authorization model on every
  change, and the database provider has no condition engine.
