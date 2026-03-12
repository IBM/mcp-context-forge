"""
test_waivers.py - Unit tests for waiver management

Tests waiver creation, approval, expiration, and active waiver lookup.
"""

# Standard
from datetime import datetime, timedelta
# Third-Party
import pytest
# Local
from ..waivers import WaiverManager


@pytest.fixture
def waiver_manager():
    """Create a waiver manager for testing (in-memory only, no persistent file)."""
    return WaiverManager(max_waiver_days=90, storage_file=None)


class TestWaiverCreation:
    """Test waiver creation."""

    def test_create_waiver_basic(self, waiver_manager):
        """Test creating a basic waiver request."""
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="max_critical_vulnerabilities",
            reason="Known issue in development",
            requested_by="developer@example.com",
            duration_days=30,
        )

        assert waiver["id"]
        assert waiver["server_id"] == "server-1"
        assert waiver["rule_name"] == "max_critical_vulnerabilities"
        assert waiver["reason"] == "Known issue in development"
        assert waiver["requested_by"] == "developer@example.com"
        assert waiver["status"] == "pending"
        assert waiver["approved"] is False

    def test_create_waiver_with_approval(self, waiver_manager):
        """Test creating a waiver that is pre-approved."""
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="sbom_required",
            reason="SBOM not needed yet",
            requested_by="dev",
            approved=True,
            approved_by="security-admin",
        )

        assert waiver["approved"] is True
        assert waiver["approved_by"] == "security-admin"
        assert waiver["status"] == "approved"

    def test_waiver_duration_enforced(self, waiver_manager):
        """Test that waiver duration is clamped to max."""
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test",
            reason="Test",
            requested_by="dev",
            duration_days=120,  # Exceeds max of 90
        )

        # Should be clamped to 90 days
        expected_expiry = datetime.utcnow() + timedelta(days=90)
        actual_expiry = waiver["expires_at"]
        # Check they're within a few seconds
        assert abs((actual_expiry - expected_expiry).total_seconds()) < 5

    def test_waiver_expiration_date(self, waiver_manager):
        """Test that waiver expiration date is correctly set."""
        now = datetime.utcnow()
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test",
            reason="Test",
            requested_by="dev",
            duration_days=30,
        )

        expected = now + timedelta(days=30)
        # Allow 1 second tolerance
        assert abs((waiver["expires_at"] - expected).total_seconds()) < 1


class TestWaiverApproval:
    """Test waiver approval workflow."""

    def test_approve_pending_waiver(self, waiver_manager):
        """Test approving a pending waiver."""
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test",
            reason="Test",
            requested_by="dev",
        )

        approved = waiver_manager.approve_waiver(waiver["id"], approved_by="admin")

        assert approved["status"] == "approved"
        assert approved["approved"] is True
        assert approved["approved_by"] == "admin"

    def test_approve_nonexistent_waiver(self, waiver_manager):
        """Test that approving non-existent waiver returns None."""
        result = waiver_manager.approve_waiver("nonexistent-id", "admin")
        assert result is None

    def test_approve_waiver_with_expires_at(self, waiver_manager):
        """Test that approving a waiver with expires_at updates the expiration date."""
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test",
            reason="Test",
            requested_by="dev",
        )

        new_expiry = "2027-06-30T00:00:00"
        approved = waiver_manager.approve_waiver(waiver["id"], approved_by="admin", expires_at=new_expiry)

        assert approved["status"] == "approved"
        assert approved["approved"] is True
        # expires_at is stored as datetime after parsing the ISO string
        # Standard
        from datetime import datetime

        assert approved["expires_at"] == datetime.fromisoformat(new_expiry)

    def test_approve_waiver_without_expires_at_preserves_original(self, waiver_manager):
        """Test that approving without expires_at keeps the original expiration."""
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test",
            reason="Test",
            requested_by="dev",
            duration_days=30,
        )
        original_expiry = waiver["expires_at"]

        approved = waiver_manager.approve_waiver(waiver["id"], approved_by="admin")

        assert approved["expires_at"] == original_expiry

    def test_reject_pending_waiver(self, waiver_manager):
        """Test rejecting a pending waiver."""
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test",
            reason="Test",
            requested_by="dev",
        )

        rejected = waiver_manager.reject_waiver(waiver["id"], rejected_by="admin")

        assert rejected["status"] == "rejected"
        assert rejected["approved"] is False
        assert rejected["rejected_by"] == "admin"

    def test_reject_nonexistent_waiver(self, waiver_manager):
        """Test that rejecting non-existent waiver returns None."""
        result = waiver_manager.reject_waiver("nonexistent-id", "admin")
        assert result is None


