"""Containerized variant of the rate-limiter TLS+AUTH single-instance binding test.

This reuses the make-dev test (``test_rate_limiter_binding_single_instance_tls.py``)
verbatim — same fixtures, same lifecycle assertions — but targets the gateway
running as the **baked container image with 2 gunicorn workers**, on a shared
docker network with container-name Redis/Postgres/fast-time. The make-dev test
file is left untouched.

Stand the stack up first (handles certs, network, the baked gateway image,
plugin ``enforce`` + CA wiring, the ``PASSWORD_CHANGE_ENFORCEMENT_ENABLED=false``
gotcha, ``LOG_LEVEL=INFO``, and fast-time pre-registration)::

    ./rl-shared-bake/up.sh
    ./rl-shared-bake/run-e2e.sh        # runs THIS test

What differs from the make-dev file (both backward-compatible reuse):

1. **Admin-API redirect guard.** On a gateway that forces a first-login password
   change, ``/admin/*`` returns ``303 -> /admin/change-password-required`` with an
   empty body, so the base ``_get_admin_plugin_state`` dies with a cryptic
   ``JSONDecodeError``. Here it is surfaced as an actionable skip. ``up.sh`` sets
   ``PASSWORD_CHANGE_ENFORCEMENT_ENABLED=false`` so it normally never triggers.

2. **fast-time addressing.** ``up.sh`` pre-registers the ``fast-time-sse`` gateway
   at its container-network URL (``http://rl-fast-time:8080/sse``), so the base
   session fixture finds it already present and skips its host-IP path (which is
   unreliable from inside a container). No code override needed here.

Everything else (container-name ``DATABASE_URL``/``REDIS_URL``, the ``rl-redis``
cert SAN, plugin ``enforce``, the ``redis_ssl_ca_certs`` line) lives in
``rl-shared-bake/up.sh`` and the baked config — where setup belongs.
"""

# Reuse of the make-dev test module necessarily touches its underscore-prefixed
# helpers, which are untyped; silence the resulting strict-mode noise here.
# Imported fixtures/autouse functions are discovered by pytest at runtime, not
# "called", so unused-import/function checks are false positives here.
# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnusedImport=false, reportUnusedFunction=false

# Standard
import os

# Third-Party
import pytest
import requests

# First-Party — reuse the make-dev test module wholesale.
import tests.live_gateway.plugins.test_rate_limiter_binding_single_instance_tls as base

# Re-export the fixtures the inherited test method depends on so pytest can
# resolve them in THIS module (fixtures are discovered by name in the test's
# module namespace). The autouse isolation fixture must be imported too.
from tests.live_gateway.plugins.test_rate_limiter_binding_single_instance_tls import (  # noqa: F401
    cleanup_bindings,
    ensure_fast_time_gateway_and_server,
    server_and_tool,
    team_id,
    _isolate_state_before_each_binding_test,
)

GATEWAY_URL = base.GATEWAY_URL

# Independent skip-guards for this module (the base module's pytestmark does not
# propagate to a subclass defined here).
pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_BINDING_SINGLE_INSTANCE", "0").lower() not in {"1", "true", "yes"},
        reason=(
            "Containerized single-instance binding-lifecycle test. "
            "Opt in with RUN_BINDING_SINGLE_INSTANCE=1, and bring the stack up "
            "first: ./rl-shared-bake/up.sh (then ./rl-shared-bake/run-e2e.sh)."
        ),
    ),
    pytest.mark.skipif(
        not base._is_gateway_running(),
        reason=f"Gateway not running at {GATEWAY_URL} — run ./rl-shared-bake/up.sh",
    ),
]


def _container_admin_plugin_state(plugin_name: str) -> dict[str, object]:
    """Redirect-aware replacement for ``base._get_admin_plugin_state``.

    A gateway enforcing a first-login password change 303-redirects ``/admin/*``
    to ``/admin/change-password-required`` with an empty body. Detect that and
    skip with a clear remedy instead of letting ``resp.json()`` raise
    ``JSONDecodeError`` on the empty body.
    """
    resp = requests.get(
        f"{GATEWAY_URL}/admin/plugins",
        headers=base._fresh_headers(),
        timeout=10,
        allow_redirects=False,
    )
    if resp.is_redirect and "change-password" in resp.headers.get("location", ""):
        pytest.skip(
            "Gateway is forcing an admin password change; set "
            "PASSWORD_CHANGE_ENFORCEMENT_ENABLED=false on the gateway "
            "(./rl-shared-bake/up.sh already does this)."
        )
    resp.raise_for_status()
    for p in resp.json().get("plugins", []):
        if p.get("name") == plugin_name:
            return p
    pytest.skip(f"Plugin {plugin_name!r} not present in /admin/plugins listing")


@pytest.fixture(autouse=True)
def _harden_admin_call_for_container(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap in the redirect-aware admin getter for the duration of each test so a
    misconfigured container gateway fails with guidance, not a JSONDecodeError."""
    monkeypatch.setattr(base, "_get_admin_plugin_state", _container_admin_plugin_state)


class TestRateLimiterBindingSingleInstanceTLSContainer(base.TestRateLimiterBindingSingleInstance):
    """Same TLS+AUTH dynamic-binding lifecycle, against the containerized stack
    from ``rl-shared-bake/up.sh`` (baked image, 2 gunicorn workers, container-
    network Redis/Postgres/fast-time). Inherits the full lifecycle test."""
