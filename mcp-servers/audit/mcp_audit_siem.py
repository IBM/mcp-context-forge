"""
SIEM integration layer for audit records.

Supports Splunk HEC, Elasticsearch, and generic webhooks.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
import asyncio
import json
import os
from datetime import datetime
from collections import deque

# aiohttp is optional for SIEM integration
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    # Create dummy module for type hints
    class aiohttp:
        class ClientSession:
            pass
        class ClientTimeout:
            def __init__(self, **kwargs):
                pass

from mcp_audit_models import AuditDecisionRecord, SIEMConfig


class SIEMExporter(ABC):
    """Abstract base class for SIEM exporters."""
    
    @abstractmethod
    async def send(self, record: AuditDecisionRecord) -> bool:
        """Send a single record. Returns True on success."""
        pass
    
    @abstractmethod
    async def send_batch(self, records: List[AuditDecisionRecord]) -> bool:
        """Send a batch of records. Returns True on success."""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if SIEM endpoint is reachable."""
        pass


class SplunkHECExporter(SIEMExporter):
    """
    Splunk HTTP Event Collector exporter.
    
    Sends audit records to Splunk via HEC endpoint.
    """
    
    def __init__(self, config: SIEMConfig):
        self.config = config
        self.endpoint = config.endpoint
        self.token = os.getenv(config.token_env, "")
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    'Authorization': f'Splunk {self.token}',
                    'Content-Type': 'application/json'
                },
                timeout=aiohttp.ClientTimeout(total=self.config.timeout_seconds)
            )
        return self.session
    
    async def send(self, record: AuditDecisionRecord) -> bool:
        """Send single record to Splunk HEC."""
        return await self.send_batch([record])
    
    async def send_batch(self, records: List[AuditDecisionRecord]) -> bool:
        """Send batch of records to Splunk HEC."""
        if not records:
            return True
        
        session = await self._get_session()
        
        # Format as newline-delimited JSON (Splunk HEC batch format)
        payload = "\n".join([
            json.dumps(record.to_splunk_hec())
            for record in records
        ])
        
        for attempt in range(self.config.retry_attempts):
            try:
                async with session.post(self.endpoint, data=payload) as response:
                    if response.status == 200:
                        return True
                    elif response.status == 403:
                        print(f"Splunk HEC: Authentication failed (invalid token)")
                        return False
                    else:
                        text = await response.text()
                        print(f"Splunk HEC: Failed with status {response.status}: {text}")
                        
            except Exception as e:
                print(f"Splunk HEC: Attempt {attempt + 1} failed: {e}")
                if attempt < self.config.retry_attempts - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        return False
    
    async def health_check(self) -> bool:
        """Check Splunk HEC endpoint."""
        try:
            session = await self._get_session()
            # Use health check endpoint if available, otherwise try main endpoint
            health_endpoint = self.endpoint.replace('/services/collector', '/services/collector/health')
            async with session.get(health_endpoint) as response:
                return response.status in [200, 503]  # 503 may mean HEC is disabled but reachable
        except Exception as e:
            print(f"Splunk health check failed: {e}")
            return False
    
    async def close(self) -> None:
        """Close the session."""
        if self.session and not self.session.closed:
            await self.session.close()


