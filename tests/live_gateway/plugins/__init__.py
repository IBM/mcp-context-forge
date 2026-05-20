# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/__init__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

E2E tests for plugin runtime behavior against a live ContextForge gateway:

* `test_plugin_runtime_management.py` — Plugin runtime management via the
  admin API; needs the multi-replica docker-compose stack (NGINX in front of
  3 gateway replicas) so propagation can be observed across workers.
* `test_plugin_dynamic_behavior_bad_words.py` — Runtime mode changes to the
  bad-words plugin take effect on tool invocations across replicas.
* `test_rate_limiter_dynamic_behavior.py` — RateLimiterPlugin runtime mode
  changes propagate and gate tool invocations under NGINX load balancing.
* `test_rate_limiter_multi_tenant.py` — Multi-tenant rate-limiting scopes
  across the multi-replica stack with shared Redis state.

Excluded from the default `make test` run because they need a running gateway
(typically `make testing-up` with the 3-replica + NGINX + Redis profile).
Invoke explicitly once the stack is healthy.
"""
