"""Read-only deterministic Praxis shadow rendering and convergence comparison."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Final

import anyio
from anyio.abc import TaskGroup
from anyio.to_thread import run_sync as run_sync_in_worker_thread
from sqlalchemy import select
from sqlalchemy.orm import Session

from mcpgateway.db import PraxisTarget
from mcpgateway.services.praxis_bundle_reconciler import PraxisBundleReconciler
from mcpgateway.services.praxis_bundle_renderer import parse_cpex_document, render_praxis_bundle
from mcpgateway.services.praxis_bundle_validation import PraxisBundleRenderError
from mcpgateway.services.praxis_config_models import PraxisBundleArtifact, PraxisConfigSourceSnapshot, PraxisSourceError
from mcpgateway.services.praxis_config_source import PraxisConfigSourceService
from mcpgateway.services.praxis_config_models import validate_canonical_archive

_SCAN_INTERVAL_SECONDS: Final = 60.0


class PraxisShadowMismatchKind(StrEnum):
    """Closed mismatch vocabulary safe for status and logs."""

    MISSING_ROUTE = "missing_route"
    UNEXPECTED_ROUTE = "unexpected_route"
    PLUGIN_MISMATCH = "plugin_mismatch"


@dataclass(frozen=True, slots=True)
class PraxisShadowDiff:
    """One redacted mismatch identified only by a stable digest."""

    kind: PraxisShadowMismatchKind
    route_digest: str


@dataclass(frozen=True, slots=True)
class PraxisShadowComparison:
    """Bounded-field status for one target's shadow comparison."""

    target_id: str
    representable: bool
    converged: bool
    reason: str | None
    source_fingerprint: str | None
    diffs: tuple[PraxisShadowDiff, ...]


RouteKey = tuple[str, str, str, str]


