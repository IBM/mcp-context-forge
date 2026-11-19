# ADR-0059: Helm Chart as Code Example, Not a Release Artifact

- *Status:* Accepted
- *Date:* 2026-11-19
- *Deciders:* Core Engineering Team
- *Supersedes:* ADR-0020 (Helm Charts section only)

## Context

ADR-0020 says the project publishes the `mcp-stack` Helm chart to an OCI registry with each release.

This did not happen in practice. The only published chart is version 0.1.1 at `oci://ghcr.io/ibm/mcp-context-forge/mcp-stack`. It is much older than the chart in the repository. It uses old images and is not a secure deployment.

Each deployment environment has its own requirements. These include Kubernetes and variations, OpenShift, hyperscaler Kubernetes or Openshift variation. One published chart cannot fit all of them without additional effort.

## Decision

The project does not publish the Helm chart as a release artifact.

- The chart in `charts/mcp-stack` is a code example. Users get it from the tagged source release.
- Users build and publish their own chart from the example, or write their own deployment method.
- The project builds the ContextForge container image and the mcp-context-forge pypi package. Users can use that image, the pypi package or build their own image from source.
- The project deletes the published chart 0.1.1 from the registry.

## Consequences

### Positive

- The project focuses on the gateway, not on each Kubernetes flavor.
- Users control the chart contents, the image source, and the publishing channel.
- No stale and insecure chart stays available for download.

### Negative

- Users must maintain their own chart and publishing pipeline.
- Users cannot install with `helm install` from a project registry.
- Users who depend on chart 0.1.1 must migrate.

### Neutral

- The chart stays in the repository, and CI keeps linting it.
- Chart changes follow the normal source release.

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **Publish the chart with each release** | The project would own support for every Kubernetes flavor and deployment model. |
| **Keep the old chart published** | The chart uses old images and is not secure. |
| **Publish to a second channel (Artifact Hub, a Helm repository)** | It adds maintenance work and does not replace per-user customization. |

## References

- Superseded in part: [ADR-0020: Multi-Format Packaging Strategy](020-multi-format-packaging-strategy.md)
- Related: [ADR-0019: Modular Architecture Split](019-modular-architecture-split.md)
- Chart source: `charts/mcp-stack`
