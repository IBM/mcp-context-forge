# -*- coding: utf-8 -*-
"""Unit tests for SecurityLogger service."""

# Standard
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.security_logger import (
    SecurityEventType,
    SecurityLogger,
    SecuritySeverity,
    get_security_logger,
)


@pytest.fixture
def sec_logger():
    return SecurityLogger()


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.execute.return_value.scalar.return_value = 0
    return db


# ---------- _requires_audit_review branches ----------


def test_requires_review_failed_confidential(sec_logger):
    assert sec_logger._requires_audit_review(action="read", resource_type="tool", data_classification="confidential", success=False) is True


def test_requires_review_failed_restricted(sec_logger):
    assert sec_logger._requires_audit_review(action="read", resource_type="tool", data_classification="restricted", success=False) is True


def test_requires_review_delete_confidential(sec_logger):
    assert sec_logger._requires_audit_review(action="delete", resource_type="tool", data_classification="confidential", success=True) is True


def test_requires_review_delete_restricted(sec_logger):
    assert sec_logger._requires_audit_review(action="delete", resource_type="tool", data_classification="restricted", success=True) is True


def test_requires_review_privilege_resource_types(sec_logger):
    for rt in ["role", "permission", "team_member"]:
        assert sec_logger._requires_audit_review(action="read", resource_type=rt, data_classification=None, success=True) is True


def test_requires_review_returns_false(sec_logger):
    assert sec_logger._requires_audit_review(action="read", resource_type="tool", data_classification="public", success=True) is False


# ---------- _count_recent_failures with db=None ----------


def test_count_recent_failures_no_user_no_ip(sec_logger):
    assert sec_logger._count_recent_failures(user_id=None, client_ip=None) == 0


def test_count_recent_failures_creates_session_when_db_none(sec_logger):
    mock_session = MagicMock()
    mock_session.execute.return_value.scalar.return_value = 3
    with patch("mcpgateway.services.security_logger.SessionLocal", return_value=mock_session):
        result = sec_logger._count_recent_failures(user_id="user1", db=None)
    assert result == 3
    mock_session.commit.assert_called_once()
    mock_session.close.assert_called_once()


def test_count_recent_failures_with_db(sec_logger, mock_db):
    mock_db.execute.return_value.scalar.return_value = 5
    result = sec_logger._count_recent_failures(user_id="user1", db=mock_db)
    assert result == 5
    mock_db.commit.assert_not_called()
    mock_db.close.assert_not_called()


def test_count_recent_failures_with_client_ip(sec_logger, mock_db):
    mock_db.execute.return_value.scalar.return_value = 2
    result = sec_logger._count_recent_failures(client_ip="1.2.3.4", db=mock_db)
    assert result == 2


def test_count_recent_failures_null_result(sec_logger, mock_db):
    mock_db.execute.return_value.scalar.return_value = None
    result = sec_logger._count_recent_failures(user_id="user1", db=mock_db)
    assert result == 0


# ---------- _calculate_auth_threat_score ----------


def test_threat_score_success(sec_logger):
    assert sec_logger._calculate_auth_threat_score(success=True, failed_attempts=10, auth_method="jwt") == 0.0


def test_threat_score_failure_low(sec_logger):
    assert sec_logger._calculate_auth_threat_score(success=False, failed_attempts=1, auth_method="jwt") == 0.3


def test_threat_score_failure_3(sec_logger):
    assert sec_logger._calculate_auth_threat_score(success=False, failed_attempts=3, auth_method="jwt") == 0.5


def test_threat_score_failure_5(sec_logger):
    assert sec_logger._calculate_auth_threat_score(success=False, failed_attempts=5, auth_method="jwt") == 0.6


def test_threat_score_failure_10(sec_logger):
    assert sec_logger._calculate_auth_threat_score(success=False, failed_attempts=10, auth_method="jwt") == 0.8


# ---------- _create_security_event ----------


