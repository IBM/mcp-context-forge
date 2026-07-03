# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/hooks/gateway.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Gateway lifecycle hook definitions for the plugin framework.

Defines the two hook points at which plugins can intercept container
image assessments before a server is registered or deployed:

- ``server_pre_register`` — fired when a new MCP server is being registered
  with the gateway.  Plugins can inspect the image and block registration.
- ``runtime_pre_deploy`` — fired at runtime just before an image is activated.
  Plugins can re-evaluate policy and block deployment.

Both hooks share the same payload shape (:class:`ServerPreRegisterPayload` /
:class:`RuntimePreDeployPayload`) and are registered into the global hook
registry on module import via :func:`_register_plugin_hooks`.
"""

# Standard
from enum import Enum
from typing import Optional

# Third-Party
from cpex.framework import PluginPayload, PluginResult
from pydantic import Field


class GatewayHookType(str, Enum):
    """Enumeration of gateway lifecycle hook identifiers.

    Values are used as keys when registering and dispatching hooks through
    the :class:`~mcpgateway.plugins.framework.hooks.registry.HookRegistry`.

    Attributes:
        SERVER_PRE_REGISTER: Hook fired before a new MCP server is registered.
        RUNTIME_PRE_DEPLOY: Hook fired before an image is activated at runtime.
    """

    SERVER_PRE_REGISTER = "server_pre_register"
    RUNTIME_PRE_DEPLOY = "runtime_pre_deploy"


class ServerPreRegisterPayload(PluginPayload):
    """Payload delivered to plugins at the ``server_pre_register`` hook point.

    Carries the identity of the container image being registered so that
    plugins (e.g. :class:`~plugins.container_scanner.ContainerScannerPlugin`)
    can inspect it and decide whether to allow or block registration.

    Attributes:
        assessment_id: Unique identifier for this assessment request (UUID).
        image_ref: Full OCI image reference, e.g. ``"ghcr.io/org/app:v1"``.
        image_digest: Optional SHA-256 digest, e.g.
            ``"sha256:abc123..."``.  When provided, enables digest-keyed
            caching in scanner plugins.
    """

    assessment_id: str
    image_ref: str
    image_digest: Optional[str] = Field(default=None)


class RuntimePreDeployPayload(PluginPayload):
    """Payload delivered to plugins at the ``runtime_pre_deploy`` hook point.

    Identical in structure to :class:`ServerPreRegisterPayload` but fired
    at a later lifecycle stage — when the gateway is about to activate an
    already-registered image.  This allows plugins to re-evaluate policy
    (e.g. after a CVE database update) without waiting for re-registration.

    Attributes:
        assessment_id: Unique identifier for this assessment request (UUID).
        image_ref: Full OCI image reference, e.g. ``"ghcr.io/org/app:v1"``.
        image_digest: Optional SHA-256 digest used for cache lookup.
    """

    assessment_id: str
    image_ref: str
    image_digest: Optional[str] = Field(default=None)


ServerPreRegisterResult = PluginResult[ServerPreRegisterPayload]
"""Concrete result type for the ``server_pre_register`` hook.

A ``continue_processing=False`` result with a populated ``violation`` field
will cause the gateway to reject the registration request.
"""

RuntimePreDeployResult = PluginResult[RuntimePreDeployPayload]
"""Concrete result type for the ``runtime_pre_deploy`` hook.

A ``continue_processing=False`` result with a populated ``violation`` field
will cause the gateway to block deployment of the image.
"""


def _register_plugin_hooks() -> None:
    """Register gateway hook types into the global hook registry.

    Called once on module import.  Uses an idempotency guard
    (``is_registered``) so that repeated imports in tests do not
    register duplicate handlers.
    """
    # First-Party
    from mcpgateway.plugins.framework.hooks.registry import get_hook_registry  # pylint: disable=import-outside-toplevel

    registry = get_hook_registry()
    if not registry.is_registered(GatewayHookType.SERVER_PRE_REGISTER):
        registry.register_hook(GatewayHookType.SERVER_PRE_REGISTER, ServerPreRegisterPayload, ServerPreRegisterResult)
        registry.register_hook(GatewayHookType.RUNTIME_PRE_DEPLOY, RuntimePreDeployPayload, RuntimePreDeployResult)


_register_plugin_hooks()
