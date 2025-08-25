"""Dependency injection for MCP Gateway services.

Provides singleton service instances using factory pattern for consistent
service lifecycle management across the application.
"""

# First-Party
from mcpgateway.cache import ResourceCache, SessionRegistry
from mcpgateway.config import settings
from mcpgateway.handlers.sampling import SamplingHandler
from mcpgateway.services.a2a_service import A2AAgentService
from mcpgateway.services.completion_service import CompletionService
from mcpgateway.services.export_service import ExportService
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.import_service import ImportService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.root_service import RootService
from mcpgateway.services.server_service import ServerService
from mcpgateway.services.tag_service import TagService
from mcpgateway.services.tool_service import ToolService
from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper


# Configure CORS with environment-aware origins
cors_origins = list(settings.allowed_origins) if settings.allowed_origins else []

# Singleton instances
_services = {}


def get_completion_service() -> CompletionService:
    """Get singleton completion service.

    Returns:
        CompletionService: Singleton completion service instance
    """
    if "completion" not in _services:
        _services["completion"] = CompletionService()
    return _services["completion"]


def get_gateway_service() -> GatewayService:
    """Get singleton gateway service.

    Returns:
        GatewayService: Singleton gateway service instance
    """
    if "gateway" not in _services:
        _services["gateway"] = GatewayService()
    return _services["gateway"]


def get_logging_service() -> LoggingService:
    """Get singleton logging service.

    Returns:
        LoggingService: Singleton logging service instance
    """
    if "logging" not in _services:
        _services["logging"] = LoggingService()
    return _services["logging"]


def get_prompt_service() -> PromptService:
    """Get singleton prompt service.

    Returns:
        PromptService: Singleton prompt service instance
    """
    if "prompt" not in _services:
        _services["prompt"] = PromptService()
    return _services["prompt"]


def get_resource_service() -> ResourceService:
    """Get singleton resource service.

    Returns:
        ResourceService: Singleton resource service instance
    """
    if "resource" not in _services:
        _services["resource"] = ResourceService()
    return _services["resource"]


def get_root_service() -> RootService:
    """Get singleton root service.

    Returns:
        RootService: Singleton root service instance
    """
    if "root" not in _services:
        _services["root"] = RootService()
    return _services["root"]


def get_server_service() -> ServerService:
    """Get singleton server service.

    Returns:
        ServerService: Singleton server service instance
    """
    if "server" not in _services:
        _services["server"] = ServerService()
    return _services["server"]


def get_tag_service() -> TagService:
    """Get singleton tag service.

    Returns:
        TagService: Singleton tag service instance
    """
    if "tag" not in _services:
        _services["tag"] = TagService()
    return _services["tag"]


def get_tool_service() -> ToolService:
    """Get singleton tool service.

    Returns:
        ToolService: Singleton tool service instance
    """
    if "tool" not in _services:
        _services["tool"] = ToolService()
    return _services["tool"]


def get_sampling_handler() -> SamplingHandler:
    """Get singleton sampling handler.

    Returns:
        SamplingHandler: Singleton sampling handler instance
    """
    if "sampling" not in _services:
        _services["sampling"] = SamplingHandler()
    return _services["sampling"]


def get_resource_cache() -> ResourceCache:
    """Get singleton resource cache.

    Returns:
        ResourceCache: Singleton resource cache instance
    """
    if "resource_cache" not in _services:
        _services["resource_cache"] = ResourceCache(max_size=settings.resource_cache_size, ttl=settings.resource_cache_ttl)
    return _services["resource_cache"]


def get_streamable_http_session() -> SessionManagerWrapper:
    """Get singleton streamable HTTP session.

    Returns:
        SessionManagerWrapper: Singleton streamable HTTP session instance
    """
    if "streamable_http_session" not in _services:
        _services["streamable_http_session"] = SessionManagerWrapper()
    return _services["streamable_http_session"]


def get_a2a_agent_service() -> A2AAgentService:
    """Get singleton A2A agent service.

    Returns:
        A2AAgentService: Singleton A2A agent service instance
    """
    if "a2a_agent" not in _services:
        _services["a2a_agent"] = A2AAgentService()
    return _services["a2a_agent"]


def get_export_service() -> ExportService:
    """Get singleton export service.

    Returns:
        ExportService: Singleton export service instance
    """
    if "export" not in _services:
        _services["export"] = ExportService()
    return _services["export"]


def get_import_service() -> ImportService:
    """Get singleton import service.

    Returns:
        ImportService: Singleton import service instance
    """
    if "import" not in _services:
        _services["import"] = ImportService()
    return _services["import"]


def get_session_registry() -> SessionRegistry:
    """Get singleton session registry.

    Returns:
        SessionRegistry: Singleton session registry instance
    """
    if "session_registry" not in _services:
        _services["session_registry"] = SessionRegistry(
            backend=settings.cache_type,
            redis_url=settings.redis_url if settings.cache_type == "redis" else None,
            database_url=settings.database_url if settings.cache_type == "database" else None,
            session_ttl=settings.session_ttl,
            message_ttl=settings.message_ttl,
        )
    return _services["session_registry"]
