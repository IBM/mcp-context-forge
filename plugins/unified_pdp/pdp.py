"""Unified Policy Decision Point (PDP) – the orchestrator.

This is the **only** class that gateway code (hooks, routers, services)
needs to import.  Everything else in this package is an implementation detail.

Lifecycle
---------
1. ``PDPConfig`` is loaded from YAML / env at application startup.
2. ``PolicyDecisionPoint`` is instantiated once and held as a singleton
   (or injected via FastAPI's dependency system).
3. ``check_access()`` is called on every tool invocation, resource fetch,
   etc.  It is the hot path – designed to be <10 ms p95 with caching.

Combination modes
-----------------
* ``all_must_allow`` – every enabled engine must return ALLOW.  If any
  returns DENY the aggregate is DENY and the first deny reason wins.
* ``any_allow``      – at least one enabled engine must return ALLOW.
  Useful when engines are alternatives (e.g. "RBAC OR MAC").
* ``first_match``    – engines are sorted by priority (ascending).  The
  first engine that returns a non-error decision wins.  Remaining engines
  are not consulted.  When ``parallel_evaluation`` is True we still launch
  all engines but short-circuit the combination after the highest-priority
  result arrives.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List

from .adapter import PolicyEngineAdapter, PolicyEvaluationError
from .cache import DecisionCache
from .engines import CedarEngineAdapter, MACEngineAdapter, NativeRBACAdapter, OPAEngineAdapter
from .pdp_models import (
    AccessDecision,
    CombinationMode,
    Context,
    Decision,
    DecisionExplanation,
    EngineDecision,
    EngineType,
    PDPConfig,
    PDPHealthReport,
    Permission,
    Resource,
    Subject,
)

logger = logging.getLogger(__name__)

# Factory map – ties EngineType enum values to their adapter classes
_ENGINE_FACTORY: Dict[EngineType, type] = {
    EngineType.OPA: OPAEngineAdapter,
    EngineType.CEDAR: CedarEngineAdapter,
    EngineType.NATIVE: NativeRBACAdapter,
    EngineType.MAC: MACEngineAdapter,
}


class PolicyDecisionPoint:
    """Unified PDP – single entry-point for all access decisions.

    This is the main orchestrator that gateway code uses to evaluate access
    requests. It manages multiple policy engines, caching, and combination logic.

    Args:
        config: Full PDP configuration including engines, combination mode,
            cache settings, and performance tuning.

    Attributes:
        _config: The PDP configuration.
        _engines: Map of engine type to initialized adapter instance.
        _engine_priorities: Map of engine type to priority (lower = higher priority).
        _cache: Decision cache for hot-path performance.
    """

    def __init__(self, config: PDPConfig):
        """Initialize the Policy Decision Point with the given configuration.

        Args:
            config: PDPConfig containing engine definitions, combination mode,
                default decision, cache settings, and performance options.
        """
        self._config = config
        self._engines: Dict[EngineType, PolicyEngineAdapter] = {}
        self._engine_priorities: Dict[EngineType, int] = {}
        self._cache = DecisionCache(
            config.cache,
            redis_url=None,  # TODO: wire from config if redis_url supplied
        )
        self._initialize_engines()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _initialize_engines(self) -> None:
        """Instantiate adapters for every enabled engine in the configuration.

        Iterates through engine configs, skips disabled engines, creates adapter
        instances using the factory map, and stores them with their priorities.
        Logs warnings for unknown engine types and errors during initialization.
        """
        for eng_cfg in self._config.engines:
            if not eng_cfg.enabled:
                logger.info("PDP: skipping disabled engine %s", eng_cfg.name.value)
                continue

            factory = _ENGINE_FACTORY.get(eng_cfg.name)
            if factory is None:
                logger.warning("PDP: unknown engine type %s – skipped", eng_cfg.name)
                continue

            try:
                adapter = factory(settings=eng_cfg.settings)
                self._engines[eng_cfg.name] = adapter
                self._engine_priorities[eng_cfg.name] = eng_cfg.priority
                logger.info("PDP: initialized engine %s (priority %d)", eng_cfg.name.value, eng_cfg.priority)
            except Exception as exc:  # noqa: BLE001
                logger.error("PDP: failed to initialize engine %s: %s", eng_cfg.name.value, exc)

    # ------------------------------------------------------------------
    # Core: check_access
    # ------------------------------------------------------------------

    async def check_access(
        self,
        subject: Subject,
        action: str,
        resource: Resource,
        context: Context,
    ) -> AccessDecision:
        """Evaluate an access request against all configured engines.

        This is the primary hot-path method designed for <10ms p95 with caching.

        Processing steps:
        1. Check the cache for a prior decision.
        2. Launch engine evaluations (parallel or sequential per config).
        3. Apply combination logic (all_must_allow, any_allow, first_match).
        4. Store the result in the cache.
        5. Return the unified AccessDecision.

        Args:
            subject: The authenticated user/principal requesting access.
            action: The action being performed (e.g., "tools.invoke.db-query").
            resource: The resource being accessed (tool, prompt, server, etc.).
            context: Request context including IP, timestamp, session info.

        Returns:
            AccessDecision containing the combined verdict, reason, matching
            policies, per-engine decisions, timing, and cache status.
        """
        overall_start = time.perf_counter()

        # --- 1. Cache lookup ---
        cached = await self._cache.get(subject, action, resource, context)
        if cached is not None:
            cached.cached = True
            logger.debug("PDP: cache hit for %s / %s", subject.email, action)
            return cached

        # --- 2. Evaluate engines ---
        engine_decisions = await self._evaluate_engines(subject, action, resource, context)

        # --- 3. Combine ---
        decision, reason, matched = self._combine(engine_decisions)

        total_ms = (time.perf_counter() - overall_start) * 1000

        result = AccessDecision(
            decision=decision,
            reason=reason,
            matching_policies=matched,
            engine_decisions=engine_decisions,
            duration_ms=round(total_ms, 2),
            cached=False,
        )

        # --- 4. Cache store ---
        await self._cache.put(subject, action, resource, context, result)

        logger.info(
            "PDP: %s | action=%s | subject=%s | engines=%s | %.1fms",
            decision.value.upper(),
            action,
            subject.email,
            [ed.engine.value for ed in engine_decisions],
            total_ms,
        )

        return result

    # ------------------------------------------------------------------
    # Engine evaluation (parallel or sequential)
    # ------------------------------------------------------------------

    async def _evaluate_engines(
        self,
        subject: Subject,
        action: str,
        resource: Resource,
        context: Context,
    ) -> List[EngineDecision]:
        """Run all enabled engines with the configured timeout.

        Delegates to parallel or sequential evaluation based on config.

        Args:
            subject: The authenticated user/principal requesting access.
            action: The action being performed.
            resource: The resource being accessed.
            context: Request context.

        Returns:
            List of EngineDecision objects from all evaluated engines.
        """
        timeout_s = self._config.performance.timeout_ms / 1000.0

        if self._config.performance.parallel_evaluation:
            return await self._evaluate_parallel(subject, action, resource, context, timeout_s)
        return await self._evaluate_sequential(subject, action, resource, context, timeout_s)

    async def _evaluate_parallel(
        self,
        subject: Subject,
        action: str,
        resource: Resource,
        context: Context,
        timeout_s: float,
    ) -> List[EngineDecision]:
        """Launch all engines concurrently via asyncio.gather.

        All engines run simultaneously with individual timeouts. Failed engines
        return default_decision rather than failing the entire request.

        Args:
            subject: The authenticated user/principal requesting access.
            action: The action being performed.
            resource: The resource being accessed.
            context: Request context.
            timeout_s: Per-engine timeout in seconds.

        Returns:
            List of EngineDecision objects from all engines.
        """

        async def _single(eng_type: EngineType, adapter: PolicyEngineAdapter) -> EngineDecision:
            """Evaluate a single engine with timeout and comprehensive error handling.

            Args:
                eng_type: The engine type identifier.
                adapter: The policy engine adapter to evaluate.

            Returns:
                EngineDecision from the engine, or default_decision on any error.
            """
            try:
                return await asyncio.wait_for(
                    adapter.evaluate(subject, action, resource, context),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning("PDP: engine %s timed out after %.0fms", eng_type.value, timeout_s * 1000)
                return EngineDecision(
                    engine=eng_type,
                    decision=self._config.default_decision,
                    reason=f"{eng_type.value}: timed out after {timeout_s * 1000:.0f}ms – using default decision",
                )
            except PolicyEvaluationError as exc:
                logger.warning("PDP: engine %s error: %s", eng_type.value, exc)
                return EngineDecision(
                    engine=eng_type,
                    decision=self._config.default_decision,
                    reason=f"{eng_type.value}: evaluation error – {exc}",
                )
            except Exception as exc:  # noqa: BLE001 – catch unexpected errors to avoid failing the whole request
                logger.exception("PDP: engine %s unexpected error: %s", eng_type.value, exc)
                return EngineDecision(
                    engine=eng_type,
                    decision=self._config.default_decision,
                    reason=f"{eng_type.value}: unexpected error – {type(exc).__name__}: {exc}",
                )

        tasks = [_single(eng_type, adapter) for eng_type, adapter in self._engines.items()]
        return list(await asyncio.gather(*tasks))

    async def _evaluate_sequential(
        self,
        subject: Subject,
        action: str,
        resource: Resource,
        context: Context,
        timeout_s: float,
    ) -> List[EngineDecision]:
        """Run engines sequentially, sorted by priority (lowest first).

        In FIRST_MATCH mode, stops after the first successful decision.
        Failed engines return default_decision and continue to next engine.

        Args:
            subject: The authenticated user/principal requesting access.
            action: The action being performed.
            resource: The resource being accessed.
            context: Request context.
            timeout_s: Per-engine timeout in seconds.

        Returns:
            List of EngineDecision objects from evaluated engines.
        """
        results: List[EngineDecision] = []
        sorted_engines = sorted(self._engines.items(), key=lambda item: self._engine_priorities.get(item[0], 99))

        for eng_type, adapter in sorted_engines:
            try:
                decision = await asyncio.wait_for(
                    adapter.evaluate(subject, action, resource, context),
                    timeout=timeout_s,
                )
                results.append(decision)

                # first_match short-circuit in sequential mode
                if self._config.combination_mode == CombinationMode.FIRST_MATCH:
                    break

            except (asyncio.TimeoutError, PolicyEvaluationError) as exc:
                logger.warning("PDP: engine %s error: %s", eng_type.value, exc)
                results.append(
                    EngineDecision(
                        engine=eng_type,
                        decision=self._config.default_decision,
                        reason=f"{eng_type.value}: {exc}",
                    )
                )
            except Exception as exc:  # noqa: BLE001 – catch unexpected errors to avoid failing the whole request
                logger.exception("PDP: engine %s unexpected error: %s", eng_type.value, exc)
                results.append(
                    EngineDecision(
                        engine=eng_type,
                        decision=self._config.default_decision,
                        reason=f"{eng_type.value}: unexpected error – {type(exc).__name__}: {exc}",
                    )
                )

        return results

    # ------------------------------------------------------------------
    # Combination logic
    # ------------------------------------------------------------------

    def _combine(
        self,
        decisions: List[EngineDecision],
    ) -> tuple[Decision, str, List[str]]:
        """Merge per-engine decisions into a single unified verdict.

        Applies the configured combination mode (ALL_MUST_ALLOW, ANY_ALLOW,
        or FIRST_MATCH) to produce the final decision.

        Args:
            decisions: List of EngineDecision objects from all evaluated engines.

        Returns:
            Tuple of (Decision enum, reason string, list of matching policy IDs).
        """
        if not decisions:
            return (
                self._config.default_decision,
                "PDP: no engines produced a decision – using default",
                [],
            )

        mode = self._config.combination_mode

        if mode == CombinationMode.ALL_MUST_ALLOW:
            return self._combine_all_must_allow(decisions)

        if mode == CombinationMode.ANY_ALLOW:
            return self._combine_any_allow(decisions)

        # FIRST_MATCH – use the first (highest priority) decision
        return self._combine_first_match(decisions)

    def _combine_all_must_allow(
        self, decisions: List[EngineDecision]
    ) -> tuple[Decision, str, List[str]]:
        """Apply AND logic: all engines must allow for access to be granted.

        Args:
            decisions: List of EngineDecision objects from all engines.

        Returns:
            Tuple of (DENY if any denied else ALLOW, combined reason, policy IDs).
        """
        denied = [d for d in decisions if d.decision == Decision.DENY]
        if denied:
            all_reasons = "; ".join(d.reason for d in denied)
            all_policies = [p for d in denied for p in d.matching_policies]
            return (Decision.DENY, f"[all_must_allow] {all_reasons}", all_policies)

        all_policies = [p for d in decisions for p in d.matching_policies]
        return (Decision.ALLOW, "[all_must_allow] All engines allowed", all_policies)

    def _combine_any_allow(
        self, decisions: List[EngineDecision]
    ) -> tuple[Decision, str, List[str]]:
        """Apply OR logic: at least one engine must allow for access.

        Args:
            decisions: List of EngineDecision objects from all engines.

        Returns:
            Tuple of (ALLOW if any allowed else DENY, reason, policy IDs).
        """
        allowed = [d for d in decisions if d.decision == Decision.ALLOW]
        if allowed:
            first_allow = allowed[0]
            all_policies = [p for d in allowed for p in d.matching_policies]
            return (Decision.ALLOW, f"[any_allow] Allowed by {first_allow.engine.value}: {first_allow.reason}", all_policies)

        # All denied
        all_reasons = "; ".join(d.reason for d in decisions)
        all_policies = [p for d in decisions for p in d.matching_policies]
        return (Decision.DENY, f"[any_allow] All engines denied: {all_reasons}", all_policies)

    def _combine_first_match(
        self, decisions: List[EngineDecision]
    ) -> tuple[Decision, str, List[str]]:
        """Use the first decision by priority (lowest priority number wins).

        Args:
            decisions: List of EngineDecision objects, sorted or unsorted.

        Returns:
            Tuple of (decision, reason, policy IDs) from highest-priority engine.
        """
        # decisions are already ordered by priority (sequential) or we sort here
        sorted_decisions = sorted(
            decisions,
            key=lambda d: self._engine_priorities.get(d.engine, 99),
        )
        first = sorted_decisions[0]
        return (first.decision, f"[first_match] {first.engine.value}: {first.reason}", first.matching_policies)

    # ------------------------------------------------------------------
    # Explain
    # ------------------------------------------------------------------

    async def explain_decision(
        self,
        subject: Subject,
        action: str,
        resource: Resource,
        context: Context,
    ) -> DecisionExplanation:
        """Run evaluation and return a verbose human-readable explanation.

        This intentionally bypasses the cache for accurate debugging and audit.
        Not intended for hot-path use due to lack of caching.

        Args:
            subject: The authenticated user/principal requesting access.
            action: The action being performed.
            resource: The resource being accessed.
            context: Request context.

        Returns:
            DecisionExplanation with detailed per-engine breakdown, combination
            mode used, which engines were evaluated vs skipped, and timing.
        """
        engine_decisions = await self._evaluate_engines(subject, action, resource, context)
        decision, reason, _ = self._combine(engine_decisions)

        evaluated = [d.engine for d in engine_decisions]
        all_engines = set(self._engines.keys())
        skipped = [e for e in all_engines if e not in evaluated]

        engine_explanations = [
            {
                "engine": d.engine.value,
                "decision": d.decision.value,
                "reason": d.reason,
                "matching_policies": d.matching_policies,
                "duration_ms": d.duration_ms,
                "metadata": d.metadata,
            }
            for d in engine_decisions
        ]

        return DecisionExplanation(
            decision=decision,
            summary=reason,
            engine_explanations=engine_explanations,
            combination_mode=self._config.combination_mode,
            evaluated_engines=evaluated,
            skipped_engines=skipped,
        )

    # ------------------------------------------------------------------
    # Effective permissions
    # ------------------------------------------------------------------

    async def get_effective_permissions(
        self,
        subject: Subject,
        context: Context,
    ) -> List[Permission]:
        """Aggregate permissions from all engines that support enumeration.

        Calls get_permissions() on each engine and combines results. Engines
        that don't support enumeration (raise NotImplementedError) are skipped.

        Args:
            subject: The authenticated user/principal to enumerate permissions for.
            context: Request context for conditional permission evaluation.

        Returns:
            Combined list of Permission objects from all supporting engines.
        """
        all_perms: List[Permission] = []
        for eng_type, adapter in self._engines.items():
            try:
                perms = await adapter.get_permissions(subject, context)
                all_perms.extend(perms)
            except NotImplementedError:
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("PDP: get_permissions failed for %s: %s", eng_type.value, exc)

        return all_perms

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health(self) -> PDPHealthReport:
        """Check all engines and return an aggregate health report.

        Runs health_check() on each initialized engine and marks disabled
        engines appropriately. The overall healthy status is True only if
        no engine reports UNHEALTHY.

        Returns:
            PDPHealthReport with overall healthy flag and per-engine reports.
        """
        reports = []
        for _, adapter in self._engines.items():
            reports.append(await adapter.health_check())

        # Add DISABLED entries for engines in config but not initialized
        initialized = set(self._engines.keys())
        from .pdp_models import EngineHealthReport, EngineStatus

        for eng_cfg in self._config.engines:
            if eng_cfg.name not in initialized:
                reports.append(
                    EngineHealthReport(engine=eng_cfg.name, status=EngineStatus.DISABLED)
                )

        healthy = all(r.status.value != "unhealthy" for r in reports)
        return PDPHealthReport(healthy=healthy, engines=reports)

    # ------------------------------------------------------------------
    # Cache stats (for admin UI / metrics)
    # ------------------------------------------------------------------

    def cache_stats(self) -> dict:
        """Return cache statistics for monitoring and admin UI.

        Returns:
            Dictionary with hits, misses, hit_rate, size, max_entries,
            ttl_seconds, and redis_enabled status.
        """
        return self._cache.stats()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Gracefully close all engine adapters and release resources.

        Calls close() on each adapter that supports it (e.g., to close HTTP
        clients for OPA/Cedar engines). Should be called during shutdown.
        """
        for adapter in self._engines.values():
            if hasattr(adapter, "close"):
                await adapter.close()
