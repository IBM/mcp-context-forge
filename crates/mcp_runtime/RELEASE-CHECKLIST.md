## Release Checklist

Use this file as the pre-release checklist for the Rust MCP runtime.

Rules:

- Leave every item unchecked in git.
- Check items off only in your working copy after the command or manual check
  completes successfully.
- If an item is not applicable for a specific release candidate, add a short
  note rather than silently skipping it.
- If an item fails because of a known unrelated repo issue, note that
  explicitly before continuing.

## 1. Rust Runtime Inner Loop

- [ ] `make -C crates/mcp_runtime fmt-check`
- [ ] `make -C crates/mcp_runtime check`
- [ ] `make -C crates/mcp_runtime check-all-targets`
- [ ] `make -C crates/mcp_runtime clippy`
- [ ] `make -C crates/mcp_runtime clippy-all`
- [ ] `make -C crates/mcp_runtime test`
- [ ] `make -C crates/mcp_runtime test-rmcp`
- [ ] `make -C crates/mcp_runtime doc-test`
- [ ] `make -C crates/mcp_runtime coverage`

## 2. Repo Formatting And Hygiene

- [ ] `make autoflake`
- [ ] `make isort`
- [ ] `make black`
- [ ] `make pre-commit`

## 3. Python / Backend Quality Gates

- [ ] `make doctest`
- [ ] `make test`
- [ ] `make htmlcov`
- [ ] `make ruff RUFF_MODE=check`
- [ ] `make bandit`
- [ ] `make interrogate`
- [ ] `make pylint`
- [ ] `make verify`

## 4. Web / Frontend Gates

- [ ] `make test-js-coverage`
- [ ] `make lint-web`
- [ ] `make test-ui-smoke`
- [ ] `make test-ui-headless`
- [ ] `uv run pytest tests/playwright/test_version_page.py -q`

## 5. Python Baseline MCP Validation

- [ ] `make testing-down`
- [ ] `make compose-clean`
- [ ] `make docker-prod DOCKER_BUILD_ARGS="--no-cache"`
- [ ] `make testing-up`
- [ ] `curl -sD - http://localhost:8080/health -o /dev/null | rg 'x-contextforge-mcp-'`
- [ ] Confirm `/health` reports Python MCP mode
- [ ] Confirm admin Overview shows `🐍 Python MCP Core`
- [ ] Confirm Version Info shows the MCP Runtime card in Python mode
- [ ] `make test-mcp-protocol-e2e`
- [ ] `make test-mcp-rbac`
- [ ] `make test-mcp-access-matrix`
- [ ] `make 2025-11-25-core`
- [ ] `make 2025-11-25-auth`
- [ ] `make testing-down`
- [ ] `PLUGINS_CONFIG_FILE=plugins/plugin_parity_config.yaml make testing-up`
- [ ] `MCP_PLUGIN_PARITY_EXPECTED_RUNTIME=python make test-mcp-plugin-parity`
- [ ] Confirm Python plugin parity covers `resources/read`, `tools/call`, and `prompts/get`
- [ ] `make testing-down`
- [ ] `make testing-up`
- [ ] Perform one manual `/mcp` tool call and confirm `x-contextforge-mcp-runtime: python`
- [ ] Perform one freshness check against `fast-time-get-system-time`

## 6. Rust Shadow Validation

- [ ] `make testing-rebuild-rust-shadow`
- [ ] `curl -sD - http://localhost:8080/health -o /dev/null | rg 'x-contextforge-mcp-'`
- [ ] Confirm `/health` reports `rust-managed` runtime with Python transport mounted
- [ ] Confirm admin Overview shows Rust runtime present but Python public transport semantics
- [ ] `make test-mcp-protocol-e2e`
- [ ] `make test-mcp-rbac`
- [ ] `make test-mcp-access-matrix`
- [ ] `make 2025-11-25-core`
- [ ] `make 2025-11-25-auth`

## 7. Rust Edge Validation

- [ ] `make testing-rebuild-rust`
- [ ] `curl -sD - http://localhost:8080/health -o /dev/null | rg 'x-contextforge-mcp-'`
- [ ] Confirm `/health` reports Rust transport mounted
- [ ] Confirm admin Overview shows `🦀 Rust MCP Core`
- [ ] Confirm Version Info shows MCP Runtime card with Rust transport mounted
- [ ] `make test-mcp-protocol-e2e`
- [ ] `make test-mcp-rbac`
- [ ] `make test-mcp-access-matrix`
- [ ] `make 2025-11-25-core`
- [ ] `make 2025-11-25-auth`

