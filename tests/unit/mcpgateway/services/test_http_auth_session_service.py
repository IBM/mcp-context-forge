# -*- coding: utf-8 -*-
"""Unit tests for HttpAuthSessionService.

Location: ./tests/unit/mcpgateway/services/test_http_auth_session_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for HTTP Auth Session Management Service 
Covers session lifecycle, validation, timeouts, limits, and security features.
"""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import uuid

# Third-Party
import pytest

# First-Party
from mcpgateway.db import HttpAuthSession
from mcpgateway.services.http_auth_session_service import (
    HttpAuthSessionService,
    create_http_auth_session,
    REDIS_SESSION_PREFIX,
    USER_AGENT_LOG_MAX_LENGTH,
    sanitize_user_agent,
    sanitize_user_agent_for_logging,
    validate_ip_address,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_db():
    """Mock database session."""
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    db.execute.return_value.scalars.return_value.all.return_value = []
    db.execute.return_value.scalar.return_value = 0
    
    def mock_refresh(obj):
        """Mock refresh that sets an id if not present."""
        if not hasattr(obj, "session_id") or obj.session_id is None:
            obj.session_id = str(uuid.uuid4())
    
    db.refresh.side_effect = mock_refresh
    return db


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    redis.get.return_value = None
    redis.set.return_value = True
    redis.delete.return_value = 1
    redis.expire.return_value = True
    return redis


@pytest.fixture
def mock_audit_service():
    """Mock audit trail service."""
    service = MagicMock()
    service.log_action = MagicMock()
    return service


@pytest.fixture
def session_service(mock_db, mock_audit_service):
    """Create HttpAuthSessionService with mocked dependencies."""
    with patch("mcpgateway.services.http_auth_session_service.AuditTrailService", return_value=mock_audit_service):
        service = HttpAuthSessionService(mock_db)
        service._audit_service = mock_audit_service
        return service


@pytest.fixture
def mock_request():
    """Mock FastAPI request object."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = "192.168.1.100"
    request.headers = {"user-agent": "Mozilla/5.0 Test Browser"}
    return request


@pytest.fixture
def sample_session():
    """Create a sample HttpAuthSession object."""
    now = datetime.now(timezone.utc)
    session = HttpAuthSession(
        session_id=str(uuid.uuid4()),
        user_email="test@example.com",
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0 Test Browser",
        device_info={},
        created_at=now,
        last_activity=now,
    )
    return session


# ============================================================================
# A. Helper Function Tests
# ============================================================================

@pytest.mark.asyncio
async def test_create_http_auth_session_success(mock_db, mock_request):
    """Test successful session creation via helper function."""
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.session_tracking_enabled = True
        mock_settings.cache_type = "memory"
        
        with patch("mcpgateway.services.http_auth_session_service.HttpAuthSessionService") as MockService:
            mock_service_instance = AsyncMock()
            mock_session = MagicMock()
            mock_session.session_id = "test-session-id"
            mock_service_instance.add_session.return_value = mock_session
            MockService.return_value = mock_service_instance
            
            session_id = await create_http_auth_session(
                db=mock_db,
                user_email="test@example.com",
                request=mock_request,
                context="test_login"
            )
            
            assert session_id == "test-session-id"
            mock_service_instance.add_session.assert_called_once_with(
                user_email="test@example.com",
                ip_address="192.168.1.100",
                user_agent="Mozilla/5.0 Test Browser",
                device_info={}
            )


@pytest.mark.asyncio
async def test_create_http_auth_session_tracking_disabled(mock_db, mock_request):
    """Test helper returns None when session tracking is disabled."""
    # Patch settings where it's imported in the service module
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.session_tracking_enabled = False
        
        session_id = await create_http_auth_session(
            db=mock_db,
            user_email="test@example.com",
            request=mock_request
        )
        
        assert session_id is None


@pytest.mark.asyncio
async def test_create_http_auth_session_db_failure(mock_db, mock_request):
    """Test helper raises HTTPException on DB failure."""
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.session_tracking_enabled = True
        mock_settings.cache_type = "memory"
        
        with patch("mcpgateway.services.http_auth_session_service.HttpAuthSessionService") as MockService:
            mock_service_instance = AsyncMock()
            mock_service_instance.add_session.side_effect = Exception("DB connection failed")
            MockService.return_value = mock_service_instance
            
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await create_http_auth_session(
                    db=mock_db,
                    user_email="test@example.com",
                    request=mock_request
                )
            
            assert exc_info.value.status_code == 500
            assert "Session creation failed" in exc_info.value.detail


# ============================================================================
# B. Session Creation Tests
# ============================================================================

@pytest.mark.asyncio
async def test_add_session_success(session_service, mock_db, mock_audit_service):
    """Test successful session creation with DB and audit logging."""
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.max_sessions_per_user = 5
        mock_settings.cache_type = "memory"
        mock_settings.session_idle_timeout_minutes = 30
        mock_settings.session_absolute_timeout_minutes = 1440
        
        with patch.object(session_service, "enforce_limits", new_callable=AsyncMock):
            session = await session_service.add_session(
                user_email="test@example.com",
                ip_address="192.168.1.100",
                user_agent="Mozilla/5.0",
                device_info={"browser": "Firefox"}
            )
            
            assert session is not None
            assert session.user_email == "test@example.com"
            assert session.ip_address == "192.168.1.100"
            mock_db.add.assert_called()
            mock_db.commit.assert_called()
            mock_db.rollback.assert_not_called()  # Verify no rollback on success
            # Verify audit log was called with correct parameters
            assert mock_audit_service.log_action.called
            call_args = mock_audit_service.log_action.call_args
            assert call_args[1]["action"] == "CREATE"
            assert call_args[1]["resource_type"] == "http_auth_session"
            assert call_args[1]["user_email"] == "test@example.com"
            assert "resource_id" in call_args[1]


@pytest.mark.asyncio
async def test_add_session_redis_failure(session_service, mock_db):
    """Test session creation continues when Redis caching fails."""
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.max_sessions_per_user = 0
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.session_absolute_timeout_minutes = 1440
        
        # Need to set _redis_enabled on the service instance
        session_service._redis_enabled = True
        
        with patch("mcpgateway.services.http_auth_session_service.get_redis_client") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.hset.side_effect = Exception("Redis connection failed")
            mock_get_redis.return_value = mock_redis
            
            with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
                session = await session_service.add_session(
                    user_email="test@example.com",
                    ip_address="192.168.1.100",
                    user_agent="Mozilla/5.0"
                )
                
                assert session is not None
                mock_db.add.assert_called()
                mock_db.commit.assert_called()
                # Verify warning was logged
                assert any("Failed to cache session" in str(call) for call in mock_logger.warning.call_args_list)


@pytest.mark.asyncio
async def test_add_session_with_device_info(session_service, mock_db):
    """Test session creation stores device_info correctly."""
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.max_sessions_per_user = 0
        mock_settings.cache_type = "memory"
        
        device_info = {"os": "Windows", "browser": "Chrome", "version": "120"}
        session = await session_service.add_session(
            user_email="test@example.com",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0",
            device_info=device_info
        )
        
        assert session.device_info == device_info


# ============================================================================
# C. Session Retrieval Tests
# ============================================================================

@pytest.mark.asyncio
async def test_get_session_from_redis_cache(session_service, sample_session, mock_db):
    """Test session retrieval from Redis cache (hot path)."""
    session_id = sample_session.session_id
    now = datetime.now(timezone.utc)
    
    # Mock DB to return the session object using query().filter().first() pattern
    mock_db.query.return_value.filter.return_value.first.return_value = sample_session
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.session_idle_timeout_minutes = 30
        mock_settings.session_absolute_timeout_minutes = 1440
        mock_settings.session_bind_to_ip = False
        mock_settings.session_bind_to_user_agent = False
        
        # Need to set _redis_enabled on the service instance
        session_service._redis_enabled = True
        
        with patch("mcpgateway.services.http_auth_session_service.get_redis_client") as mock_get_redis:
            mock_redis = AsyncMock()
            # Mock Redis hgetall() returning session data with timestamps as strings (Redis format)
            import json
            import time
            now_timestamp = time.time()
            session_data = {
                "session_id": sample_session.session_id,
                "user_email": sample_session.user_email,
                "ip_address": sample_session.ip_address,
                "user_agent": sample_session.user_agent,
                "device_info": json.dumps(sample_session.device_info) if sample_session.device_info else "{}",
                "created_at": str(now_timestamp),  # Redis stores as string
                "last_activity": str(now_timestamp),  # Redis stores as string
            }
            mock_redis.hgetall.return_value = session_data  # Use hgetall not get
            mock_get_redis.return_value = mock_redis
            
            with patch("mcpgateway.services.http_auth_session_service.utc_now", return_value=now):
                result = await session_service.get_session(session_id)
                
                assert result is not None
                assert result.session_id == session_id
                assert result.user_email == "test@example.com"
                # Verify Redis was called with correct key format
                mock_redis.hgetall.assert_called_once()
                redis_key_used = mock_redis.hgetall.call_args[0][0]
                assert redis_key_used == f"{REDIS_SESSION_PREFIX}{session_id}"


@pytest.mark.asyncio
async def test_get_session_from_db_fallback(session_service, mock_db, sample_session):
    """Test session retrieval falls back to DB when Redis misses."""
    session_id = sample_session.session_id
    now = datetime.now(timezone.utc)
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.session_idle_timeout_minutes = 30
        mock_settings.session_absolute_timeout_minutes = 1440
        mock_settings.session_bind_to_ip = False
        mock_settings.session_bind_to_user_agent = False
        
        # Need to set _redis_enabled on the service instance
        session_service._redis_enabled = True
        
        with patch("mcpgateway.services.http_auth_session_service.get_redis_client") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.hgetall.return_value = {}  # Redis miss (empty dict)
            mock_get_redis.return_value = mock_redis
            
            # Mock DB query to return session using query().filter().first() pattern
            mock_db.query.return_value.filter.return_value.first.return_value = sample_session
            
            with patch("mcpgateway.services.http_auth_session_service.utc_now", return_value=now):
                result = await session_service.get_session(session_id)
                
                assert result is not None
                assert result.session_id == session_id
                mock_redis.hgetall.assert_called_once()  # Use hgetall not get
                # Verify session was cached to Redis after DB fetch with correct key
                mock_redis.hset.assert_called()
                redis_key_used = mock_redis.hset.call_args[0][0]
                assert redis_key_used == f"{REDIS_SESSION_PREFIX}{session_id}"


@pytest.mark.asyncio
async def test_get_session_not_found(session_service, mock_db):
    """Test get_session returns None when session doesn't exist."""
    session_id = str(uuid.uuid4())
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.cache_type = "memory"
        mock_settings.session_idle_timeout_minutes = 30
        mock_settings.session_absolute_timeout_minutes = 1440
        
        # Mock DB query to return None using query().filter().first() pattern
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        result = await session_service.get_session(session_id)
        
        assert result is None


@pytest.mark.asyncio
async def test_get_session_expired_absolute_timeout(session_service, mock_db):
    """Test get_session returns None for sessions past absolute timeout."""
    # Create session that's 25 hours old (past 24-hour absolute timeout)
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(hours=25)
    
    expired_session = HttpAuthSession(
        session_id=str(uuid.uuid4()),
        user_email="test@example.com",
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0",
        device_info={},
        created_at=old_time,
        last_activity=now - timedelta(minutes=5),  # Recent activity
    )
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.cache_type = "memory"
        mock_settings.session_idle_timeout_minutes = 30
        mock_settings.session_absolute_timeout_minutes = 1440  # 24 hours
        
        # Mock DB query using query().filter().first() pattern
        mock_db.query.return_value.filter.return_value.first.return_value = expired_session
        
        with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
            with patch("mcpgateway.services.http_auth_session_service.utc_now", return_value=now):
                result = await session_service.get_session(expired_session.session_id)
                
                assert result is None
                # Verify expiry logged at DEBUG level
                assert any("expired" in str(call).lower() for call in mock_logger.debug.call_args_list)


@pytest.mark.asyncio
async def test_get_session_expired_idle_timeout(session_service, mock_db):
    """Test get_session returns None for sessions past idle timeout."""
    # Create session with last activity 2 hours ago (past 30-minute idle timeout)
    now = datetime.now(timezone.utc)
    
    expired_session = HttpAuthSession(
        session_id=str(uuid.uuid4()),
        user_email="test@example.com",
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0",
        device_info={},
        created_at=now - timedelta(hours=1),
        last_activity=now - timedelta(hours=2),  # Idle for 2 hours
    )
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.cache_type = "memory"
        mock_settings.session_idle_timeout_minutes = 30
        mock_settings.session_absolute_timeout_minutes = 1440
        
        # Mock DB query using query().filter().first() pattern
        mock_db.query.return_value.filter.return_value.first.return_value = expired_session
        
        with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
            with patch("mcpgateway.services.http_auth_session_service.utc_now", return_value=now):
                result = await session_service.get_session(expired_session.session_id)
                
                assert result is None
                # Verify expiry logged at DEBUG level
                assert any("expired" in str(call).lower() for call in mock_logger.debug.call_args_list)


# ============================================================================
# D. Session Validation Tests
# ============================================================================

@pytest.mark.asyncio
async def test_validate_session_success(session_service, sample_session):
    """Test successful session validation updates activity timestamp."""
    with patch.object(session_service, "get_session", return_value=sample_session):
        with patch.object(session_service, "touch_session", new_callable=AsyncMock) as mock_touch:
            result = await session_service.validate_session(sample_session.session_id)
            
            assert result is True
            mock_touch.assert_called_once_with(sample_session.session_id)


@pytest.mark.asyncio
async def test_validate_session_not_found(session_service):
    """Test validate_session returns False when session doesn't exist."""
    with patch.object(session_service, "get_session", return_value=None):
        result = await session_service.validate_session("nonexistent-session-id")
        
        assert result is False


@pytest.mark.asyncio
async def test_validate_session_binding_ip_mismatch(session_service, mock_db, sample_session):
    """Test session validation fails on IP mismatch when binding enabled."""
    now = datetime.now(timezone.utc)
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.session_bind_to_ip = True
        mock_settings.session_bind_to_user_agent = False
        mock_settings.cache_type = "memory"
        mock_settings.session_idle_timeout_minutes = 30
        mock_settings.session_absolute_timeout_minutes = 1440
        
        # Mock DB query using query().filter().first() pattern
        mock_db.query.return_value.filter.return_value.first.return_value = sample_session
        
        with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
            with patch("mcpgateway.services.http_auth_session_service.utc_now", return_value=now):
                # Request from different IP
                result = await session_service.get_session(
                    sample_session.session_id,
                    client_ip="10.0.0.1",  # Different from sample_session.ip_address
                    user_agent=sample_session.user_agent
                )
                
                assert result is None
                # Verify warning logged for binding failure
                assert any("binding" in str(call).lower() for call in mock_logger.warning.call_args_list)


@pytest.mark.asyncio
async def test_validate_session_binding_user_agent_mismatch(session_service, mock_db, sample_session):
    """Test session validation fails on User-Agent mismatch when binding enabled."""
    now = datetime.now(timezone.utc)
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.session_bind_to_ip = False
        mock_settings.session_bind_to_user_agent = True
        mock_settings.cache_type = "memory"
        mock_settings.session_idle_timeout_minutes = 30
        mock_settings.session_absolute_timeout_minutes = 1440
        
        # Mock DB query using query().filter().first() pattern
        mock_db.query.return_value.filter.return_value.first.return_value = sample_session
        
        with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
            with patch("mcpgateway.services.http_auth_session_service.utc_now", return_value=now):
                # Request from different User-Agent
                result = await session_service.get_session(
                    sample_session.session_id,
                    client_ip=sample_session.ip_address,
                    user_agent="Different Browser/1.0"
                )
                
                assert result is None
                # Verify warning logged for binding failure
                assert any("binding" in str(call).lower() for call in mock_logger.warning.call_args_list)


# Test file continues in next message due to length...

# Made with Bob


# ============================================================================
# E. Session Termination Tests
# ============================================================================

@pytest.mark.asyncio
async def test_terminate_session_success(session_service, mock_db, sample_session, mock_audit_service):
    """Test successful session termination deletes from DB and Redis."""
    session_id = sample_session.session_id
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        
        # Need to set _redis_enabled on the service instance
        session_service._redis_enabled = True
        
        with patch("mcpgateway.services.http_auth_session_service.get_redis_client") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Mock DB query to return session - use query().filter().first() pattern
            mock_db.query.return_value.filter.return_value.first.return_value = sample_session
            
            with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
                await session_service.terminate_session(session_id, reason="user_logout")
                
                mock_db.delete.assert_called_once_with(sample_session)
                mock_db.commit.assert_called()
                mock_redis.delete.assert_called()
                # Verify logged at DEBUG level
                assert any("Terminated session" in str(call) for call in mock_logger.debug.call_args_list)
                # Verify audit log was called
                assert mock_audit_service.log_action.called


@pytest.mark.asyncio
async def test_terminate_session_not_found(session_service, mock_db):
    """Test terminating non-existent session doesn't raise error."""
    session_id = str(uuid.uuid4())
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.cache_type = "memory"
        
        # Mock query to return None
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        # Should not raise exception
        await session_service.terminate_session(session_id, reason="test")
        
        mock_db.delete.assert_not_called()


# ============================================================================
# F. Session Cleanup Tests
# ============================================================================

@pytest.mark.asyncio
async def test_cleanup_expired_sessions_idle_timeout(session_service, mock_db):
    """Test cleanup removes sessions past idle timeout."""
    now = datetime.now(timezone.utc)
    
    # Create expired session (idle for 2 hours)
    expired_session = HttpAuthSession(
        session_id=str(uuid.uuid4()),
        user_email="test@example.com",
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0",
        device_info={},
        created_at=now - timedelta(hours=1),
        last_activity=now - timedelta(hours=2),
    )
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.session_idle_timeout_minutes = 30
        mock_settings.session_absolute_timeout_minutes = 0
        mock_settings.cache_type = "memory"
        
        # Mock the query to return expired sessions
        mock_db.query.return_value.filter.return_value.all.return_value = [expired_session]
        
        with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
            with patch("mcpgateway.services.http_auth_session_service.utc_now", return_value=now):
                deleted_count = await session_service.cleanup_expired_sessions()
                
                assert deleted_count == 1
                mock_db.delete.assert_called_once_with(expired_session)
                mock_db.commit.assert_called()
                # Verify logged at INFO level
                assert any("Cleaned up" in str(call) and "expired" in str(call) for call in mock_logger.info.call_args_list)


@pytest.mark.asyncio
async def test_cleanup_expired_sessions_absolute_timeout(session_service, mock_db):
    """Test cleanup removes sessions past absolute timeout."""
    now = datetime.now(timezone.utc)
    
    # Create expired session (created 25 hours ago)
    expired_session = HttpAuthSession(
        session_id=str(uuid.uuid4()),
        user_email="test@example.com",
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0",
        device_info={},
        created_at=now - timedelta(hours=25),
        last_activity=now - timedelta(minutes=5),  # Recent activity
    )
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.session_idle_timeout_minutes = 0
        mock_settings.session_absolute_timeout_minutes = 1440  # 24 hours
        mock_settings.cache_type = "memory"
        
        # Mock the query to return expired sessions
        mock_db.query.return_value.filter.return_value.all.return_value = [expired_session]
        
        with patch("mcpgateway.services.http_auth_session_service.utc_now", return_value=now):
            deleted_count = await session_service.cleanup_expired_sessions()
            
            assert deleted_count == 1
            mock_db.delete.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_expired_sessions_no_timeouts_enabled(session_service, mock_db):
    """Test cleanup skips when no timeouts are enabled."""
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.session_idle_timeout_minutes = 0
        mock_settings.session_absolute_timeout_minutes = 0
        
        with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
            deleted_count = await session_service.cleanup_expired_sessions()
            
            assert deleted_count == 0
            mock_db.execute.assert_not_called()
            # Verify DEBUG log
            assert any("No timeout settings enabled" in str(call) for call in mock_logger.debug.call_args_list)


# ============================================================================
# G. Session Limit Enforcement Tests
# ============================================================================

@pytest.mark.asyncio
async def test_enforce_limits_under_limit(session_service):
    """Test no eviction when user is under session limit."""
    user_email = "test@example.com"
    
    # Mock 2 existing sessions
    sessions = [
        HttpAuthSession(session_id=str(uuid.uuid4()), user_email=user_email, 
                       ip_address="192.168.1.100", user_agent="Browser1",
                       device_info={}, created_at=datetime.now(timezone.utc),
                       last_activity=datetime.now(timezone.utc)),
        HttpAuthSession(session_id=str(uuid.uuid4()), user_email=user_email,
                       ip_address="192.168.1.101", user_agent="Browser2",
                       device_info={}, created_at=datetime.now(timezone.utc),
                       last_activity=datetime.now(timezone.utc)),
    ]
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.max_sessions_per_user = 5
        
        with patch.object(session_service, "list_user_sessions", return_value=sessions):
            with patch.object(session_service, "terminate_session", new_callable=AsyncMock) as mock_terminate:
                with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
                    await session_service.enforce_limits(user_email)
                    
                    mock_terminate.assert_not_called()
                    # Verify logged at DEBUG level
                    assert any("under limit" in str(call).lower() for call in mock_logger.debug.call_args_list)


@pytest.mark.asyncio
async def test_enforce_limits_at_limit(session_service):
    """Test oldest session evicted when user is at limit."""
    user_email = "test@example.com"
    now = datetime.now(timezone.utc)
    
    # Mock 5 existing sessions (at limit of 5)
    sessions = [
        HttpAuthSession(session_id=f"session-{i}", user_email=user_email,
                       ip_address=f"192.168.1.{i}", user_agent=f"Browser{i}",
                       device_info={}, created_at=now - timedelta(hours=i),
                       last_activity=now - timedelta(hours=i))
        for i in range(5)
    ]
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.max_sessions_per_user = 5
        
        with patch.object(session_service, "list_user_sessions", return_value=sessions):
            with patch.object(session_service, "terminate_session", new_callable=AsyncMock) as mock_terminate:
                with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
                    await session_service.enforce_limits(user_email)
                    
                    # Should evict 1 session (oldest by last_activity)
                    assert mock_terminate.call_count == 1
                    # Verify warning logged for eviction
                    assert any("at/over limit" in str(call).lower() for call in mock_logger.warning.call_args_list)


@pytest.mark.asyncio
async def test_enforce_limits_over_limit(session_service):
    """Test multiple sessions evicted when user is over limit."""
    user_email = "test@example.com"
    now = datetime.now(timezone.utc)
    
    # Mock 6 existing sessions (over limit of 5)
    sessions = [
        HttpAuthSession(session_id=f"session-{i}", user_email=user_email,
                       ip_address=f"192.168.1.{i}", user_agent=f"Browser{i}",
                       device_info={}, created_at=now - timedelta(hours=i),
                       last_activity=now - timedelta(hours=i))
        for i in range(6)
    ]
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.max_sessions_per_user = 5
        
        with patch.object(session_service, "list_user_sessions", return_value=sessions):
            with patch.object(session_service, "terminate_session", new_callable=AsyncMock) as mock_terminate:
                await session_service.enforce_limits(user_email)
                
                # Should evict 2 sessions (6 - 5 + 1 for new session)
                assert mock_terminate.call_count == 2


@pytest.mark.asyncio
async def test_enforce_limits_disabled(session_service):
    """Test no enforcement when session limits are disabled."""
    user_email = "test@example.com"
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.max_sessions_per_user = 0  # Disabled
        
        with patch.object(session_service, "list_user_sessions") as mock_list:
            with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
                await session_service.enforce_limits(user_email)
                
                mock_list.assert_not_called()
                # Verify logged at DEBUG level
                assert any("disabled" in str(call).lower() for call in mock_logger.debug.call_args_list)


# ============================================================================
# H. Logging Level Tests
# ============================================================================

@pytest.mark.asyncio
async def test_logging_levels_routine_operations(session_service, mock_db):
    """Test routine operations logged at DEBUG level."""
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.max_sessions_per_user = 0
        mock_settings.cache_type = "memory"
        
        with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
            # Test session creation
            session = await session_service.add_session(
                user_email="test@example.com",
                ip_address="192.168.1.100",
                user_agent="Mozilla/5.0"
            )
            
            # Verify DEBUG level used, not INFO
            assert any("Created HTTP auth session" in str(call) for call in mock_logger.debug.call_args_list)
            # Verify INFO not called for routine creation
            info_calls = [str(call) for call in mock_logger.info.call_args_list]
            assert not any("Created HTTP auth session" in call for call in info_calls)


@pytest.mark.asyncio
async def test_logging_levels_significant_events(session_service, mock_db):
    """Test significant events logged at INFO level."""
    now = datetime.now(timezone.utc)
    expired_session = HttpAuthSession(
        session_id=str(uuid.uuid4()),
        user_email="test@example.com",
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0",
        device_info={},
        created_at=now - timedelta(hours=2),
        last_activity=now - timedelta(hours=2),
    )
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.session_idle_timeout_minutes = 30
        mock_settings.session_absolute_timeout_minutes = 0
        mock_settings.cache_type = "memory"
        
        # Mock the query to return expired sessions
        mock_db.query.return_value.filter.return_value.all.return_value = [expired_session]
        
        with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
            with patch("mcpgateway.services.http_auth_session_service.utc_now", return_value=now):
                await session_service.cleanup_expired_sessions()
                
                # Verify INFO level used for bulk cleanup
                assert any("Cleaned up" in str(call) and "expired" in str(call) for call in mock_logger.info.call_args_list)


# ============================================================================
# I. Additional Edge Cases
# ============================================================================

@pytest.mark.asyncio
async def test_user_agent_truncation_in_logs(session_service, mock_db):
    """Test user-agent strings are truncated in logs to prevent PII exposure."""
    long_user_agent = "A" * 200  # Longer than USER_AGENT_LOG_MAX_LENGTH
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.max_sessions_per_user = 0
        mock_settings.cache_type = "memory"
        
        session = await session_service.add_session(
            user_email="test@example.com",
            ip_address="192.168.1.100",
            user_agent=long_user_agent
        )
        
        # Session should store full user-agent
        assert session.user_agent == long_user_agent


@pytest.mark.asyncio
async def test_context_manager_cleanup(mock_db):
    """Test service properly cleans up DB session when used as context manager."""
    with patch("mcpgateway.services.http_auth_session_service.AuditTrailService"):
        with HttpAuthSessionService() as service:
            assert service.db is not None
            assert service._owns_db is True
        
        # After context exit, DB should be closed
        # (We can't directly test this without mocking SessionLocal)

@pytest.mark.asyncio
async def test_touch_session_success(session_service, mock_db, sample_session):
    """Test touch_session updates last_activity timestamp."""
    session_id = sample_session.session_id
    now = datetime.now(timezone.utc)
    
    # Set last_activity to old time to bypass throttling
    sample_session.last_activity = now - timedelta(hours=2)
    
    session_service._redis_enabled = True
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.cache_type = "memory"
        mock_settings.session_activity_update_interval_seconds = 60
        
        # Mock DB query to return session
        mock_db.query.return_value.filter.return_value.first.return_value = sample_session
        
        with patch("mcpgateway.services.http_auth_session_service.utc_now", return_value=now):
            result = await session_service.touch_session(session_id)
            
            # Verify last_activity was updated
            assert result is True
            assert sample_session.last_activity == now
            mock_db.commit.assert_called()


@pytest.mark.asyncio
async def test_touch_session_not_found(session_service, mock_db):
    """Test touch_session handles non-existent session gracefully."""
    session_id = str(uuid.uuid4())
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.cache_type = "memory"
        
        # Mock DB query to return None
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        # Should not raise exception
        await session_service.touch_session(session_id)
        mock_db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_touch_session_with_redis(session_service, mock_db, sample_session):
    """Test touch_session updates Redis cache."""
    session_id = sample_session.session_id
    now = datetime.now(timezone.utc)
    
    # Set last_activity to old time to bypass throttling
    sample_session.last_activity = now - timedelta(hours=2)
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.session_activity_update_interval_seconds = 60
        
        session_service._redis_enabled = True
        
        with patch("mcpgateway.services.http_auth_session_service.get_redis_client") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Mock DB query
            mock_db.query.return_value.filter.return_value.first.return_value = sample_session
            
            # Mock _update_session_activity_in_redis
            with patch.object(session_service, "_update_session_activity_in_redis", new_callable=AsyncMock) as mock_update_redis:
                with patch("mcpgateway.services.http_auth_session_service.utc_now", return_value=now):
                    result = await session_service.touch_session(session_id)
                    
                    # Verify Redis update was called
                    assert result is True
                    mock_update_redis.assert_called_once_with(session_id)


@pytest.mark.asyncio
async def test_list_user_sessions_success(session_service, mock_db):
    """Test listing sessions for a specific user."""
    user_email = "test@example.com"
    now = datetime.now(timezone.utc)
    
    sessions = [
        HttpAuthSession(
            session_id=str(uuid.uuid4()),
            user_email=user_email,
            ip_address="192.168.1.100",
            user_agent="Browser1",
            device_info={},
            created_at=now,
            last_activity=now,
        ),
        HttpAuthSession(
            session_id=str(uuid.uuid4()),
            user_email=user_email,
            ip_address="192.168.1.101",
            user_agent="Browser2",
            device_info={},
            created_at=now,
            last_activity=now,
        ),
    ]
    
    # Mock DB query
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = sessions
    
    result = await session_service.list_user_sessions(user_email)
    
    assert len(result) == 2
    assert all(s.user_email == user_email for s in result)


@pytest.mark.asyncio
async def test_get_redis_client_disabled(session_service):
    """Test _get_redis_client returns None when Redis is disabled."""
    session_service._redis_enabled = False
    
    result = await session_service._get_redis_client()
    
    assert result is None


@pytest.mark.asyncio
async def test_get_redis_client_connection_failure(session_service):
    """Test _get_redis_client handles connection failures gracefully."""
    session_service._redis_enabled = True
    
    with patch("mcpgateway.services.http_auth_session_service.get_redis_client") as mock_get_redis:
        mock_get_redis.side_effect = Exception("Connection refused")
        
        with patch("mcpgateway.services.http_auth_session_service.logger") as mock_logger:
            result = await session_service._get_redis_client()
            
            assert result is None
            assert any("Failed to get Redis client" in str(call) for call in mock_logger.warning.call_args_list)


@pytest.mark.asyncio
async def test_cleanup_expired_sessions_both_timeouts(session_service, mock_db):
    """Test cleanup with both idle and absolute timeouts enabled."""
    now = datetime.now(timezone.utc)
    
    # Create sessions that violate different timeout rules
    idle_expired = HttpAuthSession(
        session_id=str(uuid.uuid4()),
        user_email="idle@example.com",
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0",
        device_info={},
        created_at=now - timedelta(hours=1),
        last_activity=now - timedelta(hours=2),  # Idle timeout
    )
    
    absolute_expired = HttpAuthSession(
        session_id=str(uuid.uuid4()),
        user_email="absolute@example.com",
        ip_address="192.168.1.101",
        user_agent="Mozilla/5.0",
        device_info={},
        created_at=now - timedelta(hours=25),  # Absolute timeout
        last_activity=now - timedelta(minutes=5),
    )
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.session_idle_timeout_minutes = 30
        mock_settings.session_absolute_timeout_minutes = 1440
        mock_settings.cache_type = "memory"
        
        # Mock query to return both expired sessions
        mock_db.query.return_value.filter.return_value.all.return_value = [idle_expired, absolute_expired]
        
        with patch("mcpgateway.services.http_auth_session_service.utc_now", return_value=now):
            deleted_count = await session_service.cleanup_expired_sessions()
            
            assert deleted_count == 2
            assert mock_db.delete.call_count == 2


@pytest.mark.asyncio
async def test_add_session_db_error_propagates(session_service, mock_db):
    """Test session creation propagates database errors without catching them."""
    session_service._redis_enabled = False  # Disable Redis to simplify test
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.max_sessions_per_user = 0
        mock_settings.cache_type = "memory"
        mock_settings.session_bind_to_ip = False
        mock_settings.session_bind_to_user_agent = False
        
        # Mock the add operation to succeed but commit to fail
        mock_db.add = MagicMock()
        mock_db.commit.side_effect = Exception("Database error")
        
        # Exception should propagate without being caught
        with pytest.raises(Exception, match="Database error"):
            await session_service.add_session(
                user_email="test@example.com",
                ip_address="192.168.1.100",
                user_agent="Mozilla/5.0"
            )
        
        # The service doesn't handle rollback - that's the caller's responsibility
        # Just verify the exception propagated


@pytest.mark.asyncio
async def test_terminate_session_with_user_email(session_service, mock_db, sample_session):
    """Test terminating session removes from user's Redis set."""
    session_id = sample_session.session_id
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        
        session_service._redis_enabled = True
        
        with patch("mcpgateway.services.http_auth_session_service.get_redis_client") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            # Mock DB query
            mock_db.query.return_value.filter.return_value.first.return_value = sample_session
            
            await session_service.terminate_session(session_id, reason="test")
            
            # Verify Redis operations
            mock_redis.delete.assert_called()
            mock_redis.srem.assert_called()


@pytest.mark.asyncio
async def test_get_session_redis_deserialization_error(session_service, mock_db, sample_session):
    """Test get_session handles Redis deserialization errors."""
    session_id = sample_session.session_id
    now = datetime.now(timezone.utc)
    
    # Ensure sample_session has valid timestamps
    sample_session.created_at = now - timedelta(hours=1)
    sample_session.last_activity = now - timedelta(minutes=5)
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.cache_type = "redis"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.session_idle_timeout_minutes = 30
        mock_settings.session_absolute_timeout_minutes = 1440
        mock_settings.session_bind_to_ip = False
        mock_settings.session_bind_to_user_agent = False
        
        session_service._redis_enabled = True
        
        # Mock _get_session_from_redis to return None (simulating deserialization error)
        with patch.object(session_service, "_get_session_from_redis", new_callable=AsyncMock, return_value=None):
            # Mock DB fallback
            mock_db.query.return_value.filter.return_value.first.return_value = sample_session
            
            with patch("mcpgateway.services.http_auth_session_service.utc_now", return_value=now):
                result = await session_service.get_session(session_id)
                
                # Should fall back to DB
                assert result is not None
                assert result.session_id == session_id


@pytest.mark.asyncio
async def test_enforce_limits_evicts_oldest_sessions(session_service):
    """Test enforce_limits evicts sessions by last_activity (oldest first)."""
    user_email = "test@example.com"
    now = datetime.now(timezone.utc)
    
    # Create sessions with different last_activity times
    sessions = [
        HttpAuthSession(
            session_id=f"session-{i}",
            user_email=user_email,
            ip_address=f"192.168.1.{i}",
            user_agent=f"Browser{i}",
            device_info={},
            created_at=now - timedelta(hours=5-i),  # Newer created_at
            last_activity=now - timedelta(hours=i),  # Older last_activity = should be evicted first
        )
        for i in range(6)
    ]
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.max_sessions_per_user = 5
        
        with patch.object(session_service, "list_user_sessions", return_value=sessions):
            with patch.object(session_service, "terminate_session", new_callable=AsyncMock) as mock_terminate:
                await session_service.enforce_limits(user_email)
                
                # Should evict 2 sessions (6 current - 5 limit + 1 for new session)
                assert mock_terminate.call_count == 2
                # Verify oldest sessions by last_activity were terminated
                terminated_ids = [call[0][0] for call in mock_terminate.call_args_list]
                # Sessions 5 and 4 have oldest last_activity
                assert "session-5" in terminated_ids
                assert "session-4" in terminated_ids


@pytest.mark.asyncio
async def test_create_http_auth_session_no_client(mock_db):
    """Test session creation handles missing client info."""
    request = MagicMock()
    request.client = None
    request.headers = {}
    
    with patch("mcpgateway.services.http_auth_session_service.settings") as mock_settings:
        mock_settings.session_tracking_enabled = True
        mock_settings.cache_type = "memory"
        
        with patch("mcpgateway.services.http_auth_session_service.HttpAuthSessionService") as MockService:
            mock_service_instance = AsyncMock()
            mock_session = MagicMock()
            mock_session.session_id = "test-session-id"
            mock_service_instance.add_session.return_value = mock_session
            MockService.return_value = mock_service_instance
            
            session_id = await create_http_auth_session(
                db=mock_db,
                user_email="test@example.com",
                request=request,
            )
            
            assert session_id == "test-session-id"
            # Verify it was called with "unknown" for missing client info
            call_args = mock_service_instance.add_session.call_args
            assert call_args[1]["ip_address"] == "unknown"
            assert call_args[1]["user_agent"] == "unknown"


def test_sanitize_user_agent_empty():
    """Test sanitize_user_agent with empty string."""
    result = sanitize_user_agent("")
    assert result == "unknown"


def test_sanitize_user_agent_none():
    """Test sanitize_user_agent with None."""
    result = sanitize_user_agent(None)
    assert result == "unknown"


def test_sanitize_user_agent_for_logging_none():
    """Test sanitize_user_agent_for_logging with None."""
    result = sanitize_user_agent_for_logging(None)
    assert result is None


def test_validate_ip_address_empty():
    """Test validate_ip_address with empty string."""
    result = validate_ip_address("")
    assert result == "unknown"


def test_validate_ip_address_none():
    """Test validate_ip_address with None."""
    result = validate_ip_address(None)
    assert result == "unknown"
