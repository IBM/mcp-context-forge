# Agent Prose Standard (ASD-STE100)

Every piece of prose an agent authors in this repository follows the ASD-STE100 Simplified Technical English (STE) writing rules. The STE controlled dictionary is not enforced; domain, protocol, and code terms count as technical names, as STE itself allows.

This file expands the *Agent Prose* section of the root `AGENTS.md` with the full rule list and worked examples.

## Scope

Applies to all agent-authored prose read by humans:

- Code comments (inline) and docstrings
- Commit message bodies
- PR descriptions
- PR review findings and replies
- GitHub issue bodies and comments
- CHANGELOG entries

Exempt: identifiers, log and error strings (tests pin them), user-facing `docs/` prose, ephemeral working notes.

## Rules

1. **Short sentences.** One instruction or one fact per sentence. Keep instructions to 20 words or fewer; keep descriptive sentences to 25 or fewer. Split rather than subordinate.
2. **Active voice, present tense.** Write "the gateway rejects the request". Never write "the request is rejected by the gateway" or "was rejected".
3. **Imperative for instructions.** Write "Add a test". Never write "a test should be added" or "it would be good to add a test".
4. **One word, one meaning.** Pick a term and keep it for the whole artifact. A *token* stays a token; never also call it a credential or a key.
5. **Positive constructions.** State the target behavior. A prohibition earns its place only as a hard guardrail; pair it with the positive rule.
6. **No hedging, no idioms.** Delete "worth considering", "might want to", "arguably". Replace each metaphor with a plain statement.
7. **Technical names verbatim.** Identifiers, paths, env vars, error text, and protocol terms appear exactly as code writes them: `normalize_token_teams()`, `DB_POOL_SIZE`, `QueuePool limit exceeded`.
8. **Abbreviations.** Use industry-standard ones (API, HTTP, JSON, MCP) without expansion. Expand project-specific ones at first use in each artifact.
9. **Numerals for quantities.** Write "3 retries", never "three retries".
10. **One topic per paragraph.** A paragraph that carries two decisions loses one.

## Worked Examples

Every Before excerpt below is real, cited by PR, issue, or file, and trimmed for length. Each After version applies the rules above.

### Code comment

Before — `mcpgateway/handlers/sampling.py:220`:

```python
# TODO: Implement actual model sampling - currently returns mock response  # pylint: disable=fixme
# For now return mock response
response = self._mock_sample(messages=messages)
```

The second comment narrates the line under it. The TODO names no issue.

After:

```python
# TODO(#NNNN): implement model sampling. The mock keeps the sampling
# handshake answerable until then.
response = self._mock_sample(messages=messages)
```

The TODO names its issue. The narration is gone. The remaining comment states only the one fact the code cannot: why the mock exists.

Comments are a last resort. First make the code self-documenting: extract a function or rename a thing until the comment becomes redundant. A comment earns its place only when code cannot express a durable constraint. Never carry transient implementation process or decisions in a comment — decisions belong in an ADR, process in the commit body, tasks in an issue. See [Coding Standards](coding-standards.md).

### Docstring

Before — `mcpgateway/services/gateway_service.py:6334`:

```python
def _created_via_allowed(created_via: Optional[str]) -> bool:
    """Check if already created"""
    return stale_created_via_values is None or created_via in stale_created_via_values
```

"Check if already created" describes different behavior. The function tests membership in an allowlist.

After:

```python
def _created_via_allowed(created_via: Optional[str]) -> bool:
    """Return True when created_via passes the legacy allowlist.

    A None allowlist accepts every value.

    Args:
        created_via: The creation source recorded on the row, or None.

    Returns:
        True when the value passes the allowlist, False otherwise.
    """
```

Summary line first: what and when. Then the contract. Document every parameter and the return value. Ruff `D1`/`D417` and interrogate enforce presence and parameter coverage.

### Commit body

Before — one sentence from PR #6395, trimmed:

```text
The Vault plugin cannot see the real Authorization header on the A2A
branches (tool_service.py's A2A-as-tool path and a2a_service.py's
direct agent_pre_invoke path) -- both filter it out of what plugins
receive before invoking the hook, by design (#4925), so the plugin's
existing del headers["authorization"] on a vault-token mismatch was
a no-op there.
```

One sentence, 60 words, two parentheticals, and a causal chain.

After — the same facts, one per sentence:

