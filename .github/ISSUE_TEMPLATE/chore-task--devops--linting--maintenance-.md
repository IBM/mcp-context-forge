---
name: Chore Task (devops, linting, maintenance)
about: Internal devops, CI/CD, linting, formatting, dependency hygiene, or project
  maintenance
title: "[CHORE]: "
labels: chore, cicd, devops, triage
assignees: ''

---

### 🔧 Chore Summary

Provide a brief summary of the maintenance task or internal tooling update you're proposing or working on.

---

### 🧱 Area Affected

Choose the general area(s) that this chore affects:

- [ ] GitHub Actions / CI Pipelines
- [ ] Pre-commit hooks / linters
- [ ] Formatting (black, isort, ruff, etc.)
- [ ] Type-checking (mypy, pyright, pytype, etc.)
- [ ] Dependency cleanup or updates
- [ ] Build system or `Makefile`
- [ ] Containerization (Docker/Podman)
- [ ] Docs or spellcheck
- [ ] SBOM, CVE scans, licenses, or security checks
- [ ] Other:

---

### ⚙️ Context / Rationale

Why is this task needed? Does it reduce tech debt, unblock other work, or improve DX/CI reliability?

---

### 📦 Related Make Targets

Reference any relevant Makefile targets that are involved, if applicable. Ex:

- `make lint` - run ruff, mypy, flake8, etc.
- `make pre-commit` - run pre-configured hooks
- `make install-web-linters` - installs npm-based linters
- `make sonar-submit-docker` - run SonarQube scanner via Docker
- `make sbom` - generate CycloneDX software bill of materials
- `make pip-licenses` - generate markdown license inventory
- `make spellcheck` - spell-check source + docs
- `make update` - update Python dependencies in the venv
- `make check-env` - validate required `.env` entries

---

### 📋 Acceptance Criteria

Define what "done" looks like for this task.

- [ ] Linter runs cleanly (`make lint`)
- [ ] CI passes with no regressions
- [ ] Docs/tooling updated (if applicable)
- [ ] Security scans pass

---

### 🧩 Additional Notes

(Optional) Include any configs, environment quirks, or dependencies (e.g. Python, Node, Docker, CI secrets).
