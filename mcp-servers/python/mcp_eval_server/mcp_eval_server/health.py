# -*- coding: utf-8 -*-
"""Health check HTTP server for MCP Evaluation Server."""

# Standard
import logging
import os
import time
from typing import Optional

# Third-Party
from aiohttp import web, web_request, web_response

# Module-level logger
logger = logging.getLogger(__name__)


class HealthCheckServer:
    """HTTP server for health and readiness probes."""

    def __init__(self, port: int = 8080, host: str = "0.0.0.0"):
        """Initialize health check server.

        Args:
            port: Port to listen on
            host: Host to bind to
        """
        self.port = port
        self.host = host
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None

        # Server state tracking
        self.start_time = time.time()
        self.is_ready = False
        self.judge_tools_ready = False
        self.storage_ready = False
        self.last_health_check = 0.0

        # Setup routes
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Setup HTTP routes for health checks."""
        self.app.router.add_get("/health", self._health_handler)
        self.app.router.add_get("/healthz", self._health_handler)  # Kubernetes style
        self.app.router.add_get("/ready", self._readiness_handler)
        self.app.router.add_get("/readyz", self._readiness_handler)  # Kubernetes style
        self.app.router.add_get("/metrics", self._metrics_handler)
        self.app.router.add_get("/", self._root_handler)

    async def _health_handler(self, _request: web_request.Request) -> web_response.Response:
        """Handle health check requests.

        Health checks indicate if the service is alive and can handle requests.
        This should return 200 if the service is running, regardless of dependencies.

        Args:
            _request: HTTP request object

        Returns:
            HTTP response with health status
        """
        self.last_health_check = time.time()

        uptime = time.time() - self.start_time

        health_data = {
            "status": "healthy",
            "timestamp": time.time(),
            "uptime_seconds": round(uptime, 2),
            "service": "mcp-eval-server",
            "version": "0.1.0",
            "checks": {
                "server_running": True,
                "uptime_ok": uptime > 1.0,  # At least 1 second uptime
            },
        }

        # Add optional environment info
        if os.getenv("ENVIRONMENT"):
            health_data["environment"] = os.getenv("ENVIRONMENT")

        return web.json_response(health_data, status=200)

    async def _readiness_handler(self, _request: web_request.Request) -> web_response.Response:
        """Handle readiness check requests.

        Readiness checks indicate if the service is ready to handle traffic.
        This should check dependencies and return 200 only when fully operational.

        Args:
            _request: HTTP request object

        Returns:
            HTTP response with readiness status
        """
        checks = {
            "server_initialized": self.is_ready,
            "judge_tools_loaded": self.judge_tools_ready,
            "storage_initialized": self.storage_ready,
        }

        # Check if all critical components are ready
        all_ready = all(checks.values())

        readiness_data = {"status": "ready" if all_ready else "not_ready", "timestamp": time.time(), "service": "mcp-eval-server", "version": "0.1.0", "checks": checks}

        # Add details about what's not ready
        if not all_ready:
            not_ready = [check for check, status in checks.items() if not status]
            readiness_data["not_ready_components"] = not_ready
            readiness_data["message"] = f"Service not ready: {', '.join(not_ready)}"

        status_code = 200 if all_ready else 503
        return web.json_response(readiness_data, status=status_code)

    async def _metrics_handler(self, _request: web_request.Request) -> web_response.Response:
        """Handle metrics requests for monitoring.

        Args:
            _request: HTTP request object

        Returns:
            HTTP response with basic metrics
        """
        uptime = time.time() - self.start_time

        metrics_data = {
            "timestamp": time.time(),
            "uptime_seconds": round(uptime, 2),
            "last_health_check": self.last_health_check,
            "checks_since_start": max(0, int((time.time() - self.start_time) / 30)),  # Estimate based on typical 30s checks
            "service_info": {"name": "mcp-eval-server", "version": "0.1.0", "port": self.port, "ready": self.is_ready},
            "component_status": {"judge_tools": self.judge_tools_ready, "storage": self.storage_ready, "health_server": True},
        }

        return web.json_response(metrics_data, status=200)

    async def _root_handler(self, _request: web_request.Request) -> web_response.Response:
        """Handle root requests - provide service info.

        Args:
            _request: HTTP request object

        Returns:
            HTTP response with service information
        """
        info_data = {
            "service": "mcp-eval-server",
            "version": "0.1.0",
            "description": "MCP server for comprehensive agent and prompt evaluation using LLM-as-a-judge techniques",
            "status": "ready" if self.is_ready else "starting",
            "endpoints": {"health": "/health (or /healthz)", "readiness": "/ready (or /readyz)", "metrics": "/metrics", "info": "/"},
            "uptime_seconds": round(time.time() - self.start_time, 2),
        }

        return web.json_response(info_data, status=200)

    async def start(self) -> None:
        """Start the health check HTTP server.

        Raises:
            Exception: If server fails to start
        """
        try:
            logger.info(f"🏥 Starting health check server on {self.host}:{self.port}")

            self.runner = web.AppRunner(self.app, access_log=None)  # Disable access logs to reduce noise
            await self.runner.setup()

            self.site = web.TCPSite(self.runner, self.host, self.port)
            await self.site.start()

            logger.info("✅ Health check server ready:")
            logger.info(f"   • Health: http://{self.host}:{self.port}/health")
            logger.info(f"   • Ready: http://{self.host}:{self.port}/ready")
            logger.info(f"   • Metrics: http://{self.host}:{self.port}/metrics")

        except Exception as e:
            logger.error(f"❌ Failed to start health check server: {e}")
            raise

    async def stop(self) -> None:
        """Stop the health check HTTP server."""
        try:
            if self.site:
                await self.site.stop()
                logger.info("🏥 Health check server stopped")

            if self.runner:
                await self.runner.cleanup()

        except Exception as e:
            logger.error(f"❌ Error stopping health check server: {e}")

    def mark_ready(self) -> None:
        """Mark the server as ready to handle requests."""
        self.is_ready = True
        logger.info("✅ Server marked as ready")

    def mark_judge_tools_ready(self) -> None:
        """Mark judge tools as ready."""
        self.judge_tools_ready = True
        logger.debug("✅ Judge tools marked as ready")

    def mark_storage_ready(self) -> None:
        """Mark storage as ready."""
        self.storage_ready = True
        logger.debug("✅ Storage marked as ready")

    def mark_not_ready(self, reason: str = "") -> None:
        """Mark the server as not ready.

        Args:
            reason: Optional reason for not being ready
        """
        self.is_ready = False
        self.judge_tools_ready = False
        self.storage_ready = False
        logger.warning(f"⚠️  Server marked as not ready: {reason}")


# Global health check server instance
_health_server: Optional[HealthCheckServer] = None


def get_health_server() -> HealthCheckServer:
    """Get the global health check server instance.

    Returns:
        HealthCheckServer instance
    """
    global _health_server  # pylint: disable=global-statement
    if _health_server is None:
        # Get port from environment variable or default to 8080
        port = int(os.getenv("HEALTH_CHECK_PORT", "8080"))
        host = os.getenv("HEALTH_CHECK_HOST", "0.0.0.0")
        _health_server = HealthCheckServer(port=port, host=host)
    return _health_server


async def start_health_server() -> HealthCheckServer:
    """Start the health check server.

    Returns:
        HealthCheckServer instance
    """
    health_server = get_health_server()
    await health_server.start()
    return health_server


async def stop_health_server() -> None:
    """Stop the health check server."""
    global _health_server  # pylint: disable=global-statement
    if _health_server:
        await _health_server.stop()
        _health_server = None


def mark_ready() -> None:
    """Mark the server as ready (convenience function)."""
    get_health_server().mark_ready()


def mark_judge_tools_ready() -> None:
    """Mark judge tools as ready (convenience function)."""
    get_health_server().mark_judge_tools_ready()


def mark_storage_ready() -> None:
    """Mark storage as ready (convenience function)."""
    get_health_server().mark_storage_ready()


def mark_not_ready(reason: str = "") -> None:
    """Mark the server as not ready (convenience function).

    Args:
        reason: Optional reason for not being ready
    """
    get_health_server().mark_not_ready(reason)
