# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/helpers/upstream_host.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Choose the address a gateway under test uses to reach an upstream in the pytest process.

``make testing-up`` runs the gateway in a container. A listener bound to the
host loopback is unreachable from that container. Compose maps
``host.docker.internal`` to the host (``extra_hosts`` in ``docker-compose.yml``),
so that name is the default. A gateway that runs on the host needs
``127.0.0.1`` instead. Fixtures that host an upstream resolve both the advertised
host and the bind address here, so the policy has one definition.
"""

# Future
from __future__ import annotations

# Standard
import os
import warnings

DEFAULT_UPSTREAM_HOST = "host.docker.internal"
SHARED_UPSTREAM_HOST_ENV = "MCP_UPSTREAM_HOST"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
_warned_hosts: set[str] = set()


def gateway_upstream_host(env_var: str) -> str:
    """Return the host name the gateway uses to dial an in-process upstream.

    Args:
        env_var: Fixture-specific override, for example ``MCP_TEMPLATE_UPSTREAM_HOST``.

    Returns:
        The fixture override, else ``MCP_UPSTREAM_HOST``, else ``host.docker.internal``.
    """
    return os.getenv(env_var) or os.getenv(SHARED_UPSTREAM_HOST_ENV) or DEFAULT_UPSTREAM_HOST


def upstream_bind_host(gateway_host: str, *, stacklevel: int = 2) -> str:
    """Return the interface an in-process upstream must bind for ``gateway_host``.

    A container reaches the host only through a non-loopback interface, so any
    non-loopback ``gateway_host`` binds all interfaces and warns, because the
    fixture servers have no authentication. The warning fires once per process
    for each ``gateway_host``.

    Args:
        gateway_host: Host name from ``gateway_upstream_host()``.
        stacklevel: Warning stack level; callers pass their own frame depth.

    Returns:
        ``127.0.0.1`` for a host gateway, otherwise ``0.0.0.0``.
    """
    if gateway_host in _LOOPBACK_HOSTS:
        return "127.0.0.1"
    if gateway_host not in _warned_hosts:
        _warned_hosts.add(gateway_host)
        warnings.warn(
            f"An unauthenticated test upstream is binding all interfaces for gateway host {gateway_host!r}. Run it only in an isolated test environment.",
            RuntimeWarning,
            stacklevel=stacklevel + 1,
        )
    return "0.0.0.0"  # noqa: S104  # nosec B104 - a containerized gateway reaches the host only through a non-loopback interface
