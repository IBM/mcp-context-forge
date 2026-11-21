# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_live_gateway_upstream_host.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the upstream-host policy shared by live-gateway fixtures.

A containerized gateway cannot reach a listener on the host loopback, so
fixtures that host an upstream resolve the advertised host and the bind address
through ``tests.live_gateway.helpers.upstream_host``. This file sits directly
under ``tests/unit/`` because its subject is test infrastructure.
"""

# Standard
import warnings

# Third-Party
import pytest

# First-Party
from tests.live_gateway.helpers import upstream_host
from tests.live_gateway.helpers.upstream_host import DEFAULT_UPSTREAM_HOST, gateway_upstream_host, SHARED_UPSTREAM_HOST_ENV, upstream_bind_host

FIXTURE_ENV = "MCP_EXAMPLE_UPSTREAM_HOST"


@pytest.fixture(autouse=True)
def _forget_warned_hosts(monkeypatch):
    """Start each test with no host already warned about."""
    monkeypatch.setattr(upstream_host, "_warned_hosts", set())


def test_default_host_is_reachable_from_compose_gateway(monkeypatch):
    """Without overrides the fixture advertises the compose host alias."""
    monkeypatch.delenv(FIXTURE_ENV, raising=False)
    monkeypatch.delenv(SHARED_UPSTREAM_HOST_ENV, raising=False)
    assert gateway_upstream_host(FIXTURE_ENV) == DEFAULT_UPSTREAM_HOST == "host.docker.internal"


def test_fixture_override_beats_shared_override(monkeypatch):
    """The fixture-specific variable wins over the shared variable."""
    monkeypatch.setenv(FIXTURE_ENV, "127.0.0.1")
    monkeypatch.setenv(SHARED_UPSTREAM_HOST_ENV, "host.lima.internal")
    assert gateway_upstream_host(FIXTURE_ENV) == "127.0.0.1"


def test_shared_override_applies_when_fixture_override_is_absent(monkeypatch):
    """The shared variable sets one default for every fixture."""
    monkeypatch.delenv(FIXTURE_ENV, raising=False)
    monkeypatch.setenv(SHARED_UPSTREAM_HOST_ENV, "host.lima.internal")
    assert gateway_upstream_host(FIXTURE_ENV) == "host.lima.internal"


def test_empty_override_is_ignored(monkeypatch):
    """An empty variable falls through to the next source."""
    monkeypatch.setenv(FIXTURE_ENV, "")
    monkeypatch.delenv(SHARED_UPSTREAM_HOST_ENV, raising=False)
    assert gateway_upstream_host(FIXTURE_ENV) == DEFAULT_UPSTREAM_HOST


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_host_gateway_binds_loopback_without_warning(host):
    """A gateway on the host needs no exposed listener."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert upstream_bind_host(host) == "127.0.0.1"


@pytest.mark.parametrize("host", ["host.docker.internal", "host.lima.internal", "192.0.2.10"])
def test_containerized_gateway_binds_all_interfaces_with_warning(host):
    """A container reaches the host only through a non-loopback interface."""
    with pytest.warns(RuntimeWarning, match="binding all interfaces"):
        assert upstream_bind_host(host) == "0.0.0.0"


def test_all_interfaces_warning_fires_once_per_host():
    """Repeated fixtures for one gateway host report the exposure once."""
    with pytest.warns(RuntimeWarning, match="binding all interfaces"):
        upstream_bind_host("host.docker.internal")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert upstream_bind_host("host.docker.internal") == "0.0.0.0"
    with pytest.warns(RuntimeWarning, match="host.lima.internal"):
        upstream_bind_host("host.lima.internal")
