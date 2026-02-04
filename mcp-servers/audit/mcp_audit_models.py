"""
Enhanced audit models for IBM MCP Context Forge.

Aligned with issue #2225 requirements for comprehensive audit logging
with database storage, REST API, and SIEM integration.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
from uuid import uuid4
import json


class DecisionResult(Enum):
    """Policy decision results."""
    ALLOW = "allow"
    DENY = "deny"
    NOT_APPLICABLE = "not_applicable"
    INDETERMINATE = "indeterminate"


class PolicyEngineType(Enum):
    """Types of policy engines."""
    CEDAR = "cedar"
    OPA = "opa"
    MAC = "mac"
    RBAC = "rbac"
    ABAC = "abac"
    NATIVE = "native"


@dataclass
class SubjectDetails:
    """Subject (actor) details in audit record."""
    type: str  # "user", "service", "api_key"
    id: str
    email: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    teams: List[str] = field(default_factory=list)
    clearance_level: Optional[int] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResourceDetails:
    """Resource details in audit record."""
    type: str  # "tool", "database", "document", "api"
    id: str
    server: Optional[str] = None
    classification: Optional[int] = None
    owner: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ContextDetails:
    """Request context details."""
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    mfa_verified: bool = False
    time_of_day: Optional[str] = None
    geo_location: Optional[Dict[str, str]] = None
    session_id: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PolicyMatchDetails:
    """Details of a policy match/evaluation."""
    id: str
    name: str
    engine: str  # PolicyEngineType
    result: str  # "allow" or "deny"
    explanation: str
    conditions_met: List[str] = field(default_factory=list)
    conditions_failed: List[str] = field(default_factory=list)
    evaluation_time_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditDecisionRecord:
    """
    Comprehensive audit record for policy decisions.
    
    Aligned with IBM MCP Context Forge issue #2225 schema:
    https://github.com/IBM/mcp-context-forge/issues/2225
    """
    
    # Core identifiers
    id: str = field(default_factory=lambda: f"decision-{uuid4()}")
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: Optional[str] = None
    gateway_node: Optional[str] = None
    
    # Subject (who)
    subject: Optional[SubjectDetails] = None
    
    # Action (what)
    action: str = ""
    
    # Resource (on what)
    resource: Optional[ResourceDetails] = None
    
    # Decision
    decision: DecisionResult = DecisionResult.INDETERMINATE
    reason: str = ""
    
    # Policy evaluation
    matching_policies: List[PolicyMatchDetails] = field(default_factory=list)
    
    # Context
    context: Optional[ContextDetails] = None
    
    # Performance
    duration_ms: float = 0.0
    
    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary matching GitHub issue schema."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'request_id': self.request_id,
            'gateway_node': self.gateway_node,
            'subject': self.subject.to_dict() if self.subject else None,
            'action': self.action,
            'resource': self.resource.to_dict() if self.resource else None,
            'decision': self.decision.value,
            'reason': self.reason,
            'matching_policies': [p.to_dict() for p in self.matching_policies],
            'context': self.context.to_dict() if self.context else None,
            'duration_ms': self.duration_ms,
            **self.metadata
        }
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)
    
    def to_splunk_hec(self) -> Dict[str, Any]:
        """
        Convert to Splunk HTTP Event Collector format.
        
        Format: {
            "time": epoch_timestamp,
            "host": gateway_node,
            "source": "mcp-policy-engine",
            "sourcetype": "policy_decision",
            "event": {...}
        }
        """
        return {
            'time': int(self.timestamp.timestamp()),
            'host': self.gateway_node or 'unknown',
            'source': 'mcp-policy-engine',
            'sourcetype': 'policy_decision',
            'event': self.to_dict()
        }
    
    def to_elasticsearch(self) -> Dict[str, Any]:
        """
        Convert to Elasticsearch document format.
        
        Adds @timestamp and formats for ES indexing.
        """
        doc = self.to_dict()
        doc['@timestamp'] = self.timestamp.isoformat()
        doc['event_type'] = 'policy_decision'
        return doc
    
    def to_webhook(self) -> Dict[str, Any]:
        """Generic webhook format."""
        return {
            'event_type': 'policy.decision',
            'timestamp': self.timestamp.isoformat(),
            'data': self.to_dict()
        }


@dataclass
class AuditQueryFilter:
    """Query filter for audit records."""
    # Time range
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # Subject filters
    subject_id: Optional[str] = None
    subject_email: Optional[str] = None
    subject_role: Optional[str] = None
    subject_team: Optional[str] = None
    
    # Resource filters
    resource_id: Optional[str] = None
    resource_type: Optional[str] = None
    resource_server: Optional[str] = None
    
    # Decision filters
    decision: Optional[DecisionResult] = None
    action: Optional[str] = None
    
    # Pagination
    limit: int = 100
    offset: int = 0
    
    # Sorting
    sort_by: str = "timestamp"
    sort_order: str = "desc"  # "asc" or "desc"
    
    def to_sql_where(self) -> tuple[str, Dict[str, Any]]:
        """
        Convert to SQL WHERE clause and parameters.
        
        Returns:
            (where_clause, params) tuple
        """
        conditions = []
        params = {}
        
        if self.start_time:
            conditions.append("timestamp >= :start_time")
            params['start_time'] = self.start_time
        
        if self.end_time:
            conditions.append("timestamp <= :end_time")
            params['end_time'] = self.end_time
        
        if self.subject_id:
            conditions.append("subject->>'id' = :subject_id")
            params['subject_id'] = self.subject_id
        
        if self.subject_email:
            conditions.append("subject->>'email' = :subject_email")
            params['subject_email'] = self.subject_email
        
        if self.resource_id:
            conditions.append("resource->>'id' = :resource_id")
            params['resource_id'] = self.resource_id
        
        if self.resource_type:
            conditions.append("resource->>'type' = :resource_type")
            params['resource_type'] = self.resource_type
        
        if self.decision:
            conditions.append("decision = :decision")
            params['decision'] = self.decision.value
        
        if self.action:
            conditions.append("action = :action")
            params['action'] = self.action
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        return where_clause, params


@dataclass
class AuditStatistics:
    """Statistics about audit records."""
    total_decisions: int = 0
    allowed: int = 0
    denied: int = 0
    errors: int = 0
    
    unique_subjects: int = 0
    unique_resources: int = 0
    unique_actions: int = 0
    
    avg_duration_ms: float = 0.0
    
    decisions_by_hour: Dict[int, int] = field(default_factory=dict)
    top_denied_resources: List[Dict[str, Any]] = field(default_factory=list)
    top_denied_subjects: List[Dict[str, Any]] = field(default_factory=list)
    
    time_range_start: Optional[datetime] = None
    time_range_end: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_decisions': self.total_decisions,
            'allowed': self.allowed,
            'denied': self.denied,
            'errors': self.errors,
            'unique_subjects': self.unique_subjects,
            'unique_resources': self.unique_resources,
            'unique_actions': self.unique_actions,
            'avg_duration_ms': self.avg_duration_ms,
            'decisions_by_hour': self.decisions_by_hour,
            'top_denied_resources': self.top_denied_resources,
            'top_denied_subjects': self.top_denied_subjects,
            'time_range': {
                'start': self.time_range_start.isoformat() if self.time_range_start else None,
                'end': self.time_range_end.isoformat() if self.time_range_end else None
            }
        }


@dataclass
class SIEMConfig:
    """SIEM integration configuration."""
    enabled: bool = False
    type: str = "splunk"  # splunk, elasticsearch, webhook
    endpoint: str = ""
    token_env: str = "SIEM_TOKEN"
    batch_size: int = 100
    flush_interval_seconds: int = 5
    timeout_seconds: int = 30
    retry_attempts: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditStorageConfig:
    """Storage configuration for audit records."""
    type: str = "database"  # database, file, both
    retention_days: int = 365
    partition_by: str = "month"  # day, week, month
    compression_enabled: bool = True
    backup_enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditConfig:
    """Complete audit configuration."""
    decisions_enabled: bool = True
    log_allowed: bool = True
    log_denied: bool = True
    include_context: bool = True
    include_explanation: bool = True
    
    storage: AuditStorageConfig = field(default_factory=AuditStorageConfig)
    siem: SIEMConfig = field(default_factory=SIEMConfig)
    
    real_time_enabled: bool = False
    websocket_endpoint: str = "/ws/audit"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'decisions': {
                'enabled': self.decisions_enabled,
                'log_allowed': self.log_allowed,
                'log_denied': self.log_denied,
                'include_context': self.include_context,
                'include_explanation': self.include_explanation
            },
            'storage': self.storage.to_dict(),
            'siem': self.siem.to_dict(),
            'real_time': {
                'enabled': self.real_time_enabled,
                'websocket_endpoint': self.websocket_endpoint
            }
        }
