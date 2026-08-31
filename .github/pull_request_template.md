<!--
For specialized templates, append to your PR URL:
  ?template=bug_fix.md   - Bug fixes
  ?template=feature.md   - New features
  ?template=docs.md      - Documentation
  ?template=plugin.md    - New plugins

Example: https://github.com/IBM/mcp-context-forge/compare/main...your-branch?expand=1&template=bug_fix.md
-->

# Pull Request

## 🔗 Related Issue

Closes #

---

## 📝 Summary

_What does this PR do and why?_

---

## 📏 Reviewability

- [ ] This PR has one clear purpose
- [ ] The linked issue is not labeled `triage`
- [ ] Unrelated bugs or improvements are tracked in separate issues/PRs
- [ ] Tests are included with the code they validate
- [ ] If AI-assisted, I understand and can explain the generated changes

---

## 🏷️ Type of Change

- [ ] Bug fix
- [ ] Feature / Enhancement
- [ ] Documentation
- [ ] Refactor
- [ ] Chore (deps, CI, tooling)
- [ ] Other (describe below)

---

## 🧪 Verification

_List exact commands, screenshots, videos, logs, reproduction steps, or manual validation. If evidence is not feasible, explain why._

| Check                     | Command         | Status |
|---------------------------|-----------------|--------|
| Lint suite                | `make lint`     |        |
| Unit tests                | `make test`     |        |
| Coverage ≥ 80%            | `make coverage` |        |

---

## ✅ Checklist

- [ ] Code formatted (`make black isort pre-commit`)
- [ ] Tests added/updated for changes
- [ ] Documentation updated (if applicable)
- [ ] No secrets or credentials committed

---

## 📓 Notes (optional)

_Screenshots, design decisions, or additional context._