class TestActiveWaiverLookup:
    """Test finding active, approved waivers."""

    def test_get_active_waiver(self, waiver_manager):
        """Test retrieving an active, approved waiver."""
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test_rule",
            reason="Test",
            requested_by="dev",
            duration_days=30,
            approved=True,
            approved_by="admin",
        )

        found = waiver_manager.get_active_waiver("server-1", "test_rule")

        assert found is not None
        assert found["id"] == waiver["id"]

    def test_get_active_waiver_returns_none_for_pending(self, waiver_manager):
        """Test that pending waivers are not returned as active."""
        waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test_rule",
            reason="Test",
            requested_by="dev",
            approved=False,  # Not approved
        )

        found = waiver_manager.get_active_waiver("server-1", "test_rule")

        assert found is None

    def test_get_active_waiver_returns_none_for_expired(self, waiver_manager):
        """Test that expired waivers are not returned as active."""
        # Create waiver that's already expired
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test_rule",
            reason="Test",
            requested_by="dev",
            duration_days=0,  # Expires immediately
            approved=True,
            approved_by="admin",
        )
        # Create a waiver that expired in the past
        waiver["expires_at"] = datetime.utcnow() - timedelta(days=1)

        found = waiver_manager.get_active_waiver("server-1", "test_rule")

        assert found is None

    def test_get_active_waiver_wrong_server(self, waiver_manager):
        """Test that waivers for different servers are not matched."""
        waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test_rule",
            reason="Test",
            requested_by="dev",
            approved=True,
            approved_by="admin",
        )

        found = waiver_manager.get_active_waiver("server-2", "test_rule")

        assert found is None

    def test_get_active_waiver_wrong_rule(self, waiver_manager):
        """Test that waivers for different rules are not matched."""
        waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="rule_a",
            reason="Test",
            requested_by="dev",
            approved=True,
            approved_by="admin",
        )

        found = waiver_manager.get_active_waiver("server-1", "rule_b")

        assert found is None


class TestWaiverRevocation:
    """Test waiver revocation."""

    def test_revoke_waiver(self, waiver_manager):
        """Test revoking an active waiver."""
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test",
            reason="Test",
            requested_by="dev",
            approved=True,
            approved_by="admin",
        )

        revoked = waiver_manager.revoke_waiver(waiver["id"])

        assert revoked["status"] == "revoked"
        assert revoked["revoked_at"]

    def test_revoke_nonexistent_waiver(self, waiver_manager):
        """Test that revoking non-existent waiver returns None."""
        result = waiver_manager.revoke_waiver("nonexistent-id")
        assert result is None


class TestWaiverListing:
    """Test listing waivers."""

    def test_list_all_waivers(self, waiver_manager):
        """Test listing all waivers."""
        waiver1 = waiver_manager.create_waiver(server_id="server-1", rule_name="rule1", reason="Test", requested_by="dev")
        waiver2 = waiver_manager.create_waiver(server_id="server-2", rule_name="rule2", reason="Test", requested_by="dev")

        waivers = waiver_manager.list_waivers()

        assert len(waivers) == 2
        assert any(w["id"] == waiver1["id"] for w in waivers)
        assert any(w["id"] == waiver2["id"] for w in waivers)

    def test_list_waivers_by_server(self, waiver_manager):
        """Test filtering waivers by server ID."""
        waiver1 = waiver_manager.create_waiver(server_id="server-1", rule_name="rule1", reason="Test", requested_by="dev")
        waiver_manager.create_waiver(server_id="server-2", rule_name="rule2", reason="Test", requested_by="dev")

        waivers = waiver_manager.list_waivers(server_id="server-1")

        assert len(waivers) == 1
        assert waivers[0]["id"] == waiver1["id"]

    def test_list_waivers_by_status(self, waiver_manager):
        """Test filtering waivers by status."""
        approved = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="rule1",
            reason="Test",
            requested_by="dev",
            approved=True,
            approved_by="admin",
        )
        pending = waiver_manager.create_waiver(server_id="server-2", rule_name="rule2", reason="Test", requested_by="dev")

        approved_waivers = waiver_manager.list_waivers(status="approved")
        pending_waivers = waiver_manager.list_waivers(status="pending")

        assert len(approved_waivers) == 1
        assert approved_waivers[0]["id"] == approved["id"]

        assert len(pending_waivers) == 1
        assert pending_waivers[0]["id"] == pending["id"]


class TestWaiverCleanup:
    """Test cleanup of expired waivers."""

    def test_cleanup_expired_waivers(self, waiver_manager):
        """Test that expired waivers are removed."""
        # Create an active, approved waiver
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test",
            reason="Test",
            requested_by="dev",
            approved=True,
            approved_by="admin",
        )

        # Manually expire it
        waiver["expires_at"] = datetime.utcnow() - timedelta(days=1)

        # Cleanup should remove it
        count = waiver_manager.cleanup_expired()

        assert count == 1
        assert waiver_manager.get_waiver(waiver["id"]) is None

    def test_cleanup_preserves_active(self, waiver_manager):
        """Test that cleanup preserves non-expired waivers."""
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test",
            reason="Test",
            requested_by="dev",
            duration_days=30,
            approved=True,
            approved_by="admin",
        )

        count = waiver_manager.cleanup_expired()

        assert count == 0
        assert waiver_manager.get_waiver(waiver["id"]) is not None

    def test_cleanup_preserves_revoked(self, waiver_manager):
        """Test that cleanup preserves revoked waivers."""
        waiver = waiver_manager.create_waiver(
            server_id="server-1",
            rule_name="test",
            reason="Test",
            requested_by="dev",
            approved=True,
            approved_by="admin",
        )

        waiver_manager.revoke_waiver(waiver["id"])

        # Manually expire it
        waiver["expires_at"] = datetime.utcnow() - timedelta(days=1)

        count = waiver_manager.cleanup_expired()

        # Revoked waivers should be preserved
        assert count == 0
