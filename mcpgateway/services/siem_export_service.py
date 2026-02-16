# -*- coding: utf-8 -*-
"""SIEM Export Service - Integration layer for audit records.

Location: mcpgateway/services/siem_export_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Supports Splunk HEC, Elasticsearch, and generic webhooks.
Ported from mcp_servers/mcp_audit_siem.py with fixes for:
- print() replaced with logging.getLogger(__name__)
- Type signatures use PolicyDecision ORM model
- Config read from mcpgateway.config.settings
"""

# Standard
from abc import ABC, abstractmethod
import asyncio
from collections import deque
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Dict, List, Optional

# aiohttp is optional for SIEM integration
try:
    # Third-Party
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    aiohttp = None  # type: ignore[assignment]

# First-Party
from mcpgateway.common.policy_audit import PolicyDecision

logger = logging.getLogger(__name__)


class SIEMExporter(ABC):
    """Abstract base class for SIEM exporters."""

    @abstractmethod
    async def send(self, record: PolicyDecision) -> bool:
        """Send a single record. Returns True on success."""

    @abstractmethod
    async def send_batch(self, records: List[PolicyDecision]) -> bool:
        """Send a batch of records. Returns True on success."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if SIEM endpoint is reachable."""

    async def close(self) -> None:
        """Close any open connections."""


class SplunkHECExporter(SIEMExporter):
    """Splunk HTTP Event Collector exporter."""

    def __init__(self, endpoint: str, token_env: str, timeout_seconds: int, retry_attempts: int):
        self.endpoint = endpoint
        self.token = os.getenv(token_env, "")
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.session: Optional[Any] = None

    async def _get_session(self):
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"Authorization": f"Splunk {self.token}", "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
            )
        return self.session

    async def send(self, record: PolicyDecision) -> bool:
        """Send single record to Splunk HEC."""
        return await self.send_batch([record])

    async def send_batch(self, records: List[PolicyDecision]) -> bool:
        """Send batch of records to Splunk HEC."""
        if not records:
            return True

        session = await self._get_session()
        payload = "\n".join([json.dumps(record.to_splunk_hec()) for record in records])

        for attempt in range(self.retry_attempts):
            try:
                async with session.post(self.endpoint, data=payload) as response:
                    if response.status == 200:
                        return True
                    elif response.status == 403:
                        logger.error("Splunk HEC: Authentication failed (invalid token)")
                        return False
                    else:
                        text = await response.text()
                        logger.warning(f"Splunk HEC: Failed with status {response.status}: {text}")
            except Exception as e:
                logger.warning(f"Splunk HEC: Attempt {attempt + 1} failed: {e}")
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(2**attempt)

        return False

    async def health_check(self) -> bool:
        """Check Splunk HEC endpoint."""
        try:
            session = await self._get_session()
            health_endpoint = self.endpoint.replace("/services/collector", "/services/collector/health")
            async with session.get(health_endpoint) as response:
                return response.status in [200, 503]
        except Exception as e:
            logger.warning(f"Splunk health check failed: {e}")
            return False

    async def close(self) -> None:
        """Close the session."""
        if self.session and not self.session.closed:
            await self.session.close()


class ElasticsearchExporter(SIEMExporter):
    """Elasticsearch exporter."""

    def __init__(self, endpoint: str, token_env: str, timeout_seconds: int, retry_attempts: int):
        self.endpoint = endpoint.rstrip("/")
        self.token = os.getenv(token_env, "")
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.index_name = "audit-decisions"
        self.session: Optional[Any] = None

    async def _get_session(self):
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            headers: Dict[str, str] = {"Content-Type": "application/json"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
            )
        return self.session

    async def send(self, record: PolicyDecision) -> bool:
        """Send single record to Elasticsearch."""
        session = await self._get_session()
        url = f"{self.endpoint}/{self.index_name}/_doc/{record.id}"
        doc = record.to_elasticsearch()

        try:
            async with session.put(url, json=doc) as response:
                if response.status in [200, 201]:
                    return True
                else:
                    text = await response.text()
                    logger.warning(f"Elasticsearch: Failed to index: {text}")
                    return False
        except Exception as e:
            logger.error(f"Elasticsearch: Failed to send: {e}")
            return False

    async def send_batch(self, records: List[PolicyDecision]) -> bool:
        """Send batch using Elasticsearch bulk API."""
        if not records:
            return True

        session = await self._get_session()
        bulk_data = []
        for record in records:
            bulk_data.append(json.dumps({"index": {"_index": self.index_name, "_id": str(record.id)}}))
            bulk_data.append(json.dumps(record.to_elasticsearch()))

        payload = "\n".join(bulk_data) + "\n"
        url = f"{self.endpoint}/_bulk"

        try:
            async with session.post(url, data=payload, headers={"Content-Type": "application/x-ndjson"}) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("errors"):
                        logger.warning("Elasticsearch bulk: Some items failed")
                        return False
                    return True
                else:
                    text = await response.text()
                    logger.warning(f"Elasticsearch bulk failed: {text}")
                    return False
        except Exception as e:
            logger.error(f"Elasticsearch bulk error: {e}")
            return False

    async def health_check(self) -> bool:
        """Check Elasticsearch cluster health."""
        try:
            session = await self._get_session()
            url = f"{self.endpoint}/_cluster/health"
            async with session.get(url) as response:
                return response.status == 200
        except Exception as e:
            logger.warning(f"Elasticsearch health check failed: {e}")
            return False

    async def close(self) -> None:
        """Close the session."""
        if self.session and not self.session.closed:
            await self.session.close()


