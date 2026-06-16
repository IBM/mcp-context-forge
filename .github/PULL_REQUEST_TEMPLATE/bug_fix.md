# 🐛 Bug-fix PR

Before opening this PR please:

1. `make lint`            - passes `ruff`, `mypy`, `pylint`
2. `make test`            - all unit + integration tests green
3. `make coverage`        - ≥ 80 %
4. `make docker docker-run-ssl` or `make podman podman-run-ssl`
5. Update relevant documentation.
6. Tested with sqlite and postgres + redis.
7. Manual regression no longer fails. Ensure the UI and /version work correctly.

---

## 📌 Summary

_What problem does this PR fix and **why**?_

## 🔁 Reproduction Steps

_Link the issue and minimal steps to reproduce the bug._

## 🐞 Root Cause

_What was wrong and where?_

## 💡 Fix Description

_How did you solve it?  Key design points._

## 📏 Reviewability

- [ ] This PR has one clear purpose
- [ ] The linked issue is not labeled `triage`
- [ ] Unrelated bugs or improvements are tracked in separate issues/PRs
- [ ] Tests are included with the code they validate
- [ ] If AI-assisted, I understand and can explain the generated changes

## 🧪 Verification

_List exact commands, screenshots, videos, logs, reproduction steps, or manual validation. If evidence is not feasible, explain why._

| Check                                 | Command              | Status |
|---------------------------------------|----------------------|--------|
| Lint suite                            | `make lint`          |        |
| Unit tests                            | `make test`          |        |
| Coverage ≥ 80 %                       | `make coverage`      |        |
| Manual regression no longer fails     | steps / screenshots  |        |

## 📐 MCP Compliance (if relevant)

- [ ] Matches current MCP spec
- [ ] No breaking change to MCP clients

## ✅ Checklist

- [ ] Code formatted (`make black isort pre-commit`)
- [ ] No secrets/credentials committed
