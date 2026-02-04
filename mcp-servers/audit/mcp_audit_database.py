"""
Database storage layer for audit records.

Provides PostgreSQL/SQLite storage with partitioning, retention, and querying.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, AsyncIterator, Dict, Any
from datetime import datetime, timedelta, timezone
import asyncio
import json
import sqlite3
from pathlib import Path

from mcp_audit_models import (
    AuditDecisionRecord,
    AuditQueryFilter,
    AuditStatistics,
    DecisionResult
)


class AuditDatabase(ABC):
    """Abstract base class for audit database implementations."""
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize database schema."""
        pass
    
    @abstractmethod
    async def store_decision(self, record: AuditDecisionRecord) -> None:
        """Store a decision record."""
        pass
    
    @abstractmethod
    async def query_decisions(
        self,
        filter: AuditQueryFilter
    ) -> List[AuditDecisionRecord]:
        """Query decision records."""
        pass
    
    @abstractmethod
    async def get_statistics(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> AuditStatistics:
        """Get audit statistics."""
        pass
    
    @abstractmethod
    async def delete_old_records(self, older_than_days: int) -> int:
        """Delete records older than specified days."""
        pass


class SQLiteAuditDatabase(AuditDatabase):
    """
    SQLite implementation of audit database.
    
    Suitable for development and small deployments.
    """
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
    
    async def initialize(self) -> None:
        """Initialize SQLite database with schema."""
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        
        # Create main audit_decisions table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_decisions (
                id TEXT PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                request_id TEXT,
                gateway_node TEXT,
                
                subject_id TEXT,
                subject_email TEXT,
                subject_type TEXT,
                subject_data JSON,
                
                action TEXT NOT NULL,
                
                resource_id TEXT,
                resource_type TEXT,
                resource_server TEXT,
                resource_data JSON,
                
                decision TEXT NOT NULL,
                reason TEXT,
                
                matching_policies JSON,
                context_data JSON,
                
                duration_ms REAL,
                metadata JSON,
                
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes for common queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp 
            ON audit_decisions(timestamp DESC)
        """)
        
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_subject_id 
            ON audit_decisions(subject_id)
        """)
        
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_resource_id 
            ON audit_decisions(resource_id)
        """)
        
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_decision 
            ON audit_decisions(decision)
        """)
        
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_action 
            ON audit_decisions(action)
        """)
        
        self.conn.commit()
    
    async def store_decision(self, record: AuditDecisionRecord) -> None:
        """Store a decision record in SQLite."""
        if not self.conn:
            await self.initialize()
        
        self.conn.execute("""
            INSERT INTO audit_decisions (
                id, timestamp, request_id, gateway_node,
                subject_id, subject_email, subject_type, subject_data,
                action,
                resource_id, resource_type, resource_server, resource_data,
                decision, reason,
                matching_policies, context_data,
                duration_ms, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.id,
            record.timestamp,
            record.request_id,
            record.gateway_node,
            record.subject.id if record.subject else None,
            record.subject.email if record.subject else None,
            record.subject.type if record.subject else None,
            json.dumps(record.subject.to_dict()) if record.subject else None,
            record.action,
            record.resource.id if record.resource else None,
            record.resource.type if record.resource else None,
            record.resource.server if record.resource else None,
            json.dumps(record.resource.to_dict()) if record.resource else None,
            record.decision.value,
            record.reason,
            json.dumps([p.to_dict() for p in record.matching_policies]),
            json.dumps(record.context.to_dict()) if record.context else None,
            record.duration_ms,
            json.dumps(record.metadata)
        ))
        self.conn.commit()
    
    async def query_decisions(
        self,
        filter: AuditQueryFilter
    ) -> List[AuditDecisionRecord]:
        """Query decisions with filters."""
        if not self.conn:
            await self.initialize()
        
        where_parts = []
        params = []
        
        if filter.start_time:
            where_parts.append("timestamp >= ?")
            params.append(filter.start_time)
        
        if filter.end_time:
            where_parts.append("timestamp <= ?")
            params.append(filter.end_time)
        
        if filter.subject_id:
            where_parts.append("subject_id = ?")
            params.append(filter.subject_id)
        
        if filter.subject_email:
            where_parts.append("subject_email = ?")
            params.append(filter.subject_email)
        
        if filter.resource_id:
            where_parts.append("resource_id = ?")
            params.append(filter.resource_id)
        
        if filter.resource_type:
            where_parts.append("resource_type = ?")
            params.append(filter.resource_type)
        
        if filter.decision:
            where_parts.append("decision = ?")
            params.append(filter.decision.value)
        
        if filter.action:
            where_parts.append("action = ?")
            params.append(filter.action)
        
        where_clause = " AND ".join(where_parts) if where_parts else "1=1"
        
        query = f"""
            SELECT * FROM audit_decisions
            WHERE {where_clause}
            ORDER BY {filter.sort_by} {filter.sort_order}
            LIMIT ? OFFSET ?
        """
        params.extend([filter.limit, filter.offset])
        
        cursor = self.conn.execute(query, params)
        rows = cursor.fetchall()
        
        records = []
        for row in rows:
            records.append(self._row_to_record(row))
        
        return records
    
    def _row_to_record(self, row: sqlite3.Row) -> AuditDecisionRecord:
        """Convert database row to AuditDecisionRecord."""
        from mcp_audit_models import SubjectDetails, ResourceDetails, ContextDetails, PolicyMatchDetails
        
        # Parse JSON fields
        subject_data = json.loads(row['subject_data']) if row['subject_data'] else None
        resource_data = json.loads(row['resource_data']) if row['resource_data'] else None
        context_data = json.loads(row['context_data']) if row['context_data'] else None
        matching_policies_data = json.loads(row['matching_policies']) if row['matching_policies'] else []
        
        return AuditDecisionRecord(
            id=row['id'],
            timestamp=datetime.fromisoformat(row['timestamp']) if isinstance(row['timestamp'], str) else row['timestamp'],
            request_id=row['request_id'],
            gateway_node=row['gateway_node'],
            subject=SubjectDetails(**subject_data) if subject_data else None,
            resource=ResourceDetails(**resource_data) if resource_data else None,
            action=row['action'],
            decision=DecisionResult(row['decision']),
            reason=row['reason'] or "",
            matching_policies=[PolicyMatchDetails(**p) for p in matching_policies_data],
            context=ContextDetails(**context_data) if context_data else None,
            duration_ms=row['duration_ms'] or 0.0,
            metadata=json.loads(row['metadata']) if row['metadata'] else {}
        )
    
    async def get_statistics(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> AuditStatistics:
        """Calculate statistics from audit records."""
        if not self.conn:
            await self.initialize()
        
        where_parts = []
        params = []
        
        if start_time:
            where_parts.append("timestamp >= ?")
            params.append(start_time)
        
        if end_time:
            where_parts.append("timestamp <= ?")
            params.append(end_time)
        
        where_clause = " AND ".join(where_parts) if where_parts else "1=1"
        
        stats = AuditStatistics()
        
        # Total counts by decision
        cursor = self.conn.execute(f"""
            SELECT decision, COUNT(*) as count
            FROM audit_decisions
            WHERE {where_clause}
            GROUP BY decision
        """, params)
        
        for row in cursor:
            stats.total_decisions += row['count']
            if row['decision'] == 'allow':
                stats.allowed = row['count']
            elif row['decision'] == 'deny':
                stats.denied = row['count']
            else:
                stats.errors += row['count']
        
        # Unique subjects
        cursor = self.conn.execute(f"""
            SELECT COUNT(DISTINCT subject_id) as count
            FROM audit_decisions
            WHERE {where_clause}
        """, params)
        stats.unique_subjects = cursor.fetchone()['count']
        
        # Unique resources
        cursor = self.conn.execute(f"""
            SELECT COUNT(DISTINCT resource_id) as count
            FROM audit_decisions
            WHERE {where_clause}
        """, params)
        stats.unique_resources = cursor.fetchone()['count']
        
        # Average duration
        cursor = self.conn.execute(f"""
            SELECT AVG(duration_ms) as avg_duration
            FROM audit_decisions
            WHERE {where_clause}
        """, params)
        result = cursor.fetchone()
        stats.avg_duration_ms = result['avg_duration'] or 0.0
        
        # Top denied resources
        cursor = self.conn.execute(f"""
            SELECT resource_id, resource_type, COUNT(*) as count
            FROM audit_decisions
            WHERE {where_clause} AND decision = 'deny'
            GROUP BY resource_id, resource_type
            ORDER BY count DESC
            LIMIT 10
        """, params)
        
        stats.top_denied_resources = [
            {'resource_id': row['resource_id'], 'resource_type': row['resource_type'], 'count': row['count']}
            for row in cursor
        ]
        
        # Time range
        if stats.total_decisions > 0:
            cursor = self.conn.execute(f"""
                SELECT MIN(timestamp) as min_time, MAX(timestamp) as max_time
                FROM audit_decisions
                WHERE {where_clause}
            """, params)
            row = cursor.fetchone()
            if row['min_time']:
                stats.time_range_start = datetime.fromisoformat(row['min_time']) if isinstance(row['min_time'], str) else row['min_time']
            if row['max_time']:
                stats.time_range_end = datetime.fromisoformat(row['max_time']) if isinstance(row['max_time'], str) else row['max_time']
        
        return stats
    
    async def delete_old_records(self, older_than_days: int) -> int:
        """Delete records older than specified days."""
        if not self.conn:
            await self.initialize()
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        
        cursor = self.conn.execute("""
            DELETE FROM audit_decisions
            WHERE timestamp < ?
        """, (cutoff_date,))
        
        deleted_count = cursor.rowcount
        self.conn.commit()
        
        return deleted_count
    
    async def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None


class AuditDatabasePool:
    """Connection pool manager for audit database."""
    
    def __init__(self, database: AuditDatabase):
        self.database = database
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize database."""
        if not self._initialized:
            await self.database.initialize()
            self._initialized = True
    
    async def store_decision(self, record: AuditDecisionRecord) -> None:
        """Store a decision."""
        await self.initialize()
        await self.database.store_decision(record)
    
    async def query_decisions(
        self,
        filter: AuditQueryFilter
    ) -> List[AuditDecisionRecord]:
        """Query decisions."""
        await self.initialize()
        return await self.database.query_decisions(filter)
    
    async def get_statistics(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> AuditStatistics:
        """Get statistics."""
        await self.initialize()
        return await self.database.get_statistics(start_time, end_time)
