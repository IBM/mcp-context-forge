---
name: secret-detection
description: Resolve a `detect-secrets` finding or a `.secrets.baseline` change. Use when `make detect-secrets-scan` fails, when you add a placeholder credential to docs or code, or when you resolve a baseline merge conflict.
---

# Secret Detection (detect-secrets)

Prefer removing the trigger. Rewrite the line so it holds no credential-shaped value. Suppress only when the value must stay.

## Suppress a False Positive

- **Python files**: suppress inline with `# pragma: allowlist secret`. The finding then stays out of `.secrets.baseline` after `make detect-secrets-scan`.
  - Exception: doctest strings where the comment breaks the assertion. Rely on `.secrets.baseline` and audit with `make detect-secrets-audit`.
- **Makefile**: suppress audited false positives inline with `# pragma: allowlist secret`. In variable assignments, append the pragma directly after the value, with no space. Make keeps whitespace before a comment in the value.
- **Markdown**: inside a fenced code block, append `# pragma: allowlist secret` to the line. In prose, append `<!-- pragma: allowlist secret -->`. Rewrite the line instead when the pragma would break a sample that readers copy verbatim.
- **All other file types**: regenerate the baseline with `make detect-secrets-scan`.
- **Merge conflicts**: resolve `.secrets.baseline` with the version from `main`.

## Verify

Run `make detect-secrets-scan`. It exits non-zero on live or unaudited findings. Remediate with `make detect-secrets-audit`. Done when the command exits zero and `.secrets.baseline` holds no entry for a line you suppressed or removed.