```text
The Vault plugin cannot see the real Authorization header on the two
A2A branches: tool_service.py's A2A-as-tool path and a2a_service.py's
direct agent_pre_invoke path. Both branches filter the header from the
plugin payload before the hook runs. The filter is by design (#4925).
The plugin's del headers["authorization"] on a vault-token mismatch was
therefore a no-op on both branches.
```

Every fact survives the split. State what changed, the exact behavior boundary, and the issue link.

### PR description

Before — opening of PR #6788:

```text
Retroactively corrects documentation files that contained incorrect
package and container image references. These references posed a
potential security concern and have been corrected to the canonical
values.
```

Passive voice ("have been corrected"), hedging ("posed a potential security concern"), and no named file or value.

After:

```text
## Summary

Fix wrong package and image names in ADR-025 and the altk README. Each
reference now uses the canonical name. ADR-025 stays marked superseded;
each corrected block carries a note that names the correction.
```

### Review finding

Before — review comment on PR #6716 at `docker-compose.yml:1197`:

```text
Nice improvement over latest. Could we make this immutable too by
pinning the image digest (for example, …:0.2.1@sha256:…)? A version tag
can be retargeted, and this BFF handles user sessions/authentication.
Digest pinning makes the supported ui profile reproducible and prevents
a registry-tag replacement from changing deployed code unexpectedly.
Please update the documented example and release verification step to
use the digest as well.
```

The content is complete: risk, rationale, and scope. Question framing and compound clauses bury it.

After — the same finding in the house format:

```text
suggestion | docker-compose.yml:1197 | The pinned tag …:0.2.1 is mutable at the registry; this BFF handles user sessions, so a retargeted tag silently changes deployed code | Pin the digest (…:0.2.1@sha256:…) in docker-compose.yml, the documented example, and the release verification step
```

Nothing is lost: the retarget risk, the session sensitivity, and the three places to update all survive. Severity, location, problem, fix. One line. See *PR Review* in the root `AGENTS.md` for the severity taxonomy and blocking criteria.

### Issue body

Before — opening of issue #6799:

```text
When `OAUTH_TOKEN_BACKEND=vault`, a Vault outage or expired
`VAULT_TOKEN` breaks tool invocation on **every non-OAuth gateway** —
including gateways that have no per-user credentials at all
(`auth_type=none`, or gateways relying solely on gateway-wide static
auth). The per-user Vault lookup in the non-OAuth branch is
unconditional: it is gated only on `app_user_email` being present and
the process-wide `oauth_token_backend == "vault"` setting.
```

Two sentences, five facts each, chained with dashes and colons.

After:

```text
## Symptom

With OAUTH_TOKEN_BACKEND=vault, a Vault outage or an expired VAULT_TOKEN
blocks tool invocation on every non-OAuth gateway. Gateways without
per-user credentials fail too.

## Cause

The non-OAuth branch runs the per-user Vault lookup unconditionally.
The only gates are a present app_user_email and
oauth_token_backend == "vault". No per-gateway signal says the gateway
uses per-user credentials.
```

Observable symptom first, then cause. One fact per sentence. Give the fix what it needs.

### CHANGELOG entry

Before — the uv entry from this repository's CHANGELOG:

```text
- **uv 0.6.9 or later required** - `pyproject.toml` now declares
  `required-version = ">=0.6.9"` under `[tool.uv]`. The
  `exclude-newer = "10 days"` relative duration syntax was introduced
  in uv 0.6.9; older versions silently fail to parse it, discard the
  lockfile, and re-resolve freely — which can pull in packages lacking
  Linux wheels. Upgrade uv before running `uv sync` or `uv lock`.
```

After — the same entry, split at the semicolon:

```text
- **uv 0.6.9 or later required** - `pyproject.toml` now declares
  `required-version = ">=0.6.9"` under `[tool.uv]`. The
  `exclude-newer = "10 days"` syntax needs uv 0.6.9. Older versions
  fail to parse the setting silently. They discard the lockfile and
  re-resolve freely. The re-resolve can select packages that lack
  Linux wheels. Upgrade uv before you run `uv sync` or `uv lock`.
```

Every fact survives: the requirement, the cause, the failure chain, and the action. Name the behavior change, the exact boundary, and the migration step.

## Relationship to Tone

Tone governs content order: lead with what works, categorize severity, stay direct without harshness. STE governs sentence construction. A finding can be courteous in structure and blunt in sentence at the same time. Both serve the author.