def test_create_security_event_success(sec_logger, mock_db):
    mock_db.refresh = MagicMock()
    event = sec_logger._create_security_event(
        event_type="test",
        severity=SecuritySeverity.LOW,
        category="test",
        client_ip="1.2.3.4",
        description="test event",
        threat_score=0.1,
        db=mock_db,
    )
    assert event is not None
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once()


def test_create_security_event_db_none_creates_session(sec_logger):
    mock_session = MagicMock()
    mock_session.refresh = MagicMock()
    with patch("mcpgateway.services.security_logger.SessionLocal", return_value=mock_session):
        event = sec_logger._create_security_event(
            event_type="test",
            severity=SecuritySeverity.LOW,
            category="test",
            client_ip="1.2.3.4",
            description="test event",
            threat_score=0.1,
            db=None,
        )
    assert event is not None
    mock_session.close.assert_called_once()


def test_create_security_event_exception_rollback(sec_logger, mock_db):
    mock_db.add.side_effect = Exception("DB error")
    event = sec_logger._create_security_event(
        event_type="test",
        severity=SecuritySeverity.LOW,
        category="test",
        client_ip="1.2.3.4",
        description="test event",
        threat_score=0.1,
        db=mock_db,
    )
    assert event is None
    mock_db.rollback.assert_called_once()


def test_create_security_event_exception_with_db_none_closes(sec_logger):
    mock_session = MagicMock()
    mock_session.add.side_effect = Exception("DB error")
    with patch("mcpgateway.services.security_logger.SessionLocal", return_value=mock_session):
        event = sec_logger._create_security_event(
            event_type="test",
            severity=SecuritySeverity.LOW,
            category="test",
            client_ip="1.2.3.4",
            description="test event",
            threat_score=0.1,
            db=None,
        )
    assert event is None
    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()


# ---------- _create_audit_trail ----------


def test_create_audit_trail_success(sec_logger, mock_db):
    mock_db.refresh = MagicMock()
    audit = sec_logger._create_audit_trail(
        action="create",
        resource_type="tool",
        user_id="user1",
        success=True,
        db=mock_db,
    )
    assert audit is not None
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


def test_create_audit_trail_db_none_creates_session(sec_logger):
    mock_session = MagicMock()
    mock_session.refresh = MagicMock()
    with patch("mcpgateway.services.security_logger.SessionLocal", return_value=mock_session):
        audit = sec_logger._create_audit_trail(
            action="delete",
            resource_type="tool",
            user_id="user1",
            success=True,
            db=None,
        )
    assert audit is not None
    mock_session.close.assert_called_once()


def test_create_audit_trail_exception_rollback(sec_logger, mock_db):
    mock_db.add.side_effect = Exception("DB error")
    audit = sec_logger._create_audit_trail(
        action="delete",
        resource_type="tool",
        user_id="user1",
        success=True,
        db=mock_db,
    )
    assert audit is None
    mock_db.rollback.assert_called_once()


def test_create_audit_trail_exception_db_none_closes(sec_logger):
    mock_session = MagicMock()
    mock_session.add.side_effect = Exception("DB error")
    with patch("mcpgateway.services.security_logger.SessionLocal", return_value=mock_session):
        audit = sec_logger._create_audit_trail(
            action="delete",
            resource_type="tool",
            user_id="user1",
            success=True,
            db=None,
        )
    assert audit is None
    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()


# ---------- log_authentication_attempt ----------


def test_log_auth_attempt_success(sec_logger, mock_db):
    mock_db.refresh = MagicMock()
    with patch("mcpgateway.services.security_logger.get_correlation_id", return_value="corr-1"):
        event = sec_logger.log_authentication_attempt(
            user_id="user1",
            user_email="user@test.com",
            auth_method="jwt",
            success=True,
            client_ip="1.2.3.4",
            db=mock_db,
        )
    assert event is not None


