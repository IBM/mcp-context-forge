# Pull Request

## 🔗 Related Issue

Closes #

---

## 📝 Summary

Stop the `detect-secrets` pre-commit hook from rewriting `.secrets.baseline` or failing solely because baseline metadata changes.

### Problem

The stock `detect-secrets-hook` does two things:

1. It scans files for secrets (API keys, passwords, tokens).
2. It updates `.secrets.baseline` when a known secret moves to another line or disappears.

The second behavior causes avoidable delays:

- The hook writes the new `line_number` values into the committed baseline.
- The hook then exits with code 3 and fails the commit.
- The author stages `.secrets.baseline` and commits again.
- Every unrelated line shift in a file with an audited secret adds a diff to the baseline.

Secret matching does not use `line_number`. The scanner compares `hashed_secret` per file. The rewrite also restamps `generated_at` on every change. Both fields add Git diff noise and merge conflicts without changing any verdict.

### Change

- Add `scripts/git/detect-secrets-hook-readonly.sh`. The script copies `.secrets.baseline` to a temporary file and runs `detect-secrets-hook` against the copy. The committed baseline is never modified.
- Change the `detect-secrets` hook in `.pre-commit-config.yaml` from the upstream `ibm/detect-secrets` repo hook to a `local` hook. The hook runs the wrapper script. The `detect-secrets` revision stays pinned to the same commit (`0.13.1+ibm.64.dss`) through `additional_dependencies`.
- Keep the hook arguments unchanged: `--use-all-plugins` and `--fail-on-unaudited`.

### How the wrapper script works

1. **First run.** `detect-secrets-hook` may update the temporary baseline and exit with code 3.
2. **Second run.** After exit code 3, the script runs the hook again on the updated temporary baseline.
3. **Verdict.** The script returns the second scan's exit code. New secrets and unaudited findings still fail the hook.

Any other first-run exit code returns unchanged. The hook never hides a real finding.

### Baseline maintenance

The wrapper does not refresh `.secrets.baseline`. Use the existing targets to refresh it:

- `make detect-secrets-scan` scans files changed against `main` and merges the result into the baseline.
- `make detect-secrets-scan-all` rescans the whole repository.
- `make detect-secrets-audit` marks findings as real or false positive.

A moved `line_number` does not fail the hook. The committed baseline remains unchanged.

---

## 📏 Reviewability

- [x] This PR has one clear purpose
- [ ] The linked issue is not labeled `triage`
- [x] Unrelated bugs or improvements are tracked in separate issues/PRs
- [ ] Tests are included with the code they validate (no unit tests; verified by running the hook, see Verification)
- [ ] If AI-assisted, I understand and can explain the generated changes

---

## 🏷️ Type of Change

- [ ] Bug fix
- [ ] Feature / Enhancement
- [ ] Documentation
- [ ] Refactor
- [x] Chore (deps, CI, tooling)
- [ ] Other (describe below)

---

## 🧪 Verification

| Check                          | Command                                                            | Status |
|--------------------------------|--------------------------------------------------------------------|--------|
| Hook passes with clean tree    | `pre-commit run detect-secrets --files Makefile mcpgateway/config.py` | Passed |
| Baseline unchanged by the hook | `git status --short .secrets.baseline`                             | Clean  |
| Baseline regeneration          | `make detect-secrets-scan`                                         | 474 reviewed, 0 unaudited, 0 live |

---

## ✅ Checklist

- [ ] Code formatted (`make black isort pre-commit`)
- [ ] Tests added/updated for changes
- [ ] Documentation updated (if applicable)
- [x] No secrets or credentials committed

---

## 📓 Notes

- The wrapper reads `DETECT_SECRETS_BASELINE` to override the baseline path. The default is `.secrets.baseline`.
- The wrapper needs `detect-secrets-hook` on `PATH`. The `local` hook installs it through `additional_dependencies`.
