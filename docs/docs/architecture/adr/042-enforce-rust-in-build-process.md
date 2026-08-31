# ADR-0042: Enforce Rust in the Build Process

- *Status:* Proposed
- *Date:* 2026-02-26
- *Deciders:* Core Engineering Team

## Context

ContextForge is introducing **core Rust components** in the main gateway—for example the experimental Rust transport backend (Streamable HTTP, ADR-038) and other performance-critical paths. Concrete examples of what will be implemented as main components can be seen in the [open pull requests with the `rust` label](https://github.com/IBM/mcp-context-forge/pulls?q=is%3Aopen+is%3Apr+label%3Arust). These are **main** gateway features, not optional plugins. If we ship them as optional with Python fallbacks, we incur:

- **Dual code paths**: Core behavior (e.g. transport, protocol handling) would exist in both Rust and Python. Logic and bugs must be maintained in two places.
- **Dual security surface**: Two implementations mean two attack surfaces; security fixes, hardening, and audits must be applied to both. One path may lag or diverge, increasing risk.
- **Double bug surface**: Bugs can exist in either codebase; the same feature may behave or fail differently depending on which path runs. Fixes and regression tests must cover both.
- **Dual testing**: Tests would need to cover "Rust available" and "Rust unavailable"; integration and performance tests would duplicate or skip by path, increasing matrix and fragility.
- **Unpredictable behavior**: Depending on install method or environment, users would get either the Rust or Python implementation; behavior and performance would differ.
- **Poor visibility**: It is not easy to tell which implementation is actually running (Rust vs Python). Operators, support, and users cannot reliably know what they are debugging or what behavior to expect, which complicates troubleshooting and incident response.
- **Documentation and support burden**: Docs would need to describe both code paths and when fallbacks apply; support would need to diagnose which implementation is running.

We want **Rust to be the single implementation** for these core components: the build process must guarantee the Rust extension is present so we do not maintain Python fallbacks, do not maintain or test two implementations, and deliver consistent behavior, security, and visibility.

## Options

Three main approaches to making Rust components mandatory. **Options A and B are complementary and can be done at the same time:** publish wheels for supported platforms (B) and support source build with Rust required when no wheel is available or when the user opts in (A).

### Option A: Enforce Rust at Install Time (Source Build)

**Mechanism:** The main gateway package declares the core Rust extension as a **mandatory** dependency. When no pre-built wheel is used (unsupported platform, or `pip install --no-binary <rust-package> ...`), installation requires the Rust toolchain and triggers a PEP 517 build that compiles the extension locally via maturin.

**Implications:**

- **Prerequisites:** Users and CI must have `rustc`/`cargo` (and typically maturin) installed. Documentation and images must include Rust in "getting started" and base images.
- **Install time:** First install (and any version bump of the Rust crate) incurs compile time (tens of seconds to a few minutes depending on hardware).
- **Platform coverage:** Any platform with a Rust toolchain can build; no need to pre-build wheels for every OS/arch.
- **Supply chain:** No separate wheel publishing or signing for the Rust extension; build from source is the only path.
- **Containers:** Dockerfiles can either use a multi-stage build (Rust stage → copy wheels into runtime image) or install Rust in the final image and build on container build. The former is already used in project Containerfiles.

**Pros:** No wheel publishing pipeline; works on any platform with Rust; single "build from source" story.
**Cons:** Higher barrier for contributors and users (must install Rust); slower and more resource-heavy installs; CI and Docker builds must install and cache Rust.

### Option B: Publish Pre-Built Wheels

**Mechanism:** Build the core Rust extension in CI for a fixed set of platforms (e.g. manylinux x86_64/arm64, macOS x86_64/arm64, Windows), produce wheels via maturin, and publish them to PyPI (or an internal index). The main gateway package depends on that extension; `pip install mcp-contextforge-gateway` pulls the appropriate wheel. No Rust toolchain needed for end users.

**Implications:**

- **Prerequisites:** End users need only Python and pip; no Rust. Contributors who touch Rust still need Rust for local builds and tests.
- **Install time:** Fast: download and unpack wheel (no compile).
- **Platform coverage:** Only platforms for which wheels are built and published are supported "out of the box." Other platforms (e.g. less common Linux arches, older glibc) either need a source fallback (reintroducing dual path) or are unsupported.
- **Supply chain:** Requires wheel build and publish pipeline, signing, and possibly SBOM/provenance (aligned with ADR-0020). Must maintain and extend the matrix (Python version × OS × arch) as needed.
- **Containers:** Same as today: use pre-built wheels in the image, or build from source in a builder stage; no need to install Rust in the final image if wheels are used.

**Pros:** Best UX for most users (no Rust, fast install); consistent behavior and performance for supported platforms.
**Cons:** Wheel build/release and matrix maintenance; unsupported platforms need a clear story (no fallback vs "install Rust and build from source" only).

### Option C: Provide Docker Image with Pre-Installed Gateway

**Mechanism:** Ship an official container image (e.g. on GHCR) with the **gateway pre-installed**—including the core Rust extension already built in. The image is produced in CI (multi-stage build or install of published wheels); the user never sees Rust or pip. Users pull the image and run the container; the gateway is ready to go. No Rust, no `pip install`, no local build—just run the container.

**Implications:**

- **Prerequisites:** For container users, **none**—no Rust, no pip, no Python on the host. Only Docker (or a container runtime). The gateway is already inside the image.
- **Install time:** Pull image and run; no build or install step.
- **Platform coverage:** Image can be built for the same matrix as Option B (e.g. linux/amd64, linux/arm64); multi-arch is standard for containers.
- **Supply chain:** Image build and publish in CI; can be signed and attested (e.g. cosign) per ADR-0020. Rust is used only in CI to produce the image; end users never need it.
- **pip / local install:** Option C does not address "I want to `pip install` and run on my laptop." So C is combined with A or B for those users; the container is the path for anyone who wants zero Rust/pip on their machine.

**Pros:** Users need no Rust at all—pull and run; gateway is pre-installed in the image; single, reproducible artifact; aligns with existing container/Helm strategy (ADR-0020).
**Cons:** Does not remove the need for A or B for non-container users (developers, pip-based installs); image build and multi-arch pipeline must be maintained.

## Decision

*(To be decided: choose Option A, Option B, Option C, or a combination.)*

**Recommended direction:** Do **Option A and Option B together**, plus **Option C** for deployment:

- Add the core Rust extension as a **required** dependency of `mcp-contextforge-gateway` (no optional/extra).
- **Option B:** In CI, build wheels for the supported platform matrix (e.g. manylinux, macOS, Windows; see ADR-0020) and publish to PyPI. On those platforms, `pip install` gets a wheel—no Rust needed.
- **Option A:** When no wheel is available (unsupported platform) or the user chooses source build (e.g. `pip install --no-binary <rust-package> mcp-contextforge-gateway`), require Rust and build from source. A and B together cover both "easy install" and "any platform / from source."
- **Option C:** Provide an official Docker image (and Helm chart using it) with the gateway pre-installed (Rust extension already built in). Users need no Rust or pip—pull and run. Recommend this as the default for production and anyone who prefers zero local toolchain.
- Remove Python fallbacks for core Rust-backed features once the dependency and images/wheels are in place; single code path and single test suite.

**Alternatives:** **Option C only** (container with gateway pre-installed, no wheels) is viable if the project is willing to tell pip users they must have Rust to install from source (Option A) or use the container. **Pure Option A** (no wheels, no pre-built image) is possible but raises the barrier for everyone; the existing Containerfiles already bake Rust-built artifacts into the image, which is a form of C.

## Consequences

### Positive (once enforced)

- Single implementation for Rust-backed features; no Python fallback to maintain.
- Single test suite; no "skip if Rust missing" or dual-path differential tests for those features.
- Predictable behavior and performance for all installs (Rust code always used when the package is installed).
- Clearer docs and support: "install the package" implies Rust extension is present.

### Negative

- **Option A:** Rust becomes a required developer and user dependency; longer and heavier installs; base images and docs must include Rust.
- **Option B:** CI and release process must build, sign, and publish wheels; platform matrix must be maintained; unsupported platforms must either build from source (Rust required there) or be documented as unsupported.
- **Option C:** Does not help pip-only or local-development users; image build and multi-arch pipeline must be maintained. Typically used together with A or B. For container users, no Rust is ever required.

### Risks / Mitigations

- **Option B – broken or missing wheel for a platform:** Mitigate with CI checks (install from wheel on representative OS/arch) and documented "build from source" for edge platforms.
- **Option A – users without Rust:** Mitigate with clear prerequisites; Option C (Docker image with gateway pre-installed) lets deployers avoid Rust entirely—they never need Rust or pip.
- **Option C – image as only path:** If we rely on container-only distribution, pip users and some CI flows need either Rust (A) or wheels (B); document and support at least one of those.

## Contributor impact (barrier to entry)

Making Rust mandatory in the build affects **new and existing contributors** who do not have (or do not want) a Rust toolchain. The barrier is worth documenting so the project can mitigate it explicitly.

- **Who is affected:** Contributors who only work on Python (routers, services, tests, docs), contributors on platforms without a published wheel (e.g. less common Linux arches), and anyone setting up a fresh dev environment (e.g. `make install-dev` or `pip install -e .`).
- **Option A only (source build):** Every contributor must install Rust and maturin to install or run the gateway locally. First-time setup and CI are slower; newcomers used to a Python-only workflow face an extra prerequisite and possible friction (toolchain size, PATH, platform-specific issues). This raises the barrier to contribution for Python-only changes.
- **Option B (wheels):** On supported platforms (e.g. manylinux x86_64/arm64, macOS, Windows), `pip install` can use a pre-built wheel—**no Rust required** for typical Python-only workflows (run tests, change routers/services, run the app). Contributors who never touch Rust code can contribute without installing Rust. Those who modify the Rust extension or work on unsupported platforms still need the Rust toolchain; the barrier is limited to a subset of contributors and tasks.
- **Option C (container):** Does not by itself lower the barrier for local development; it helps deployers. Contributors doing local `pip install` or `make` workflows still depend on A or B.
- **Recommended combination (A + B + C):** With wheels published for the common platform matrix, **most new contributors** (Python-only, on supported OS/arch) can clone, install from wheel, and contribute without ever installing Rust. The barrier to entry is minimized for the common case. The project should document this in contributor onboarding (e.g. CONTRIBUTING, developer docs): "Rust is not required for Python-only contributions on supported platforms; install from the published wheel." For contributors who do need Rust (Rust changes, unsupported platforms, or intentional source build), document a single, clear path: install Rust and maturin, then build from source, with links to official Rust install and any project-specific notes (e.g. minimum `rustc` version, use of `maturin`). Optionally, provide a dev container or dev environment that already includes the Rust toolchain so one-time setup is reproducible and documented.

## Alternatives Considered

| Option | Why Not |
|--------|--------|
| Keep current optional Rust + Python fallback | Per context: double maintenance, double testing, inconsistent behavior. |
| Rust-only with no pip package (e.g. standalone binaries) | Would not integrate with existing Python packaging (ADR-0020) and gateway distribution; would require a different distribution story. |
| Publish wheels only for Linux/macOS, require source elsewhere | Acceptable variant of Option B with a smaller matrix; still need to document and support source build for "elsewhere." |

## Related

- [Open PRs with `rust` label](https://github.com/IBM/mcp-context-forge/pulls?q=is%3Aopen+is%3Apr+label%3Arust) — examples of main Rust components being implemented
- ADR-0020: Multi-Format Packaging Strategy (wheels, containers, Helm)
- ADR-0038: Experimental Rust Transport Backend (Streamable HTTP) — first main Rust component in the gateway
- Plugin crates and Rust MCP servers with their own packaging lifecycle are out of scope for this ADR; they keep their own optional/required policy.
