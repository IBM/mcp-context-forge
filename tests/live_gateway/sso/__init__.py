# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/sso/__init__.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

E2E tests requiring a live Single Sign-On identity provider:

* `test_oauth_jwks_e2e.py` — Keycloak (docker-compose --profile sso)

Excluded from the default `make test` run because it depends on external
identity infrastructure that isn't available in CI by default. Invoke
explicitly via `make test-e2e-sso` once the Keycloak stack is in place.

Note: the in-process Entra ID integration test now lives in
``tests/integration/test_entra_id_integration.py`` — it uses
``httpx.ASGITransport`` against the in-process app and skips when the
AZURE_* credentials are absent, so it runs (and self-skips) as part of
the normal `make test` flow.
"""
