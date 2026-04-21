# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_token_blocklist_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for Token Blocklist Service.

Tests cover:
- Token revocation
- Revocation checking
- Idle timeout enforcement
- Activity tracking
- Automatic cleanup
- Statistics gathering
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import uuid

# Third-Party
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.db import Base, TokenRevocation, EmailUser, utc_now
from mcpgateway.services.token_blocklist_service import TokenBlocklistService, get_token_blocklist_service


@pytest.fixture
def test_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    # Create test user
    test_user = EmailUser(
        email="test@example.com",
        password_hash="test_hash",
        full_name="Test User",
        is_admin=False,
        is_active=True,
        auth_provider="local"
    )
    db.add(test_user)
    db.commit()
    
    yield db
    
    db.close()
    engine.dispose()


@pytest.fixture
def blocklist_service(test_db):
    """Create blocklist service with test database."""
    return TokenBlocklistService(db=test_db)


class TestTokenRevocation:
    """Tests for token revocation functionality."""
    
    def test_revoke_token_success(self, blocklist_service, test_db):
        """Test successful token revocation."""
        jti = str(uuid.uuid4())
        # Use utc_now() to ensure consistent timezone handling
        token_expiry = utc_now() + timedelta(minutes=20)
        
        result = blocklist_service.revoke_token(
            jti=jti,
            revoked_by="test@example.com",
            reason="logout",
            token_expiry=token_expiry
        )
        
        assert result is True
        
        # Verify token is in database
        revocation = test_db.execute(
            select(TokenRevocation).where(TokenRevocation.jti == jti)
        ).scalar_one_or_none()
        
        assert revocation is not None
        assert revocation.jti == jti
        assert revocation.revoked_by == "test@example.com"
        assert revocation.reason == "logout"
        
        # SQLite doesn't preserve timezone info, so we need to handle both cases
        if revocation.token_expiry.tzinfo is None:
            # Make token_expiry naive for comparison
            token_expiry_naive = token_expiry.replace(tzinfo=None)
            assert abs((revocation.token_expiry - token_expiry_naive).total_seconds()) < 1
        else:
            # Both are timezone-aware
            assert abs((revocation.token_expiry - token_expiry).total_seconds()) < 1
    
    def test_revoke_token_duplicate(self, blocklist_service, test_db):
        """Test revoking an already revoked token."""
        jti = str(uuid.uuid4())
        
        # Revoke once
        blocklist_service.revoke_token(
            jti=jti,
            revoked_by="test@example.com",
            reason="logout"
        )
        
        # Revoke again - should succeed (idempotent)
        result = blocklist_service.revoke_token(
            jti=jti,
            revoked_by="test@example.com",
            reason="logout"
        )
        
        assert result is True
    
    def test_revoke_token_with_last_activity(self, blocklist_service, test_db):
        """Test token revocation with last activity timestamp."""
        jti = str(uuid.uuid4())
        last_activity = utc_now() - timedelta(minutes=30)
        
        result = blocklist_service.revoke_token(
            jti=jti,
            revoked_by="test@example.com",
            reason="idle_timeout",
            last_activity=last_activity
        )
        
        assert result is True
        
        revocation = test_db.execute(
            select(TokenRevocation).where(TokenRevocation.jti == jti)
        ).scalar_one_or_none()
        
        assert revocation.last_activity is not None
        assert revocation.reason == "idle_timeout"


class TestRevocationCheck:
    """Tests for checking if tokens are revoked."""
    
    def test_is_token_revoked_true(self, blocklist_service, test_db):
        """Test checking a revoked token."""
        jti = str(uuid.uuid4())
        
        # Revoke token
        blocklist_service.revoke_token(
            jti=jti,
            revoked_by="test@example.com",
            reason="logout"
        )
        
        # Check if revoked
        assert blocklist_service.is_token_revoked(jti) is True
    
    def test_is_token_revoked_false(self, blocklist_service):
        """Test checking a non-revoked token."""
        jti = str(uuid.uuid4())
        
        assert blocklist_service.is_token_revoked(jti) is False
    
    @patch('mcpgateway.services.token_blocklist_service.TokenBlocklistService._get_redis_client')
    def test_is_token_revoked_with_redis_cache(self, mock_redis, blocklist_service, test_db):
        """Test revocation check with Redis caching."""
        jti = str(uuid.uuid4())
        
        # Mock Redis client
        redis_mock = MagicMock()
        redis_mock.exists.return_value = True
        mock_redis.return_value = redis_mock
        
        # Revoke token (should cache in Redis)
        blocklist_service.revoke_token(
            jti=jti,
            revoked_by="test@example.com",
            reason="logout"
        )
        
        # Check revocation (should hit Redis cache)
        assert blocklist_service.is_token_revoked(jti) is True


