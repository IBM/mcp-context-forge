# -*- coding: utf-8 -*-
"""Location: ./tests/utils/plugin_redis_helper.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test-only helper that wires the framework's Redis shim to the real provider.

Production sets up ``mcpgateway.plugins.framework._redis`` during FastAPI
lifespan. Unit tests don't run lifespan, so without explicit wiring every
``_redis()`` call in the framework returns ``None`` and mocked Redis clients
never get reached. This helper installs a dynamic provider that re-reads
``get_redis_client`` from ``mcpgateway.utils.redis_client`` on every call —
capturing the reference at registration time would bind the pre-patch
function and defeat ``monkeypatch``/``patch`` in tests.

Usage:
    from tests.unit.mcpgateway.plugins._redis_test_helper import install_dynamic_redis_provider

    with install_dynamic_redis_provider():
        ...  # test body, can monkeypatch ``mcpgateway.utils.redis_client.get_redis_client``
"""

from contextlib import contextmanager

from mcpgateway.plugins.framework._redis import set_shared_redis_provider


async def _dynamic_get_redis_client():
    # First-Party — import on every call so monkeypatch of the module attr works.
    from mcpgateway.utils import redis_client as _rc  # pylint: disable=import-outside-toplevel

    return await _rc.get_redis_client()


@contextmanager
def install_dynamic_redis_provider():
    """Register the test provider for the duration of the context."""
    set_shared_redis_provider(_dynamic_get_redis_client)
    try:
        yield
    finally:
        set_shared_redis_provider(None)
