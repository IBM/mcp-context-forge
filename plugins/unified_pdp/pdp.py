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

    Parameters
    ----------
    config : PDPConfig
        Full configuration (engines, combination mode, cache, perf).
    """

    def __init__(self, config: PDPConfig):
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
        """Instantiate adapters for every enabled engine in the config."""
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

        This is the primary hot-path method.  It:
        1. Checks the cache.
        2. Launches engine evaluations (in parallel if configured).
        3. Applies combination logic.
        4. Stores the result in the cache.
        5. Returns the unified ``AccessDecision``.
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
        """Run all enabled engines, respecting the timeout setting."""
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
        """Launch all engines concurrently via asyncio.gather."""

        async def _single(eng_type: EngineType, adapter: PolicyEngineAdapter) -> EngineDecision:
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
        """Run engines one at a time, sorted by priority."""
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
                results.append(
                    EngineDecision(
                        engine=eng_type,
                        decision=self._config.default_decision,
                        reason=f"{eng_type.value}: {exc}",
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
        """Merge per-engine decisions into a single verdict.

        Returns
        -------
        (decision, reason, matched_policies)
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
        """AND logic – all engines must allow."""
        denied = [d for d in decisions if d.decision == Decision.DENY]
        if denied:
            first_deny = denied[0]
            all_reasons = "; ".join(d.reason for d in denied)
            all_policies = [p for d in denied for p in d.matching_policies]
            return (Decision.DENY, f"[all_must_allow] {all_reasons}", all_policies)

        all_policies = [p for d in decisions for p in d.matching_policies]
        return (Decision.ALLOW, "[all_must_allow] All engines allowed", all_policies)

    def _combine_any_allow(
        self, decisions: List[EngineDecision]
    ) -> tuple[Decision, str, List[str]]:
        """OR logic – at least one engine must allow."""
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
        """First non-error decision by priority wins."""
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

        This intentionally **bypasses the cache** – it is meant for
        debugging and audit, not the hot path.
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
        """Aggregate permissions from all engines that support enumeration."""
        all_perms: List[Permission] = []
        for _, adapter in self._engines.items():
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
        """Check all engines and return an aggregate health report."""
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
        return self._cache.stats()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Gracefully close all engine adapters."""
        for adapter in self._engines.values():
            if hasattr(adapter, "close"):
                await adapter.close()
