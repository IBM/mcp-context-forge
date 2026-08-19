# -*- coding: utf-8 -*-
"""Bounded process-local queue for asynchronous ToolService invocations.

The service is deliberately an in-process implementation: job state and
results live only in the worker that accepted the request.  Its public API and
executor boundary are kept independent of the HTTP router so a durable broker
(for example Redis Streams, RabbitMQ, or a database-backed queue) can replace
the storage/dispatch layer later without changing the REST contract.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, Literal, Optional
import uuid

# Third-Party
from cpex.framework import GlobalContext, HttpAuthCheckPermissionPayload, HttpHookType
import orjson
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.cache.global_config_cache import global_config_cache
from mcpgateway.config import settings
from mcpgateway.db import EmailApiToken, EmailTeamMember, EmailUser, fresh_db_session, Gateway as DbGateway, server_tool_association
from mcpgateway.middleware.rbac import token_scope_grants
from mcpgateway.plugins import get_plugin_manager
from mcpgateway.plugins.gateway_plugin_manager import make_context_id
from mcpgateway.plugins.utils import build_request_extensions, record_plugin_metrics
from mcpgateway.schemas_async_jobs import AsyncJobStatus
from mcpgateway.services.observability_service import current_trace_id
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.services.token_blocklist_service import get_token_blocklist_service
from mcpgateway.services.tool_service import ToolService
from mcpgateway.utils.trace_redaction import sanitize_trace_text

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
_TARGET_VISIBILITIES = frozenset({"private", "team", "public"})


class AsyncJobError(Exception):
    """Base error for asynchronous job operations."""


class AsyncJobServiceUnavailableError(AsyncJobError):
    """Raised when enqueue is attempted before startup or during shutdown."""


class AsyncJobQueueFullError(AsyncJobError):
    """Raised when the bounded pending queue has reached capacity."""


class AsyncJobPayloadTooLargeError(AsyncJobError):
    """Raised when a request would retain more memory than one job allows."""


class AsyncJobResultTooLargeError(AsyncJobError):
    """Raised when a completed result is too large for process-local retention."""


class AsyncJobNotFoundError(AsyncJobError):
    """Raised for a missing job or a job owned by another principal."""


class AsyncJobStateConflictError(AsyncJobError):
    """Raised when an operation is invalid for the current terminal state."""


class AsyncJobAuthorizationError(AsyncJobError):
    """Raised when current session membership or RBAC no longer permits execution."""


@dataclass(frozen=True, slots=True)
class AsyncJobSummarySnapshot:
    """Immutable, credential-free job summary without retained result data."""

    id: str
    tool_id: str
    tool_name: str
    status: AsyncJobStatus
    timeout_seconds: float
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    duration_ms: Optional[float]
    error: Optional[Dict[str, str]]


@dataclass(frozen=True, slots=True)
class AsyncJobSnapshot(AsyncJobSummarySnapshot):
    """Immutable detail representation returned only by single-job operations."""

    result: Optional[Dict[str, Any]]


@dataclass(slots=True)
class _JobRecord:
    """Private job state, including execution credentials never exposed by API."""

    id: str
    owner_email: str
    access_user_email: Optional[str]
    access_is_admin: bool
    token_teams: Optional[list[str]]
    tool_id: str
    tool_name: str
    target_visibility: str
    target_team_id: Optional[str]
    target_owner_email: Optional[str]
    arguments: Dict[str, Any]
    request_headers: Dict[str, str]
    metadata: Dict[str, str]
    timeout_seconds: float
    policy_client_host: Optional[str] = None
    policy_user_agent: Optional[str] = None
    token_use: Optional[str] = None
    auth_method: Optional[str] = None
    token_jti: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    token_scopes: Optional[list[str]] = None
    token_server_id: Optional[str] = None
    catalog_token_id: Optional[str] = None
    status: AsyncJobStatus = "queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, str]] = None
    result_bytes: int = 0

    def summary(self) -> AsyncJobSummarySnapshot:
        """Return a result-free public summary for collection responses."""
        duration_ms: Optional[float] = None
        if self.started_at is not None and self.finished_at is not None:
            duration_ms = max(0.0, (self.finished_at - self.started_at).total_seconds() * 1000)
        return AsyncJobSummarySnapshot(
            id=self.id,
            tool_id=self.tool_id,
            tool_name=self.tool_name,
            status=self.status,
            timeout_seconds=self.timeout_seconds,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
            duration_ms=duration_ms,
            error=self.error,
        )

    def snapshot(self) -> AsyncJobSnapshot:
        """Return a detailed public view without owner scopes or execution inputs."""
        summary = self.summary()
        return AsyncJobSnapshot(
            id=summary.id,
            tool_id=summary.tool_id,
            tool_name=summary.tool_name,
            status=summary.status,
            timeout_seconds=summary.timeout_seconds,
            created_at=summary.created_at,
            started_at=summary.started_at,
            finished_at=summary.finished_at,
            duration_ms=summary.duration_ms,
            error=summary.error,
            result=self.result,
        )

    def clear_execution_payload(self) -> None:
        """Release potentially sensitive or large request data after termination."""
        self.arguments = {}
        self.request_headers = {}
        self.metadata = {}
        self.token_jti = None
        self.token_expires_at = None
        self.token_scopes = None
        self.catalog_token_id = None
        self.policy_client_host = None
        self.policy_user_agent = None


class AsyncJobService:
    """Manage a bounded queue and fixed-size pool of local async workers."""

    def __init__(
        self,
        *,
        queue_capacity: int,
        worker_count: int,
        default_timeout_seconds: float,
        max_timeout_seconds: float,
        retention_seconds: float,
        cleanup_interval_seconds: float,
        max_retained_jobs: int,
        max_payload_bytes: int,
        max_result_bytes: int,
        max_retained_result_bytes: int,
        shutdown_timeout_seconds: float,
    ) -> None:
        """Initialize limits without binding primitives to an event loop."""
        if queue_capacity < 1 or worker_count < 1 or max_retained_jobs < 1 or max_payload_bytes < 1 or max_result_bytes < 1 or max_retained_result_bytes < 1:
            raise ValueError("queue_capacity, worker_count, retention counts, and byte limits must be positive")
        if not 0 < default_timeout_seconds <= max_timeout_seconds:
            raise ValueError("default_timeout_seconds must be within the configured maximum")
        if retention_seconds <= 0 or cleanup_interval_seconds <= 0 or shutdown_timeout_seconds <= 0:
            raise ValueError("retention and lifecycle timeouts must be positive")

        self.queue_capacity = queue_capacity
        self.worker_count = worker_count
        self.default_timeout_seconds = default_timeout_seconds
        self.max_timeout_seconds = max_timeout_seconds
        self.retention_seconds = retention_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.max_retained_jobs = max_retained_jobs
        self.max_payload_bytes = max_payload_bytes
        self.max_result_bytes = max_result_bytes
        self.max_retained_result_bytes = max_retained_result_bytes
        self.shutdown_timeout_seconds = shutdown_timeout_seconds

        self._jobs: dict[str, _JobRecord] = {}
        self._pending: deque[str] = deque()
        self._active_tasks: dict[str, asyncio.Task[Dict[str, Any]]] = {}
        self._retained_result_bytes = 0
        self._lock: Optional[asyncio.Lock] = None
        self._condition: Optional[asyncio.Condition] = None
        self._workers: list[asyncio.Task[None]] = []
        self._cleanup_task: Optional[asyncio.Task[None]] = None
        self._tool_service: Optional[ToolService] = None
        self._started = False
        self._accepting = False

    @property
    def started(self) -> bool:
        """Return whether workers are initialized and accepting may be possible."""
        return self._started

    async def start(self, tool_service: ToolService) -> None:
        """Start worker and retention loops idempotently."""
        if self._started:
            return
        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(self._lock)
        self._tool_service = tool_service
        self._accepting = True
        self._started = True
        self._workers = [asyncio.create_task(self._worker_loop(index), name=f"async-job-worker-{index}") for index in range(self.worker_count)]
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(), name="async-job-cleanup")
        logger.info("Async job service started with workers=%d queue_capacity=%d", self.worker_count, self.queue_capacity)

    async def shutdown(self) -> None:
        """Stop accepting jobs, cancel outstanding work, and drain workers."""
        if not self._started or self._condition is None:
            return

        # Close admission first. Cancelling the cleanup task before this lock
        # left a small window where a request could enqueue during shutdown.
        async with self._condition:
            self._accepting = False
            now = self._now()
            for job_id in list(self._pending):
                record = self._jobs.get(job_id)
                if record is not None and record.status == "queued":
                    self._set_cancelled(record, now)
            self._pending.clear()
            active_tasks = list(self._active_tasks.items())
            for job_id, task in active_tasks:
                record = self._jobs.get(job_id)
                if record is not None and record.status == "running":
                    self._set_cancelled(record, now, clear_execution_payload=False)
                task.cancel()
            self._condition.notify_all()

        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        _done, pending_workers = await asyncio.wait(self._workers, timeout=self.shutdown_timeout_seconds)
        if pending_workers:
            logger.warning("Async job workers exceeded shutdown timeout; forcing cancellation")
            for worker in pending_workers:
                worker.cancel()
            _done, pending_workers = await asyncio.wait(pending_workers, timeout=min(1.0, self.shutdown_timeout_seconds))
            if pending_workers:  # pragma: no cover - requires a cancellation-hostile executor
                logger.error("%d async job workers did not stop after forced cancellation", len(pending_workers))

        self._workers.clear()
        self._active_tasks.clear()
        self._tool_service = None
        self._started = False
        logger.info("Async job service shutdown complete")

    async def enqueue_tool_invocation(
        self,
        db: Session,
        *,
        owner_email: str,
        access_user_email: Optional[str],
        access_is_admin: bool,
        token_teams: Optional[list[str]],
        tool_id: str,
        arguments: Dict[str, Any],
        request_headers: Dict[str, str],
        supplemental_header_names: Optional[list[str]] = None,
        metadata: Dict[str, str],
        timeout_seconds: Optional[float],
        token_use: Optional[str] = None,
        auth_method: Optional[str] = None,
        token_jti: Optional[str] = None,
        token_expires_at: Optional[datetime] = None,
        token_scopes: Optional[list[str]] = None,
        token_server_id: Optional[str] = None,
        policy_client_host: Optional[str] = None,
        policy_user_agent: Optional[str] = None,
    ) -> AsyncJobSnapshot:
        """Authorize and enqueue one tool invocation without retaining ``db``."""
        if not self._started or not self._accepting or self._condition is None or self._tool_service is None:
            raise AsyncJobServiceUnavailableError("Async job service is not accepting work")
        effective_timeout = self.default_timeout_seconds if timeout_seconds is None else float(timeout_seconds)
        if not 0 < effective_timeout <= self.max_timeout_seconds:
            raise ValueError(f"timeout_seconds must be greater than zero and no more than {self.max_timeout_seconds:g}")
        try:
            retained_payload_bytes = len(orjson.dumps({"arguments": arguments, "request_headers": request_headers, "metadata": metadata}))
        except (TypeError, ValueError, orjson.JSONEncodeError) as exc:
            raise ValueError("Async job payload must be JSON serializable") from exc
        if retained_payload_bytes > self.max_payload_bytes:
            raise AsyncJobPayloadTooLargeError(f"Async job payload exceeds the {self.max_payload_bytes}-byte limit")

        # Layer 1 is checked before acceptance, then checked again in a fresh
        # database session immediately before execution.
        tool = await self._tool_service.get_tool(
            db,
            tool_id,
            requesting_user_email=access_user_email,
            requesting_user_is_admin=access_is_admin,
            token_teams=token_teams,
        )
        if token_server_id and not self._tool_belongs_to_server(db, tool_id, token_server_id):
            # Hide catalog structure in the same way as ToolService access checks.
            from mcpgateway.services.tool_service import ToolNotFoundError  # pylint: disable=import-outside-toplevel

            raise ToolNotFoundError("Tool not found")
        target_visibility, target_team_id, target_owner_email = self._target_access_scope(tool)
        plugin_override = await self._recheck_plugin_permission(
            record_id=f"async-enqueue-{uuid.uuid4().hex}",
            owner_email=owner_email,
            is_admin=access_is_admin,
            auth_method=auth_method,
            tool=tool,
            team_id=target_team_id,
            server_id=token_server_id,
            request_headers=request_headers,
            client_host=policy_client_host,
            user_agent=policy_user_agent,
        )
        if target_team_id:
            permission_granted = await PermissionService(db, audit_enabled=False).check_permission(
                user_email=owner_email,
                permission="tools.execute",
                resource_type="tool",
                resource_id=tool_id,
                team_id=target_team_id,
                token_teams=token_teams,
                allow_admin_bypass=False,
                check_any_team=False,
            )
            if not permission_granted and not plugin_override:
                raise AsyncJobAuthorizationError("Tool execution permission is not granted for the target team")
        retained_headers = self._minimize_request_headers(
            db,
            tool,
            request_headers,
            supplemental_header_names=supplemental_header_names,
        )
        catalog_token_id: Optional[str] = None
        if auth_method == "api_token" and token_jti:
            catalog_token = db.execute(select(EmailApiToken).where(EmailApiToken.jti == token_jti)).scalar_one_or_none()
            if catalog_token is not None:
                catalog_token_id = str(catalog_token.id)
        record = _JobRecord(
            id=str(uuid.uuid4()),
            owner_email=owner_email,
            access_user_email=access_user_email,
            access_is_admin=access_is_admin,
            token_teams=list(token_teams) if token_teams is not None else None,
            tool_id=tool_id,
            tool_name=tool.name,
            target_visibility=target_visibility,
            target_team_id=target_team_id,
            target_owner_email=target_owner_email,
            arguments=dict(arguments),
            request_headers=retained_headers,
            metadata=dict(metadata),
            timeout_seconds=effective_timeout,
            policy_client_host=policy_client_host,
            policy_user_agent=policy_user_agent,
            token_use=token_use,
            auth_method=auth_method,
            token_jti=token_jti,
            token_expires_at=token_expires_at,
            token_scopes=list(token_scopes) if token_scopes is not None else None,
            token_server_id=token_server_id,
            catalog_token_id=catalog_token_id,
        )

        async with self._condition:
            if not self._accepting:
                raise AsyncJobServiceUnavailableError("Async job service is shutting down")
            self._cleanup_locked(self._now())
            if len(self._pending) >= self.queue_capacity:
                raise AsyncJobQueueFullError("Async job queue is full")
            self._jobs[record.id] = record
            self._pending.append(record.id)
            self._condition.notify(1)
        return record.snapshot()

    async def get_job(
        self,
        job_id: str,
        owner_email: str,
        *,
        access_user_email: Optional[str],
        token_teams: Optional[list[str]],
        token_server_id: Optional[str] = None,
    ) -> AsyncJobSnapshot:
        """Return one owner-visible job or hide it behind a not-found response."""
        condition = self._require_condition()
        async with condition:
            record = self._get_owned_locked(
                job_id,
                owner_email,
                access_user_email=access_user_email,
                token_teams=token_teams,
                token_server_id=token_server_id,
            )
            return record.snapshot()

    async def list_jobs(
        self,
        owner_email: str,
        *,
        access_user_email: Optional[str],
        token_teams: Optional[list[str]],
        status: Optional[AsyncJobStatus] = None,
        limit: int = 100,
        token_server_id: Optional[str] = None,
    ) -> list[AsyncJobSummarySnapshot]:
        """List newest jobs for exactly one owner."""
        condition = self._require_condition()
        async with condition:
            self._cleanup_locked(self._now())
            records = [
                record
                for record in self._jobs.values()
                if self._same_owner(record.owner_email, owner_email)
                and (token_server_id is None or record.token_server_id == token_server_id)
                and self._target_is_visible(record, access_user_email=access_user_email, token_teams=token_teams)
                and (status is None or record.status == status)
            ]
            records.sort(key=lambda item: (item.created_at, item.id), reverse=True)
            return [record.summary() for record in records[:limit]]

    async def cancel_job(
        self,
        job_id: str,
        owner_email: str,
        *,
        access_user_email: Optional[str],
        token_teams: Optional[list[str]],
        token_server_id: Optional[str] = None,
    ) -> AsyncJobSnapshot:
        """Cancel a queued/running owner job; completed jobs cannot be cancelled."""
        condition = self._require_condition()
        active_task: Optional[asyncio.Task[Dict[str, Any]]] = None
        async with condition:
            record = self._get_owned_locked(
                job_id,
                owner_email,
                access_user_email=access_user_email,
                token_teams=token_teams,
                token_server_id=token_server_id,
            )
            if record.status == "cancelled":
                return record.snapshot()
            if record.status in {"succeeded", "failed"}:
                raise AsyncJobStateConflictError(f"Job is already {record.status}")
            if record.status == "queued":
                try:
                    self._pending.remove(job_id)
                except ValueError:
                    # A worker may have dequeued it immediately before acquiring
                    # the execution lock; its status check will observe cancelled.
                    pass
            active_task = self._active_tasks.get(job_id)
            self._set_cancelled(record, self._now(), clear_execution_payload=record.status == "queued")
            snapshot = record.snapshot()
            condition.notify_all()
        if active_task is not None:
            active_task.cancel()
        return snapshot

    async def cleanup(self) -> int:
        """Remove expired terminal jobs and enforce the retained-result cap."""
        condition = self._require_condition()
        async with condition:
            return self._cleanup_locked(self._now())

    async def _worker_loop(self, worker_index: int) -> None:
        """Wait for pending IDs and execute them until shutdown."""
        condition = self._require_condition()
        while True:
            async with condition:
                while not self._pending and self._accepting:
                    await condition.wait()
                if not self._pending and not self._accepting:
                    return
                job_id = self._pending.popleft()
            try:
                await self._run_job(job_id)
            except Exception:  # pragma: no cover - worker isolation safety net
                logger.exception("Unexpected async job worker failure: worker=%d job_id=%s", worker_index, job_id)

    async def _run_job(self, job_id: str) -> None:
        """Transition one queued job through execution to a terminal state."""
        condition = self._require_condition()
        async with condition:
            record = self._jobs.get(job_id)
            if record is None or record.status != "queued":
                return
            record.status = "running"
            record.started_at = self._now()
            execution_task = asyncio.create_task(self._execute_tool(record), name=f"async-tool-job-{job_id}")
            self._active_tasks[job_id] = execution_task

        try:
            result = await asyncio.wait_for(execution_task, timeout=record.timeout_seconds)
        except asyncio.TimeoutError:
            await self._finish_job(
                record,
                status="failed",
                error={"type": "TimeoutError", "message": f"Tool invocation exceeded {record.timeout_seconds:g} seconds"},
            )
        except asyncio.CancelledError:
            await self._finish_job(record, status="cancelled")
        except Exception as exc:  # pylint: disable=broad-except
            error_message = sanitize_trace_text(str(exc))[:2048] or "Tool invocation failed"
            await self._finish_job(record, status="failed", error={"type": type(exc).__name__, "message": error_message})
        else:
            await self._finish_job(record, status="succeeded", result=result)
        finally:
            async with condition:
                self._active_tasks.pop(job_id, None)

    async def _execute_tool(self, record: _JobRecord) -> Dict[str, Any]:
        """Re-authorize and execute through ToolService in a fresh DB session."""
        if self._tool_service is None:
            raise AsyncJobServiceUnavailableError("Tool service is unavailable")
        with fresh_db_session() as db:
            catalog_server_id, catalog_team_id = self._validate_execution_credential(db, record)
            invocation_server_id = self._resolve_execution_server(db, record, catalog_server_id)
            access_user_email, access_is_admin, token_teams = await self._refresh_execution_scope(db, record, catalog_team_id=catalog_team_id)
            tool = await self._tool_service.get_tool(
                db,
                record.tool_id,
                requesting_user_email=access_user_email,
                requesting_user_is_admin=access_is_admin,
                token_teams=token_teams,
            )
            current_target_scope = self._target_access_scope(tool)
            stored_target_scope = (record.target_visibility, record.target_team_id, record.target_owner_email)
            if current_target_scope != stored_target_scope:
                raise AsyncJobAuthorizationError("Tool visibility scope changed before the job started")
            target_team_id = record.target_team_id
            plugin_override = await self._recheck_plugin_permission(
                record_id=record.id,
                owner_email=record.owner_email,
                is_admin=access_is_admin,
                auth_method=record.auth_method,
                tool=tool,
                team_id=target_team_id,
                server_id=invocation_server_id,
                request_headers=record.request_headers,
                client_host=record.policy_client_host,
                user_agent=record.policy_user_agent,
            )
            permission_granted = await PermissionService(db, audit_enabled=False).check_permission(
                user_email=record.owner_email,
                permission="tools.execute",
                resource_type="tool",
                resource_id=record.tool_id,
                team_id=target_team_id,
                token_teams=token_teams,
                allow_admin_bypass=False,
                check_any_team=target_team_id is None,
            )
            if not permission_granted and not plugin_override:
                raise AsyncJobAuthorizationError("Tool execution permission was revoked before the job started")
            metadata: Dict[str, Any] = {"async_job_id": record.id}
            if tool.integration_type == "gRPC" and record.metadata:
                metadata.update({"grpc_metadata": record.metadata, "capture_grpc_call_metadata": True})
            result = await self._tool_service.invoke_tool(
                db,
                tool.name,
                record.arguments,
                request_headers=record.request_headers,
                app_user_email=record.owner_email,
                user_email=access_user_email,
                token_teams=token_teams,
                meta_data=metadata,
                server_id=invocation_server_id,
                timeout_override=record.timeout_seconds,
            )
            serialized_result = result.model_dump(by_alias=True)
            try:
                result_size = len(orjson.dumps(serialized_result))
            except (TypeError, ValueError, orjson.JSONEncodeError) as exc:
                raise AsyncJobResultTooLargeError("Async job result is not JSON serializable") from exc
            if result_size > self.max_result_bytes:
                raise AsyncJobResultTooLargeError(f"Async job result exceeds the {self.max_result_bytes}-byte retention limit")
            return serialized_result

    def _validate_execution_credential(self, db: Session, record: _JobRecord) -> tuple[Optional[str], Optional[str]]:
        """Fail closed when the enqueue-time credential is no longer valid."""
        now = self._now()
        if record.token_expires_at is not None and self._as_utc(record.token_expires_at) <= now:
            raise AsyncJobAuthorizationError("Authentication token expired before the job started")

        if record.token_jti and get_token_blocklist_service(db=db).is_token_revoked(record.token_jti):
            raise AsyncJobAuthorizationError("Authentication token was revoked before the job started")

        if not token_scope_grants(record.token_scopes, "tools.execute"):
            raise AsyncJobAuthorizationError("Token scope no longer permits tool execution")

        if record.catalog_token_id is None:
            return None, None
        catalog_token = db.execute(select(EmailApiToken).where(EmailApiToken.id == record.catalog_token_id)).scalar_one_or_none()
        if (
            catalog_token is None
            or catalog_token.jti != record.token_jti
            or catalog_token.user_email.casefold() != record.owner_email.casefold()
            or not catalog_token.is_active
            or (catalog_token.expires_at is not None and self._as_utc(catalog_token.expires_at) <= now)
            or not token_scope_grants(catalog_token.resource_scopes, "tools.execute")
        ):
            raise AsyncJobAuthorizationError("API token is no longer authorized to execute this job")
        return catalog_token.server_id, catalog_token.team_id

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        """Normalize database/JWT timestamps for safe expiration comparisons."""
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    async def _refresh_execution_scope(
        self,
        db: Session,
        record: _JobRecord,
        *,
        catalog_team_id: Optional[str] = None,
    ) -> tuple[Optional[str], bool, Optional[list[str]]]:
        """Refresh account and membership state without broadening enqueue scope."""
        if record.auth_method is None and record.token_use is None:
            # Trusted internal callers may omit an HTTP credential context.
            return record.access_user_email, record.access_is_admin, record.token_teams

        user = db.execute(select(EmailUser).where(EmailUser.email == record.owner_email, EmailUser.is_active.is_(True))).scalar_one_or_none()
        bootstrap_admin = user is None and not settings.require_user_in_db and record.owner_email == settings.platform_admin_email and record.access_is_admin and record.token_teams is None
        if user is None and not bootstrap_admin:
            raise AsyncJobAuthorizationError("Authenticated session is no longer active")

        if record.token_use != "session":
            current_teams = list(record.token_teams) if record.token_teams is not None else None
            if catalog_team_id:
                if current_teams is None:
                    current_teams = [catalog_team_id]
                elif catalog_team_id not in current_teams:
                    raise AsyncJobAuthorizationError("API token team scope changed before the job started")
                else:
                    current_teams = [catalog_team_id]
            if current_teams:
                active_memberships = set(
                    db.execute(
                        select(EmailTeamMember.team_id).where(
                            EmailTeamMember.user_email == record.owner_email,
                            EmailTeamMember.team_id.in_(current_teams),
                            EmailTeamMember.is_active.is_(True),
                        )
                    )
                    .scalars()
                    .all()
                )
                if set(current_teams) - active_memberships:
                    raise AsyncJobAuthorizationError("Authenticated user is no longer a member of the token team")
            current_is_admin = bool(user.is_admin) if user is not None else True
            return record.owner_email, record.access_is_admin and current_is_admin, current_teams

        current_is_admin = True if user is None else bool(user.is_admin)
        current_db_teams: Optional[list[str]]
        admin_bypass_remains_valid = current_is_admin and record.access_is_admin and record.token_teams is None
        if admin_bypass_remains_valid:
            current_db_teams = None
        else:
            current_db_teams = list(
                db.execute(
                    select(EmailTeamMember.team_id).where(
                        EmailTeamMember.user_email == record.owner_email,
                        EmailTeamMember.is_active.is_(True),
                    )
                ).scalars()
            )
        # The stored effective scope is used as a conservative JWT narrowing
        # cap: a delayed job never gains a team that was absent at enqueue,
        # while revoked DB memberships disappear immediately.
        if current_db_teams is None:
            refreshed_teams = None
        elif record.token_teams is None:
            refreshed_teams = current_db_teams
        else:
            enqueue_team_cap = set(record.token_teams)
            refreshed_teams = [team_id for team_id in current_db_teams if team_id in enqueue_team_cap]
        return record.owner_email, admin_bypass_remains_valid, refreshed_teams

    @staticmethod
    def _tool_belongs_to_server(db: Session, tool_id: str, server_id: str) -> bool:
        """Return whether the target tool is attached to a scoped virtual server."""
        return (
            db.execute(
                select(server_tool_association.c.tool_id).where(
                    server_tool_association.c.server_id == server_id,
                    server_tool_association.c.tool_id == tool_id,
                )
            ).first()
            is not None
        )

    def _resolve_execution_server(self, db: Session, record: _JobRecord, catalog_server_id: Optional[str]) -> Optional[str]:
        """Intersect enqueue-time and current catalog server restrictions."""
        if record.token_server_id and catalog_server_id and record.token_server_id != catalog_server_id:
            raise AsyncJobAuthorizationError("API token server scope changed before the job started")
        server_id = catalog_server_id or record.token_server_id
        if server_id and not self._tool_belongs_to_server(db, record.tool_id, server_id):
            raise AsyncJobAuthorizationError("Tool is no longer available through the token-scoped server")
        return server_id

    @staticmethod
    async def _recheck_plugin_permission(
        *,
        record_id: str,
        owner_email: str,
        is_admin: bool,
        auth_method: Optional[str],
        tool: Any,
        team_id: Optional[str],
        server_id: Optional[str],
        request_headers: Dict[str, str],
        client_host: Optional[str],
        user_agent: Optional[str],
    ) -> bool:
        """Replay dynamic HTTP authorization policy with a fresh safe context.

        Returns whether an explicit plugin grant may override RBAC. Plugin
        denials and hook failures fail closed; no request-local plugin context
        or untrusted ambient headers are reused by the delayed worker.
        """
        tool_name = str(getattr(tool, "name", ""))
        context_id = make_context_id(team_id, tool_name) if team_id and tool_name else server_id
        try:
            plugin_manager = await get_plugin_manager(context_id) if context_id else await get_plugin_manager()
            if plugin_manager is None or not plugin_manager.has_hooks_for(HttpHookType.HTTP_AUTH_CHECK_PERMISSION):
                return False
            if not client_host or not user_agent:
                raise AsyncJobAuthorizationError("Authorization plugin request context cannot be reproduced for the queued job")
            global_context = GlobalContext(
                request_id=record_id,
                user=owner_email,
                tenant_id=team_id,
                server_id=server_id,
                content_type=request_headers.get("content-type"),
            )
            result, _ = await plugin_manager.invoke_hook(
                HttpHookType.HTTP_AUTH_CHECK_PERMISSION,
                payload=HttpAuthCheckPermissionPayload(
                    user_email=owner_email,
                    permission="tools.execute",
                    resource_type="tool",
                    team_id=team_id,
                    is_admin=is_admin,
                    auth_method=auth_method,
                    client_host=client_host,
                    user_agent=user_agent,
                ),
                global_context=global_context,
                local_contexts=None,
                extensions=build_request_extensions(),
            )
        except Exception as exc:
            logger.warning(
                "Async job authorization plugin replay failed for tool_id=%s: %s",
                getattr(tool, "id", None),
                sanitize_trace_text(str(exc))[:512],
            )
            raise AsyncJobAuthorizationError("Authorization plugin could not validate the queued job") from exc

        if result is None:
            raise AsyncJobAuthorizationError("Authorization plugin returned no decision context for the queued job")
        record_plugin_metrics(current_trace_id.get(), result.metadata)
        if getattr(result, "violation", None) is not None:
            raise AsyncJobAuthorizationError("Authorization plugin denied the queued job")
        modified_payload = getattr(result, "modified_payload", None)
        if modified_payload is None or not hasattr(modified_payload, "granted"):
            return False
        if not bool(modified_payload.granted):
            raise AsyncJobAuthorizationError("Authorization plugin denied the queued job")
        return bool(settings.plugins_can_override_rbac)

    @staticmethod
    def _minimize_request_headers(
        db: Session,
        tool: Any,
        request_headers: Dict[str, str],
        *,
        supplemental_header_names: Optional[list[str]],
    ) -> Dict[str, str]:
        """Retain only headers that the target invocation can consume."""
        if supplemental_header_names is None:
            return dict(request_headers)

        globally_allowed = global_config_cache.get_passthrough_headers(db, settings.default_passthrough_headers)
        gateway = db.get(DbGateway, tool.gateway_id) if getattr(tool, "gateway_id", None) else None
        gateway_allowed = gateway.passthrough_headers if gateway is not None else None
        allowed = {name.lower() for name in (gateway_allowed if gateway_allowed is not None else globally_allowed)}
        allowed.update({"baggage", "content-type", "traceparent", "tracestate", "x-correlation-id", "x-upstream-authorization"})

        oauth_config = gateway.oauth_config if gateway is not None and isinstance(gateway.oauth_config, dict) else {}
        needs_subject_token = oauth_config.get("grant_type") == "token-exchange"
        passes_client_authorization = gateway is not None and gateway.auth_type == "none"
        if needs_subject_token or passes_client_authorization:
            allowed.add("authorization")

        # A customized inbound auth header is retained only when explicitly
        # allowlisted; it is not automatically a downstream credential.
        hard_drop = {
            "connection",
            "content-length",
            "cookie",
            "host",
            "proxy-authorization",
            "set-cookie",
            "transfer-encoding",
            settings.proxy_user_header.strip().lower(),
        }
        return {
            name: value for name, value in request_headers.items() if name.lower() in allowed and name.lower() not in hard_drop and not name.lower().startswith(("x-context-forge-", "x-contextforge-"))
        }

    async def _finish_job(
        self,
        record: _JobRecord,
        *,
        status: Literal["succeeded", "failed", "cancelled"],
        result: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, str]] = None,
    ) -> None:
        """Set terminal state without overwriting an explicit cancellation."""
        condition = self._require_condition()
        async with condition:
            if record.status == "cancelled":
                record.clear_execution_payload()
                return
            final_status = status
            final_result = result
            final_error = error
            result_bytes = 0
            if status == "succeeded" and result is not None:
                try:
                    result_bytes = len(orjson.dumps(result))
                except (TypeError, ValueError, orjson.JSONEncodeError):  # pragma: no cover - executor validates first
                    result_bytes = self.max_retained_result_bytes + 1
                if result_bytes > self.max_retained_result_bytes:
                    final_status = "failed"
                    final_result = None
                    final_error = {
                        "type": "AsyncJobResultTooLargeError",
                        "message": f"Async job result exceeds the {self.max_retained_result_bytes}-byte aggregate retention budget",
                    }
                    result_bytes = 0
                elif not self._evict_for_result_budget_locked(result_bytes, exclude_job_id=record.id):
                    final_status = "failed"
                    final_result = None
                    final_error = {
                        "type": "AsyncJobResultTooLargeError",
                        "message": "Async job aggregate result budget could not be reclaimed",
                    }
                    result_bytes = 0
            record.status = final_status
            record.finished_at = self._now()
            record.result = final_result
            record.error = final_error
            record.result_bytes = result_bytes
            self._retained_result_bytes += result_bytes
            record.clear_execution_payload()

    async def _cleanup_loop(self) -> None:
        """Run periodic terminal-result cleanup until cancelled."""
        try:
            while True:
                await asyncio.sleep(self.cleanup_interval_seconds)
                await self.cleanup()
        except asyncio.CancelledError:
            raise

    def _cleanup_locked(self, now: datetime) -> int:
        """Cleanup helper called only while the shared lock is held."""
        cutoff = now - timedelta(seconds=self.retention_seconds)
        removable = [
            job_id for job_id, record in self._jobs.items() if record.status in _TERMINAL_STATUSES and job_id not in self._active_tasks and (record.finished_at or record.created_at) <= cutoff
        ]
        for job_id in removable:
            self._remove_job_locked(job_id)

        retained_terminal = sorted(
            (((record.finished_at or record.created_at), job_id) for job_id, record in self._jobs.items() if record.status in _TERMINAL_STATUSES and job_id not in self._active_tasks),
            key=lambda item: (item[0], item[1]),
        )
        overflow = max(0, len(retained_terminal) - self.max_retained_jobs)
        for _timestamp, job_id in retained_terminal[:overflow]:
            self._remove_job_locked(job_id)
            removable.append(job_id)
        return len(removable)

    def _evict_for_result_budget_locked(self, required_bytes: int, *, exclude_job_id: str) -> bool:
        """Evict oldest terminal results until a new result fits the aggregate cap."""
        excess = self._retained_result_bytes + required_bytes - self.max_retained_result_bytes
        if excess <= 0:
            return True
        candidates = sorted(
            (
                (record.finished_at or record.created_at, job_id)
                for job_id, record in self._jobs.items()
                if job_id != exclude_job_id and record.status in _TERMINAL_STATUSES and record.result_bytes > 0
            ),
            key=lambda item: (item[0], item[1]),
        )
        for _timestamp, job_id in candidates:
            removed = self._remove_job_locked(job_id)
            if removed is not None:
                excess -= removed.result_bytes
            if excess <= 0:
                return True

        # ``required_bytes`` is already bounded by the aggregate cap, so all
        # existing retained result bytes are reclaimable terminal data. This
        # branch protects the invariant if internal accounting is ever damaged.
        return False

    def _remove_job_locked(self, job_id: str) -> Optional[_JobRecord]:
        """Remove one retained record and update aggregate result accounting."""
        record = self._jobs.pop(job_id, None)
        if record is not None:
            self._retained_result_bytes = max(0, self._retained_result_bytes - record.result_bytes)
        return record

    def _get_owned_locked(
        self,
        job_id: str,
        owner_email: str,
        *,
        access_user_email: Optional[str],
        token_teams: Optional[list[str]],
        token_server_id: Optional[str] = None,
    ) -> _JobRecord:
        """Hide absent, cross-owner, server-scoped, and visibility-denied jobs."""
        record = self._jobs.get(job_id)
        if (
            record is None
            or not self._same_owner(record.owner_email, owner_email)
            or (token_server_id is not None and record.token_server_id != token_server_id)
            or not self._target_is_visible(record, access_user_email=access_user_email, token_teams=token_teams)
        ):
            raise AsyncJobNotFoundError("Job not found")
        return record

    @staticmethod
    def _target_access_scope(tool: Any) -> tuple[str, Optional[str], Optional[str]]:
        """Extract and validate the immutable Layer-1 scope of a target tool."""
        visibility = getattr(tool, "visibility", None)
        if visibility not in _TARGET_VISIBILITIES:
            raise AsyncJobAuthorizationError("Tool visibility scope cannot be retained safely")
        raw_team_id = getattr(tool, "team_id", None)
        raw_owner_email = getattr(tool, "owner_email", None)
        team_id = raw_team_id if isinstance(raw_team_id, str) and raw_team_id else None
        owner_email = raw_owner_email if isinstance(raw_owner_email, str) and raw_owner_email else None
        if visibility == "team" and team_id is None:
            raise AsyncJobAuthorizationError("Team tool is missing its access scope")
        if visibility == "private" and owner_email is None:
            raise AsyncJobAuthorizationError("Private tool is missing its owner scope")
        return str(visibility), team_id, owner_email

    @staticmethod
    def _target_is_visible(record: _JobRecord, *, access_user_email: Optional[str], token_teams: Optional[list[str]]) -> bool:
        """Apply BaseService-equivalent visibility rules to retained job data."""
        if record.target_visibility == "public":
            return True
        if record.target_visibility == "private":
            # An explicit empty scope is public-only and suppresses owner access,
            # including for an administrator. Other tokens may see only their
            # own private target; bypass never exposes another user's target.
            return token_teams != [] and access_user_email is not None and record.target_owner_email == access_user_email
        if record.target_visibility == "team":
            # ``None`` is the canonical admin-bypass shape supplied by the
            # request auth context. Otherwise the immutable target team must
            # still be present in the current token scope.
            return token_teams is None or (record.target_team_id is not None and record.target_team_id in token_teams)
        return False

    def _set_cancelled(self, record: _JobRecord, now: datetime, *, clear_execution_payload: bool = True) -> None:
        """Set cancellation fields and discard the request payload."""
        record.status = "cancelled"
        record.finished_at = now
        record.result = None
        record.error = None
        if clear_execution_payload:
            record.clear_execution_payload()

    def _require_condition(self) -> asyncio.Condition:
        """Return initialized synchronization state or raise a lifecycle error."""
        if not self._started or self._condition is None:
            raise AsyncJobServiceUnavailableError("Async job service is not initialized")
        return self._condition

    @staticmethod
    def _same_owner(left: str, right: str) -> bool:
        """Compare canonical identities exactly to prevent principal conflation."""
        return left == right

    @staticmethod
    def _now() -> datetime:
        """Return an aware UTC timestamp."""
        return datetime.now(timezone.utc)


_async_job_service: Optional[AsyncJobService] = None


def get_async_job_service() -> AsyncJobService:
    """Return the process-local singleton using current configured limits."""
    global _async_job_service  # pylint: disable=global-statement
    if _async_job_service is None:
        _async_job_service = AsyncJobService(
            queue_capacity=settings.mcpgateway_async_jobs_queue_capacity,
            worker_count=settings.mcpgateway_async_jobs_worker_count,
            default_timeout_seconds=settings.mcpgateway_async_jobs_default_timeout,
            max_timeout_seconds=settings.mcpgateway_async_jobs_max_timeout,
            retention_seconds=settings.mcpgateway_async_jobs_retention_seconds,
            cleanup_interval_seconds=settings.mcpgateway_async_jobs_cleanup_interval,
            max_retained_jobs=settings.mcpgateway_async_jobs_max_retained,
            max_payload_bytes=settings.mcpgateway_async_jobs_max_payload_bytes,
            max_result_bytes=settings.mcpgateway_async_jobs_max_result_bytes,
            max_retained_result_bytes=settings.mcpgateway_async_jobs_max_retained_result_bytes,
            shutdown_timeout_seconds=settings.mcpgateway_async_jobs_shutdown_timeout,
        )
    return _async_job_service