class WebhookExporter(SIEMExporter):
    """Generic webhook exporter."""

    def __init__(self, endpoint: str, token_env: str, timeout_seconds: int, retry_attempts: int):
        self.endpoint = endpoint
        self.token = os.getenv(token_env, "")
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.session: Optional[Any] = None

    async def _get_session(self):
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            headers: Dict[str, str] = {"Content-Type": "application/json"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
            )
        return self.session

    async def send(self, record: PolicyDecision) -> bool:
        """Send single record to webhook."""
        return await self.send_batch([record])

    async def send_batch(self, records: List[PolicyDecision]) -> bool:
        """Send batch to webhook."""
        if not records:
            return True

        session = await self._get_session()
        payload = {
            "events": [record.to_webhook() for record in records],
            "batch_size": len(records),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            async with session.post(self.endpoint, json=payload) as response:
                if response.status in [200, 201, 202]:
                    return True
                else:
                    text = await response.text()
                    logger.warning(f"Webhook failed: {response.status} - {text}")
                    return False
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return False

    async def health_check(self) -> bool:
        """Check webhook endpoint."""
        try:
            session = await self._get_session()
            async with session.head(self.endpoint) as response:
                return response.status < 500
        except Exception as e:
            logger.warning(f"Webhook health check failed: {e}")
            return False

    async def close(self) -> None:
        """Close the session."""
        if self.session and not self.session.closed:
            await self.session.close()


class SIEMBatchProcessor:
    """Batches audit records and sends them to SIEM periodically."""

    def __init__(self, exporter: SIEMExporter, batch_size: int, flush_interval_seconds: int):
        self.exporter = exporter
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds
        self.queue: deque = deque()
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the batch processor."""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        """Stop the batch processor and flush remaining records."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Flush any remaining records
        await self._flush()
        await self.exporter.close()

    async def add(self, record: PolicyDecision) -> None:
        """Add a record to the batch queue."""
        self.queue.append(record)
        if len(self.queue) >= self.batch_size:
            await self._flush()

    async def _flush(self) -> None:
        """Flush the current batch to SIEM."""
        if not self.queue:
            return

        batch = []
        while self.queue and len(batch) < self.batch_size:
            batch.append(self.queue.popleft())

        if batch:
            success = await self.exporter.send_batch(batch)
            if not success:
                for record in reversed(batch):
                    self.queue.appendleft(record)

    async def _flush_loop(self) -> None:
        """Periodically flush batches."""
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval_seconds)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SIEM flush loop error: {e}")


def create_siem_service(siem_settings) -> Optional[SIEMBatchProcessor]:
    """Factory function to create SIEM batch processor from settings.

    Args:
        siem_settings: Object with siem_enabled, siem_type, siem_endpoint, etc.

    Returns:
        SIEMBatchProcessor if enabled and configured, None otherwise.
    """
    if not siem_settings.siem_enabled:
        return None

    if not AIOHTTP_AVAILABLE:
        logger.warning("aiohttp not available, SIEM integration disabled. Install with: pip install aiohttp")
        return None

    if not siem_settings.siem_endpoint:
        logger.warning("SIEM endpoint not configured, SIEM integration disabled")
        return None

    exporter_kwargs = {
        "endpoint": siem_settings.siem_endpoint,
        "token_env": siem_settings.siem_token_env,
        "timeout_seconds": siem_settings.siem_timeout_seconds,
        "retry_attempts": siem_settings.siem_retry_attempts,
    }

    siem_type = siem_settings.siem_type.lower()
    if siem_type == "splunk":
        exporter: SIEMExporter = SplunkHECExporter(**exporter_kwargs)
    elif siem_type == "elasticsearch":
        exporter = ElasticsearchExporter(**exporter_kwargs)
    elif siem_type == "webhook":
        exporter = WebhookExporter(**exporter_kwargs)
    else:
        logger.error(f"Unknown SIEM type: {siem_type}")
        return None

    processor = SIEMBatchProcessor(
        exporter=exporter,
        batch_size=siem_settings.siem_batch_size,
        flush_interval_seconds=siem_settings.siem_flush_interval_seconds,
    )
    logger.info(f"SIEM export service created: type={siem_type}, endpoint={siem_settings.siem_endpoint}")
    return processor
