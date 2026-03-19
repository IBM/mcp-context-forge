# -*- coding: utf-8 -*-
"""Location: ./plugins/unified_pdp/unified_pdp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Your Name

Unified Policy Decision Point plugin.

Integrates the PDP orchestrator into ContextForge gateway plugin
framework.  Hooks into ``tool_pre_invoke`` and ``resource_pre_fetch``; on
every call it builds a Subject/Resource/Context from the hook payload,
calls ``PolicyDecisionPoint.check_access()``, and either passes the
request through or blocks it with a ``PluginViolation``.

Configuration (inside plugins/config.yaml ``config:`` block)
------------------------------------------------------------
See ``PDPConfig`` in ``pdp_models.py`` for the full schema.  Minimal example::

    config:
      engines:
        - name: native
          enabled: true
          priority: 1
          settings:
            rules_file: "plugins/unified_pdp/default_rules.json"
      combination_mode: "all_must_allow"
      default_decision: "deny"
      cache:
        enabled: true
        ttl_seconds: 60
        max_entries: 10000
      performance:
        timeout_ms: 1000
        parallel_evaluation: true
"""

# Standard
import logging

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
)
from mcpgateway.plugins.framework.hooks.tools import (
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from mcpgateway.plugins.framework.hooks.resources import (
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
)

# Sibling imports — the PDP engine lives alongside this file in plugins/unified_pdp/
from .pdp_models import (
    CacheConfig,
    CombinationMode,
    Decision,
    EngineConfig,
    EngineType,
    PDPConfig,
    PerformanceConfig,
    Resource,
    Subject,
    Context,
)
from .pdp import PolicyDecisionPoint

logger = logging.getLogger(__name__)


class UnifiedPDPPlugin(Plugin):
    """Unified Policy Decision Point — gateway plugin entry point.

    The plugin loader instantiates this class once at startup with the
    ``PluginConfig`` that was parsed from ``plugins/config.yaml``.  The
    ``config`` dict inside that ``PluginConfig`` is our PDP configuration;
    we parse it into ``PDPConfig`` here and spin up the
    ``PolicyDecisionPoint`` singleton.

    Hook methods
    ------------
    * ``tool_pre_invoke``      – called before every tool invocation.
    * ``resource_pre_fetch``   – called before every resource read.

    Both follow the same pattern:
        1. Extract Subject / Resource / Context from the hook payload.
        2. Call ``self._pdp.check_access()``.
        3. ALLOW → return the payload unmodified (``continue_processing=True``).
        4. DENY  → return with ``continue_processing=False`` + ``PluginViolation``.
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialise plugin and build the PDP from the config block.

        Args:
            config: The full ``PluginConfig`` as parsed from YAML.
                    ``config.config`` is the dict we care about — it maps
                    directly onto ``PDPConfig``.
        """
        super().__init__(config)
        self._pdp = self._build_pdp(self._config.config or {})

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Cleanup PDP resources during application shutdown.

        Closes HTTP clients for external engines (OPA, Cedar) and releases
        any other resources held by the PolicyDecisionPoint.
        """
        await self._pdp.close()

    # ------------------------------------------------------------------
    # PDP construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_pdp(raw: dict) -> PolicyDecisionPoint:
        """Parse the raw YAML config dict into a PDPConfig and create the PDP.

        Args:
            raw: The ``config:`` block from plugins/config.yaml.

        Returns:
            An initialised PolicyDecisionPoint ready to evaluate requests.
        """
        engines = [
            EngineConfig(
                name=EngineType(e["name"]),
                enabled=e.get("enabled", True),
                priority=e.get("priority", 1),
                settings=e.get("settings", {}),
            )
            for e in raw.get("engines", [])
        ]

        cache_raw = raw.get("cache", {})
        perf_raw = raw.get("performance", {})

        pdp_config = PDPConfig(
            engines=engines,
            combination_mode=CombinationMode(raw.get("combination_mode", "all_must_allow")),
            default_decision=Decision(raw.get("default_decision", "deny")),
            cache=CacheConfig(
                enabled=cache_raw.get("enabled", True),
                ttl_seconds=cache_raw.get("ttl_seconds", 60),
                max_entries=cache_raw.get("max_entries", 10000),
            ),
            performance=PerformanceConfig(
                timeout_ms=perf_raw.get("timeout_ms", 1000),
                parallel_evaluation=perf_raw.get("parallel_evaluation", True),
            ),
        )

        pdp = PolicyDecisionPoint(pdp_config)
        logger.info(
            "UnifiedPDPPlugin initialised | engines=%s | combination=%s",
            [e.name.value for e in engines if e.enabled],
            pdp_config.combination_mode.value,
        )
        return pdp

    # ------------------------------------------------------------------
    # Subject / Resource / Context extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_subject(context: PluginContext) -> Subject:
        """Build a PDP Subject from the framework's PluginContext.

        The gateway populates ``global_context.user`` when
        ``include_user_info`` is enabled in plugin_settings.  We fall
        back to safe defaults when fields are missing.

        Args:
            context: The PluginContext provided by the framework.

        Returns:
            A Subject populated from the gateway's user info.
        """
        user = context.global_context.user or {}

        # user can be a plain string (just an ID) or a dict with details
        if isinstance(user, str):
            return Subject(email=user, roles=[])

        return Subject(
            email=user.get("email", "anonymous@internal"),
            roles=user.get("roles", []),
            team_id=user.get("team_id") or context.global_context.tenant_id,
            mfa_verified=user.get("mfa_verified", False),
            clearance_level=user.get("clearance_level"),
            attributes=user.get("attributes", {}),
        )

    @staticmethod
    def _extract_http_metadata(headers) -> dict:
        """Extract IP and user_agent from HTTP headers.

        Args:
            headers: HttpHeaderPayload or None.

        Returns:
            Dict with 'ip' and 'user_agent' keys (values may be None).
        """
        if headers is None:
            return {"ip": None, "user_agent": None}

        # Try to get headers as dict
        try:
            header_dict = headers.root if hasattr(headers, "root") else dict(headers)
        except (TypeError, AttributeError):
            return {"ip": None, "user_agent": None}

        # Extract IP from X-Forwarded-For or X-Real-IP
        ip = header_dict.get("x-forwarded-for") or header_dict.get("x-real-ip")
        if ip and "," in ip:
            ip = ip.split(",")[0].strip()  # Take first IP in chain

        # Extract User-Agent
        user_agent = header_dict.get("user-agent")

        return {"ip": ip, "user_agent": user_agent}

    # ------------------------------------------------------------------
    # Hook: tool_pre_invoke
    # ------------------------------------------------------------------

    async def tool_pre_invoke(
        self,
        payload: ToolPreInvokePayload,
        context: PluginContext,
    ) -> ToolPreInvokeResult:
        """Called before every tool invocation.

        Builds the action string as ``tools.invoke.<tool_name>`` so that
        policies can match on the specific tool or use a wildcard
        (``tools.invoke.*``).

        Args:
            payload: Contains the tool name and invocation arguments.
            context: Gateway-provided request context (user, tenant, etc.).

        Returns:
            A ToolPreInvokeResult — either pass-through or blocked with a
            PluginViolation.
        """
        subject = self._extract_subject(context)

        # Extract HTTP metadata from headers for IP and user_agent
        http_meta = self._extract_http_metadata(payload.headers)

        # Extract classification_level from tool args if provided (for MAC engine)
        tool_args = payload.args or {}
        classification_level = tool_args.get("classification_level")

        resource = Resource(
            type="tool",
            id=payload.name,
            server=context.global_context.server_id,
            classification_level=classification_level,
            # Pass tool annotations for fine-grained policy checks
            annotations={"args_keys": list(tool_args.keys())},
        )

        pdp_context = Context(
            ip=http_meta["ip"],
            user_agent=http_meta["user_agent"],
            session_id=context.global_context.request_id,
            # Pass tool args to context.extra for policy evaluation
            extra={"tool_args": payload.args or {}},
        )

        action = f"tools.invoke.{payload.name}"

        decision = await self._pdp.check_access(subject, action, resource, pdp_context)

        if decision.decision == Decision.DENY:
            logger.warning(
                "PDP DENY tool_pre_invoke | tool=%s | user=%s | reason=%s",
                payload.name,
                subject.email,
                decision.reason,
            )
            violation = PluginViolation(
                reason="Policy decision: DENY",
                description=decision.reason or "Access denied by unified PDP",
                code="PDP_DENY",
                details={
                    "tool": payload.name,
                    "user": subject.email,
                    "engines": [ed.engine.value for ed in decision.engine_decisions],
                },
            )
            return ToolPreInvokeResult(
                continue_processing=False,
                modified_payload=payload,
                violation=violation,
            )

        logger.debug(
            "PDP ALLOW tool_pre_invoke | tool=%s | user=%s | cached=%s",
            payload.name,
            subject.email,
            decision.cached,
        )
        return ToolPreInvokeResult(modified_payload=payload)

    # ------------------------------------------------------------------
    # Hook: resource_pre_fetch
    # ------------------------------------------------------------------

    async def resource_pre_fetch(
        self,
        payload: ResourcePreFetchPayload,
        context: PluginContext,
    ) -> ResourcePreFetchResult:
        """Called before every resource fetch.

        The resource ID is the URI from the payload.  The action is fixed
        as ``resources.fetch`` — policies that need to distinguish
        individual resources should match on the resource ID.

        Args:
            payload: Contains the resource URI and optional metadata.
            context: Gateway-provided request context.

        Returns:
            A ResourcePreFetchResult — either pass-through or blocked.
        """
        subject = self._extract_subject(context)

        # Extract classification_level from metadata if provided (for MAC engine)
        metadata = payload.metadata or {}
        classification_level = metadata.get("classification_level")

        resource = Resource(
            type="resource",
            id=payload.uri,
            server=context.global_context.server_id,
            classification_level=classification_level,
            # Pass resource metadata for fine-grained policy checks
            annotations=metadata,
        )

        pdp_context = Context(
            session_id=context.global_context.request_id,
            # Pass resource metadata to context.extra as well
            extra={"resource_metadata": payload.metadata or {}},
        )

        action = "resources.fetch"

        decision = await self._pdp.check_access(subject, action, resource, pdp_context)

        if decision.decision == Decision.DENY:
            logger.warning(
                "PDP DENY resource_pre_fetch | resource=%s | user=%s | reason=%s",
                payload.uri,
                subject.email,
                decision.reason,
            )
            violation = PluginViolation(
                reason="Policy decision: DENY",
                description=decision.reason or "Access denied by unified PDP",
                code="PDP_DENY",
                details={
                    "resource_uri": payload.uri,
                    "user": subject.email,
                    "engines": [ed.engine.value for ed in decision.engine_decisions],
                },
            )
            return ResourcePreFetchResult(
                continue_processing=False,
                modified_payload=payload,
                violation=violation,
            )

        logger.debug(
            "PDP ALLOW resource_pre_fetch | resource=%s | user=%s | cached=%s",
            payload.uri,
            subject.email,
            decision.cached,
        )
        return ResourcePreFetchResult(modified_payload=payload)
