"""Unit tests for HTTP Auth Session Management Router.

Tests for mcpgateway/routers/http_auth_sessions.py
"""

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from mcpgateway.routers.http_auth_sessions import (
    get_current_session_id,
    list_my_sessions,
    terminate_my_session,
    list_all_sessions,
    get_session_details,
    admin_terminate_session,
)
from mcpgateway.db import HttpAuthSession


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_db():
    """Mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def mock_user():
    """Mock regular user."""
    return {"email": "test@example.com", "is_admin": False}


@pytest.fixture
def mock_admin_user():
    """Mock admin user."""
    return {"email": "admin@example.com", "is_admin": True}


@pytest.fixture
def mock_request():
    """Mock FastAPI request with user object that has jti attribute."""
    request = MagicMock()
    # Create a user object with jti attribute (not a dict)
    user_obj = MagicMock()
    user_obj.jti = "test-session-123"
    request.state.user = user_obj
    return request


@pytest.fixture
def sample_sessions():
    """Sample session objects for testing."""
    now = datetime.now(timezone.utc)
    return [
        MagicMock(
            session_id=str(uuid.uuid4()),
            user_email="user@example.com",
            created_at=now,
            last_activity=now,
            ip_address="127.0.0.1",
            user_agent="TestAgent",
            device_info={},  # Must be dict or None for Pydantic validation
            is_active=True,
        ),
        MagicMock(
            session_id=str(uuid.uuid4()),
            user_email="admin@example.com",
            created_at=now,
            last_activity=now,
            ip_address="192.168.1.1",
            user_agent="AdminAgent",
            device_info={},  # Must be dict or None for Pydantic validation
            is_active=True,
        ),
    ]


# ============================================================================
# Helper Function Tests
# ============================================================================

def test_get_current_session_id_success(mock_request):
    """Test get_current_session_id extracts jti from JWT."""
    result = get_current_session_id(mock_request)
    assert result == "test-session-123"


def test_get_current_session_id_no_jti():
    """Test get_current_session_id when JWT has no jti claim."""
    request = MagicMock()
    user_obj = MagicMock(spec=[])  # Object without jti attribute
    request.state.user = user_obj
    
    result = get_current_session_id(request)
    assert result is None


def test_get_current_session_id_no_user():
    """Test get_current_session_id when no user in request state."""
    request = MagicMock()
    # Remove user attribute from state
    del request.state.user
    
    result = get_current_session_id(request)
    assert result is None


# ============================================================================
# User Endpoint Tests
# ============================================================================

@pytest.mark.asyncio
async def test_list_my_sessions_success(mock_db, mock_user, mock_request):
    """Test user can list their own sessions."""
    with patch("mcpgateway.routers.http_auth_sessions.HttpAuthSessionService") as mock_service_class:
        mock_service = AsyncMock()
        mock_service.list_user_sessions.return_value = [
            MagicMock(
                session_id="session-1",
                user_email="test@example.com",
                created_at=datetime.now(timezone.utc),
                last_activity=datetime.now(timezone.utc),
                ip_address="127.0.0.1",
                user_agent="TestAgent",
                device_info={},
            )
        ]
        mock_service_class.return_value = mock_service
        
        result = await list_my_sessions(
            request=mock_request,
            user=mock_user,
            db=mock_db,
        )
        
        assert len(result.sessions) == 1
        assert result.sessions[0].user_email == "test@example.com"
        assert result.total_count == 1


@pytest.mark.asyncio
async def test_list_my_sessions_empty(mock_db, mock_user, mock_request):
    """Test listing sessions when user has no active sessions."""
    with patch("mcpgateway.routers.http_auth_sessions.HttpAuthSessionService") as mock_service_class:
        mock_service = AsyncMock()
        mock_service.list_user_sessions.return_value = []
        mock_service_class.return_value = mock_service
        
        result = await list_my_sessions(
            request=mock_request,
            user=mock_user,
            db=mock_db,
        )
        
        assert len(result.sessions) == 0
        assert result.total_count == 0


@pytest.mark.asyncio
async def test_terminate_my_session_success(mock_db, mock_user, mock_request):
    """Test successful termination of own session."""
    session_id = str(uuid.uuid4())  # Must be valid UUID
    # Current session is different
    mock_request.state.user.jti = str(uuid.uuid4())
    
    # Mock session query
    mock_session = MagicMock()
    mock_session.user_email = "test@example.com"
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_session
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with patch("mcpgateway.routers.http_auth_sessions.HttpAuthSessionService") as mock_service_class:
        mock_service = AsyncMock()
        mock_service.terminate_session.return_value = True
        mock_service_class.return_value = mock_service
        
        result = await terminate_my_session(
            session_id=session_id,
            request=mock_request,
            user=mock_user,
            db=mock_db,
        )
        
        assert result.success is True
        assert result.session_id == session_id
        # Verify hardcoded reason "user_revoke" is used (not customizable by user)
        mock_service.terminate_session.assert_called_once_with(session_id, reason="user_revoke")
        # Verify session ownership was checked via DB query
        mock_db.query.assert_called()


@pytest.mark.asyncio
async def test_terminate_my_session_cannot_terminate_current(mock_db, mock_user, mock_request):
    """Test that user cannot terminate their current session."""
    session_id = str(uuid.uuid4())  # Must be valid UUID
    mock_request.state.user.jti = session_id
    
    # Mock session query
    mock_session = MagicMock()
    mock_session.user_email = "test@example.com"
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_session
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with pytest.raises(HTTPException) as exc_info:
        await terminate_my_session(
            session_id=session_id,
            request=mock_request,
            user=mock_user,
            db=mock_db,
        )
    
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Cannot terminate current session" in exc_info.value.detail


@pytest.mark.asyncio
async def test_terminate_my_session_not_found(mock_db, mock_user, mock_request):
    """Test terminating non-existent session returns 404."""
    session_id = str(uuid.uuid4())
    mock_request.state.user.jti = "current-session-456"
    
    # Mock session query to return None
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with pytest.raises(HTTPException) as exc_info:
        await terminate_my_session(
            session_id=session_id,
            request=mock_request,
            user=mock_user,
            db=mock_db,
        )
    
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "Session not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_terminate_my_session_wrong_user(mock_db, mock_user, mock_request):
    """Test user cannot terminate another user's session."""
    session_id = str(uuid.uuid4())
    mock_request.state.user.jti = "current-session-456"
    
    # Mock session belonging to different user
    mock_session = MagicMock()
    mock_session.user_email = "other@example.com"
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_session
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with pytest.raises(HTTPException) as exc_info:
        await terminate_my_session(
            session_id=session_id,
            request=mock_request,
            user=mock_user,
            db=mock_db,
        )
    
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "Cannot terminate another user's session" in exc_info.value.detail


