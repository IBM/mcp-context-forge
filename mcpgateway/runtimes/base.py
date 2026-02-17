# -*- coding: utf-8 -*-
"""Base interfaces for runtime backends."""

# Standard
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class RuntimeBackendError(RuntimeError):
    """Runtime backend operation error."""


@dataclass
class RuntimeBackendCapabilities:
    """Capability matrix for a runtime backend."""

    backend: str
    supports_compose: bool = False
    supports_github_build: bool = False
    supports_allowed_hosts: bool = False
    supports_readonly_fs: bool = False
    supports_custom_capabilities: bool = False
    supports_pids_limit: bool = False
    supports_network_egress_toggle: bool = True
    max_cpu: Optional[float] = None
    max_memory_gb: Optional[float] = None
    max_timeout_seconds: Optional[int] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class RuntimeBackendDeployRequest:
    """Backend-neutral deployment request payload."""

    runtime_id: str
    name: str
    source_type: str
    source: Dict[str, Any]
    resources: Dict[str, Any] = field(default_factory=dict)
    environment: Dict[str, str] = field(default_factory=dict)
    guardrails: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeBackendDeployResult:
    """Result of backend deployment."""

    status: str
    runtime_ref: Optional[str] = None
    endpoint_url: Optional[str] = None
    image: Optional[str] = None
    logs: List[str] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    backend_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeBackendStatus:
    """Runtime status in backend."""

    status: str
    endpoint_url: Optional[str] = None
    backend_response: Dict[str, Any] = field(default_factory=dict)


class RuntimeBackend(ABC):
    """Abstract runtime backend."""

    @abstractmethod
    def get_capabilities(self) -> RuntimeBackendCapabilities:
        """Return backend capabilities."""

    @abstractmethod
    async def deploy(self, request: RuntimeBackendDeployRequest) -> RuntimeBackendDeployResult:
        """Deploy runtime on backend.

        Args:
            request: Backend-neutral runtime deployment request.

        Returns:
            RuntimeBackendDeployResult: Backend deployment result.
        """

    @abstractmethod
    async def get_status(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None) -> RuntimeBackendStatus:
        """Get runtime status.

        Args:
            runtime_ref: Backend runtime identifier.
            metadata: Backend-specific runtime metadata.

        Returns:
            RuntimeBackendStatus: Current runtime status.
        """

    @abstractmethod
    async def start(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None) -> RuntimeBackendStatus:
        """Start runtime.

        Args:
            runtime_ref: Backend runtime identifier.
            metadata: Backend-specific runtime metadata.

        Returns:
            RuntimeBackendStatus: Runtime status after start request.
        """

    @abstractmethod
    async def stop(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None) -> RuntimeBackendStatus:
        """Stop runtime.

        Args:
            runtime_ref: Backend runtime identifier.
            metadata: Backend-specific runtime metadata.

        Returns:
            RuntimeBackendStatus: Runtime status after stop request.
        """

    @abstractmethod
    async def delete(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Delete runtime.

        Args:
            runtime_ref: Backend runtime identifier.
            metadata: Backend-specific runtime metadata.
        """

    @abstractmethod
    async def logs(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None, tail: int = 200) -> List[str]:
        """Read runtime logs.

        Args:
            runtime_ref: Backend runtime identifier.
            metadata: Backend-specific runtime metadata.
            tail: Number of log lines requested from the end.

        Returns:
            List[str]: Runtime log lines.
        """