## 8. Rust Full Validation

- [ ] `make testing-rebuild-rust-full`
- [ ] `curl -sD - http://localhost:8080/health -o /dev/null | rg 'x-contextforge-mcp-'`
- [ ] Confirm `/health` reports Rust transport/session/event-store/resume/live-stream/affinity/auth-reuse mounted as expected
- [ ] Confirm admin Overview shows `🦀 Rust MCP Core`
- [ ] Confirm Version Info shows MCP Runtime card with the expected mounted/core modes
- [ ] `make test-mcp-protocol-e2e`
- [ ] `make test-mcp-rbac`
- [ ] `make test-mcp-access-matrix`
- [ ] `make test-mcp-session-isolation`
- [ ] `make test-mcp-session-isolation-load MCP_ISOLATION_LOAD_RUN_TIME=30s`
- [ ] `make 2025-11-25-core`
- [ ] `make 2025-11-25-auth`
- [ ] `PLUGINS_CONFIG_FILE=plugins/plugin_parity_config.yaml make testing-rebuild-rust-full`
- [ ] `MCP_PLUGIN_PARITY_EXPECTED_RUNTIME=rust make test-mcp-plugin-parity`
- [ ] Confirm Rust plugin parity covers `resources/read`, `tools/call`, and `prompts/get`
- [ ] `make testing-rebuild-rust-full`
- [ ] `uv run pytest tests/e2e_rust/test_mcp_access_matrix.py -q -k 'invalid_arguments_return_structured_error'`
- [ ] Confirm malformed `prompts/get` arguments return MCP `-32602` on the Rust public path instead of an opaque backend decode failure
- [ ] `cargo test --release --manifest-path crates/mcp_runtime/Cargo.toml`
- [ ] Perform one manual `/mcp` tool call and confirm `x-contextforge-mcp-runtime: rust`
- [ ] Perform one manual freshness check against `fast-time-get-system-time`
- [ ] Re-run the Rust full validation with a short session-auth reuse TTL for bounded revocation checks:
  `MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS=2 MCP_RUST_SESSION_AUTH_REUSE_GRACE_SECONDS=1 make testing-rebuild-rust-full`
- [ ] Re-run `make test-mcp-session-isolation` on the short-TTL stack
- [ ] Re-run `make test-mcp-session-isolation-load MCP_ISOLATION_LOAD_RUN_TIME=30s` on the short-TTL stack
- [ ] Re-run `make test-mcp-access-matrix` on the short-TTL stack

## 9. Optional PostgreSQL TLS Validation

These checks are required for any release that claims Rust PostgreSQL TLS
support beyond local non-TLS compose testing.

- [ ] Validate Python runtime against a PostgreSQL deployment that requires TLS (`DATABASE_URL=...?...sslmode=require`)
- [ ] Validate Rust runtime against a PostgreSQL deployment that requires TLS (`MCP_RUST_DATABASE_URL=...?...sslmode=require`)
- [ ] Validate Rust runtime against a PostgreSQL deployment using `sslmode=prefer`
- [ ] Validate Rust runtime against a PostgreSQL deployment using `sslrootcert=/path/to/ca.pem`
- [ ] Confirm the Rust runtime still starts and serves requests against a non-TLS local PostgreSQL deployment
- [ ] Confirm unsupported `sslcert` / `sslkey` inputs fail fast with a clear startup/config error

## 10. MCP Runtime UI Validation

- [ ] Open `http://localhost:8080/admin/`
- [ ] Confirm Overview shows `🐍 Python MCP Core` in Python mode
- [ ] Confirm Overview shows `🦀 Rust MCP Core` in Rust mode
- [ ] Confirm Version Info shows the MCP Runtime card
- [ ] Confirm Version Info reflects mounted transport/core modes correctly
- [ ] Confirm runtime mode badges match `/health`

## 10a. Optional Embedded UI Validation

- [ ] `make embedded-up`
- [ ] `make embedded-status`
- [ ] Confirm the embedded stack comes up cleanly with the iframe-safe UI mode
- [ ] Open the embedded/admin surface and confirm MCP Runtime indicators still render correctly
- [ ] `make embedded-down`
- [ ] `make embedded-clean`

## 10b. Optional Minikube / Helm Validation

