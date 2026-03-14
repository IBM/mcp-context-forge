"""
waivers.py - WAIVER MANAGEMENT

Handles waiver creation, approval, and checking.
Manages waiver expiration and active waiver lookup.

A waiver allows a failed rule to pass for a specific server,
subject to approval and expiration.
"""

# Standard
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

logger = logging.getLogger(__name__)


class WaiverManager:
    """Manages policy waivers and exceptions."""

    def __init__(self, max_waiver_days: int = 90, storage_file: Optional[str] = "/tmp/policy_engine_waivers.json"):
        """Initialize waiver manager.

        Args:
            max_waiver_days: Maximum duration for a waiver (default 90 days)
            storage_file: Path to persistent storage file, or None for in-memory only
        """
        self.max_waiver_days = max_waiver_days
        # In-memory storage; in production would use database
        self._waivers: Dict[str, Dict[str, Any]] = {}
        # Persistent storage (None = in-memory only, used for tests)
        self._waiver_file = Path(storage_file) if storage_file else None
        # Load from persistent storage on init
        if self._waiver_file:
            self._load_waivers()

    def create_waiver(
        self,
        server_id: str,
        rule_name: str,
        reason: str,
        requested_by: str,
        duration_days: int = 30,
        approved: bool = False,
        approved_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new waiver request.

        Args:
            server_id: ID of the server
            rule_name: Name of the rule to waive
            reason: Reason for the waiver
            requested_by: User requesting the waiver
            duration_days: How long waiver should last (default 30, max 90)
            approved: Whether waiver is pre-approved
            approved_by: User who approved the waiver

        Returns:
            Created waiver object
        """
        # Validate duration
        duration_days = min(duration_days, self.max_waiver_days)

        waiver_id = str(uuid.uuid4())
        now = datetime.utcnow()
        expires_at = now + timedelta(days=duration_days)

        waiver = {
            "id": waiver_id,
            "server_id": server_id,
            "rule_name": rule_name,
            "reason": reason,
            "requested_by": requested_by,
            "requested_at": now,
            "expires_at": expires_at,
            "approved": approved,
            "approved_by": approved_by,
            "approved_at": now if approved else None,
            "status": "approved" if approved else "pending",
        }

        self._waivers[waiver_id] = waiver
        self._save_waivers()
        return waiver

    def approve_waiver(
        self,
        waiver_id: str,
        approved_by: str,
        expires_at: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Approve a pending waiver.

        Args:
            waiver_id: ID of waiver to approve
            approved_by: User approving the waiver
            expires_at: Optional new expiration date (ISO format)

        Returns:
            Updated waiver or None if not found
        """
        waiver = self._waivers.get(waiver_id)
        if not waiver:
            return None

        waiver["approved"] = True
        waiver["approved_by"] = approved_by
        waiver["approved_at"] = datetime.utcnow()
        waiver["status"] = "approved"

        # Update expiration date if provided (parse string to datetime)
        if expires_at:
            if isinstance(expires_at, str):
                waiver["expires_at"] = datetime.fromisoformat(expires_at)
            else:
                waiver["expires_at"] = expires_at

        self._save_waivers()

        return waiver

    def reject_waiver(
        self,
        waiver_id: str,
        rejected_by: str,
    ) -> Optional[Dict[str, Any]]:
        """Reject a pending waiver.

        Args:
            waiver_id: ID of waiver to reject
            rejected_by: User rejecting the waiver

        Returns:
            Updated waiver or None if not found
        """
        waiver = self._waivers.get(waiver_id)
        if not waiver:
            return None

        waiver["approved"] = False
        waiver["rejected_by"] = rejected_by
        waiver["rejected_at"] = datetime.utcnow()
        waiver["status"] = "rejected"
        self._save_waivers()

        return waiver

    def revoke_waiver(self, waiver_id: str) -> Optional[Dict[str, Any]]:
        """Revoke an active waiver.

        Args:
            waiver_id: ID of waiver to revoke

        Returns:
            Updated waiver or None if not found
        """
        waiver = self._waivers.get(waiver_id)
        if not waiver:
            return None

        waiver["status"] = "revoked"
        waiver["revoked_at"] = datetime.utcnow()
        self._save_waivers()

        return waiver

    def get_active_waiver(
        self,
        server_id: str,
        rule_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Get an active, approved, non-expired waiver for a rule.

        Args:
            server_id: Server ID
            rule_name: Rule name

        Returns:
            Active waiver or None if no match
        """
        now = datetime.utcnow()

        for waiver in self._waivers.values():
            if waiver["server_id"] == server_id and waiver["rule_name"] == rule_name and waiver["approved"] and waiver["status"] == "approved" and waiver["expires_at"] > now:
                return waiver

        return None

    def get_waiver(self, waiver_id: str) -> Optional[Dict[str, Any]]:
        """Get a waiver by ID.

        Args:
            waiver_id: Waiver ID

        Returns:
            Waiver or None if not found
        """
        return self._waivers.get(waiver_id)

    def list_waivers(
        self,
        server_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List waivers with optional filtering.

        Args:
            server_id: Optional filter by server
            status: Optional filter by status (pending, approved, rejected, revoked)

        Returns:
            List of matching waivers
        """
        # Reload from disk each time to get latest waivers from CLI
        if self._waiver_file:
            self._load_waivers()
        waivers = list(self._waivers.values())

        if server_id:
            waivers = [w for w in waivers if w["server_id"] == server_id]

        if status:
            waivers = [w for w in waivers if w["status"] == status]

        return waivers

    def cleanup_expired(self) -> int:
        """Remove expired waivers.

        Returns:
            Count of removed waivers
        """
        now = datetime.utcnow()
        expired_ids = [waiver_id for waiver_id, waiver in self._waivers.items() if waiver["expires_at"] <= now and waiver["status"] != "revoked"]

        for waiver_id in expired_ids:
            del self._waivers[waiver_id]

        if expired_ids:
            self._save_waivers()

        return len(expired_ids)

    def _load_waivers(self) -> None:
        """Load waivers from persistent storage."""
        if not self._waiver_file:
            return
        try:
            if self._waiver_file.exists():
                with open(self._waiver_file, "r") as f:
                    data = json.load(f)
                    self._waivers = data if isinstance(data, dict) else {}
                # Parse string datetime fields back to datetime objects
                for waiver in self._waivers.values():
                    for field in ("expires_at", "approved_at", "rejected_at", "revoked_at", "created_at"):
                        val = waiver.get(field)
                        if isinstance(val, str):
                            try:
                                waiver[field] = datetime.fromisoformat(val)
                            except (ValueError, TypeError):
                                pass
                logger.info(f"Loaded {len(self._waivers)} waivers from persistent storage")
            else:
                logger.debug("No waiver file found, starting fresh")
        except Exception as e:
            logger.error(f"Error loading waivers: {e}")
            self._waivers = {}

    def _save_waivers(self) -> None:
        """Save waivers to persistent storage."""
        if not self._waiver_file:
            return
        try:
            self._waiver_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._waiver_file, "w") as f:
                json.dump(self._waivers, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving waivers: {e}")
