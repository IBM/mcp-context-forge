# -*- coding: utf-8 -*-
"""mcpgateway.api.v1 — versioned API v1 router factory.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

Usage (Phase 1 — inline routers still live in main.py):

    from mcpgateway.api.v1 import build_v1_router
    v1_router = build_v1_router(
        settings,
        protocol_router=protocol_router,
        tool_router=tool_router,
        ...
    )
    app.include_router(v1_router)

Phase 2 will move individual router modules here so that the factory
imports them directly and no longer requires kwargs.
"""

# Standard
from typing import Any

# Third-Party
from fastapi import APIRouter

# First-Party
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


def build_v1_router(  # noqa: C901 — deliberate single-function assembly, complexity is structural not algorithmic
    settings: Any,
    *,
    # Always-on inline routers (Phase 1: passed from main.py; Phase 2: imported from submodules)
    protocol_router: APIRouter,
    tool_router: APIRouter,
    resource_router: APIRouter,
    prompt_router: APIRouter,
    gateway_router: APIRouter,
    root_router: APIRouter,
    server_router: APIRouter,
    metrics_router: APIRouter,
    tag_router: APIRouter,
    export_import_router: APIRouter,
    # A2A router is always-defined in main.py but conditionally mounted
    a2a_router: APIRouter,
) -> APIRouter:
    """Assemble and return the /v1 APIRouter.

    All routes registered here will be served under the /v1 prefix.
    Unversioned routes (well-known, oauth, health, utility, llm-proxy)
    are mounted directly on ``app`` by the caller.

    Args:
        settings: Application settings instance.
        protocol_router: Inline protocol router from main.py.
        tool_router: Inline tools router from main.py.
        resource_router: Inline resources router from main.py.
        prompt_router: Inline prompts router from main.py.
        gateway_router: Inline gateways router from main.py.
        root_router: Inline roots router from main.py.
        server_router: Inline servers router from main.py.
        metrics_router: Inline metrics router from main.py.
        tag_router: Inline tags router from main.py.
        export_import_router: Inline export/import router from main.py.
        a2a_router: Inline A2A router from main.py.

    Returns:
        APIRouter: Fully assembled v1 router with prefix "/v1".
    """
    v1_router = APIRouter(prefix="/v1")

    # -------------------------------------------------------------------------
    # Group A — always-on inline routers
    # -------------------------------------------------------------------------
    v1_router.include_router(protocol_router)
    v1_router.include_router(tool_router)
    v1_router.include_router(resource_router)
    v1_router.include_router(prompt_router)
    v1_router.include_router(gateway_router)
    v1_router.include_router(root_router)
    v1_router.include_router(server_router)
    v1_router.include_router(metrics_router)
    v1_router.include_router(tag_router)
    v1_router.include_router(export_import_router)

    # -------------------------------------------------------------------------
    # Group B — always-tried optional router (tool plugin bindings)
    # -------------------------------------------------------------------------
    try:
        # First-Party
        from mcpgateway.routers.tool_plugin_bindings import router as tool_plugin_bindings_router  # pylint: disable=import-outside-toplevel

        v1_router.include_router(tool_plugin_bindings_router)
        logger.info("Tool plugin bindings router included")
    except ImportError as e:
        logger.error(f"Tool plugin bindings router not available: {e}")

    # -------------------------------------------------------------------------
    # Group C — feature-flagged conditional routers
    # -------------------------------------------------------------------------
    if settings.mcpgateway_a2a_enabled:
        v1_router.include_router(a2a_router)
        logger.info("A2A router included - A2A features enabled")
    else:
        logger.info("A2A router not included - A2A features disabled")

    if settings.observability_enabled:
        # First-Party
        from mcpgateway.routers.observability import router as observability_router  # pylint: disable=import-outside-toplevel

        v1_router.include_router(observability_router)
        logger.info("Observability router included - observability API endpoints enabled")
    else:
        logger.info("Observability router not included - observability disabled")

    if settings.mcpgateway_reverse_proxy_enabled:
        try:
            # First-Party
            from mcpgateway.routers.reverse_proxy import router as reverse_proxy_router  # pylint: disable=import-outside-toplevel

            v1_router.include_router(reverse_proxy_router)
            logger.info("Reverse proxy router included")
        except ImportError:
            logger.debug("Reverse proxy router not available")
    else:
        logger.info("Reverse proxy router not included - feature disabled")

    if settings.toolops_enabled:
        try:
            # First-Party
            from mcpgateway.routers.toolops_router import toolops_router  # pylint: disable=import-outside-toplevel

            v1_router.include_router(toolops_router)
            logger.info("Toolops router included")
        except ImportError:
            logger.debug("Toolops router not available")

    if settings.mcpgateway_tool_cancellation_enabled:
        try:
            # First-Party
            from mcpgateway.routers.cancellation_router import router as cancellation_router  # pylint: disable=import-outside-toplevel

            v1_router.include_router(cancellation_router)
            logger.info("Cancellation router included (tool cancellation enabled)")
        except ImportError:
            logger.debug("Cancellation router not available")
    else:
        logger.info("Tool cancellation feature disabled - cancellation endpoints not available")

    if settings.metrics_cleanup_enabled or settings.metrics_rollup_enabled:
        # First-Party
        from mcpgateway.routers.metrics_maintenance import router as metrics_maintenance_router  # pylint: disable=import-outside-toplevel

        v1_router.include_router(metrics_maintenance_router)
        logger.info("Metrics maintenance router included - cleanup/rollup API endpoints enabled")

    # -------------------------------------------------------------------------
    # Group D — auth cluster (all gated on email_auth_enabled)
    # -------------------------------------------------------------------------
    if settings.email_auth_enabled:
        try:
            # First-Party
            from mcpgateway.routers.auth import auth_router  # pylint: disable=import-outside-toplevel
            from mcpgateway.routers.email_auth import email_auth_router  # pylint: disable=import-outside-toplevel

            v1_router.include_router(email_auth_router, prefix="/auth/email", tags=["Email Authentication"])
            v1_router.include_router(auth_router, tags=["Main Authentication"])
            logger.info("Authentication routers included - Auth enabled")

            if settings.sso_enabled:
                try:
                    # First-Party
                    from mcpgateway.routers.sso import sso_router  # pylint: disable=import-outside-toplevel

                    v1_router.include_router(sso_router, tags=["SSO Authentication"])
                    logger.info("SSO router included - SSO authentication enabled")
                except ImportError as e:
                    logger.error(f"SSO router not available: {e}")
            else:
                logger.info("SSO router not included - SSO authentication disabled")
        except ImportError as e:
            logger.error(f"Authentication routers not available: {e}")

        try:
            # First-Party
            from mcpgateway.routers.teams import teams_router  # pylint: disable=import-outside-toplevel

            v1_router.include_router(teams_router, prefix="/teams", tags=["Teams"])
            logger.info("Team management router included - Teams enabled with email auth")
        except ImportError as e:
            logger.error(f"Team management router not available: {e}")

        try:
            # First-Party
            from mcpgateway.routers.tokens import router as tokens_router  # pylint: disable=import-outside-toplevel

            v1_router.include_router(tokens_router, tags=["JWT Token Catalog"])
            logger.info("JWT Token Catalog router included - Token management enabled with email auth")
        except ImportError as e:
            logger.error(f"JWT Token Catalog router not available: {e}")

        try:
            # First-Party
            from mcpgateway.routers.rbac import router as rbac_router  # pylint: disable=import-outside-toplevel

            v1_router.include_router(rbac_router, tags=["RBAC"])
            logger.info("RBAC router included - Role-based access control enabled")
        except ImportError as e:
            logger.error(f"RBAC router not available: {e}")
    else:
        logger.info("Auth/teams/tokens/RBAC routers not included - Email auth disabled")

    # -------------------------------------------------------------------------
    # Group E — LLM cluster (llm_proxy_router excluded; it lives on app directly
    # because its prefix is runtime-configured via settings.llm_api_prefix)
    # -------------------------------------------------------------------------
    if settings.llmchat_enabled:
        try:
            # First-Party
            from mcpgateway.routers.llmchat_router import llmchat_router  # pylint: disable=import-outside-toplevel

            v1_router.include_router(llmchat_router)
            logger.info("LLM Chat router included")
        except ImportError:
            logger.debug("LLM Chat router not available")

        try:
            # First-Party
            from mcpgateway.routers.llm_admin_router import llm_admin_router  # pylint: disable=import-outside-toplevel
            from mcpgateway.routers.llm_config_router import llm_config_router  # pylint: disable=import-outside-toplevel

            v1_router.include_router(llm_config_router, prefix="/llm", tags=["LLM Configuration"])
            v1_router.include_router(llm_admin_router, prefix="/admin/llm", tags=["LLM Admin"])
            logger.info("LLM configuration and admin routers included")
        except ImportError as e:
            logger.debug(f"LLM routers not available: {e}")

    # -------------------------------------------------------------------------
    # Group F — admin cluster
    # -------------------------------------------------------------------------
    if settings.mcpgateway_admin_api_enabled:
        try:
            # First-Party
            from mcpgateway.routers.compliance_router import router as compliance_router  # pylint: disable=import-outside-toplevel

            v1_router.include_router(compliance_router)
            logger.info("Compliance router included")
        except ImportError as e:  # pragma: no cover - optional import guard
            logger.warning(f"Compliance router not available: {e}")

        try:
            # First-Party
            from mcpgateway.admin import admin_router, set_logging_service, validate_section_permissions  # pylint: disable=import-outside-toplevel

            set_logging_service(logging_service)
            v1_router.include_router(admin_router)
            validate_section_permissions(admin_router)
            logger.info("Admin router included - Admin API enabled")

            # First-Party
            from mcpgateway.routers.runtime_admin_router import runtime_admin_router  # pylint: disable=import-outside-toplevel

            v1_router.include_router(runtime_admin_router, prefix="/admin/runtime", tags=["Runtime Admin"])
        except ImportError as e:
            logger.error(f"Admin router not available: {e}")
    else:
        logger.warning("Admin API routes not mounted - Admin API disabled via MCPGATEWAY_ADMIN_API_ENABLED=False")

    return v1_router