- [ ] `make helm-lint`
- [ ] `make helm-package`
- [ ] `make minikube-start`
- [ ] `make minikube-context`
- [ ] `make minikube-image-load`
- [ ] `VALUES=charts/mcp-stack/values-minikube.yaml NAMESPACE=mcp-private RELEASE_NAME=mcp-stack make helm-deploy`
- [ ] `make minikube-status`
- [ ] `kubectl get all -n mcp-private`
- [ ] `helm status mcp-stack -n mcp-private --show-desc`
- [ ] `make minikube-port-forward`
- [ ] Confirm `/health` is reachable through the Minikube deployment
- [ ] Confirm the admin UI loads through the Minikube deployment
- [ ] Run at least one MCP protocol check against the Minikube deployment (`make test-mcp-protocol-e2e` with the base URL pointed at the forwarded service)
- [ ] If re-install validation is required, run the explicit cleanup/reinstall flow:
  `helm list -A | grep mcp-stack`
- [ ] `helm uninstall mcp-stack -n mcp-private`
- [ ] `kubectl delete pvc --all -n mcp-private` when data reset is acceptable
- [ ] `kubectl delete namespace mcp-private` when namespace reset is acceptable
- [ ] `kubectl create namespace mcp-private`
- [ ] `helm upgrade --install mcp-stack charts/mcp-stack --namespace mcp-private -f charts/mcp-stack/values-minikube.yaml --wait --timeout 15m --debug`
- [ ] `kubectl get all -n mcp-private`
- [ ] `helm status mcp-stack -n mcp-private --show-desc`
- [ ] `RELEASE_NAME=mcp-stack NAMESPACE=mcp-private make helm-delete`

Note:
- if validating a Rust-enabled direct Minikube/Helm gateway path (`RUST_MCP_MODE=edge|full`),
  explicitly verify MCP responses are not app-level compressed with `zstd`
  on the direct service path, or disable app-level compression for that lane
  until MCP compression bypass is fixed

## 10c. Upgrade / Migration Validation

- [ ] `make upgrade-validate`
- [ ] Confirm the default upgrade base image is still `ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2`
- [ ] `make migration-test-postgres`
- [ ] `make migration-test-sqlite`
- [ ] Review upgrade logs for Alembic failures, startup regressions, or post-upgrade data loss
- [ ] If validating a Helm release originally installed from `1.0.0-BETA-2`, apply the documented one-time MinIO selector workaround when needed:
  `kubectl delete deployment -n mcp-private mcp-stack-minio`
- [ ] Re-run the Helm upgrade after the BETA-2 MinIO workaround and confirm success

## 11. Benchmarking

- [ ] `make benchmark-mcp-mixed`
- [ ] `make benchmark-mcp-tools`
- [ ] `make benchmark-mcp-mixed-300`
- [ ] `make benchmark-mcp-tools-300`
- [ ] `make benchmark-mcp-tools-300 MCP_BENCHMARK_HIGH_USERS=1000 MCP_BENCHMARK_HIGH_RUN_TIME=60s`
- [ ] `make benchmark-mcp-tools-300 MCP_BENCHMARK_HIGH_USERS=1000 MCP_BENCHMARK_HIGH_RUN_TIME=300s`
- [ ] Compare results against `crates/mcp_runtime/STATUS.md`
- [ ] Note any regression or unexpected failure count before release
- [ ] Record Python baseline tools-only benchmark numbers for comparison
- [ ] Record Rust full tools-only benchmark numbers for comparison

## 11a. Optional MCP Compliance Artifacts

- [ ] `make 2025-11-25-report`
- [ ] Review generated artifacts under `artifacts/mcp-2025-11-25/`

## 12. Profiling

- [ ] `make -C crates/mcp_runtime setup-profiling`
- [ ] `make -C crates/mcp_runtime flamegraph-test`
- [ ] `make -C crates/mcp_runtime flamegraph-test-rmcp`
- [ ] Review artifacts under `crates/mcp_runtime/profiles/`
- [ ] Confirm any performance-sensitive change has a profiling note or rationale

## 13. SonarQube Static Analysis

Run a full SonarQube scan with Clippy enabled against the Rust runtime.
See `todo/sonar-rust.md` for detailed reproduction steps and prior findings.