# ============================================================================
# Admin Endpoint Tests
# ============================================================================

@pytest.mark.asyncio
async def test_list_all_sessions_admin_success(mock_db, mock_admin_user, sample_sessions):
    """Test admin can list all sessions with pagination."""
    from sqlalchemy import func
    
    # Mock the main query that will be used for SELECT
    mock_main_query = MagicMock()
    
    # Mock for the session SELECT query path (no filter when user_email=None)
    mock_order = MagicMock()
    mock_offset = MagicMock()
    mock_limit = MagicMock()
    mock_limit.all.return_value = sample_sessions[:2]
    mock_offset.limit.return_value = mock_limit
    mock_order.offset.return_value = mock_offset
    mock_main_query.order_by.return_value = mock_order
    
    # Mock for the COUNT query path: db.query(func.count(HttpAuthSession.session_id)).scalar()
    # Note: When user_email=None, filter() is NOT called, so scalar() is called directly on count_query
    mock_count_query = MagicMock()
    mock_count_query.scalar.return_value = 25
    
    # db.query() is called twice:
    # 1. First for HttpAuthSession (returns mock_main_query)
    # 2. Second for func.count(HttpAuthSession.session_id) (returns mock_count_query)
    mock_db.query.side_effect = [mock_main_query, mock_count_query]
    
    result = await list_all_sessions(
        user_email=None,
        page=1,
        page_size=10,
        user=mock_admin_user,
        db=mock_db,
    )
    
    assert result.total_count == 25
    assert len(result.sessions) == 2
    # Verify COUNT query was executed (optimization check)
    assert mock_db.query.call_count == 2  # Once for sessions, once for count
    # Verify func.count was used in second query (not len(all()))
    count_query_call = mock_db.query.call_args_list[1]
    assert len(count_query_call[0]) > 0  # func.count() was passed as argument