def _route_digest(route: RouteKey) -> str:
    encoded = json.dumps(route, ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _effective_routes(snapshot: PraxisConfigSourceSnapshot) -> dict[RouteKey, tuple[str, ...]]:
    routes: dict[RouteKey, tuple[str, ...]] = {}
    for server in snapshot.servers:
        for tool in server.tools:
            plugins = tuple(plugin.name for plugin in (tool.compiled_config.plugins or []))
            routes[(server.scope, server.id, "tool", tool.name)] = plugins
    return routes


def _generated_routes(snapshot: PraxisConfigSourceSnapshot, artifact: PraxisBundleArtifact) -> dict[RouteKey, tuple[str, ...]]:
    documents = {document.path: document.content for document in validate_canonical_archive(artifact.archive_bytes)}
    routes: dict[RouteKey, tuple[str, ...]] = {}
    for server in snapshot.servers:
        path = f"cpex/{server.scope}--{server.id}.yaml"
        document = parse_cpex_document(documents[path])
        for route in document.routes:
            if route.tool is not None and route.tool != "*":
                routes[(server.scope, server.id, "tool", route.tool)] = route.plugins
    return routes


def compare_shadow_routes(snapshot: PraxisConfigSourceSnapshot, artifact: PraxisBundleArtifact) -> tuple[PraxisShadowDiff, ...]:
    """Compare Python effective tool/plugin routes with generated CPEX routes."""
    effective = _effective_routes(snapshot)
    generated = _generated_routes(snapshot, artifact)
    diffs: list[PraxisShadowDiff] = []
    for route in sorted(effective.keys() - generated.keys()):
        diffs.append(PraxisShadowDiff(PraxisShadowMismatchKind.MISSING_ROUTE, _route_digest(route)))
    for route in sorted(generated.keys() - effective.keys()):
        diffs.append(PraxisShadowDiff(PraxisShadowMismatchKind.UNEXPECTED_ROUTE, _route_digest(route)))
    for route in sorted(effective.keys() & generated.keys()):
        if effective[route] != generated[route]:
            diffs.append(PraxisShadowDiff(PraxisShadowMismatchKind.PLUGIN_MISMATCH, _route_digest(route)))
    return tuple(sorted(diffs, key=lambda item: (item.route_digest, item.kind.value)))


class PraxisShadowRendererService:
    """Periodically compare all enabled targets without any publication dependency."""

    def __init__(self, session_factory: Callable[[], Session], source_service: PraxisConfigSourceService, *, interval_seconds: float = _SCAN_INTERVAL_SECONDS) -> None:
        """Bind read-only target sessions and the authoritative source service."""
        self._sessions = session_factory
        self._source = source_service
        self._interval_seconds = interval_seconds
        self._task_group: TaskGroup | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._stop = anyio.Event()
        self._results: dict[str, PraxisShadowComparison] = {}

    @property
    def results(self) -> tuple[PraxisShadowComparison, ...]:
        """Return deterministic latest statuses for this process."""
        return tuple(self._results[target_id] for target_id in sorted(self._results))

    def compare(self, target_id: str) -> PraxisShadowComparison:
        """Render and compare one target without retaining artifact content."""
        try:
            snapshot = self._source.snapshot(target_id)
        except PraxisSourceError as error:
            return PraxisShadowComparison(target_id, False, False, error.code.value, None, ())
        try:
            artifact = render_praxis_bundle(snapshot)
            diffs = compare_shadow_routes(snapshot, artifact)
        except PraxisBundleRenderError as error:
            return PraxisShadowComparison(target_id, True, False, error.code.value, snapshot.source_fingerprint, ())
        return PraxisShadowComparison(target_id, True, not diffs, None, snapshot.source_fingerprint, diffs)

    def scan_once(self) -> tuple[PraxisShadowComparison, ...]:
        """Compare every enabled target using database-authoritative assignments."""
        with self._sessions() as db:
            target_ids = tuple(db.scalars(select(PraxisTarget.id).where(PraxisTarget.enabled.is_(True)).order_by(PraxisTarget.id)).all())
        self._results = {target_id: self.compare(target_id) for target_id in target_ids}
        return self.results

    async def start(self) -> None:
        """Start the idempotent read-only shadow loop."""
        if self._task_group is not None:
            return
        self._stop = anyio.Event()
        exit_stack = AsyncExitStack()
        task_group = await exit_stack.enter_async_context(anyio.create_task_group())
        task_group.start_soon(self._run)
        self._task_group = task_group
        self._exit_stack = exit_stack

    async def shutdown(self) -> None:
        """Stop the shadow loop."""
        if self._task_group is None:
            return
        self._stop.set()
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
        self._task_group = None
        self._exit_stack = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            await run_sync_in_worker_thread(self.scan_once)
            with anyio.move_on_after(self._interval_seconds):
                await self._stop.wait()


class PraxisReconcilerLifecycleService:
    """Run the database-serialized reconciliation fallback loop."""

    def __init__(self, reconciler: PraxisBundleReconciler, *, interval_seconds: float = _SCAN_INTERVAL_SECONDS) -> None:
        """Bind the database-authoritative reconciler and scan interval."""
        self._reconciler = reconciler
        self._interval_seconds = interval_seconds
        self._task_group: TaskGroup | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._stop = anyio.Event()

    async def start(self) -> None:
        """Start reconciliation once; SQL serialization provides worker correctness."""
        if self._task_group is None:
            self._stop = anyio.Event()
            exit_stack = AsyncExitStack()
            task_group = await exit_stack.enter_async_context(anyio.create_task_group())
            task_group.start_soon(self._run)
            self._task_group = task_group
            self._exit_stack = exit_stack

    async def shutdown(self) -> None:
        """Stop reconciliation."""
        if self._task_group is not None:
            self._stop.set()
            if self._exit_stack is not None:
                await self._exit_stack.aclose()
            self._task_group = None
            self._exit_stack = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            await run_sync_in_worker_thread(self._reconciler.fallback_scan)
            with anyio.move_on_after(self._interval_seconds):
                await self._stop.wait()


__all__ = (
    "PraxisReconcilerLifecycleService",
    "PraxisShadowComparison",
    "PraxisShadowDiff",
    "PraxisShadowMismatchKind",
    "PraxisShadowRendererService",
    "compare_shadow_routes",
)
