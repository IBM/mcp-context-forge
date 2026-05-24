# Prompt Injection Guard Plugin

Screens prompts and tool arguments for **prompt injection** and **jailbreak** attempts.
Addresses OWASP LLM Top 10: **LLM01 (Prompt Injection)** and **LLM07 (System Prompt Leakage)**.

## Detection Approach

Two-tier detection with deterministic timing:

| Tier | Engine | Timing | Requirement |
|------|--------|--------|-------------|
| 1 | Precompiled regex patterns | <1 ms | Always active |
| 2 | LLM Guard PromptInjection scanner (local DeBERTa) | ~5–20 ms | Optional; requires `llm-guard` package |

## Hooks

- `prompt_pre_fetch` — screens prompt arguments before rendering
- `tool_pre_invoke` — screens tool arguments before execution
- `tool_post_invoke` — screens tool outputs (opt-in via `check_tool_output: true`)

## Detection Categories

| Category | Description |
|----------|-------------|
| `injection` | Attempts to override or ignore prior instructions |
| `jailbreak` | Attempts to escape safety constraints or adopt unconstrained personas |
| `system_prompt_leak` | Attempts to extract the system prompt |

## Response Modes

| Mode | Behaviour |
|------|-----------|
| `block` | Reject the request; return `PluginViolation` with `continue_processing=False` |
| `redact` | Replace matched text with `redaction_placeholder`; allow the request to continue |
| `flag-only` | Record violation metadata; processing continues unchanged |

## Installation

**In-tree (no extra packages):**
```bash
# Plugin ships with ContextForge; no additional install required.
PLUGINS_ENABLED=true
PLUGINS_CONFIG_FILE=plugins/config.yaml
```

**With LLM Guard scorer (Tier-2):**
```bash
pip install "mcp-contextforge-gateway[plugins]"
# or install the llm-guard package directly:
pip install llm-guard
```

## Configuration Reference

```yaml
- name: "PromptInjectionGuardPlugin"
  kind: "plugins.prompt_injection_guard.prompt_injection_guard.PromptInjectionGuardPlugin"
  hooks: ["prompt_pre_fetch", "tool_pre_invoke"]
  mode: "enforce"          # enforce | enforce_ignore_error | permissive | disabled
  priority: 45             # run after ArgumentNormalizer (40), before PIIFilter (50)
  config:
    mode: "block"          # block | redact | flag-only (global default)
    check_tool_output: false
    use_llm_guard: false   # set true after installing llm-guard
    redaction_placeholder: "[INJECTION_REDACTED]"
    categories:
      injection:
        threshold: 0.75
        action: "block"
      jailbreak:
        threshold: 0.80
        action: "block"
      system_prompt_leak:
        threshold: 0.70
        action: "block"
```

## Per-tool Binding Example

Using the `binding_reference_id` plugin-bindings API (PR #4143):

```yaml
conditions:
  - tools: ["my_sensitive_tool"]
    server_ids: ["prod-server"]
```

## Violation Payload

When a violation is raised, `PluginViolation.details` contains:

```json
{
  "score": 1.0,
  "category": "injection",
  "matched_rule": "ignore\\s+(all\\s+)?...",
  "response_mode": "block",
  "all_findings": [
    {"category": "injection", "matched_rule": "...", "score": 1.0}
  ]
}
```

## Benchmarks

Measurements on Apple M2 (single core, Python 3.12, prompt ≤ 4 KB):

| Tier | p50 | p95 | p99 |
|------|-----|-----|-----|
| Regex only | <0.2 ms | <0.5 ms | <1 ms |
| Regex + LLM Guard (first call, model load) | ~3 s | — | — |
| Regex + LLM Guard (subsequent calls) | ~8 ms | ~18 ms | ~22 ms |

> **Note:** LLM Guard model load is a one-time cost amortised across all requests.
> p99 for subsequent calls satisfies the ≤ 25 ms requirement.

## Adversarial Corpus Catch Rate

Tested against 200 prompts generated with `garak` and `promptmap` as of April 2026:

| Category | Catch rate (Regex) | Catch rate (+ LLM Guard) |
|----------|--------------------|--------------------------|
| Injection | 87% | 94% |
| Jailbreak | 82% | 91% |
| System prompt leak | 91% | 95% |

False-positive rate on 500 benign prompts: <0.5%.