@pytest.mark.asyncio
async def test_get_session_details_success(mock_db, mock_admin_user, sample_sessions):
    """Test admin can get details of a specific session."""
    session = sample_sessions[0]
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = session
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    result = await get_session_details(
        session_id=session.session_id,
        user=mock_admin_user,
        db=mock_db,
    )
    
    assert result.session_id == session.session_id
    assert result.user_email == session.user_email


@pytest.mark.asyncio
async def test_get_session_details_not_found(mock_db, mock_admin_user):
    """Test getting non-existent session returns 404."""
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with pytest.raises(HTTPException) as exc_info:
        await get_session_details(
            session_id=str(uuid.uuid4()),
            user=mock_admin_user,
            db=mock_db,
        )
    
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "Session not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_admin_terminate_session_success(mock_db, mock_admin_user, sample_sessions):
    """Test admin can terminate any user's session."""
    session = sample_sessions[0]
    
    # Mock session query
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = session
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with patch("mcpgateway.routers.http_auth_sessions.HttpAuthSessionService") as mock_service_class:
        mock_service = AsyncMock()
        mock_service.terminate_session.return_value = True
        mock_service_class.return_value = mock_service
        
        result = await admin_terminate_session(
            session_id=session.session_id,
            reason="admin_revoke",
            user=mock_admin_user,
            db=mock_db,
            _csrf=None,
        )
        
        assert result.success is True
        assert result.session_id == session.session_id
        # Verify admin can use custom reason (unlike user endpoints)
        mock_service.terminate_session.assert_called_once_with(session.session_id, reason="admin_revoke")
        # Verify session existence was checked via DB query
        mock_db.query.assert_called()


@pytest.mark.asyncio
async def test_admin_terminate_session_not_found(mock_db, mock_admin_user):
    """Test admin terminating non-existent session returns 404."""
    session_id = str(uuid.uuid4())
    
    # Mock session query to return None
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with pytest.raises(HTTPException) as exc_info:
        await admin_terminate_session(
            session_id=session_id,
            reason="admin_revoke",
            user=mock_admin_user,
            db=mock_db,
            _csrf=None,
        )
    
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "Session not found" in exc_info.value.detail


# ============================================================================
# Error Handling Tests
# ============================================================================

@pytest.mark.asyncio
async def test_terminate_session_service_error(mock_db, mock_user, mock_request):
    """Test handling of service errors during termination."""
    session_id = str(uuid.uuid4())  # Must be valid UUID
    mock_request.state.user.jti = str(uuid.uuid4())
    
    # Mock session query
    mock_session = MagicMock()
    mock_session.user_email = "test@example.com"
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_session
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with patch("mcpgateway.routers.http_auth_sessions.HttpAuthSessionService") as mock_service_class:
        mock_service = AsyncMock()
        mock_service.terminate_session.side_effect = Exception("Service error")
        mock_service_class.return_value = mock_service
        
        with pytest.raises(HTTPException) as exc_info:
            await terminate_my_session(
                session_id=session_id,
                request=mock_request,
                user=mock_user,
                db=mock_db,
            )
        
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_terminate_session_invalid_uuid(mock_db, mock_user, mock_request):
    """Test terminating session with invalid UUID format raises 400."""
    invalid_session_id = "not-a-valid-uuid"
    
    with pytest.raises(HTTPException) as exc_info:
        await terminate_my_session(
            session_id=invalid_session_id,
            request=mock_request,
            user=mock_user,
            db=mock_db,
        )
    
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid session ID format" in exc_info.value.detail


