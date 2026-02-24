# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/ip_control_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

IP Access Control Service.

This module provides IP-based access control with allowlist/blocklist evaluation,
CIDR matching, path-scoped rules, temporary blocks, priority-based evaluation,
and in-memory caching.
"""

# Standard
from datetime import timedelta
from functools import lru_cache
import ipaddress
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

# Third-Party
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import IPBlock, IPRule, SessionLocal, utc_now
from mcpgateway.services.audit_trail_service import get_audit_trail_service

logger = logging.getLogger(__name__)


class IPControlService:
    """Service for IP-based access control evaluation and management.

    Supports allowlist and blocklist modes with CIDR notation, path-scoped rules,
    temporary blocks, priority-based evaluation, and in-memory caching.
    """

    _instance: Optional["IPControlService"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "IPControlService":
        """Ensure singleton instance.

        Returns:
            Singleton IPControlService instance.
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        """Initialize the IP control service."""
        if self._initialized:
            return
        self._cache: Dict[str, Tuple[bool, float]] = {}  # key -> (allowed, expire_time)
        self._cache_lock = threading.Lock()
        self._initialized = True

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def invalidate_cache(self) -> None:
        """Clear the entire evaluation cache."""
        with self._cache_lock:
            self._cache.clear()

    def _cache_key(self, ip: str, path: str) -> str:
        return f"{ip}|{path}"

    def _cache_get(self, key: str) -> Optional[bool]:
        """Get a cached result if present and not expired.

        Args:
            key: Cache key.

        Returns:
            Cached boolean result, or None if not cached or expired.
        """
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            allowed, expire_time = entry
            if time.monotonic() > expire_time:
                del self._cache[key]
                return None
            return allowed

    def _cache_set(self, key: str, allowed: bool) -> None:
        """Set a cached result with TTL.

        Args:
            key: Cache key.
            allowed: Whether the IP was allowed.
        """
        ttl = settings.ip_control_cache_ttl
        if ttl <= 0:
            return
        with self._cache_lock:
            # Evict oldest entries if at capacity
            if len(self._cache) >= settings.ip_control_cache_size:
                # Remove ~25% of entries (oldest by expiry)
                to_remove = max(1, settings.ip_control_cache_size // 4)
                sorted_keys = sorted(self._cache, key=lambda k: self._cache[k][1])
                for k in sorted_keys[:to_remove]:
                    del self._cache[k]
            self._cache[key] = (allowed, time.monotonic() + ttl)

    def get_cache_stats(self) -> Dict[str, Any]:
        """Return cache statistics.

        Returns:
            Dict with total_entries, live_entries, expired_entries, max_size, ttl_seconds.
        """
        with self._cache_lock:
            now = time.monotonic()
            live = sum(1 for _, (__, exp) in self._cache.items() if exp > now)
            return {
                "total_entries": len(self._cache),
                "live_entries": live,
                "expired_entries": len(self._cache) - live,
                "max_size": settings.ip_control_cache_size,
                "ttl_seconds": settings.ip_control_cache_ttl,
            }

    # ------------------------------------------------------------------
    # IP and path matching (static helpers)
    # ------------------------------------------------------------------

    @staticmethod
    def _ip_matches(ip_str: str, pattern: str) -> bool:
        """Check if an IP address matches a pattern (single IP or CIDR).

        Args:
            ip_str: The IP address to check.
            pattern: An IP address or CIDR network.

        Returns:
            True if the IP matches the pattern.
        """
        try:
            addr = ipaddress.ip_address(ip_str)
            if "/" in pattern:
                network = ipaddress.ip_network(pattern, strict=False)
                return addr in network
            else:
                return addr == ipaddress.ip_address(pattern)
        except ValueError:
            return False

    @staticmethod
    @lru_cache(maxsize=256)
    def _compile_path_pattern(pattern: str) -> Optional[re.Pattern]:
        """Compile and cache a path regex pattern.

        Args:
            pattern: Regex pattern string.

        Returns:
            Compiled pattern or None if invalid.
        """
        try:
            return re.compile(pattern)
        except re.error:
            logger.warning(f"Invalid path pattern: {pattern}")
            return None

    @staticmethod
    def _path_matches(path: str, pattern: Optional[str]) -> bool:
        """Check if a request path matches a pattern.

        Args:
            path: The request path.
            pattern: Optional regex pattern. None means match all paths.

        Returns:
            True if the path matches (or pattern is None).
        """
        if pattern is None:
            return True
        compiled = IPControlService._compile_path_pattern(pattern)
        if compiled is None:
            return False
        return compiled.search(path) is not None

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    def evaluate_ip(self, ip: str, path: str, db: Optional[Session] = None) -> bool:
        """Evaluate whether an IP address should be allowed for a given path.

        Steps:
        1. Check in-memory cache
        2. Check temporary blocks
        3. Load active rules sorted by priority (ascending)
        4. First match wins
        5. Default: allowlist -> deny, blocklist -> allow

        Args:
            ip: Client IP address.
            path: Request path.
            db: Optional database session.

        Returns:
            True if the request should be allowed, False otherwise.
        """
        if not settings.ip_control_enabled or settings.ip_control_mode == "disabled":
            return True

        # 1. Check cache
        cache_key = self._cache_key(ip, path)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # Use provided session or create a new one
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            allowed = self._evaluate_ip_uncached(ip, path, db)
            self._cache_set(cache_key, allowed)
            return allowed
        except Exception as e:
            logger.error(f"IP evaluation error for {ip}: {e}", exc_info=True)
            # Fail open on error to avoid blocking legitimate traffic
            return True
        finally:
            if close_db:
                db.close()

    def _evaluate_ip_uncached(self, ip: str, path: str, db: Session) -> bool:
        """Evaluate IP without cache. Called internally by evaluate_ip.

        Args:
            ip: Client IP address.
            path: Request path.
            db: Database session.

        Returns:
            True if allowed, False if denied.
        """
        now = utc_now()

        # 2. Check temporary blocks (active + not expired)
        block_query = select(IPBlock).where(
            and_(
                IPBlock.is_active == True,  # noqa: E712
                IPBlock.ip_address == ip,
                IPBlock.expires_at > now,
            )
        )
        block = db.execute(block_query).scalars().first()
        if block is not None:
            return False

        # 3. Load active rules sorted by priority ascending
        rules_query = (
            select(IPRule)
            .where(
                and_(
                    IPRule.is_active == True,  # noqa: E712
                    # Exclude expired rules
                    (IPRule.expires_at == None) | (IPRule.expires_at > now),  # noqa: E711
                )
            )
            .order_by(IPRule.priority.asc())
        )
        rules = db.execute(rules_query).scalars().all()

        # 4. First match wins
        for rule in rules:
            if self._ip_matches(ip, rule.ip_pattern) and self._path_matches(path, rule.path_pattern):
                # Update hit count asynchronously (best effort)
                try:
                    rule.hit_count = (rule.hit_count or 0) + 1
                    rule.last_hit_at = now
                    db.commit()
                except Exception:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                return rule.rule_type == "allow"

        # 5. Default based on mode
        mode = settings.ip_control_mode
        if mode == "allowlist":
            return False  # Not in allowlist -> deny
        else:
            return True  # Not in blocklist -> allow

    # ------------------------------------------------------------------
    # Test / diagnostics (bypasses cache)
    # ------------------------------------------------------------------

    def test_ip(self, ip: str, path: str, db: Session) -> Dict[str, Any]:
        """Test an IP against current rules without caching.

        Args:
            ip: IP address to test.
            path: Request path to test.
            db: Database session.

        Returns:
            Dict with evaluation details.
        """
        if not settings.ip_control_enabled or settings.ip_control_mode == "disabled":
            return {
                "ip_address": ip,
                "path": path,
                "allowed": True,
                "matched_rule_id": None,
                "matched_rule_type": None,
                "blocked_by_temp_block": False,
                "mode": settings.ip_control_mode,
            }

        now = utc_now()

        # Check temporary blocks
        block_query = select(IPBlock).where(
            and_(
                IPBlock.is_active == True,  # noqa: E712
                IPBlock.ip_address == ip,
                IPBlock.expires_at > now,
            )
        )
        block = db.execute(block_query).scalars().first()
        if block is not None:
            return {
                "ip_address": ip,
                "path": path,
                "allowed": False,
                "matched_rule_id": block.id,
                "matched_rule_type": "block",
                "blocked_by_temp_block": True,
                "mode": settings.ip_control_mode,
            }

        # Load active rules
        rules_query = (
            select(IPRule)
            .where(
                and_(
                    IPRule.is_active == True,  # noqa: E712
                    (IPRule.expires_at == None) | (IPRule.expires_at > now),  # noqa: E711
                )
            )
            .order_by(IPRule.priority.asc())
        )
        rules = db.execute(rules_query).scalars().all()

        for rule in rules:
            if self._ip_matches(ip, rule.ip_pattern) and self._path_matches(path, rule.path_pattern):
                return {
                    "ip_address": ip,
                    "path": path,
                    "allowed": rule.rule_type == "allow",
                    "matched_rule_id": rule.id,
                    "matched_rule_type": rule.rule_type,
                    "blocked_by_temp_block": False,
                    "mode": settings.ip_control_mode,
                }

        # Default
        mode = settings.ip_control_mode
        return {
            "ip_address": ip,
            "path": path,
            "allowed": mode != "allowlist",
            "matched_rule_id": None,
            "matched_rule_type": None,
            "blocked_by_temp_block": False,
            "mode": mode,
        }

    def get_status(self, db: Session) -> Dict[str, Any]:
        """Get IP control system status.

        Args:
            db: Database session.

        Returns:
            Status dict.
        """
        now = utc_now()

        total_rules = db.execute(select(func.count(IPRule.id))).scalar() or 0
        active_rules = db.execute(select(func.count(IPRule.id)).where(IPRule.is_active == True)).scalar() or 0  # noqa: E712
        total_blocks = db.execute(select(func.count(IPBlock.id))).scalar() or 0
        active_blocks = (
            db.execute(
                select(func.count(IPBlock.id)).where(
                    and_(
                        IPBlock.is_active == True,  # noqa: E712
                        IPBlock.expires_at > now,
                    )
                )
            ).scalar()
            or 0
        )

        cache_stats = self.get_cache_stats()

        return {
            "enabled": settings.ip_control_enabled,
            "mode": settings.ip_control_mode,
            "log_only": settings.ip_control_log_only,
            "total_rules": total_rules,
            "active_rules": active_rules,
            "total_blocks": total_blocks,
            "active_blocks": active_blocks,
            "cache_size": cache_stats["total_entries"],
            "cache_ttl": settings.ip_control_cache_ttl,
            "skip_paths": settings.ip_control_skip_paths,
        }

    # ------------------------------------------------------------------
    # CRUD: Rules
    # ------------------------------------------------------------------

    def create_rule(self, data: Dict[str, Any], user_email: str, db: Session) -> IPRule:
        """Create a new IP rule.

        Args:
            data: Rule data dict.
            user_email: Email of user creating the rule.
            db: Database session.

        Returns:
            Created IPRule.
        """
        rule = IPRule(
            id=uuid.uuid4().hex,
            ip_pattern=data["ip_pattern"],
            rule_type=data["rule_type"],
            priority=data.get("priority", settings.ip_control_default_priority),
            path_pattern=data.get("path_pattern"),
            description=data.get("description"),
            is_active=data.get("is_active", True),
            created_by=user_email,
            updated_by=user_email,
            expires_at=data.get("expires_at"),
            metadata_json=data.get("metadata_json"),
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)

        self.invalidate_cache()

        audit = get_audit_trail_service()
        audit.log_action(
            action="CREATE",
            resource_type="ip_rule",
            resource_id=rule.id,
            user_id=user_email,
            new_values=data,
            db=db,
        )

        logger.info(f"IP rule created: {rule.id} ({rule.rule_type} {rule.ip_pattern})")
        return rule

    def update_rule(self, rule_id: str, data: Dict[str, Any], user_email: str, db: Session) -> Optional[IPRule]:
        """Update an existing IP rule.

        Args:
            rule_id: ID of the rule to update.
            data: Fields to update.
            user_email: Email of user performing the update.
            db: Database session.

        Returns:
            Updated IPRule or None if not found.
        """
        rule = db.execute(select(IPRule).where(IPRule.id == rule_id)).scalars().first()
        if rule is None:
            return None

        old_values = {
            "ip_pattern": rule.ip_pattern,
            "rule_type": rule.rule_type,
            "priority": rule.priority,
            "path_pattern": rule.path_pattern,
            "is_active": rule.is_active,
        }

        for key, value in data.items():
            if hasattr(rule, key) and value is not None:
                setattr(rule, key, value)
        rule.updated_by = user_email

        db.commit()
        db.refresh(rule)

        self.invalidate_cache()

        audit = get_audit_trail_service()
        audit.log_action(
            action="UPDATE",
            resource_type="ip_rule",
            resource_id=rule.id,
            user_id=user_email,
            old_values=old_values,
            new_values=data,
            db=db,
        )

        logger.info(f"IP rule updated: {rule.id}")
        return rule

    def delete_rule(self, rule_id: str, user_email: str, db: Session) -> bool:
        """Delete an IP rule.

        Args:
            rule_id: ID of the rule to delete.
            user_email: Email of user performing the deletion.
            db: Database session.

        Returns:
            True if deleted, False if not found.
        """
        rule = db.execute(select(IPRule).where(IPRule.id == rule_id)).scalars().first()
        if rule is None:
            return False

        db.delete(rule)
        db.commit()

        self.invalidate_cache()

        audit = get_audit_trail_service()
        audit.log_action(
            action="DELETE",
            resource_type="ip_rule",
            resource_id=rule_id,
            user_id=user_email,
            db=db,
        )

        logger.info(f"IP rule deleted: {rule_id}")
        return True

    def get_rule(self, rule_id: str, db: Session) -> Optional[IPRule]:
        """Get a single IP rule by ID.

        Args:
            rule_id: Rule ID.
            db: Database session.

        Returns:
            IPRule or None.
        """
        return db.execute(select(IPRule).where(IPRule.id == rule_id)).scalars().first()

    def list_rules(self, db: Session, limit: int = 50, offset: int = 0, is_active: Optional[bool] = None, rule_type: Optional[str] = None) -> Tuple[List[IPRule], int]:
        """List IP rules with pagination and filtering.

        Args:
            db: Database session.
            limit: Page size.
            offset: Page offset.
            is_active: Optional filter by active status.
            rule_type: Optional filter by rule type.

        Returns:
            Tuple of (rules list, total count).
        """
        query = select(IPRule)
        count_query = select(func.count(IPRule.id))

        if is_active is not None:
            query = query.where(IPRule.is_active == is_active)
            count_query = count_query.where(IPRule.is_active == is_active)
        if rule_type is not None:
            query = query.where(IPRule.rule_type == rule_type)
            count_query = count_query.where(IPRule.rule_type == rule_type)

        total = db.execute(count_query).scalar() or 0
        rules = db.execute(query.order_by(IPRule.priority.asc()).limit(limit).offset(offset)).scalars().all()

        return rules, total

    # ------------------------------------------------------------------
    # CRUD: Blocks
    # ------------------------------------------------------------------

    def create_block(self, data: Dict[str, Any], user_email: str, db: Session) -> IPBlock:
        """Create a temporary IP block.

        Args:
            data: Block data including ip_address, reason, duration_minutes.
            user_email: Email of user creating the block.
            db: Database session.

        Returns:
            Created IPBlock.
        """
        now = utc_now()
        block = IPBlock(
            id=uuid.uuid4().hex,
            ip_address=data["ip_address"],
            reason=data["reason"],
            blocked_at=now,
            expires_at=now + timedelta(minutes=data["duration_minutes"]),
            blocked_by=user_email,
            is_active=True,
        )
        db.add(block)
        db.commit()
        db.refresh(block)

        self.invalidate_cache()

        audit = get_audit_trail_service()
        audit.log_action(
            action="CREATE",
            resource_type="ip_block",
            resource_id=block.id,
            user_id=user_email,
            new_values=data,
            db=db,
        )

        logger.info(f"IP block created: {block.id} ({block.ip_address} for {data['duration_minutes']}m)")
        return block

    def remove_block(self, block_id: str, user_email: str, db: Session) -> bool:
        """Remove (deactivate) a temporary IP block.

        Args:
            block_id: ID of the block to remove.
            user_email: Email of user removing the block.
            db: Database session.

        Returns:
            True if removed, False if not found.
        """
        block = db.execute(select(IPBlock).where(IPBlock.id == block_id)).scalars().first()
        if block is None:
            return False

        block.is_active = False
        block.unblocked_at = utc_now()
        block.unblocked_by = user_email
        db.commit()

        self.invalidate_cache()

        audit = get_audit_trail_service()
        audit.log_action(
            action="DELETE",
            resource_type="ip_block",
            resource_id=block_id,
            user_id=user_email,
            db=db,
        )

        logger.info(f"IP block removed: {block_id}")
        return True

    def list_blocks(self, db: Session, active_only: bool = True) -> List[IPBlock]:
        """List IP blocks.

        Args:
            db: Database session.
            active_only: If True, only return active non-expired blocks.

        Returns:
            List of IPBlock entries.
        """
        query = select(IPBlock)
        if active_only:
            now = utc_now()
            query = query.where(
                and_(
                    IPBlock.is_active == True,  # noqa: E712
                    IPBlock.expires_at > now,
                )
            )
        return list(db.execute(query.order_by(IPBlock.blocked_at.desc())).scalars().all())

    def cleanup_expired_blocks(self, db: Session) -> int:
        """Deactivate expired blocks.

        Args:
            db: Database session.

        Returns:
            Number of blocks deactivated.
        """
        now = utc_now()
        blocks = (
            db.execute(
                select(IPBlock).where(
                    and_(
                        IPBlock.is_active == True,  # noqa: E712
                        IPBlock.expires_at <= now,
                    )
                )
            )
            .scalars()
            .all()
        )

        count = 0
        for block in blocks:
            block.is_active = False
            count += 1

        if count > 0:
            db.commit()
            self.invalidate_cache()
            logger.info(f"Cleaned up {count} expired IP blocks")

        return count


# Singleton accessor
_ip_control_service: Optional[IPControlService] = None


def get_ip_control_service() -> IPControlService:
    """Get or create the singleton IPControlService instance.

    Returns:
        IPControlService instance.
    """
    global _ip_control_service
    if _ip_control_service is None:
        _ip_control_service = IPControlService()
    return _ip_control_service