```bash
# Start SonarQube and fix ES disk watermarks
make sonar-up-docker
docker exec mcp-context-forge-sonarqube-1 bash -c \
  'wget -q -O- --method=PUT \
    --body-data="{\"persistent\":{\"cluster.routing.allocation.disk.watermark.flood_stage\":\"99%\",\"cluster.routing.allocation.disk.watermark.high\":\"98%\",\"cluster.routing.allocation.disk.watermark.low\":\"97%\"}}" \
    --header="Content-Type: application/json" "http://localhost:9001/_cluster/settings"'
docker exec mcp-context-forge-sonarqube-1 bash -c \
  'wget -q -O- --method=PUT \
    --body-data="{\"index.blocks.read_only_allow_delete\": null}" \
    --header="Content-Type: application/json" "http://localhost:9001/_all/_settings"'

# Build the Rust-enabled scanner image (one-time)
docker build -t sonar-scanner-rust:latest -f- /tmp <<'DOCKERFILE'
FROM docker.io/sonarsource/sonar-scanner-cli:latest
USER root
RUN dnf install -y gcc make openssl-devel pkgconfig git && dnf clean all
ENV RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo
ENV PATH="/usr/local/cargo/bin:${PATH}"
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain stable --profile minimal --component clippy
RUN chmod -R a+rwX /usr/local/cargo /usr/local/rustup
USER scanner-cli
DOCKERFILE

# Create project and token (skip if already exists)
curl -s -u admin:admin -X POST \
  "http://localhost:9000/api/projects/create?name=mcp-runtime-rust&project=mcp-runtime-rust"
TOKEN=$(curl -s -u admin:admin -X POST \
  "http://localhost:9000/api/user_tokens/generate?name=scan-$(date +%s)" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

# Run the scan
docker run --rm \
  --network mcp-context-forge_sonarnet \
  -v "$PWD/crates/mcp_runtime:/usr/src:ro" \
  -e SONAR_HOST_URL="http://sonarqube:9000" \
  -e SONAR_TOKEN="$TOKEN" \
  -e CARGO_TARGET_DIR="/tmp/cargo-target" \
  sonar-scanner-rust:latest \
  -Dsonar.projectKey=mcp-runtime-rust \
  -Dsonar.sources=src \
  -Dsonar.tests=tests \
  -Dsonar.exclusions="**/target/**,**/*.lock" \
  -Dsonar.scm.disabled=true

# View results
echo "Dashboard: http://localhost:9000/dashboard?id=mcp-runtime-rust"
```

- [ ] SonarQube quality gate passes (status: OK)
- [ ] No new bugs or vulnerabilities introduced
- [ ] No new security hotspots
- [ ] Clippy sensor ran successfully (check scanner output for `Sensor Clippy [rust] (done)` without `ERROR Failed to run Clippy`)
- [ ] Cognitive complexity issues are not worse than the baseline in `todo/sonar-rust.md`
- [ ] Duplication percentage is not significantly worse than baseline (13.2% as of 2026-03-15)
- [ ] Review any new findings against `todo/sonar-rust.md` and note regressions

## 14. Security / Correctness Review

- [ ] Review `todo/code-review.md`
- [ ] Review `todo/findings.md`
- [ ] Review `todo/sonar-rust.md`
- [ ] Review `crates/mcp_runtime/STATUS.md`
- [ ] Confirm remaining open items are documented and acceptable for release
- [ ] Recheck that direct public Rust ingress strips internal-only headers
- [ ] Recheck that session ownership / auth-binding isolation tests still pass
- [ ] Recheck that error responses do not leak internal transport details on the Rust path
- [ ] Review Rust `/health` `runtime_stats` and confirm reuse/fallback/denial counters look sane during the validation run

## 15. Docs And Release Docs

- [ ] Review `crates/mcp_runtime/README.md`
- [ ] Review `crates/mcp_runtime/STATUS.md`
- [ ] Review `crates/mcp_runtime/TESTING-DESIGN.md`
- [ ] Review `crates/mcp_runtime/DEVELOPING.md`
- [ ] Review `docs/docs/architecture/rust-mcp-runtime.md`
- [ ] Review `docs/docs/architecture/adr/043-rust-mcp-runtime-sidecar-mode-model.md`
- [ ] Review `docs/docs/testing/index.md`
- [ ] Review `docs/docs/testing/performance.md`
- [ ] Review `docs/docs/development/profiling.md`
- [ ] `cd docs && make build`

## 16. Final Release Notes

- [ ] Record final Python baseline MCP result summary
- [ ] Record final Rust full MCP result summary
- [ ] Record final benchmark summary
- [ ] Record final profiling summary
- [ ] Record any known caveats or follow-up items
- [ ] Confirm this file is left unchecked before commit