class TestIdleTimeout:
    """Tests for idle timeout functionality."""
    
    def test_check_idle_timeout_exceeded(self, blocklist_service):
        """Test idle timeout detection when exceeded."""
        jti = str(uuid.uuid4())
        last_activity = utc_now() - timedelta(minutes=90)  # 90 minutes ago
        
        # Default idle timeout is 60 minutes
        with patch('mcpgateway.services.token_blocklist_service.settings') as mock_settings:
            mock_settings.token_idle_timeout = 60
            
            result = blocklist_service.check_idle_timeout(
                jti=jti,
                last_activity=last_activity
            )
            
            assert result is True
    
    def test_check_idle_timeout_not_exceeded(self, blocklist_service):
        """Test idle timeout detection when not exceeded."""
        jti = str(uuid.uuid4())
        last_activity = utc_now() - timedelta(minutes=30)  # 30 minutes ago
        
        with patch('mcpgateway.services.token_blocklist_service.settings') as mock_settings:
            mock_settings.token_idle_timeout = 60
            
            result = blocklist_service.check_idle_timeout(
                jti=jti,
                last_activity=last_activity
            )
            
            assert result is False
    
    def test_check_idle_timeout_with_custom_time(self, blocklist_service):
        """Test idle timeout with custom current time."""
        jti = str(uuid.uuid4())
        last_activity = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        current_time = datetime(2026, 1, 1, 13, 30, 0, tzinfo=timezone.utc)  # 90 minutes later
        
        with patch('mcpgateway.services.token_blocklist_service.settings') as mock_settings:
            mock_settings.token_idle_timeout = 60
            
            result = blocklist_service.check_idle_timeout(
                jti=jti,
                last_activity=last_activity,
                current_time=current_time
            )
            
            assert result is True


class TestActivityTracking:
    """Tests for activity tracking functionality."""
    
    @patch('mcpgateway.services.token_blocklist_service.TokenBlocklistService._get_redis_client')
    def test_update_activity_success(self, mock_redis, blocklist_service):
        """Test updating token activity timestamp."""
        jti = str(uuid.uuid4())
        
        # Mock Redis client
        redis_mock = MagicMock()
        mock_redis.return_value = redis_mock
        
        result = blocklist_service.update_activity(jti)
        
        assert result is True
        redis_mock.setex.assert_called_once()
    
    @patch('mcpgateway.services.token_blocklist_service.TokenBlocklistService._get_redis_client')
    def test_get_last_activity_from_redis(self, mock_redis, blocklist_service):
        """Test retrieving last activity from Redis."""
        jti = str(uuid.uuid4())
        activity_time = utc_now()
        
        # Mock Redis client
        redis_mock = MagicMock()
        redis_mock.get.return_value = activity_time.isoformat()
        mock_redis.return_value = redis_mock
        
        result = blocklist_service.get_last_activity(jti)
        
        assert result is not None
        assert isinstance(result, datetime)
    
    @patch('mcpgateway.services.token_blocklist_service.TokenBlocklistService._get_redis_client')
    def test_get_last_activity_not_found(self, mock_redis, blocklist_service):
        """Test retrieving last activity when not found."""
        jti = str(uuid.uuid4())
        
        # Mock Redis client
        redis_mock = MagicMock()
        redis_mock.get.return_value = None
        mock_redis.return_value = redis_mock
        
        result = blocklist_service.get_last_activity(jti)
        
        assert result is None


