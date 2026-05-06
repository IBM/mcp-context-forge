# -*- coding: utf-8 -*-
"""Smoke test for the rate-limiter's env-sourced redis_url.

Pins the contract that ``plugins/config.yaml`` resolves the rate-limiter's
``redis_url`` from the gateway's ``REDIS_URL`` environment variable via the
plugin loader's Jinja substitution AND that the resolved URL points at a
live Redis (not just a parseable string).

Companion to issue IBM/mcp-context-forge#4581 — guards against three
classes of regression:

  1. The yaml stops Jinja-substituting ``{{ env.REDIS_URL }}`` (e.g. loader
     change drops the env render context).
  2. The ``REDIS_URL`` env var isn't honored at config-load time.
  3. The resolved URL points at a broken endpoint (e.g. someone hard-codes
     a stale literal back into the yaml without realising it).

Skips cleanly when Redis isn't reachable, so the suite stays green on
runners without a Redis service available.
"""

# Standard
import pathlib
import socket

# Third-Party
import pytest
import redis

# Third-Party
from cpex.framework import ConfigLoader

# Anchor the plugins/config.yaml path to this file's location so the test
# works regardless of where pytest is invoked from (repo root, tests/, etc.).
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CONFIG_YAML = str(_REPO_ROOT / "plugins" / "config.yaml")


def _redis_reachable(host: str = "127.0.0.1", port: int = 6379, timeout: float = 0.2) -> bool:
    """Return True if a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _redis_reachable(),
    reason="Redis not reachable on 127.0.0.1:6379",
)
def test_rate_limiter_redis_url_resolves_and_connects(monkeypatch):
    """The rate-limiter's redis_url, sourced from the REDIS_URL env via the
    plugin loader's Jinja substitution, must resolve to a non-empty string
    AND the resolved URL must reach a live Redis (PING -> PONG).
    """
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    cfg = ConfigLoader.load_config(_CONFIG_YAML)
    rl = next(p for p in cfg.plugins if p.name == "RateLimiterPlugin")
    resolved = rl.config.get("redis_url")

    assert resolved, "redis_url must resolve to a non-empty string after Jinja substitution"
    assert "{{" not in resolved, f"Jinja placeholder leaked through unrendered: {resolved!r}"

    client = redis.from_url(resolved, socket_connect_timeout=2, socket_timeout=2)
    try:
        assert client.ping() is True
    finally:
        client.close()


def test_rate_limiter_redis_url_uses_default_when_env_unset(monkeypatch):
    """When REDIS_URL is unset, the Jinja ``default(...)`` filter must
    resolve to the literal fallback baked into ``plugins/config.yaml``.

    Pins the contract that the loader's Jinja env applies the ``default``
    filter (not just plain env-var substitution) — a regression here would
    silently leave operators on a broken redis_url whenever the env var
    isn't injected.  Runs without Redis.
    """
    monkeypatch.delenv("REDIS_URL", raising=False)

    cfg = ConfigLoader.load_config(_CONFIG_YAML)
    rl = next(p for p in cfg.plugins if p.name == "RateLimiterPlugin")

    assert rl.config.get("redis_url") == "redis://redis:6379/0"