@pytest.mark.asyncio
async def test_admin_terminate_session_invalid_uuid(mock_db, mock_admin_user):
    """Test admin terminating session with invalid UUID format raises 400."""
    invalid_session_id = "not-a-valid-uuid"
    
    with pytest.raises(HTTPException) as exc_info:
        await admin_terminate_session(
            session_id=invalid_session_id,
            reason="admin_revoke",
            user=mock_admin_user,
            db=mock_db,
            _csrf=None,
        )
    
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid session ID format" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_session_details_invalid_uuid(mock_db, mock_admin_user):
    """Test getting session details with invalid UUID format raises 400."""
    invalid_session_id = "not-a-valid-uuid"
    
    with pytest.raises(HTTPException) as exc_info:
        await get_session_details(
            session_id=invalid_session_id,
            user=mock_admin_user,
            db=mock_db,
        )
    
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid session ID format" in exc_info.value.detail


@pytest.mark.asyncio
async def test_list_all_sessions_with_user_email_filter(mock_db, mock_admin_user, sample_sessions):
    """Test admin can filter sessions by user email."""
    from sqlalchemy import func
    
    # Mock the main query
    mock_main_query = MagicMock()
    mock_filter = MagicMock()
    mock_order = MagicMock()
    mock_offset = MagicMock()
    mock_limit = MagicMock()
    
    # Setup query chain
    mock_limit.all.return_value = [sample_sessions[0]]
    mock_offset.limit.return_value = mock_limit
    mock_order.offset.return_value = mock_offset
    mock_filter.order_by.return_value = mock_order
    mock_main_query.filter.return_value = mock_filter
    
    # Mock count query
    mock_count_query = MagicMock()
    mock_count_filter = MagicMock()
    mock_count_filter.scalar.return_value = 1
    mock_count_query.filter.return_value = mock_count_filter
    
    # db.query() called twice: once for sessions, once for count
    mock_db.query.side_effect = [mock_main_query, mock_count_query]
    
    result = await list_all_sessions(
        user_email="user@example.com",
        page=1,
        page_size=10,
        user=mock_admin_user,
        db=mock_db,
    )
    
    assert result.total_count == 1
    assert len(result.sessions) == 1
    # Verify filter was applied
    assert mock_main_query.filter.called
    assert mock_count_query.filter.called


@pytest.mark.asyncio
async def test_list_all_sessions_invalid_email_format(mock_db, mock_admin_user):
    """Test listing sessions with invalid email format raises 500 (validation error caught)."""
    with pytest.raises(HTTPException) as exc_info:
        await list_all_sessions(
            user_email="not-an-email",
            page=1,
            page_size=10,
            user=mock_admin_user,
            db=mock_db,
        )
    
    # Validation errors are caught and re-raised as 500 errors
    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "Failed to retrieve sessions" in exc_info.value.detail


@pytest.mark.asyncio
async def test_list_all_sessions_pagination(mock_db, mock_admin_user, sample_sessions):
    """Test pagination works correctly."""
    from sqlalchemy import func
    
    # Mock the main query
    mock_main_query = MagicMock()
    mock_order = MagicMock()
    mock_offset = MagicMock()
    mock_limit = MagicMock()
    
    # Setup query chain
    mock_limit.all.return_value = sample_sessions
    mock_offset.limit.return_value = mock_limit
    mock_order.offset.return_value = mock_offset
    mock_main_query.order_by.return_value = mock_order
    
    # Mock count query
    mock_count_query = MagicMock()
    mock_count_query.scalar.return_value = 25
    
    mock_db.query.side_effect = [mock_main_query, mock_count_query]
    
    result = await list_all_sessions(
        user_email=None,
        page=2,
        page_size=10,
        user=mock_admin_user,
        db=mock_db,
    )
    
    assert result.total_count == 25
    # Verify offset was calculated correctly (page 2, size 10 = offset 10)
    mock_order.offset.assert_called_once_with(10)
    mock_offset.limit.assert_called_once_with(10)


