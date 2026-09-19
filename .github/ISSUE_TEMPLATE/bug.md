---
name: Bug report
about: Report behavior that works incorrectly.
labels: ["triage"]
assignees: ''
type: Bug
---

<!--
Maintainers fix reproducible reports faster. Fill every section not marked optional.
Bugs stand alone or nest under an Epic, Feature, Story, or Task.
Link this bug as a sub-issue of the work it blocks.
Never paste secrets, credentials, or tokens.
-->

### Existing issue check

<!-- Search open and closed issues before filing. -->

- [ ] I searched the existing issues for this bug

### Bug summary

<!-- State what works incorrectly and where. -->

### Steps to reproduce

<!--
1. Start the gateway with this configuration: ...
2. Call this endpoint or run this command: ...
3. Observe: ...
-->

### Expected behavior

<!-- Describe the behavior you expect. -->

### Actual behavior

<!-- Describe what happened. Include the full error text. -->

### Affected area

<!-- Check every area involved. -->

- [ ] Gateway core (API, services, middleware)
- [ ] Admin UI
- [ ] Federation or transports (SSE, WebSocket, stdio, gRPC)
- [ ] Auth, RBAC, or security
- [ ] Rust runtime (crates/mcp_runtime)
- [ ] CLI, Makefile, or scripts
- [ ] Containers or CI
- [ ] Documentation
- [ ] Other

### Log output (optional)

<!-- Paste stack traces or log lines. Never paste secrets. -->

```shell

```

### Environment

<!-- The `/version` endpoint reports most values. -->

- Version or commit:
- Runtime:
- Platform / OS:
- Container:

### Additional context (optional)

<!-- List configuration details, workarounds tried, or related issues. -->
