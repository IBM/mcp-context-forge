# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/sso/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

E2E tests requiring a live Single Sign-On identity provider:

* `test_oauth_jwks_e2e.py` — Keycloak (docker-compose --profile sso)
* `test_entra_id_integration.py` — Microsoft Entra ID (Azure tenant + creds)

Both are excluded from the default `make test` run because they depend on
external identity infrastructure that isn't available in CI by default.
Invoke explicitly via `make test-e2e-sso` once the relevant stack/creds
are in place.
"""
