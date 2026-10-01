# Coding Standards: Clean Code

This page turns *Clean Code* (Robert C. Martin) into rules an agent can apply directly in this repository. Every rule is checkable: you can look at the code and answer yes or no.

Style mechanics (formatting, naming conventions, import order, lint gates) live in the root `AGENTS.md` under *Coding Standards*. This page covers readability: names, functions, comments, structure, error handling, and boundaries.

## Scope

Apply these rules to code you write or modify. Do not mass-refactor working code you did not touch — clean the code in your change, and leave neighboring code alone unless it violates a rule in a way that causes bugs.

Languages: Python (`mcpgateway/`, `plugins/`, `mcp-servers/`), Rust (`crates/`), TypeScript/JavaScript (Admin UI). Examples are Python; the rules transfer.

## Names

1. A name states what the thing is or does. `validate_tool_payload` tells the truth; `process_data` does not.
2. Follow repo convention: `snake_case` functions and variables, `PascalCase` classes, `UPPER_CASE` constants.
3. One concept, one word, at least per module. `fetch`, `retrieve`, and `get` are one concept — pick one and keep it.
4. Use the encodings the codebase already uses (`Db` prefix for ORM models, `Pydantic` alias prefix). Invent no new ones.
5. Booleans read as predicates: `is_active`, `has_scope`, `can_execute`.
6. Delete disinformation. A name that understates or overstates scope misleads harder than a vague one.

## Functions

1. One function does one thing. When you can extract a function and name a step of the current function with it, extract it.
2. Keep functions small. A function past ~50 lines gets a second look; past ~100, split it or record why not. These numbers trigger attention; they are not hard gates.
3. Few arguments. Prefer 3 positional or fewer; move to a dataclass or keyword-only arguments beyond that.
4. A boolean that switches a function between two behaviors is two functions. A boolean that filters a query is a parameter.
5. Command-query separation: a function performs an action or returns data. Repository exception: service methods that mutate and return the updated record — the return value documents the new state.
6. A `get_*` or `list_*` function never mutates persisted state.
7. Raise the specific exception (`ToolNotFoundError`, `PermissionError`). Return `None` for "absent", never for "failed".

## Comments: Last Resort

1. Make the code self-documenting first. Extract a function, rename a variable, introduce an explaining constant — keep going until the comment you were about to write becomes redundant.
2. A comment earns its place only when the code cannot express the content:
   - a security invariant and why it fails closed,
   - a workaround for an upstream bug, with the link,
   - a dependency pin and what breaks without it,
   - a protocol or regulatory constraint external to the code.
3. Comments never carry transient implementation process or decisions. Route each to its owner:
   - an architectural decision goes to an ADR (`docs/docs/architecture/adr/`),
   - implementation process goes to the commit body,
   - future work goes to a GitHub issue.
4. Delete on sight: commented-out code, change history ("now uses X", "fixed in #123" — the commit owns this), narration of what the next line does.
5. A `TODO` names its issue number, or becomes one.
6. Docstrings are API contract, not comments. Presence and parameter coverage are enforced (Ruff `D1`/`D417`, interrogate). Summary line first, then the contract. Prose follows the [Agent Prose Standard](agent-prose.md).

## Structure

1. One responsibility per class and module. The moment a service validates schemas and also sends notifications, split it.
2. Keep related code together and declare near first use.
3. Behavior that belongs to one model lives in one service; keep it out of routers and away from duplication.
4. Hide chains. `gateway.peer_cache.entries.keys()` inside a method is fine; passing that chain around the codebase is not.

## Error Handling

1. Catch what you handle; let the rest propagate. `except Exception` appears only at a genuine boundary (request handler, task runner) that converts the failure to a response or a log.
2. Never swallow silently. A handler that logs and continues states why continuing is safe.
3. Fail closed on security paths: an unknown auth mode rejects; it never defaults.
4. Error text carries the technical name verbatim (`QueuePool limit exceeded`) plus the context an operator needs.  For security, HTTP responses do NOT contain technical names that would reveal implementation structure or details.

## Boundaries

1. Validate at the edge: Pydantic schemas own input validation at the routers; internals trust typed inputs.
2. Wrap external services (httpx, redis, cpex): map their failures to repo exception types in one place.
3. Adapt third-party return types at the boundary; do not leak them past the service layer.

## Tests

Clean tests guard the rules above; full conventions live in `tests/AGENTS.md`. The readability rules that apply to tests: a test name states the behavior (`test_expired_token_is_rejected`), one behavioral concept per test, arrange-act-assert structure.

## What Not to Refactor

- The synchronous-SQLAlchemy-in-async-handlers pattern — a documented design decision (root `AGENTS.md`).
- Dependency-pin comments in `pyproject.toml` — the durable-constraint comment done right.
- Alembic migrations already merged — historical record.

## Checking Your Work

A change meets this standard when:

- [ ] Every name you added states its purpose.
- [ ] Every function you wrote or touched does one thing.
- [ ] Every comment you added or kept states a constraint the code cannot express.
- [ ] No comment carries process, history, or decisions.
- [ ] `make ruff interrogate pylint` and `make mypy` pass on your files.