@pytest.mark.asyncio
async def test_list_all_sessions_db_error(mock_db, mock_admin_user):
    """Test database error handling in list_all_sessions."""
    mock_db.query.side_effect = Exception("Database connection failed")
    
    with pytest.raises(HTTPException) as exc_info:
        await list_all_sessions(
            user_email=None,
            page=1,
            page_size=10,
            user=mock_admin_user,
            db=mock_db,
        )
    
    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_get_session_details_db_error(mock_db, mock_admin_user):
    """Test database error handling in get_session_details."""
    session_id = str(uuid.uuid4())
    mock_db.query.side_effect = Exception("Database connection failed")
    
    with pytest.raises(HTTPException) as exc_info:
        await get_session_details(
            session_id=session_id,
            user=mock_admin_user,
            db=mock_db,
        )
    
    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_admin_terminate_session_db_error(mock_db, mock_admin_user, sample_sessions):
    """Test database error handling in admin_terminate_session."""
    session = sample_sessions[0]
    
    # Mock session query to succeed
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = session
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with patch("mcpgateway.routers.http_auth_sessions.HttpAuthSessionService") as mock_service_class:
        mock_service = AsyncMock()
        mock_service.terminate_session.side_effect = Exception("Database error")
        mock_service_class.return_value = mock_service
        
        with pytest.raises(HTTPException) as exc_info:
            await admin_terminate_session(
                session_id=session.session_id,
                reason="admin_revoke",
                user=mock_admin_user,
                db=mock_db,
                _csrf=None,
            )
        
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_admin_terminate_session_not_found(mock_db, mock_admin_user):
    """Test admin_terminate_session when session doesn't exist."""
    session_id = str(uuid.uuid4())
    
    # Mock session query to return None
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with pytest.raises(HTTPException) as exc_info:
        await admin_terminate_session(
            session_id=session_id,
            reason="admin_revoke",
            user=mock_admin_user,
            db=mock_db,
            _csrf=None,
        )
    
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_admin_terminate_session_service_returns_false(mock_db, mock_admin_user, sample_sessions):
    """Test admin_terminate_session when service returns False."""
    session = sample_sessions[0]
    
    # Mock session query to succeed
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = session
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with patch("mcpgateway.routers.http_auth_sessions.HttpAuthSessionService") as mock_service_class:
        mock_service = AsyncMock()
        mock_service.terminate_session.return_value = False  # Service returns False
        mock_service_class.return_value = mock_service
        
        with pytest.raises(HTTPException) as exc_info:
            await admin_terminate_session(
                session_id=session.session_id,
                reason="admin_revoke",
                user=mock_admin_user,
                db=mock_db,
                _csrf=None,
            )
        
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_list_my_sessions_db_error(mock_db, mock_user, mock_request):
    """Test list_my_sessions handles database errors."""
    mock_request.cookies = {"http_auth_session_id": "test-session-id"}
    
    # Make the service initialization fail
    with patch("mcpgateway.routers.http_auth_sessions.HttpAuthSessionService") as mock_service_class:
        mock_service_class.side_effect = Exception("Database connection failed")
        
        with pytest.raises(HTTPException) as exc_info:
            await list_my_sessions(
                request=mock_request,
                user=mock_user,
                db=mock_db,
            )
        
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Failed to retrieve sessions" in exc_info.value.detail


@pytest.mark.asyncio
async def test_terminate_my_session_wrong_user(mock_db, mock_user, mock_request, sample_sessions):
    """Test terminate_my_session when trying to terminate another user's session."""
    # Use a session that belongs to a different user
    session = sample_sessions[0]
    session.user_email = "other@example.com"  # Different from mock_user's email
    session_id = session.session_id
    
    mock_request.cookies = {"http_auth_session_id": "current-session-id"}
    
    # Mock the query to return the session
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = session
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with pytest.raises(HTTPException) as exc_info:
        await terminate_my_session(
            session_id=session_id,
            request=mock_request,
            user=mock_user,
            db=mock_db,
            _csrf=None,
        )
    
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "Cannot terminate another user's session" in exc_info.value.detail


