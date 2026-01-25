---
name: Testing (bug, unit, manual. or new test)
about: Add or improve unit tests, integration tests, or perform manual testing
title: "[TESTING]: "
labels: testing, triage
assignees: ''

---

### ✅ Test Summary
Briefly describe what needs to be tested or validated.

---

### 🧪 Test Type
Choose one or more applicable categories:

- [ ] Unit tests (Python)
- [ ] Integration / end-to-end tests
- [ ] Manual UI testing (admin panel)
- [ ] Transport coverage (HTTP, WebSocket, SSE, stdio)
- [ ] Federation / multi-gateway testing
- [ ] Configuration / environment-specific behavior
- [ ] Other (explain below)

---

### 🧬 Scope & Affected Components
Select what this test covers or validates:

- [ ] `mcpgateway` core (API logic, handlers)
- [ ] Admin UI (HTMX / Alpine / Tailwind)
- [ ] Tool/Resource/Prompt logic
- [ ] Federation sync/discovery
- [ ] Server interactions or SSE
- [ ] Auth / JWT / security flows
- [ ] Observability (logging, metrics)
- [ ] Makefile, shell scripts or CLI
- [ ] Containerized setup (Docker/Podman)
- [ ] Other (explain below)

---

### 📋 Acceptance Criteria
What should pass or be verified?

- [ ] All relevant assertions are covered
- [ ] No side-effects or regressions observed
- [ ] Confirmed in multiple environments (if needed)
- [ ] Edge cases and error handling tested
- [ ] Logs and output are clean and expected

---

### 📓 Additional Context & Steps
Include commands, expected behaviors, or test strategy.

```bash
# Example: run coverage locally
make test coverage
pytest tests/test_example.py
```

---

### 🧠 Environment Info (if manual testing)

| Key              | Value                        |
| ---------------- | ---------------------------- |
| Gateway version  | `e.g. main@a1b2c3d`          |
| Python version   | `e.g. 3.11`                  |
| Transport tested | `http`, `ws`, `sse`, `stdio` |
| OS / Platform    | `e.g. macOS, Ubuntu`         |
| Container        | `e.g. Docker, Podman, none`  |

> If applicable (ex: new type of test) add information on how to set this up using CI/CD with GitHub Actions or contribute directly to the workflow in `.github/workflows`

---

### 📎 Related PRs / Issues (optional)

Link any relevant work.
