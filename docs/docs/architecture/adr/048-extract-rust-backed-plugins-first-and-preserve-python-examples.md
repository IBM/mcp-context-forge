# ADR-048: Extract Rust-Backed Plugins First and Preserve Python Examples Separately

- *Status:* Accepted
- *Date:* 2026-04-10
- *Deciders:* Platform Team
- *Related:* [ADR-039](039-adopt-fully-independent-plugin-crates-architecture.md), [ADR-047](047-incremental-migration-over-rewrite.md), [PR #3965](https://github.com/IBM/mcp-context-forge/pull/3965), [IBM/cpex-plugins](https://github.com/IBM/cpex-plugins), [IBM/contextforge-examples](https://github.com/IBM/contextforge-examples)

## Context

ContextForge historically carried plugin code in-tree under `plugins/` and
`plugins_rust/`. That model coupled core gateway changes, plugin
implementation changes, plugin packaging, and plugin CI into one repository.

It also encouraged a dual-implementation model for some plugins:

- one Python implementation in-tree
- one Rust implementation in-tree
- fallback or parity logic to switch between them

That dual-path approach increased maintenance cost. Every behavioral change,
bug fix, docs update, test suite change, and release check had to account for
more than one implementation path.

PR [#3965](https://github.com/IBM/mcp-context-forge/pull/3965) changes that
direction by moving managed plugins to standalone `cpex-*` packages installed
from PyPI. At the same time, the team discussed two related but distinct
questions:

1. **Migration order:** which plugins move out first, and where should the old
   Python counterparts live?
2. **Repository operating model:** how should `cpex-plugins` be stabilized
   while its independent testing and release workflow is still being defined?

The external repositories now have distinct roles:

- [`IBM/cpex-plugins`](https://github.com/IBM/cpex-plugins) is the managed
  plugin monorepo for Rust-backed plugins published as Python packages.
- [`IBM/contextforge-examples`](https://github.com/IBM/contextforge-examples)
  is the lightly supported examples repository for sample ContextForge assets,
  including non-production or historical Python plugin examples.

The PR discussion also established a follow-on stabilization plan for
`cpex-plugins`:

- **Step 1:** move plugin code out, keep gateway-facing plugin tests in
  `mcp-context-forge`, and freeze plugin development in `cpex-plugins`
  temporarily.
- **Step 2:** establish an independent testing strategy for `cpex-plugins`
  (for example by cloning `mcp-context-forge` in CI for compatibility tests),
  then unfreeze plugin development.

## Decision

We adopt a **phased plugin extraction strategy** with three explicit rules.

### 1. Move Rust-backed managed plugins out first

The first migration wave targets plugins that already have a Rust-backed,
package-ready shape and can be distributed as pre-built `cpex-*` wheels.

This first wave includes the plugins being migrated in PR #3965:

- `pii_filter`
- `secrets_detection`
- `url_reputation`
- `retry_with_backoff`
- `encoded_exfil_detection`
- `rate_limiter`

These plugins move to `IBM/cpex-plugins` and are consumed by
`mcp-context-forge` through published packages rather than in-tree source.

### 2. Preserve old Python counterparts as examples, not production-managed code

When an older Python implementation is still useful for learning, reference,
or experimentation, it should not remain in the core gateway repository and it
should not be treated as a managed production plugin inside `cpex-plugins`.

Instead, those historical or lightly supported Python implementations belong in
`IBM/contextforge-examples`.

This keeps:

- `mcp-context-forge` focused on gateway integration and compatibility
- `cpex-plugins` focused on managed packaged plugins
- example or legacy Python plugin code available without implying active
  production support

### 3. Defer broader Python-plugin migration until the Rust-backed path is stable

The initial extraction does **not** mean "move all Python plugins now."

The platform first proves the external plugin model with the Rust-backed
managed plugins. Broader migration of additional Python plugins is a later
phase, after:

- package boundaries are stable
- CI boundaries are stable
- gateway compatibility testing is defined
- ownership and release expectations are clearer

## Consequences

### Positive

- Reduces coupling between gateway changes and managed plugin implementation changes.
- Removes the need for a Rust toolchain in the main gateway build for these plugins.
- Makes managed plugin packaging, versioning, and release cadence more independent.
- Preserves old Python implementations without keeping them on the critical path.
- Establishes a cleaner separation between production-managed plugins and examples.
- Creates a lower-risk migration path by proving the model on the Rust-backed set first.
- Removes the need to maintain both Python and Rust production implementations for the same plugin.
- Removes fallback-selection logic whose main purpose was to bridge two maintained implementations.
- Shrinks the test matrix by eliminating parity, fallback, and implementation-selection test cases for migrated plugins.
- Makes plugin behavior easier to reason about because each managed plugin has one supported production path.
- Allows plugin-specific release, ownership, and CI concerns to evolve without repeatedly touching the core gateway repo.
- Reduces unrelated CI breakage in `mcp-context-forge` caused by plugin-internal refactors or packaging work.

### Negative

- Compatibility testing becomes cross-repository rather than purely in-repo.
- There is temporary complexity while tests remain in `mcp-context-forge` but code lives in `cpex-plugins`.
- Contributors must understand three locations instead of one:
  core gateway, managed packaged plugins, and examples.
- Cross-repository changes may need coordinated PRs, tags, and release timing.

### Neutral

- Some test coverage remains gateway-owned even after plugin code moves out.
- Example-repo Python plugins are intentionally lightly supported and should not
  be assumed to have the same release guarantees as managed `cpex-*` packages.

## Rationale

This decision is not only about packaging. It is also about reducing
structural duplication.

### Why avoid dual implementations and fallbacks

Keeping both Python and Rust production implementations for the same plugin
creates ongoing costs:

- two code paths to debug
- two places to apply fixes
- two implementations to keep behaviorally aligned
- extra fallback and parity logic in runtime code
- extra fallback and parity assertions in tests
- more room for version skew, feature skew, and documentation drift

By choosing one managed production implementation per migrated plugin, the
platform avoids carrying "temporary" compatibility layers indefinitely.

This is especially important for plugins like rate limiting, PII detection,
secret detection, encoded exfiltration detection, and retry policy, where
behavioral drift between implementations can quietly become correctness or
operability problems.

### Why use a separate managed-plugin repository

Keeping managed plugins in `cpex-plugins` provides operational advantages:

- plugin release cadence can differ from gateway release cadence
- plugin-specific CI, packaging, and publishing can evolve independently
- plugin ownership is clearer
- plugin code review scope is narrower
- the gateway repo no longer needs to carry all plugin build machinery
- plugin consumers outside the gateway repo can adopt the packages directly

In short, the separate repository turns managed plugins into independently
versioned products instead of subtrees inside the gateway monorepo.

### Why use PyO3-backed packages published to PyPI

The chosen delivery model for these managed plugins is:

- implement the performance-critical core in Rust
- expose the gateway-facing Python module surface through PyO3
- publish pre-built wheels to PyPI as `cpex-*` packages
- install those packages into `mcp-context-forge` with `uv`

This model keeps the runtime integration Python-native while moving the
implementation and packaging concerns out of the gateway repository.

It has several practical advantages:

- `mcp-context-forge` imports plugins as normal Python modules, so the gateway
  integration model does not need a special runtime protocol just to load them
- operators do not need a local Rust toolchain to install or run the migrated
  plugins
- CI in the gateway repo can consume released artifacts instead of rebuilding
  plugin crates every time
- the package boundary is explicit and versioned
- the same package can be used by the gateway, tests, and external consumers

This follows a proven pattern already used by Python-facing Rust projects:
ship fast native code behind a normal Python import surface.

### Why install through `uv` and the `plugins` extra

The gateway should consume these plugins the same way users do: as declared
dependencies, not as hidden in-tree source code.

Using `uv` and the optional `plugins` dependency group makes that explicit:

- plugin dependencies are resolved and locked like other Python dependencies
- CI can opt into plugin support with `uv run --extra plugins ...`
- container builds can install the same dependency set consistently
- plugin runtime behavior is tested against the published package shape rather
  than an in-repo implementation shortcut

This also makes the contract clearer: if a plugin is managed and supported as a
package, the gateway depends on the package artifact, not on its source tree
being present inside `mcp-context-forge`.

## Follow-On Operating Plan

The PR discussion's **Step 1 / Step 2** plan is accepted as a separate
stabilization plan for `cpex-plugins`, not as the definition of the initial
extraction order.

### Step 1

- Move the targeted managed plugins out to `cpex-plugins`.
- Keep gateway-facing plugin tests in `mcp-context-forge`.
- Freeze plugin development in `cpex-plugins` temporarily.

The purpose of this freeze is to avoid unrelated plugin-repo changes breaking
`mcp-context-forge` CI while compatibility testing is still coupled to the
gateway repository.

### Step 2

- Define and implement the long-term compatibility-testing model for
  `cpex-plugins`.
- Likely options include cloning `mcp-context-forge` during plugin CI or
  otherwise running gateway compatibility suites from the plugin repo.
- Once that compatibility loop is reliable, unfreeze plugin development in
  `cpex-plugins`.

## Alternatives Considered

### Keep all plugin code in `mcp-context-forge`

Rejected. This keeps plugin release cadence, Rust build requirements, and core
gateway CI tightly coupled.

### Move all plugins, including Python-only plugins, at once

Rejected for now. This increases migration scope and risk before the external
plugin operating model is proven.

### Keep old Python counterparts inside `cpex-plugins`

Rejected. `cpex-plugins` is the managed packaged-plugin repo, not a home for
historical or example implementations with weaker support guarantees.

### Delete old Python counterparts entirely

Rejected. Some of those implementations are still useful as examples,
reference material, or migration aids.

## References

- [PR #3965](https://github.com/IBM/mcp-context-forge/pull/3965)
- [IBM/cpex-plugins](https://github.com/IBM/cpex-plugins)
- [IBM/contextforge-examples](https://github.com/IBM/contextforge-examples)
- [ADR-039](039-adopt-fully-independent-plugin-crates-architecture.md)
- [ADR-047](047-incremental-migration-over-rewrite.md)
