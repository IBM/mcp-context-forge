# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/__init__.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

End-to-end tests exercising observable gateway flows against a live stack:

* `test_e2e.py` — consolidated end-to-end coverage (currently virtual-server lifecycle)

Excluded from the default `make test` run because they need a running gateway
(typically `make testing-up`). Invoke explicitly via `make test-e2e`.

These tests read the stack's shared `fast_time` gateway registration but never
create, modify, or delete it. They therefore cannot run concurrently with suites
that mutate gateway registrations — see the execution-order note in
`tests/live_gateway/README.md`.
"""
