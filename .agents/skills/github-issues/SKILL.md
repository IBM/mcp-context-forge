---
name: github-issues
description: Create, label, or triage a GitHub issue for this repository. Defines issue types, title style, label baseline, and lifecycle labels.
---

# GitHub Issues

- Start from the matching template in `.github/ISSUE_TEMPLATE/`. The template sets the GitHub Issue Type (`Epic`, `Feature`, `Story`, `Task`, `Bug`). The template's sections define the body.
- Hierarchy: an Epic holds Features, a Feature holds Stories, a Story holds Tasks. Link children with GitHub sub-issues on the parent. Bugs stand alone or nest anywhere in that chain.
- Titles carry no type prefix. Write a plain imperative summary: `Gateway drops WebSocket sessions on restart`.
- Labels carry no issue types. New issues start with `triage`. The Chore and Documentation templates also apply `chore` and `documentation`. Add 1-3 optional scope labels (`security`, `performance`, `ui`, `api`, `python`, `devops`, `a2a`, `mcp-protocol`).
- The organization defines the issue type names. Template `type` values must match those names exactly.
- Lifecycle labels: `awaiting-user` when blocked on reporter feedback, `blocked` for dependency blockers, `planned` when accepted but deferred, `fixed` only after the resolving change merges.
- Bodies and comments follow *Agent Prose* in `AGENTS.md`. Before you post, rewrite them with the `asd-ste100` skill in STE-flavored mode. For public tone, see the `pr-review` skill, section *Tone*.
