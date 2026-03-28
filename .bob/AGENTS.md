# AGENTS.md

This file provides guidance to agents when working with code in this repository.

- Before saying work is ready for PR or using a PR creation flow, run a full pre-PR review across correctness, security, testing, docs/API usage, performance, maintainability, and architecture.
- Prefer Bob's Review panel when available; otherwise run an explicit review task over the branch or intended diff before PR creation.
- Do not treat review findings as true until they are supported by direct evidence from code paths, repo state, command output, or tests.
- If a claim depends on external behavior, library semantics, flags, versions, or product capabilities, verify it against primary online sources before asserting it.
- Security-sensitive changes must verify deny paths and permission boundaries, not just happy paths.
- Testing feedback should call out missing or brittle coverage and recommend the smallest concrete test additions that would prove or disprove the risk.
- Architecture feedback should focus on boundaries, ownership, coupling, migration risk, and whether the change fits the existing service and transport model.