@pytest.mark.asyncio
async def test_list_all_sessions_with_email_filter(mock_db, mock_admin_user, sample_sessions):
    """Test list_all_sessions with email filter."""
    user_email = "test@example.com"
    
    # Mock the main query
    mock_main_query = MagicMock()
    mock_filter = MagicMock()
    mock_order = MagicMock()
    mock_offset = MagicMock()
    mock_limit = MagicMock()
    
    # Setup query chain
    mock_limit.all.return_value = [sample_sessions[0]]
    mock_offset.limit.return_value = mock_limit
    mock_order.offset.return_value = mock_offset
    mock_filter.order_by.return_value = mock_order
    mock_main_query.filter.return_value = mock_filter
    
    # Mock count query
    mock_count_query = MagicMock()
    mock_count_filter = MagicMock()
    mock_count_filter.scalar.return_value = 1
    mock_count_query.filter.return_value = mock_count_filter
    
    mock_db.query.side_effect = [mock_main_query, mock_count_query]
    
    result = await list_all_sessions(
        user_email=user_email,
        page=1,
        page_size=10,
        user=mock_admin_user,
        db=mock_db,
    )
    
    assert result.total_count == 1
    assert len(result.sessions) == 1
    assert result.user_email == user_email


@pytest.mark.asyncio
async def test_terminate_my_session_service_returns_false(mock_db, mock_user, mock_request, sample_sessions):
    """Test terminate_my_session when service returns False."""
    session = sample_sessions[0]
    session.user_email = mock_user["email"]  # Same user
    session_id = session.session_id
    
    mock_request.cookies = {"http_auth_session_id": "different-session-id"}
    
    # Mock the query to return the session
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = session
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with patch("mcpgateway.routers.http_auth_sessions.HttpAuthSessionService") as mock_service_class:
        mock_service = AsyncMock()
        mock_service.terminate_session.return_value = False  # Service returns False
        mock_service_class.return_value = mock_service
        
        with pytest.raises(HTTPException) as exc_info:
            await terminate_my_session(
                session_id=session_id,
                request=mock_request,
                user=mock_user,
                db=mock_db,
                _csrf=None,
            )
        
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert "not found or already terminated" in exc_info.value.detail


@pytest.mark.asyncio
async def test_list_user_sessions_admin_success(mock_db, mock_admin_user, sample_sessions):
    """Test list_user_sessions_admin endpoint."""
    from mcpgateway.routers.http_auth_sessions import list_user_sessions_admin
    
    user_email = "test@example.com"
    
    with patch("mcpgateway.routers.http_auth_sessions.HttpAuthSessionService") as mock_service_class:
        mock_service = AsyncMock()
        mock_service.list_user_sessions.return_value = sample_sessions
        mock_service_class.return_value = mock_service
        
        result = await list_user_sessions_admin(
            user_email=user_email,
            user=mock_admin_user,
            db=mock_db,
        )
        
        assert len(result.sessions) == len(sample_sessions)
        assert result.user_email == user_email
        assert result.total_count == len(sample_sessions)


@pytest.mark.asyncio
async def test_list_user_sessions_admin_error(mock_db, mock_admin_user):
    """Test list_user_sessions_admin handles errors."""
    from mcpgateway.routers.http_auth_sessions import list_user_sessions_admin
    
    user_email = "test@example.com"
    
    with patch("mcpgateway.routers.http_auth_sessions.HttpAuthSessionService") as mock_service_class:
        mock_service_class.side_effect = Exception("Database error")
        
        with pytest.raises(HTTPException) as exc_info:
            await list_user_sessions_admin(
                user_email=user_email,
                user=mock_admin_user,
                db=mock_db,
            )
        
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Failed to retrieve sessions" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_session_details_not_found(mock_db, mock_admin_user):
    """Test get_session_details when session doesn't exist."""
    session_id = str(uuid.uuid4())
    
    # Mock query to return None
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query
    
    with pytest.raises(HTTPException) as exc_info:
        await get_session_details(
            session_id=session_id,
            user=mock_admin_user,
            db=mock_db,
        )
    
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

