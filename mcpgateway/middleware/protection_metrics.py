# -*- coding: utf-8 -*-
"""Service that handles Protection metrics.
Location: ./mcpgateway/middleware/protection_metrics.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhavan Kidambi

This module is responsible for sending protection metrics to the destinations.
"""
from typing import Dict, Any, Optional, List
import json
import logging
import asyncio
import aiohttp

# SQL
from sqlalchemy import delete,select,func
from sqlalchemy.orm import Session

# First party
from mcpgateway.db import  SessionLocal,ProtectionMetrics
from mcpgateway.config import  settings
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class ProtectionMetricsService:
    """
    Service for sending protection metrics to db and webhook endpoint.
    """
    _instance = None
    _metrics_queue: List[ProtectionMetrics] = []
    _is_sending = False
    _batch_size = 10
    _send_interval = 5  # seconds

    def __init__(self) : 
        self._metrics_queue = []
        self._is_sending = False
        # Start the background task if metrics are enabled
        if settings.protection_metrics_enabled and settings.protection_alert_webhook:
            asyncio.create_task(self._background_send_metrics())

    async def send_metric(self, metric: ProtectionMetrics) -> bool:
        """
        Queue a metric to be sent to the webhook endpoint.
        
        Args:
            metric: The metric to send
            
        Returns:
            True if the metric was queued successfully, False otherwise
        """
        if not settings.protection_metrics_enabled:
            return False
        
        # Commit the metrics to the db
        await self.send_metric_to_db(metric)

        if settings.protection_alert_webhook :
            await self.send_metric_to_webhook(metric)
            
        return True

    async def send_metric_to_db(self,metric:ProtectionMetrics) :
        db = None
        try :
            db = SessionLocal()
            db.add(metric)
            db.commit()
        finally:
            if db:
             db.close()
    
    async def send_metric_to_webhook(self,metric:ProtectionMetrics):
        # Add the metric to the queue
        self._metrics_queue.append(metric)
        
        # If we have enough metrics, trigger a send
        if len(self._metrics_queue) >= self._batch_size and not self._is_sending:
            asyncio.create_task(self._send_metrics_batch())

    async def _background_send_metrics(self):
        """Background task to periodically send metrics."""
        while True:
            await asyncio.sleep(self._send_interval)
            if self._metrics_queue and not self._is_sending:
                await self._send_metrics_batch()

    async def _send_metrics_batch(self):
        """Send a batch of metrics to the webhook endpoint."""
        if not self._metrics_queue or self._is_sending:
            return
            
        self._is_sending = True
        
        batch = None
        try:
            # Take a batch of metrics from the queue
            batch = self._metrics_queue[:self._batch_size]
            self._metrics_queue = self._metrics_queue[self._batch_size:]
            
            # Convert metrics to JSON
            metrics_json = json.dumps([metric for metric in batch])
            
            # Send metrics to webhook
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    settings.protection_alert_webhook,
                    data=metrics_json,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status >= 400:
                        logging.error(f"Failed to send metrics to webhook: {response.status}")
                        # Put metrics back in the queue
                        self._metrics_queue = batch + self._metrics_queue
                    else:
                        logging.debug(f"Sent {len(batch)} metrics to webhook")
        except Exception as e:
            logging.error(f"Error sending metrics to webhook: {e}")
            # Put metrics back in the queue on error
            if batch:
                self._metrics_queue = batch + self._metrics_queue
        finally:
            self._is_sending = False



    async def record_protection_metric(
        self,
        client_id: str,
        client_ip: Optional[str],
        path: str,
        method: str,
        rate_limit_key: Optional[str] = None,
        metric_type: str = "rate_limit",
        current_usage: Optional[float] = None,
        limit: Optional[int] = None,
        remaining: Optional[int] = None,
        reset_time: Optional[int] = None,
        is_blocked: bool = False
    ) -> bool:
        """
        Record a protection metric.
        
        Args:
            client_id: The client identifier
            client_ip: The client IP address
            path: The request path
            method: The HTTP method
            metric_type: The type of protection metric ("rate_limit", "ddos", etc.)
            rate_limit_key: The rate limit key ("anonymous", "tool", "admin", etc.)
            current_usage: The current usage count (for rate limiting)
            limit: The rate limit (for rate limiting)
            remaining: The remaining requests (for rate limiting)
            reset_time: The reset time (Unix timestamp) (for rate limiting)
            is_blocked: Whether the request was blocked
            headers: The request headers
            user_agent: The user agent
            additional_data: Additional data to include
            
        Returns:
            True if the metric was recorded successfully, False otherwise
        """
        if not settings.protection_metrics_enabled:
            return False
            
        metric = ProtectionMetrics(
            client_id=client_id,
            client_ip=client_ip,
            path=path,
            method=method,
            rate_limit_key=rate_limit_key,
            metric_type=metric_type,
            current_usage=current_usage,
            limit=limit,
            remaining=remaining,
            reset_time=reset_time,
            is_blocked=is_blocked,
            
        )
        
        return await self.send_metric(metric)
    
    async def get_protection_metrics(self, db: Session) -> Dict[str, Any]:
        try :
            total_admin_metrics = db.execute(select(func.count(ProtectionMetrics.id)).where(ProtectionMetrics.rate_limit_key == "admin")).scalar() or 0 
            total_tools_metrics = db.execute(select(func.count(ProtectionMetrics.id)).where(ProtectionMetrics.rate_limit_key == "tools")).scalar() or 0
            total_anon_metrics =  db.execute(select(func.count(ProtectionMetrics.id)).where(ProtectionMetrics.rate_limit_key == "anonymous")).scalar() or 0
            total_warnings = db.execute(select(func.count(ProtectionMetrics.id)).where(ProtectionMetrics.is_blocked.is_(False))).scalar() or 0
            total= db.execute(select(func.count(ProtectionMetrics.id))).scalar() or 0 
            total_others = total - (total_admin_metrics+total_tools_metrics+total_anon_metrics)
            return {"total_admin_metrics":total_admin_metrics,
                    "total_tools_metrics":total_tools_metrics,
                    "total_anon_metrics":total_anon_metrics,
                    "total_others":total_others,
                    "total_warnings":total_warnings}
        except Exception as e:
            logger.error(f"Exception occured during retreiving protection metrics:{e}")
            raise e
    
    async def reset_metrics(self, db: Session):
        try :
            db.execute(delete(ProtectionMetrics))
        except Exception as e:
            logger.error(f"Exception occured during purging protection metrics:{e}")
            raise e

    