class ElasticsearchExporter(SIEMExporter):
    """
    Elasticsearch exporter.
    
    Sends audit records to Elasticsearch for indexing and searching.
    """
    
    def __init__(self, config: SIEMConfig):
        self.config = config
        self.endpoint = config.endpoint.rstrip('/')
        self.token = os.getenv(config.token_env, "")
        self.index_name = "audit-decisions"
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            headers = {'Content-Type': 'application/json'}
            if self.token:
                headers['Authorization'] = f'Bearer {self.token}'
            
            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.config.timeout_seconds)
            )
        return self.session
    
    async def send(self, record: AuditDecisionRecord) -> bool:
        """Send single record to Elasticsearch."""
        session = await self._get_session()
        
        # Index the document
        url = f"{self.endpoint}/{self.index_name}/_doc/{record.id}"
        doc = record.to_elasticsearch()
        
        try:
            async with session.put(url, json=doc) as response:
                if response.status in [200, 201]:
                    return True
                else:
                    text = await response.text()
                    print(f"Elasticsearch: Failed to index: {text}")
                    return False
        except Exception as e:
            print(f"Elasticsearch: Failed to send: {e}")
            return False
    
    async def send_batch(self, records: List[AuditDecisionRecord]) -> bool:
        """Send batch using Elasticsearch bulk API."""
        if not records:
            return True
        
        session = await self._get_session()
        
        # Format for bulk API
        bulk_data = []
        for record in records:
            # Index action
            bulk_data.append(json.dumps({
                "index": {
                    "_index": self.index_name,
                    "_id": record.id
                }
            }))
            # Document
            bulk_data.append(json.dumps(record.to_elasticsearch()))
        
        payload = "\n".join(bulk_data) + "\n"
        
        url = f"{self.endpoint}/_bulk"
        
        try:
            async with session.post(
                url,
                data=payload,
                headers={'Content-Type': 'application/x-ndjson'}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get('errors'):
                        print(f"Elasticsearch bulk: Some items failed")
                        return False
                    return True
                else:
                    text = await response.text()
                    print(f"Elasticsearch bulk failed: {text}")
                    return False
        except Exception as e:
            print(f"Elasticsearch bulk error: {e}")
            return False
    
    async def health_check(self) -> bool:
        """Check Elasticsearch cluster health."""
        try:
            session = await self._get_session()
            url = f"{self.endpoint}/_cluster/health"
            async with session.get(url) as response:
                return response.status == 200
        except Exception as e:
            print(f"Elasticsearch health check failed: {e}")
            return False
    
    async def close(self) -> None:
        """Close the session."""
        if self.session and not self.session.closed:
            await self.session.close()


class WebhookExporter(SIEMExporter):
    """
    Generic webhook exporter.
    
    Sends audit records to any HTTP endpoint.
    """
    
    def __init__(self, config: SIEMConfig):
        self.config = config
        self.endpoint = config.endpoint
        self.token = os.getenv(config.token_env, "")
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            headers = {'Content-Type': 'application/json'}
            if self.token:
                headers['Authorization'] = f'Bearer {self.token}'
            
            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.config.timeout_seconds)
            )
        return self.session
    
    async def send(self, record: AuditDecisionRecord) -> bool:
        """Send single record to webhook."""
        return await self.send_batch([record])
    
    async def send_batch(self, records: List[AuditDecisionRecord]) -> bool:
        """Send batch to webhook."""
        if not records:
            return True
        
        session = await self._get_session()
        
        payload = {
            'events': [record.to_webhook() for record in records],
            'batch_size': len(records),
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            async with session.post(self.endpoint, json=payload) as response:
                if response.status in [200, 201, 202]:
                    return True
                else:
                    text = await response.text()
                    print(f"Webhook failed: {response.status} - {text}")
                    return False
        except Exception as e:
            print(f"Webhook error: {e}")
            return False
    
    async def health_check(self) -> bool:
        """Check webhook endpoint."""
        try:
            session = await self._get_session()
            async with session.head(self.endpoint) as response:
                return response.status < 500
        except Exception as e:
            print(f"Webhook health check failed: {e}")
            return False
    
    async def close(self) -> None:
        """Close the session."""
        if self.session and not self.session.closed:
            await self.session.close()


class SIEMBatchProcessor:
    """
    Batches audit records and sends them to SIEM periodically.
    
    Improves performance by reducing number of HTTP requests.
    """
    
    def __init__(self, exporter: SIEMExporter, config: SIEMConfig):
        self.exporter = exporter
        self.config = config
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
    
    async def add(self, record: AuditDecisionRecord) -> None:
        """Add a record to the batch queue."""
        self.queue.append(record)
        
        # Flush if batch is full
        if len(self.queue) >= self.config.batch_size:
            await self._flush()
    
    async def _flush(self) -> None:
        """Flush the current batch to SIEM."""
        if not self.queue:
            return
        
        # Get records to send
        batch = []
        while self.queue and len(batch) < self.config.batch_size:
            batch.append(self.queue.popleft())
        
        if batch:
            success = await self.exporter.send_batch(batch)
            if not success:
                # Put failed records back
                for record in reversed(batch):
                    self.queue.appendleft(record)
    
    async def _flush_loop(self) -> None:
        """Periodically flush batches."""
        while self._running:
            try:
                await asyncio.sleep(self.config.flush_interval_seconds)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Flush loop error: {e}")


def create_siem_exporter(config: SIEMConfig) -> Optional[SIEMExporter]:
    """Factory function to create appropriate SIEM exporter."""
    if not config.enabled:
        return None
    
    if not AIOHTTP_AVAILABLE:
        print("Warning: aiohttp not available, SIEM integration disabled")
        print("Install with: pip install aiohttp --break-system-packages")
        return None
    
    if config.type == "splunk":
        return SplunkHECExporter(config)
    elif config.type == "elasticsearch":
        return ElasticsearchExporter(config)
    elif config.type == "webhook":
        return WebhookExporter(config)
    else:
        raise ValueError(f"Unknown SIEM type: {config.type}")
