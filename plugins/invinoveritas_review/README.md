# invinoveritas Review Plugin for ContextForge

> Author: babyblueviper1
> Version: 0.1.0

Gates `tool_pre_invoke` on an independent, signed pre-action verdict from
[invinoveritas](https://api.babyblueviper.com) — a judgment call about whether a
specific tool invocation is sound, not a static rule. Grew out of
[#5437](https://github.com/IBM/mcp-context-forge/issues/5437) (Human in the loop
Approval for tool execution): a `risk_tier`/`gate.mode` rule engine can decide *whether*
a human or policy needs to look at a call; it structurally cannot decide *whether this
specific, novel action is actually sound* — that needs a judgment call, which is what
`/review` does.

## Features

- Calls `POST /review` before every tool invocation with `{tool_name, arguments}` as the
  artifact.
- A `reject` verdict blocks the call by default (`block_on_reject: true`); set to `false`
  for an advisory/observe-only rollout that never blocks, only annotates the result.
- **Fails open** on any `/review`-side problem (network error, timeout, malformed
  response, missing API key) — the tool call proceeds ungated rather than hanging or
  crashing the gateway; `metadata["invinoveritas_review"] = "unavailable"` is set so this
  is visible, not silent.
- Optional `sign: true` attaches a portable, independently-verifiable signed proof
  (verify at `https://api.babyblueviper.com/verify-proof`, free, no auth) to every
  verdict.
- Zero framework changes — a normal `Plugin` hooking `tool_pre_invoke`, same seam as
  `unified_pdp` and the other example plugins in this directory.

## Installation

1. Register free, instant, no payment: `POST https://api.babyblueviper.com/register`
2. Set `IVV_API_KEY` in your environment, or pass `api_key` directly in the plugin config
   below (env var is preferred — don't commit a key to `config.yaml`).
3. Add the plugin configuration to `plugins/config.yaml`:

```yaml
plugins:
  - name: "InvinoveritasReviewPlugin"
    kind: "plugins.invinoveritas_review.invinoveritas_review.InvinoveritasReviewPlugin"
    description: "Gates tool_pre_invoke on an independent invinoveritas /review verdict."
    version: "0.1.0"
    author: "babyblueviper1"
    hooks: ["tool_pre_invoke"]
    tags: ["plugin", "safety", "review", "human-in-the-loop"]
    mode: "enforce"  # enforce | permissive | disabled
    priority: 100
    config:
      base_url: "https://api.babyblueviper.com"
      block_on_reject: true
      sign: false
      artifact_type: "general"
      timeout_s: 15.0
```

## Relationship to a rule-based PDP (e.g. `unified_pdp`)

This plugin is deliberately **not** a replacement for a rule engine — it answers a
different question. A PDP like `unified_pdp` decides *eligibility* (may this
actor/tool/resource combination happen at all, per policy) deterministically and fast.
`InvinoveritasReviewPlugin` decides *soundness for this specific payload* — the same
tool call with different arguments can be fine or genuinely risky, which a static rule
can't distinguish without an explosion of conditions. Run both: PDP first (cheap,
deterministic, denies the clearly-disallowed), review second (judgment, for what the PDP
lets through). Every `/review` verdict is independently checkable via
`/verify-proof` — recompute it yourself, don't trust the plugin's word for it.

## Testing

```bash
pytest plugins/invinoveritas_review/tests/test_invinoveritas_review.py -v
```

No live API key needed — all 6 tests run against `httpx.MockTransport`, covering
reject-blocks, advisory-mode-never-blocks, approve-passes-through, fail-open-on-timeout,
fail-open-on-malformed-response, and no-api-key-skips-the-call-entirely.
