# -*- coding: utf-8 -*-
# flake8: noqa: DAR101,DAR201,DAR401
"""Location: ./mcpgateway/services/siem_export_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

SIEM Export Service.

Asynchronously exports security/audit events to external SIEM destinations.
Supports Redis Streams (consumer groups) with local queue fallback, destination
fan-out, filtering, retries with exponential backoff, and destination health.
"""

# Standard
import asyncio
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import logging
import os
import socket
import time
from typing import Any, Deque, Dict, List, Literal, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse
import uuid

# Third-Party
from jinja2 import Template
import orjson

# First-Party
from mcpgateway import __version__
from mcpgateway.config import settings
from mcpgateway.services.http_client_service import get_http_client
from mcpgateway.services.metrics import siem_events_exported_total, siem_export_latency_seconds, siem_queue_depth
from mcpgateway.utils.redis_client import get_redis_client

logger = logging.getLogger(__name__)

SIEMDestinationType = Literal["splunk_hec", "datadog", "elasticsearch", "webhook", "syslog"]
SIEMFormat = Literal["json", "cef", "leef"]
BackpressurePolicy = Literal["drop_oldest", "block_producer"]

_ALLOWED_DEST_TYPES: Set[str] = {"splunk_hec", "datadog", "elasticsearch", "webhook", "syslog"}
_ALLOWED_FORMATS: Set[str] = {"json", "cef", "leef"}

_CEF_SEVERITY_MAP = {
    "LOW": 3,
    "MEDIUM": 5,
    "HIGH": 7,
    "CRITICAL": 10,
}

_SYSLOG_SEVERITY_MAP = {
    "LOW": 6,
    "MEDIUM": 4,
    "HIGH": 3,
    "CRITICAL": 2,
}


@dataclass
class DestinationStats:  # pragma: no cover - data holder exercised indirectly
    """Rolling health and delivery stats for one destination."""

    last_event_sent: Optional[datetime] = None
    avg_latency_ms: float = 0.0
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    sent_timestamps: Deque[datetime] = field(default_factory=deque)
    failed_timestamps: Deque[datetime] = field(default_factory=deque)

    def prune(self, now: datetime) -> None:
        """Prune counters to 1h window."""
        cutoff = now - timedelta(hours=1)
        while self.sent_timestamps and self.sent_timestamps[0] < cutoff:
            self.sent_timestamps.popleft()
        while self.failed_timestamps and self.failed_timestamps[0] < cutoff:
            self.failed_timestamps.popleft()


