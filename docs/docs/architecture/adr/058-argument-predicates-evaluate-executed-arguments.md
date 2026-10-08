# ADR 058: Argument predicates evaluate the executed arguments

- Status: Accepted
- Date: 2026-10-06
- Deciders: platform security

## Context

Rule predicates can reference tool arguments as `args.<name>` per
ADR 056. Two candidate sources exist for the values:

1. **Mirrored headers.** The MCP 2026-07-28 tools specification
   (SEP-2243) lets a server advertise a parameter with
   `x-mcp-header`. A conforming client then mirrors the parameter
   value into an `Mcp-Param-<name>` request header on `tools/call`.
2. **Body arguments.** The JSON-RPC request carries the arguments
   the tool will execute.

The first implementation read only the mirrored headers. Two defects
followed, found live against a deny rule on a timezone tool:

- **Bypass.** A caller omitted the header and the predicate never
  evaluated, while the tool still executed with the body argument.
  Every argument predicate was optional to the attacker.
- **Dark rules.** The specification allows the annotation only on a
  property whose type is one primitive. A union type such as
  `["string", "null"]` must not carry it, so clients never learned to
  mirror the parameter, and no rule on it could ever fire.

## Decision

1. **The predicate evaluates the executed arguments.** All four
   serving sites pass the call's body arguments merged with the
   mirrored headers. The body wins on a conflict, because it carries
   what executes. The evaluation runs before tool dispatch on every
   serving path: the JSON-RPC handlers, the streamable transport,
   and the session-affinity owner forward.
2. **Headers supplement, never override.** A mirrored header
   contributes a value only when the body omits the parameter.
3. **Union-typed parameters never receive the annotation.** The
   annotator rejects a property whose `type` is a list, even when one
   branch is a primitive. A validating client drops a whole tool that
   carries the annotation on a union-typed property; the rejection
   keeps the tool listed and the rule live through the body path.
4. **The decision cache keys on the arguments.** The engine cache
   key carries a fingerprint of the evaluated arguments. The stored
   value is the final answer after the catalog overlay ran. A first
   allowed call can no longer satisfy a later call that matches a
   deny rule.
5. **Denials stay opaque on the wire.** A matching deny returns the
   JSON-RPC error `-32003` with the message `Access denied`. The
   transport raises a typed `MCPError` so the SDK's exception ladder
   cannot recast the denial as an internal error.

## Consequences

- Argument rules enforce regardless of client behavior. A client that
  ignores the annotation, or a parameter the specification forbids
  annotating, still evaluates.
- The header path adds defense for parameters the body omits, and
  keeps SEP-2243 clients conformant.
- Predicates see native types from the body and strings from
  headers. See ADR 057 for the `int()` coercion.
- Session-affinity forwarding carries `Mcp-Param-*` headers in its
   envelope. A future proxy that strips them cannot weaken the
   enforcement, because the body arguments remain authoritative.
- The cache stores one entry per distinct argument set. Rules that
   evaluate arguments do not share cache entries with rules that
   do not.

## Alternatives considered

- **Normalize union types to a primitive at advertisement time.**
  Rejected: the gateway would advertise a contract the upstream tool
  does not declare, and the coercion only served the header path,
  which the body evaluation makes redundant.
- **Evaluate mirrored headers only, and require the annotation.**
  Rejected: enforcement that a caller can skip by omitting a header
  is not enforcement.
- **Push the comparison into OpenFGA conditions.** Rejected, as in
  ADR 056 and ADR 057.
