# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_main_module_init.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Documentation for main.py module-level initialization coverage.

Lines 3149-3155 in main.py contain module-level initialization code that executes
when the module is imported. This code configures the OTEL baggage middleware based
on environment settings.

## Why These Lines Are Not Unit Tested

Module-level initialization in main.py triggers the entire FastAPI application
initialization chain, including:
- Database connection setup
- Service initialization (including Argon2PasswordService)
- Middleware registration
- Router mounting
- Plugin loading

Attempting to mock this initialization in unit tests is impractical because:
1. The import cascade is deep and complex
2. Many services require real configuration values (not mocks)
3. The initialization order matters and is difficult to control in tests

## Coverage Strategy

These lines are covered by:

1. **Integration Tests**: `tests/integration/test_baggage_middleware.py`
   - Tests the full middleware stack with real configuration
   - Exercises all three code paths (enabled+tracing, enabled+no-tracing, disabled)

2. **Smoke Tests**: `smoketest.py`
   - Verifies the application starts successfully with default configuration
   - Confirms middleware is properly registered

3. **Manual Testing**: Starting the application with different environment variables
   - `OTEL_BAGGAGE_ENABLED=true OTEL_ENABLE_OBSERVABILITY=true` → line 3153
   - `OTEL_BAGGAGE_ENABLED=true OTEL_ENABLE_OBSERVABILITY=false` → line 3155
   - `OTEL_BAGGAGE_ENABLED=false` → line 3157

## Code Under Test

```python
# Lines 3149-3157 in mcpgateway/main.py
if settings.otel_baggage_enabled and otel_tracing_enabled():
    from mcpgateway.middleware.baggage_middleware import BaggageMiddleware
    app.add_middleware(BaggageMiddleware)
    logger.info("🧳 OTEL baggage middleware enabled for HTTP header extraction")
elif settings.otel_baggage_enabled and not otel_tracing_enabled():
    logger.warning("🧳 OTEL baggage enabled but tracing disabled - baggage will not be captured in spans")
else:
    logger.debug("🧳 OTEL baggage middleware disabled")
```

## Verification

To verify these lines execute correctly:

```bash
# Test enabled path
OTEL_BAGGAGE_ENABLED=true OTEL_ENABLE_OBSERVABILITY=true make dev
# Look for: "🧳 OTEL baggage middleware enabled for HTTP header extraction"

# Test warning path
OTEL_BAGGAGE_ENABLED=true OTEL_ENABLE_OBSERVABILITY=false make dev
# Look for: "🧳 OTEL baggage enabled but tracing disabled"

# Test disabled path
OTEL_BAGGAGE_ENABLED=false make dev
# Look for: "🧳 OTEL baggage middleware disabled" (in debug logs)
```
"""

# Note: This file intentionally contains no test classes.
# See module docstring for coverage strategy.
