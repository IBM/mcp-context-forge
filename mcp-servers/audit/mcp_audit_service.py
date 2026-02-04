"""
Main audit service for IBM MCP Context Forge.

Combines database storage, SIEM integration, and decision logging.
"""

from typing import Optional
from pathlib import Path
from datetime import datetime
import asyncio

from mcp_audit_models import (
    AuditDecisionRecord,
    AuditConfig,
    SubjectDetails,
    ResourceDetails,
    ContextDetails,
    PolicyMatchDetails,
    DecisionResult
)
from mcp_audit_database import SQLiteAuditDatabase, AuditDatabasePool
from mcp_audit_siem import create_siem_exporter, SIEMBatchProcessor


class AuditService:
    """
    Main audit service for policy decision logging.
    
    Features:
    - Database storage with querying
    - SIEM integration (Splunk, Elasticsearch, Webhook)
    - Batch processing for performance
    - Configurable retention policies
    """
    
    def __init__(
        self,
        config: AuditConfig,
        db_path: Optional[Path] = None
    ):
        self.config = config
        
        # Initialize database
        if db_path is None:
            db_path = Path("./audit.db")
        self.database = SQLiteAuditDatabase(db_path)
        self.db_pool = AuditDatabasePool(self.database)
        
        # Initialize SIEM if enabled
        self.siem_exporter = None
        self.siem_processor = None
        if config.siem.enabled:
            self.siem_exporter = create_siem_exporter(config.siem)
            if self.siem_exporter:
                self.siem_processor = SIEMBatchProcessor(
                    self.siem_exporter,
                    config.siem
                )
    
    async def start(self) -> None:
        """Start the audit service."""
        # Initialize database
        await self.db_pool.initialize()
        
        # Start SIEM processor if enabled
        if self.siem_processor:
            await self.siem_processor.start()
    
    async def stop(self) -> None:
        """Stop the audit service and flush pending records."""
        # Stop SIEM processor
        if self.siem_processor:
            await self.siem_processor.stop()
        
        # Close SIEM exporter
        if self.siem_exporter and hasattr(self.siem_exporter, 'close'):
            await self.siem_exporter.close()
    
    async def log_decision(
        self,
        decision: DecisionResult,
        action: str,
        subject: SubjectDetails,
        resource: ResourceDetails,
        reason: str = "",
        matching_policies: Optional[list] = None,
        context: Optional[ContextDetails] = None,
        request_id: Optional[str] = None,
        gateway_node: Optional[str] = None,
        duration_ms: float = 0.0
    ) -> AuditDecisionRecord:
        """
        Log a policy decision.
        
        Args:
            decision: The decision result (allow/deny)
            action: The action attempted
            subject: Subject details (who)
            resource: Resource details (what)
            reason: Explanation of the decision
            matching_policies: List of policies that were evaluated
            context: Request context
            request_id: Correlation ID for the request
            gateway_node: Which gateway processed the request
            duration_ms: How long the decision took
        
        Returns:
            The created audit record
        """
        
        # Check if we should log this decision
        if not self.config.decisions_enabled:
            return None
        
        if decision == DecisionResult.ALLOW and not self.config.log_allowed:
            return None
        
        if decision == DecisionResult.DENY and not self.config.log_denied:
            return None
        
        # Create audit record
        record = AuditDecisionRecord(
            timestamp=datetime.now(),
            request_id=request_id,
            gateway_node=gateway_node,
            subject=subject if self.config.include_context else SubjectDetails(type=subject.type, id=subject.id),
            action=action,
            resource=resource if self.config.include_context else ResourceDetails(type=resource.type, id=resource.id),
            decision=decision,
            reason=reason if self.config.include_explanation else "",
            matching_policies=matching_policies or [],
            context=context if self.config.include_context else None,
            duration_ms=duration_ms
        )
        
        # Store in database
        if self.config.storage.type in ["database", "both"]:
            await self.db_pool.store_decision(record)
        
        # Send to SIEM
        if self.siem_processor:
            await self.siem_processor.add(record)
        
        return record
    
    def get_db_pool(self) -> AuditDatabasePool:
        """Get the database pool for direct querying."""
        return self.db_pool


class PolicyDecisionLogger:
    """
    Simple wrapper for logging policy decisions.
    
    Use this in your policy engine to log every access decision.
    """
    
    def __init__(self, audit_service: AuditService):
        self.audit_service = audit_service
    
    async def log_allow(
        self,
        action: str,
        subject: SubjectDetails,
        resource: ResourceDetails,
        policies: list,
        context: Optional[ContextDetails] = None,
        **kwargs
    ) -> None:
        """Log an allowed access decision."""
        await self.audit_service.log_decision(
            decision=DecisionResult.ALLOW,
            action=action,
            subject=subject,
            resource=resource,
            reason="Access granted by policy",
            matching_policies=policies,
            context=context,
            **kwargs
        )
    
    async def log_deny(
        self,
        action: str,
        subject: SubjectDetails,
        resource: ResourceDetails,
        reason: str,
        policies: list,
        context: Optional[ContextDetails] = None,
        **kwargs
    ) -> None:
        """Log a denied access decision."""
        await self.audit_service.log_decision(
            decision=DecisionResult.DENY,
            action=action,
            subject=subject,
            resource=resource,
            reason=reason,
            matching_policies=policies,
            context=context,
            **kwargs
        )


# Factory function for easy setup
def create_audit_service(
    db_path: Optional[Path] = None,
    enable_siem: bool = False,
    siem_type: str = "splunk",
    siem_endpoint: str = "",
    siem_token_env: str = "SIEM_TOKEN"
) -> AuditService:
    """
    Create an audit service with default configuration.
    
    Args:
        db_path: Path to SQLite database file
        enable_siem: Whether to enable SIEM integration
        siem_type: Type of SIEM (splunk, elasticsearch, webhook)
        siem_endpoint: SIEM endpoint URL
        siem_token_env: Environment variable name for SIEM token
    
    Returns:
        Configured AuditService instance
    """
    from mcp_audit_models import AuditConfig, SIEMConfig, AuditStorageConfig
    
    config = AuditConfig(
        decisions_enabled=True,
        log_allowed=True,
        log_denied=True,
        include_context=True,
        include_explanation=True,
        storage=AuditStorageConfig(
            type="database",
            retention_days=365
        ),
        siem=SIEMConfig(
            enabled=enable_siem,
            type=siem_type,
            endpoint=siem_endpoint,
            token_env=siem_token_env
        )
    )
    
    return AuditService(config, db_path)