class TestCleanup:
    """Tests for automatic cleanup functionality."""
    
    def test_cleanup_expired_tokens(self, blocklist_service, test_db):
        """Test cleanup of expired tokens."""
        # Create expired token (expired 48 hours ago)
        expired_jti = str(uuid.uuid4())
        expired_time = utc_now() - timedelta(hours=48)
        
        revocation = TokenRevocation(
            jti=expired_jti,
            revoked_by="test@example.com",
            reason="logout",
            token_expiry=expired_time
        )
        test_db.add(revocation)
        
        # Create recent token (expires in future)
        recent_jti = str(uuid.uuid4())
        future_time = utc_now() + timedelta(hours=1)
        
        revocation2 = TokenRevocation(
            jti=recent_jti,
            revoked_by="test@example.com",
            reason="logout",
            token_expiry=future_time
        )
        test_db.add(revocation2)
        test_db.commit()
        
        # Cleanup with 24-hour retention
        deleted_count = blocklist_service.cleanup_expired_tokens(hours_retention=24)
        
        assert deleted_count == 1
        
        # Verify expired token is gone
        expired = test_db.execute(
            select(TokenRevocation).where(TokenRevocation.jti == expired_jti)
        ).scalar_one_or_none()
        assert expired is None
        
        # Verify recent token remains
        recent = test_db.execute(
            select(TokenRevocation).where(TokenRevocation.jti == recent_jti)
        ).scalar_one_or_none()
        assert recent is not None
    
    def test_cleanup_no_expired_tokens(self, blocklist_service, test_db):
        """Test cleanup when no tokens are expired."""
        # Create recent token
        jti = str(uuid.uuid4())
        future_time = utc_now() + timedelta(hours=1)
        
        revocation = TokenRevocation(
            jti=jti,
            revoked_by="test@example.com",
            reason="logout",
            token_expiry=future_time
        )
        test_db.add(revocation)
        test_db.commit()
        
        deleted_count = blocklist_service.cleanup_expired_tokens(hours_retention=24)
        
        assert deleted_count == 0


class TestStatistics:
    """Tests for revocation statistics."""
    
    def test_get_revocation_stats(self, test_db):
        """Test getting revocation statistics."""
        # Create revocations directly in the database
        reasons = ["logout", "logout", "idle_timeout", "security"]
        
        for reason in reasons:
            jti = str(uuid.uuid4())
            revocation = TokenRevocation(
                jti=jti,
                revoked_by="test@example.com",
                reason=reason
            )
            test_db.add(revocation)
        
        test_db.commit()
        test_db.flush()
        
        # Verify data was actually inserted
        count = test_db.execute(select(func.count()).select_from(TokenRevocation)).scalar()
        assert count == 4, f"Expected 4 revocations in DB, found {count}"
        
        # Create a service that uses the test database
        service = TokenBlocklistService(db=test_db)
        
        # Get stats using the same database session
        stats = service.get_revocation_stats()
        
        assert stats["total_revoked"] == 4
        assert stats["by_reason"]["logout"] == 2
        assert stats["by_reason"]["idle_timeout"] == 1
        assert stats["by_reason"]["security"] == 1
    
    def test_get_revocation_stats_empty(self, blocklist_service):
        """Test getting statistics when no revocations exist."""
        stats = blocklist_service.get_revocation_stats()
        
        assert stats["total_revoked"] == 0
        assert stats["by_reason"] == {}


class TestSingletonService:
    """Tests for singleton service instance."""
    
    def test_get_token_blocklist_service_singleton(self):
        """Test that service returns singleton instance."""
        service1 = get_token_blocklist_service()
        service2 = get_token_blocklist_service()
        
        assert service1 is service2
    
    def test_get_token_blocklist_service_with_db(self, test_db):
        """Test that service creates new instance when db is provided."""
        service1 = get_token_blocklist_service(db=test_db)
        service2 = get_token_blocklist_service(db=test_db)
        
        # Should be different instances when db is provided
        assert service1 is not service2
        assert service1.db is test_db
        assert service2.db is test_db


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_revoke_token_database_error(self):
        """Test token revocation with database error."""
        # Create a service with no database (will use fresh_db_session)
        service = TokenBlocklistService(db=None)
        
        # Mock fresh_db_session to raise an error
        with patch('mcpgateway.services.token_blocklist_service.fresh_db_session') as mock_session:
            mock_session.side_effect = Exception("Database connection failed")
            
            result = service.revoke_token(
                jti=str(uuid.uuid4()),
                revoked_by="test@example.com",
                reason="logout"
            )
            
            assert result is False
    
    def test_is_token_revoked_database_error(self):
        """Test revocation check with database error."""
        # Create a service with no database (will use fresh_db_session)
        service = TokenBlocklistService(db=None)
        
        # Mock fresh_db_session to raise an error
        with patch('mcpgateway.services.token_blocklist_service.fresh_db_session') as mock_session:
            mock_session.side_effect = Exception("Database connection failed")
            
            # Should fail closed (treat as revoked on error)
            result = service.is_token_revoked(str(uuid.uuid4()))
            
            assert result is True