class SIEMExportService:  # pragma: no cover - covered by targeted unit tests and runtime integration
    """Asynchronous SIEM export pipeline for security events."""

    def __init__(self) -> None:
        """Initialize runtime state from configuration."""
        self.enabled: bool = bool(getattr(settings, "siem_export_enabled", False))
        self.batch_size: int = int(getattr(settings, "siem_export_batch_size", 100))
        self.flush_interval_seconds: int = int(getattr(settings, "siem_export_flush_interval_seconds", 5))
        self.queue_max_size: int = int(getattr(settings, "siem_export_queue_max_size", 10000))
        self.max_retries: int = int(getattr(settings, "siem_export_max_retries", 10))
        self.backoff_max_seconds: int = int(getattr(settings, "siem_export_backoff_max_seconds", 60))
        self.backpressure_policy: BackpressurePolicy = str(getattr(settings, "siem_export_backpressure_policy", "drop_oldest")).lower()  # type: ignore[assignment]
        self.stream_name: str = str(getattr(settings, "siem_export_stream_name", "mcpgateway:siem:events"))
        self.consumer_group: str = str(getattr(settings, "siem_export_consumer_group", "siem-exporters"))
        self.consumer_name: str = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"

        sources = getattr(settings, "siem_export_event_sources", ["auth", "security", "audit"])
        self._event_sources: Set[str] = {str(source).strip().lower() for source in sources if str(source).strip()}

        allowlist = getattr(settings, "siem_export_url_allowlist", [])
        self._url_allowlist: List[str] = [str(item).strip() for item in allowlist if str(item).strip()]

        redact_fields = getattr(settings, "siem_export_redact_fields", ["user_email", "authorization", "token", "password", "secret", "api_key"])
        self._redact_fields: Set[str] = {str(item).strip() for item in redact_fields if str(item).strip()}

        self._destinations: Dict[str, Dict[str, Any]] = {}
        self._destination_stats: Dict[str, DestinationStats] = {}

        self._redis: Any = None
        self._queue_backend: Literal["redis", "local"] = "local"
        self._local_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=self.queue_max_size)
        self._local_dead_letter: Deque[Dict[str, Any]] = deque(maxlen=self.queue_max_size)

        self._shutdown_event = asyncio.Event()
        self._worker_task: Optional[asyncio.Task] = None
        self._retry_tasks: Set[asyncio.Task] = set()

    @property
    def destinations(self) -> Dict[str, Dict[str, Any]]:
        """Read-only view of active destination configs."""
        return self._destinations

    def is_source_enabled(self, source: str) -> bool:
        """Check if event source is configured for export."""
        normalized = str(source or "").strip().lower()
        return bool(normalized and normalized in self._event_sources)

    async def initialize(self) -> None:
        """Initialize destination config and start worker loop."""
        self._load_destination_settings()
        self.enabled = bool(getattr(settings, "siem_export_enabled", self.enabled))

        if not self.enabled and not self._destinations:
            logger.info("SIEM export disabled")
            return

        await self._start_worker_if_needed()

    async def shutdown(self) -> None:
        """Stop workers and flush retry tasks."""
        self._shutdown_event.set()

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

        for retry_task in list(self._retry_tasks):
            retry_task.cancel()
        for retry_task in list(self._retry_tasks):
            try:
                await retry_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive cleanup
                logger.debug("SIEM retry task error on shutdown: %s", exc)

        self._retry_tasks.clear()

    async def _start_worker_if_needed(self) -> None:
        """Start the worker only once."""
        if self._worker_task and not self._worker_task.done():
            return

        self._shutdown_event.clear()

        self._redis = await get_redis_client()
        if self._redis:
            self._queue_backend = "redis"
            await self._ensure_stream_group()
            logger.info("SIEM export using Redis Streams backend")
        else:
            self._queue_backend = "local"
            logger.info("SIEM export using local in-memory queue backend")

        self._worker_task = asyncio.create_task(self._worker_loop())

    def submit_event(self, event: Dict[str, Any], source: str = "security") -> bool:
        """Non-blocking event submission from sync code paths.

        Returns True if event scheduling was attempted.
        """
        if not self.enabled and not self._destinations:
            return False

        if not self.is_source_enabled(source):
            return False

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("No running event loop for SIEM event submission")
            return False

        loop.create_task(self.enqueue_event(event=event, source=source))
        return True

    async def enqueue_event(self, event: Dict[str, Any], source: str = "security") -> bool:
        """Build and enqueue an event for asynchronous delivery."""
        if not self.enabled and not self._destinations:
            return False

        if not self.is_source_enabled(source):
            return False

        if not self._worker_task or self._worker_task.done():
            await self._start_worker_if_needed()

        envelope = self._build_event_envelope(event=event, source=source)
        await self._enqueue_envelope(envelope)
        return True

    async def add_destination(self, destination: Dict[str, Any]) -> Dict[str, Any]:
        """Add destination at runtime and activate worker immediately."""
        normalized = self._normalize_destination_config(destination)
        name = normalized["name"]

        self._destinations[name] = normalized
        self._destination_stats.setdefault(name, DestinationStats())

        # Enabling destinations via admin API should immediately activate export.
        self.enabled = True
        await self._start_worker_if_needed()

        return self._sanitize_destination_for_response(normalized)

    async def replace_destinations(self, destinations: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Replace runtime destination set."""
        new_destinations: Dict[str, Dict[str, Any]] = {}
        for destination in destinations:
            normalized = self._normalize_destination_config(destination)
            new_destinations[normalized["name"]] = normalized

        self._destinations = new_destinations
        for name in self._destinations:
            self._destination_stats.setdefault(name, DestinationStats())

        if self._destinations:
            self.enabled = True
            await self._start_worker_if_needed()

        return [self._sanitize_destination_for_response(destination) for destination in self._destinations.values()]

    def list_destinations(self) -> List[Dict[str, Any]]:
        """Return sanitized destination configuration list."""
        return [self._sanitize_destination_for_response(destination) for destination in self._destinations.values()]

    async def test_destination(self, destination_name: str) -> Dict[str, Any]:
        """Send a test event to one destination and report result."""
        destination = self._destinations.get(destination_name)
        if destination is None:
            raise KeyError(f"Unknown destination: {destination_name}")

        test_event = self._build_event_envelope(
            event={
                "event_type": "siem_connectivity_test",
                "severity": "LOW",
                "category": "system",
                "description": "SIEM connectivity test",
                "action_taken": "test",
            },
            source="admin",
        )

        start = time.perf_counter()
        try:
            await self._send_to_destination(destination=destination, event=test_event)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return {
                "name": destination_name,
                "status": "failed",
                "latency_ms": round(latency_ms, 2),
                "error": str(exc),
            }

        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "name": destination_name,
            "status": "ok",
            "latency_ms": round(latency_ms, 2),
        }

    async def get_health(self) -> Dict[str, Any]:
        """Return exporter and per-destination health summary."""
        now = datetime.now(timezone.utc)

        queue_depth = await self._get_queue_depth()

        destination_statuses: List[Dict[str, Any]] = []
        has_failures = False

        for name, destination in self._destinations.items():
            stats = self._destination_stats.setdefault(name, DestinationStats())
            stats.prune(now)

            if not destination.get("enabled", True):
                status = "disabled"
            elif stats.consecutive_failures >= 10:
                status = "failing"
            elif stats.consecutive_failures > 0:
                status = "degraded"
            else:
                status = "connected"

            if status in {"failing", "degraded"}:
                has_failures = True

            destination_statuses.append(
                {
                    "name": name,
                    "type": destination.get("type"),
                    "status": status,
                    "last_event_sent": stats.last_event_sent.isoformat() if stats.last_event_sent else None,
                    "events_sent_1h": len(stats.sent_timestamps),
                    "events_failed_1h": len(stats.failed_timestamps),
                    "queue_depth": queue_depth,
                    "avg_latency_ms": round(stats.avg_latency_ms, 2),
                    "consecutive_failures": stats.consecutive_failures,
                    "last_error": stats.last_error,
                }
            )

        if not self.enabled and not self._destinations:
            overall_status = "disabled"
        elif has_failures:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        return {
            "status": overall_status,
            "backend": self._queue_backend,
            "enabled": self.enabled,
            "event_sources": sorted(self._event_sources),
            "queue_depth": queue_depth,
            "destinations": destination_statuses,
        }

    async def _worker_loop(self) -> None:
        """Background worker consuming queued events and exporting them."""
        logger.info("SIEM export worker started")

        try:
            while not self._shutdown_event.is_set():
                batch = await self._dequeue_batch()
                if not batch:
                    continue

                for entry_id, event in batch:
                    try:
                        await self._process_queued_event(entry_id=entry_id, event=event)
                    except Exception as exc:  # pragma: no cover - defensive catch
                        logger.error("SIEM worker failed to process event: %s", exc, exc_info=True)
                    finally:
                        if self._queue_backend == "local":
                            self._local_queue.task_done()

                await self._update_queue_depth_metrics()

        except asyncio.CancelledError:
            logger.debug("SIEM export worker cancelled")
            raise
        finally:
            logger.info("SIEM export worker stopped")

    async def _dequeue_batch(self) -> List[Tuple[Optional[str], Dict[str, Any]]]:
        """Read one batch from queue backend."""
        if self._queue_backend == "redis" and self._redis:
            return await self._dequeue_batch_redis()
        return await self._dequeue_batch_local()

    async def _dequeue_batch_local(self) -> List[Tuple[Optional[str], Dict[str, Any]]]:
        """Read one batch from local in-memory queue."""
        try:
            first = await asyncio.wait_for(self._local_queue.get(), timeout=self.flush_interval_seconds)
        except asyncio.TimeoutError:
            return []

        batch: List[Tuple[Optional[str], Dict[str, Any]]] = [(None, first)]
        while len(batch) < self.batch_size:
            try:
                item = self._local_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            batch.append((None, item))

        return batch

    async def _dequeue_batch_redis(self) -> List[Tuple[Optional[str], Dict[str, Any]]]:
        """Read one batch from Redis Stream consumer group."""
        block_ms = max(1, self.flush_interval_seconds * 1000)

        try:
            responses = await self._redis.xreadgroup(
                groupname=self.consumer_group,
                consumername=self.consumer_name,
                streams={self.stream_name: ">"},
                count=self.batch_size,
                block=block_ms,
            )
        except Exception as exc:
            logger.warning("SIEM Redis dequeue failed: %s", exc)
            await asyncio.sleep(1.0)
            return []

        if not responses:
            return []

        batch: List[Tuple[Optional[str], Dict[str, Any]]] = []
        for _stream_name, entries in responses:
            for entry_id, fields in entries:
                raw_event = fields.get("event")
                if raw_event is None:
                    await self._ack_redis_entry(entry_id)
                    continue

                try:
                    if isinstance(raw_event, bytes):
                        raw_event = raw_event.decode("utf-8")
                    event = orjson.loads(raw_event)
                except Exception:
                    logger.warning("Dropping malformed SIEM event payload")
                    await self._ack_redis_entry(entry_id)
                    continue

                batch.append((entry_id, event))

        return batch

    async def _process_queued_event(self, entry_id: Optional[str], event: Dict[str, Any]) -> None:
        """Dispatch one event to matching destinations with retry handling."""
        meta = event.setdefault("_meta", {})
        pending_destinations = meta.get("pending_destinations")
        if pending_destinations and isinstance(pending_destinations, list):
            target_destinations = {str(item) for item in pending_destinations}
        else:
            target_destinations = None

        failed_destinations = await self._dispatch_to_destinations(event=event, target_destinations=target_destinations)

        if failed_destinations:
            await self._schedule_retry_or_dead_letter(event=event, failed_destinations=failed_destinations)

        if self._queue_backend == "redis" and entry_id:
            await self._ack_redis_entry(entry_id)

    async def _dispatch_to_destinations(self, event: Dict[str, Any], target_destinations: Optional[Set[str]]) -> List[str]:
        """Send event to all selected destinations and return failures."""
        failed: List[str] = []

        for destination_name, destination in self._destinations.items():
            if target_destinations is not None and destination_name not in target_destinations:
                continue

            if not destination.get("enabled", True):
                continue

            if not self._matches_filters(destination=destination, event=event):
                continue

            start = time.perf_counter()
            try:
                await self._send_to_destination(destination=destination, event=event)
            except Exception as exc:
                failed.append(destination_name)
                self._record_delivery_failure(destination_name=destination_name, error=str(exc))
                siem_events_exported_total.labels(destination=destination_name, status="failure").inc()
            else:
                latency_seconds = time.perf_counter() - start
                self._record_delivery_success(destination_name=destination_name, latency_seconds=latency_seconds)
                siem_events_exported_total.labels(destination=destination_name, status="success").inc()
                siem_export_latency_seconds.labels(destination=destination_name).observe(latency_seconds)

        return failed

    async def _schedule_retry_or_dead_letter(self, event: Dict[str, Any], failed_destinations: List[str]) -> None:
        """Requeue failed deliveries with exponential backoff or dead-letter."""
        event_copy = deepcopy(event)
        meta = event_copy.setdefault("_meta", {})

        attempt = int(meta.get("attempt", 0)) + 1
        meta["attempt"] = attempt
        meta["pending_destinations"] = failed_destinations

        if attempt > self.max_retries:
            meta["dead_lettered_at"] = datetime.now(timezone.utc).isoformat()
            await self._push_dead_letter(event_copy)
            logger.error("SIEM event moved to dead letter queue after %s retries", self.max_retries)
            return

        delay_seconds = min(2 ** (attempt - 1), self.backoff_max_seconds)
        retry_task = asyncio.create_task(self._delayed_requeue(event_copy, delay_seconds))
        self._retry_tasks.add(retry_task)
        retry_task.add_done_callback(self._retry_tasks.discard)

    async def _delayed_requeue(self, event: Dict[str, Any], delay_seconds: float) -> None:
        """Delay and requeue event for retry."""
        try:
            await asyncio.sleep(delay_seconds)
            await self._enqueue_envelope(event)
        except Exception as exc:  # pragma: no cover - defensive path
            logger.warning("SIEM delayed requeue failed: %s", exc)
            await self._push_dead_letter(event)

    async def _push_dead_letter(self, event: Dict[str, Any]) -> None:
        """Store event in dead-letter queue."""
        if self._queue_backend == "redis" and self._redis:
            try:
                await self._redis.xadd(f"{self.stream_name}:dlq", {"event": orjson.dumps(event).decode("utf-8")}, maxlen=self.queue_max_size, approximate=True)
                return
            except Exception as exc:
                logger.warning("Failed writing SIEM dead-letter event to Redis: %s", exc)

        self._local_dead_letter.append(event)

    async def _enqueue_envelope(self, envelope: Dict[str, Any]) -> None:
        """Enqueue envelope to configured backend with backpressure policy."""
        if self._queue_backend == "redis" and self._redis:
            await self._enqueue_redis(envelope)
        else:
            await self._enqueue_local(envelope)

        await self._update_queue_depth_metrics()

    async def _enqueue_local(self, envelope: Dict[str, Any]) -> None:
        """Enqueue one event to local queue with configured backpressure handling."""
        if self._local_queue.full():
            if self.backpressure_policy == "block_producer":
                await self._local_queue.put(envelope)
                return

            # drop_oldest default behavior
            try:
                self._local_queue.get_nowait()
                self._local_queue.task_done()
            except asyncio.QueueEmpty:
                pass

        self._local_queue.put_nowait(envelope)

    async def _enqueue_redis(self, envelope: Dict[str, Any]) -> None:
        """Enqueue one event to Redis stream."""
        payload = orjson.dumps(envelope).decode("utf-8")
        await self._redis.xadd(self.stream_name, {"event": payload}, maxlen=self.queue_max_size, approximate=True)

    async def _ack_redis_entry(self, entry_id: str) -> None:
        """Acknowledge one Redis stream entry."""
        try:
            await self._redis.xack(self.stream_name, self.consumer_group, entry_id)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("SIEM Redis ACK failed for %s: %s", entry_id, exc)

    async def _ensure_stream_group(self) -> None:
        """Create consumer group if absent."""
        try:
            await self._redis.xgroup_create(name=self.stream_name, groupname=self.consumer_group, id="$", mkstream=True)
        except Exception as exc:
            # BUSYGROUP is expected after first initialization.
            if "BUSYGROUP" not in str(exc):
                logger.warning("Failed to ensure SIEM stream group: %s", exc)

    async def _get_queue_depth(self) -> int:
        """Get current queue depth."""
        if self._queue_backend == "redis" and self._redis:
            try:
                depth = await self._redis.xlen(self.stream_name)
                return int(depth)
            except Exception:
                return 0
        return self._local_queue.qsize()

    async def _update_queue_depth_metrics(self) -> None:
        """Update per-destination queue depth gauges."""
        depth = await self._get_queue_depth()

        if not self._destinations:
            siem_queue_depth.labels(destination="all").set(depth)
            return

        for destination_name in self._destinations:
            siem_queue_depth.labels(destination=destination_name).set(depth)

    def _record_delivery_success(self, destination_name: str, latency_seconds: float) -> None:
        """Update health stats for successful delivery."""
        now = datetime.now(timezone.utc)
        stats = self._destination_stats.setdefault(destination_name, DestinationStats())
        stats.sent_timestamps.append(now)
        stats.last_event_sent = now
        stats.last_error = None
        stats.consecutive_failures = 0

        latency_ms = latency_seconds * 1000.0
        if stats.avg_latency_ms <= 0:
            stats.avg_latency_ms = latency_ms
        else:
            # Exponential moving average with alpha=0.2
            stats.avg_latency_ms = (0.2 * latency_ms) + (0.8 * stats.avg_latency_ms)

        stats.prune(now)

    def _record_delivery_failure(self, destination_name: str, error: str) -> None:
        """Update health stats for failed delivery."""
        now = datetime.now(timezone.utc)
        stats = self._destination_stats.setdefault(destination_name, DestinationStats())
        stats.failed_timestamps.append(now)
        stats.consecutive_failures += 1
        stats.last_error = error
        stats.prune(now)

        if stats.consecutive_failures >= 10:
            logger.error("SIEM destination '%s' has %s consecutive failures", destination_name, stats.consecutive_failures)

    def _build_event_envelope(self, event: Dict[str, Any], source: str) -> Dict[str, Any]:
        """Build normalized SIEM envelope from source event."""
        now = datetime.now(timezone.utc)
        timestamp = self._normalize_timestamp(event.get("timestamp")) or now

        event_type = str(event.get("event_type") or "security_event")
        severity = str(event.get("severity") or "LOW").upper()
        category = str(event.get("category") or source)

        context_payload = deepcopy(event.get("context") if isinstance(event.get("context"), dict) else {})
        correlation_id = event.get("correlation_id")
        if correlation_id and "correlation_id" not in context_payload:
            context_payload["correlation_id"] = correlation_id

        threat_score_raw = event.get("threat_score")
        if threat_score_raw is None:
            threat_payload = event.get("threat") if isinstance(event.get("threat"), dict) else {}
            threat_score_raw = threat_payload.get("score")

        failed_attempts_raw = event.get("failed_attempts")
        if failed_attempts_raw is None:
            failed_attempts_raw = event.get("failed_attempts_count", 0)

        threat_indicators = event.get("threat_indicators")
        if threat_indicators is None:
            threat_payload = event.get("threat") if isinstance(event.get("threat"), dict) else {}
            threat_indicators = threat_payload.get("indicators") or []

        actor_payload = {
            "user_id": event.get("user_id"),
            "user_email": event.get("user_email"),
            "client_ip": event.get("client_ip"),
            "user_agent": event.get("user_agent"),
            "geo": event.get("geo") if isinstance(event.get("geo"), dict) else None,
        }

        envelope: Dict[str, Any] = {
            "schema_version": "1.0",
            "event_id": str(event.get("event_id") or f"evt_{uuid.uuid4().hex[:12]}"),
            "timestamp": timestamp.isoformat(),
            "event_type": event_type,
            "severity": severity,
            "category": category,
            "description": event.get("description") or f"{event_type} detected",
            "source": {
                "service": "mcpgateway",
                "version": __version__,
                "instance_id": socket.gethostname(),
                "event_source": source,
            },
            "actor": actor_payload,
            "threat": {
                "score": self._to_float(threat_score_raw, default=0.0),
                "failed_attempts": self._to_int(failed_attempts_raw, default=0),
                "indicators": threat_indicators if isinstance(threat_indicators, list) else [str(threat_indicators)] if threat_indicators else [],
            },
            "context": context_payload,
            "action_taken": event.get("action_taken"),
            "_meta": {
                "attempt": int(event.get("_meta", {}).get("attempt", 0)) if isinstance(event.get("_meta"), dict) else 0,
            },
        }

        # Preserve source-specific payload for downstream templates/investigation.
        passthrough = event.get("metadata")
        if isinstance(passthrough, dict):
            envelope["metadata"] = deepcopy(passthrough)

        return envelope

    def _normalize_timestamp(self, value: Any) -> Optional[datetime]:
        """Normalize timestamp to UTC datetime."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                return None
        return None

    def _to_float(self, value: Any, default: float) -> float:
        """Best-effort float conversion."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _to_int(self, value: Any, default: int) -> int:
        """Best-effort int conversion."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    async def _send_to_destination(self, destination: Dict[str, Any], event: Dict[str, Any]) -> None:
        """Dispatch one event to one configured destination adapter."""
        destination_type = str(destination.get("type", "")).lower()

        if destination_type == "syslog":
            await self._send_syslog(destination=destination, event=event)
            return

        if destination_type == "splunk_hec":
            await self._send_splunk(destination=destination, event=event)
            return

        if destination_type == "datadog":
            await self._send_datadog(destination=destination, event=event)
            return

        if destination_type == "elasticsearch":
            await self._send_elasticsearch(destination=destination, event=event)
            return

        if destination_type == "webhook":
            await self._send_webhook(destination=destination, event=event)
            return

        raise ValueError(f"Unsupported destination type: {destination_type}")

    async def _send_splunk(self, destination: Dict[str, Any], event: Dict[str, Any]) -> None:
        """Send event to Splunk HEC."""
        url = str(destination.get("url") or "")
        token = str(destination.get("token") or "")
        if not url or not token:
            raise ValueError("Splunk destination requires url and token")

        formatted = self._format_for_destination(destination=destination, event=event)

        payload: Dict[str, Any] = {
            "time": self._to_float(datetime.fromisoformat(event["timestamp"]).timestamp(), default=time.time()),
            "host": socket.gethostname(),
            "source": destination.get("source", "mcpgateway"),
            "sourcetype": destination.get("sourcetype", "mcpgateway"),
            "event": formatted,
        }

        if destination.get("index"):
            payload["index"] = destination["index"]

        client = await get_http_client()
        response = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Splunk {token}", "Content-Type": "application/json"},
        )

        if response.status_code >= 400:
            raise RuntimeError(f"Splunk HEC failed with status {response.status_code}: {response.text}")

    async def _send_datadog(self, destination: Dict[str, Any], event: Dict[str, Any]) -> None:
        """Send event to Datadog Logs API."""
        api_key = str(destination.get("api_key") or "")
        if not api_key:
            raise ValueError("Datadog destination requires api_key")

        url = str(destination.get("url") or "")
        if not url:
            site = str(destination.get("site") or "datadoghq.com")
            url = f"https://http-intake.logs.{site}/api/v2/logs"

        formatted = self._format_for_destination(destination=destination, event=event)
        if isinstance(formatted, str):
            message = formatted
            attributes: Dict[str, Any] = {}
        else:
            message = str(event.get("description") or event.get("event_type") or "mcpgateway security event")
            attributes = formatted

        payload = [
            {
                "message": message,
                "ddsource": destination.get("source", "mcpgateway"),
                "service": destination.get("service", "mcpgateway"),
                "hostname": socket.gethostname(),
                "attributes": attributes,
            }
        ]

        tags = destination.get("tags")
        if tags:
            payload[0]["ddtags"] = ",".join(str(item) for item in tags) if isinstance(tags, list) else str(tags)

        client = await get_http_client()
        response = await client.post(
            url,
            json=payload,
            headers={"DD-API-KEY": api_key, "Content-Type": "application/json"},
        )

        if response.status_code >= 400:
            raise RuntimeError(f"Datadog export failed with status {response.status_code}: {response.text}")

    async def _send_elasticsearch(self, destination: Dict[str, Any], event: Dict[str, Any]) -> None:
        """Send event to Elasticsearch bulk ingestion endpoint."""
        url = str(destination.get("url") or "").rstrip("/")
        if not url:
            raise ValueError("Elasticsearch destination requires url")

        index_pattern = str(destination.get("index_pattern") or "mcpgateway-security-%Y.%m.%d")
        event_dt = datetime.fromisoformat(event["timestamp"])
        index_name = event_dt.strftime(index_pattern)

        formatted = self._format_for_destination(destination=destination, event=event)

        bulk_lines = [
            {"index": {"_index": index_name}},
            formatted,
        ]
        body = "\n".join(orjson.dumps(line).decode("utf-8") for line in bulk_lines) + "\n"

        auth = None
        username = destination.get("username")
        password = destination.get("password")
        if username is not None and password is not None:
            auth = (str(username), str(password))

        client = await get_http_client()
        response = await client.post(
            f"{url}/_bulk",
            content=body,
            headers={"Content-Type": "application/x-ndjson"},
            auth=auth,
        )

        if response.status_code >= 400:
            raise RuntimeError(f"Elasticsearch export failed with status {response.status_code}: {response.text}")

    async def _send_webhook(self, destination: Dict[str, Any], event: Dict[str, Any]) -> None:
        """Send event to generic webhook destination."""
        url = str(destination.get("url") or "")
        if not url:
            raise ValueError("Webhook destination requires url")

        method = str(destination.get("method") or "POST").upper()
        headers = {str(k): str(v) for k, v in dict(destination.get("headers") or {}).items()}

        template_payload = self._render_template_payload(destination=destination, event=event)

        if template_payload is not None:
            content_bytes = template_payload.encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
            request_kwargs: Dict[str, Any] = {"content": content_bytes}
        else:
            formatted = self._format_for_destination(destination=destination, event=event)
            request_kwargs = {"json": formatted}
            content_bytes = orjson.dumps(formatted)

        hmac_secret = destination.get("hmac_secret")
        if hmac_secret:
            algorithm = str(destination.get("hmac_algorithm") or "sha256").lower()
            digest = self._hmac_digest(secret=str(hmac_secret), payload=content_bytes, algorithm=algorithm)
            header_name = str(destination.get("hmac_header") or "X-SIEM-Signature")
            headers[header_name] = digest

        client = await get_http_client()
        response = await client.request(method=method, url=url, headers=headers, **request_kwargs)

        expected_status_codes = destination.get("expected_status_codes")
        if isinstance(expected_status_codes, list) and expected_status_codes:
            if response.status_code not in [int(item) for item in expected_status_codes]:
                raise RuntimeError(f"Webhook returned unexpected status {response.status_code}")
        elif response.status_code >= 400:
            raise RuntimeError(f"Webhook export failed with status {response.status_code}: {response.text}")

    async def _send_syslog(self, destination: Dict[str, Any], event: Dict[str, Any]) -> None:
        """Send event as syslog message (UDP/TCP)."""
        host = str(destination.get("host") or "")
        port = int(destination.get("port") or 514)
        protocol = str(destination.get("protocol") or "udp").lower()
        if not host:
            raise ValueError("Syslog destination requires host")

        formatted = self._format_for_destination(destination=destination, event=event)
        if isinstance(formatted, dict):
            message = orjson.dumps(formatted).decode("utf-8")
        else:
            message = str(formatted)

        if not destination.get("syslog_wrapper", True):
            payload = message
        else:
            payload = self._wrap_syslog_message(message=message, event=event, app_name=str(destination.get("app_name") or "mcpgateway"), facility=int(destination.get("facility") or 1))

        if protocol == "tcp":
            reader, writer = await asyncio.open_connection(host, port)
            del reader
            writer.write(payload.encode("utf-8") + b"\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        if protocol != "udp":
            raise ValueError("Syslog protocol must be 'udp' or 'tcp'")

        loop = asyncio.get_running_loop()
        addr_info = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
        family, socktype, proto, _, sockaddr = addr_info[0]
        sock = socket.socket(family, socktype, proto)
        sock.setblocking(False)
        try:
            await loop.sock_sendto(sock, payload.encode("utf-8"), sockaddr)
        finally:
            sock.close()

    def _render_template_payload(self, destination: Dict[str, Any], event: Dict[str, Any]) -> Optional[str]:
        """Render optional destination-specific Jinja2 payload template."""
        template_text = destination.get("template")
        template_file = destination.get("template_file")

        if not template_text and template_file:
            try:
                with open(str(template_file), "r", encoding="utf-8") as file_handle:
                    template_text = file_handle.read()
            except OSError as exc:
                raise RuntimeError(f"Failed to read webhook template file: {exc}") from exc

        if not template_text:
            return None

        template = Template(str(template_text))
        rendered = template.render(event=event)
        return rendered

    def _hmac_digest(self, secret: str, payload: bytes, algorithm: str) -> str:
        """Compute hex digest for webhook signing."""
        digestmod = getattr(hashlib, algorithm, None)
        if digestmod is None:
            raise ValueError(f"Unsupported HMAC algorithm: {algorithm}")
        return hmac.new(secret.encode("utf-8"), payload, digestmod=digestmod).hexdigest()

    def _format_for_destination(self, destination: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any] | str:
        """Apply redaction + destination format transformation."""
        redacted_event = self._apply_redaction(destination=destination, event=event)

        fmt = str(destination.get("format") or "json").lower()
        if fmt == "cef":
            return self._to_cef(event=redacted_event)
        if fmt == "leef":
            return self._to_leef(event=redacted_event)
        return redacted_event

    def _to_cef(self, event: Dict[str, Any]) -> str:
        """Convert event to Common Event Format (CEF)."""
        actor = event.get("actor") if isinstance(event.get("actor"), dict) else {}
        threat = event.get("threat") if isinstance(event.get("threat"), dict) else {}
        context = event.get("context") if isinstance(event.get("context"), dict) else {}

        severity = _CEF_SEVERITY_MAP.get(str(event.get("severity", "LOW")).upper(), 3)
        signature = self._cef_escape(str(event.get("event_type", "SECURITY_EVENT")).upper())
        name = self._cef_escape(str(event.get("description", "Security Event")))

        extension_fields = {
            "src": actor.get("client_ip"),
            "suser": actor.get("user_email") or actor.get("user_id"),
            "msg": event.get("description"),
            "cs1": context.get("correlation_id"),
            "cs1Label": "CorrelationID",
            "cn1": threat.get("failed_attempts"),
            "cn1Label": "FailedAttempts",
            "cfp1": threat.get("score"),
            "cfp1Label": "ThreatScore",
        }

        ext_parts = []
        for key, value in extension_fields.items():
            if value is None:
                continue
            ext_parts.append(f"{key}={self._cef_escape(str(value))}")

        ext = " ".join(ext_parts)
        return f"CEF:0|IBM|ContextForge|{__version__}|{signature}|{name}|{severity}|{ext}".rstrip()

    def _to_leef(self, event: Dict[str, Any]) -> str:
        """Convert event to Log Event Extended Format (LEEF)."""
        actor = event.get("actor") if isinstance(event.get("actor"), dict) else {}
        threat = event.get("threat") if isinstance(event.get("threat"), dict) else {}
        context = event.get("context") if isinstance(event.get("context"), dict) else {}

        event_id = str(event.get("event_type", "SECURITY_EVENT")).upper()
        header = f"LEEF:2.0|IBM|ContextForge|{__version__}|{event_id}|"

        kv_fields = {
            "src": actor.get("client_ip"),
            "usrName": actor.get("user_email") or actor.get("user_id"),
            "msg": event.get("description"),
            "severity": event.get("severity"),
            "cat": event.get("category"),
            "threatScore": threat.get("score"),
            "failedAttempts": threat.get("failed_attempts"),
            "correlationId": context.get("correlation_id"),
        }

        parts = []
        for key, value in kv_fields.items():
            if value is None:
                continue
            escaped = str(value).replace("\\", "\\\\").replace("\t", " ").replace("\n", " ")
            parts.append(f"{key}={escaped}")

        return header + "\t" + "\t".join(parts)

    def _wrap_syslog_message(self, message: str, event: Dict[str, Any], app_name: str, facility: int) -> str:
        """Wrap message in RFC 5424 syslog envelope."""
        severity_name = str(event.get("severity") or "LOW").upper()
        severity = _SYSLOG_SEVERITY_MAP.get(severity_name, 6)
        pri = (facility * 8) + severity

        timestamp = event.get("timestamp") or datetime.now(timezone.utc).isoformat()
        hostname = socket.gethostname()
        msg_id = str(event.get("event_type") or "SIEM_EXPORT")

        return f"<{pri}>1 {timestamp} {hostname} {app_name} {os.getpid()} {msg_id} - {message}"

    def _cef_escape(self, value: str) -> str:
        """Escape CEF special characters."""
        return value.replace("\\", "\\\\").replace("|", "\\|").replace("=", "\\=").replace("\n", " ")

    def _matches_filters(self, destination: Dict[str, Any], event: Dict[str, Any]) -> bool:
        """Evaluate destination filter predicates."""
        filters = destination.get("filters")
        if not isinstance(filters, dict) or not filters:
            return True

        severity_filter = filters.get("severity")
        if isinstance(severity_filter, list) and severity_filter:
            event_severity = str(event.get("severity") or "").upper()
            allowed = {str(item).upper() for item in severity_filter}
            if event_severity not in allowed:
                return False

        event_type_filter = filters.get("event_types")
        if isinstance(event_type_filter, list) and event_type_filter:
            event_type = str(event.get("event_type") or "")
            allowed = {str(item) for item in event_type_filter}
            if event_type not in allowed:
                return False

        category_filter = filters.get("categories")
        if isinstance(category_filter, list) and category_filter:
            category = str(event.get("category") or "")
            allowed = {str(item) for item in category_filter}
            if category not in allowed:
                return False

        return True

    def _apply_redaction(self, destination: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        """Redact configured sensitive fields recursively."""
        destination_fields = destination.get("redact_fields")
        redaction_fields = set(self._redact_fields)
        if isinstance(destination_fields, list):
            redaction_fields.update(str(item) for item in destination_fields)

        redacted = deepcopy(event)

        def redact_obj(obj: Any) -> Any:
            """Recursively redact matching keys in dictionaries and lists."""
            if isinstance(obj, dict):
                redacted_dict: Dict[str, Any] = {}
                for key, value in obj.items():
                    if str(key) in redaction_fields:
                        redacted_dict[key] = "***REDACTED***"
                    else:
                        redacted_dict[key] = redact_obj(value)
                return redacted_dict
            if isinstance(obj, list):
                return [redact_obj(item) for item in obj]
            return obj

        return redact_obj(redacted)

    def _load_destination_settings(self) -> None:
        """Load and normalize destination config from settings."""
        configured = getattr(settings, "siem_destinations", [])
        new_destinations: Dict[str, Dict[str, Any]] = {}

        for raw_destination in configured:
            try:
                destination = self._normalize_destination_config(raw_destination)
            except Exception as exc:
                logger.warning("Skipping invalid SIEM destination config: %s", exc)
                continue
            new_destinations[destination["name"]] = destination

        self._destinations = new_destinations
        for name in self._destinations:
            self._destination_stats.setdefault(name, DestinationStats())

    def _normalize_destination_config(self, destination: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize one destination config dictionary."""
        if not isinstance(destination, dict):
            raise ValueError("Destination must be an object")

        normalized = self._resolve_env_placeholders(deepcopy(destination))

        name = str(normalized.get("name") or "").strip()
        if not name:
            raise ValueError("Destination requires non-empty 'name'")

        destination_type = str(normalized.get("type") or "").strip().lower()
        if destination_type not in _ALLOWED_DEST_TYPES:
            raise ValueError(f"Destination '{name}' has unsupported type '{destination_type}'")

        fmt = str(normalized.get("format") or "json").strip().lower()
        if fmt not in _ALLOWED_FORMATS:
            raise ValueError(f"Destination '{name}' has unsupported format '{fmt}'")

        normalized["name"] = name
        normalized["type"] = destination_type
        normalized["format"] = fmt
        normalized["enabled"] = bool(normalized.get("enabled", True))

        # Normalize filters
        filters = normalized.get("filters")
        if filters is None:
            normalized["filters"] = {}
        elif not isinstance(filters, dict):
            raise ValueError(f"Destination '{name}' filters must be an object")

        # Normalize URL-like destinations and enforce outbound allowlist.
        destination_url = self._resolve_destination_url(normalized)
        if destination_url:
            self._validate_outbound_url(destination_url)
            normalized["url"] = destination_url

        # Validate destination-specific required fields.
        if destination_type == "syslog":
            if not normalized.get("host"):
                raise ValueError(f"Destination '{name}' (syslog) requires 'host'")

        return normalized

    def _resolve_destination_url(self, destination: Dict[str, Any]) -> Optional[str]:
        """Resolve URL for destination if applicable."""
        destination_type = str(destination.get("type") or "").lower()

        if destination_type == "datadog":
            if destination.get("url"):
                return str(destination["url"])
            site = str(destination.get("site") or "datadoghq.com")
            return f"https://http-intake.logs.{site}/api/v2/logs"

        if destination_type in {"splunk_hec", "elasticsearch", "webhook"}:
            url = destination.get("url")
            return str(url) if url else None

        return None

    def _validate_outbound_url(self, url: str) -> None:
        """Enforce destination outbound URL allowlist."""
        if not self._url_allowlist:
            return

        parsed = urlparse(url)
        hostname = parsed.hostname or ""

        for allow_rule in self._url_allowlist:
            rule = allow_rule.strip()
            if not rule:
                continue

            if "://" in rule and url.startswith(rule):
                return

            if rule.startswith("*."):
                suffix = rule[1:]
                if hostname.endswith(suffix):
                    return

            if hostname == rule:
                return

        raise ValueError(f"Destination URL not in allowlist: {url}")

    def _resolve_env_placeholders(self, value: Any) -> Any:
        """Resolve ${ENV_VAR} placeholders recursively."""
        if isinstance(value, dict):
            return {k: self._resolve_env_placeholders(v) for k, v in value.items()}

        if isinstance(value, list):
            return [self._resolve_env_placeholders(item) for item in value]

        if isinstance(value, str):
            text = value
            start = text.find("${")
            while start != -1:
                end = text.find("}", start + 2)
                if end == -1:
                    break
                key = text[start + 2 : end]
                replacement = os.getenv(key, "")
                text = text[:start] + replacement + text[end + 1 :]
                start = text.find("${")
            return text

        return value

    def _sanitize_destination_for_response(self, destination: Dict[str, Any]) -> Dict[str, Any]:
        """Redact destination secrets for admin API responses."""
        secret_keys = {"token", "api_key", "password", "secret", "hmac_secret"}
        sanitized: Dict[str, Any] = {}

        for key, value in destination.items():
            if key in secret_keys:
                sanitized[key] = "***REDACTED***"
                continue

            if key == "headers" and isinstance(value, dict):
                masked_headers: Dict[str, str] = {}
                for header_name, header_value in value.items():
                    if "auth" in str(header_name).lower() or "token" in str(header_name).lower() or "key" in str(header_name).lower():
                        masked_headers[str(header_name)] = "***REDACTED***"
                    else:
                        masked_headers[str(header_name)] = str(header_value)
                sanitized[key] = masked_headers
                continue

            sanitized[key] = value

        return sanitized


_siem_export_service: Optional[SIEMExportService] = None


def get_siem_export_service() -> SIEMExportService:  # pragma: no cover - singleton accessor
    """Get singleton SIEM export service instance."""
    global _siem_export_service  # pylint: disable=global-statement
    if _siem_export_service is None:
        _siem_export_service = SIEMExportService()
    return _siem_export_service