def test_log_auth_attempt_failure_high_severity(sec_logger, mock_db):
    mock_db.execute.return_value.scalar.return_value = 6
    mock_db.refresh = MagicMock()
    with patch("mcpgateway.services.security_logger.get_correlation_id", return_value="corr-2"):
        event = sec_logger.log_authentication_attempt(
            user_id="user1",
            user_email="user@test.com",
            auth_method="jwt",
            success=False,
            client_ip="1.2.3.4",
            failure_reason="bad password",
            db=mock_db,
        )
    assert event is not None


def test_log_auth_attempt_failure_medium_severity(sec_logger, mock_db):
    mock_db.execute.return_value.scalar.return_value = 3
    mock_db.refresh = MagicMock()
    with patch("mcpgateway.services.security_logger.get_correlation_id", return_value="corr-3"):
        event = sec_logger.log_authentication_attempt(
            user_id="user1",
            user_email=None,
            auth_method="basic",
            success=False,
            client_ip="1.2.3.4",
            db=mock_db,
        )
    assert event is not None


def test_log_auth_attempt_failure_low_severity(sec_logger, mock_db):
    mock_db.execute.return_value.scalar.return_value = 1
    mock_db.refresh = MagicMock()
    with patch("mcpgateway.services.security_logger.get_correlation_id", return_value="corr-4"):
        event = sec_logger.log_authentication_attempt(
            user_id="user1",
            user_email=None,
            auth_method="basic",
            success=False,
            client_ip="1.2.3.4",
            additional_context={"source": "api"},
            db=mock_db,
        )
    assert event is not None


# ---------- log_data_access ----------


def test_log_data_access_sensitive_classification(sec_logger, mock_db):
    mock_db.refresh = MagicMock()
    with patch("mcpgateway.services.security_logger.get_correlation_id", return_value="corr-5"):
        audit = sec_logger.log_data_access(
            action="read",
            resource_type="secret",
            resource_id="s1",
            resource_name="API Key",
            user_id="user1",
            user_email="user@test.com",
            team_id="team1",
            client_ip="1.2.3.4",
            user_agent="curl",
            success=True,
            data_classification="confidential",
            db=mock_db,
        )
    assert audit is not None


def test_log_data_access_with_changes(sec_logger, mock_db):
    mock_db.refresh = MagicMock()
    with patch("mcpgateway.services.security_logger.get_correlation_id", return_value="corr-6"):
        audit = sec_logger.log_data_access(
            action="update",
            resource_type="tool",
            resource_id="t1",
            resource_name="my-tool",
            user_id="user1",
            user_email="user@test.com",
            team_id=None,
            client_ip="1.2.3.4",
            user_agent=None,
            success=True,
            old_values={"name": "old"},
            new_values={"name": "new"},
            db=mock_db,
        )
    assert audit is not None


def test_log_data_access_non_sensitive(sec_logger, mock_db):
    mock_db.refresh = MagicMock()
    with patch("mcpgateway.services.security_logger.get_correlation_id", return_value="corr-7"):
        audit = sec_logger.log_data_access(
            action="read",
            resource_type="tool",
            resource_id="t1",
            resource_name=None,
            user_id="user1",
            user_email=None,
            team_id=None,
            client_ip=None,
            user_agent=None,
            success=True,
            db=mock_db,
        )
    assert audit is not None


# ---------- log_suspicious_activity ----------


def test_log_suspicious_activity(sec_logger, mock_db):
    mock_db.refresh = MagicMock()
    with patch("mcpgateway.services.security_logger.get_correlation_id", return_value="corr-8"):
        event = sec_logger.log_suspicious_activity(
            activity_type="brute_force",
            description="Multiple failed logins",
            user_id="user1",
            user_email="user@test.com",
            client_ip="1.2.3.4",
            user_agent="curl",
            threat_score=0.9,
            severity=SecuritySeverity.HIGH,
            threat_indicators={"failed_count": 20},
            action_taken="blocked",
            additional_context={"note": "test"},
            db=mock_db,
        )
    assert event is not None


# ---------- get_security_logger singleton ----------


def test_get_security_logger_singleton():
    with patch("mcpgateway.services.security_logger._security_logger", None):
        lg = get_security_logger()
        assert isinstance(lg, SecurityLogger)
