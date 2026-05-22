# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/bootstrap_db.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Madhav Kandukuri

Database bootstrap/upgrade entry-point for ContextForge.
The script:

1. Creates a synchronous SQLAlchemy ``Engine`` from ``settings.database_url``.
2. Looks for an *alembic.ini* two levels up from this file to drive migrations.
3. Applies Alembic migrations (``alembic upgrade head``) to create or update the schema.
4. Runs post-upgrade normalization tasks and bootstraps admin/roles as configured.
5. Logs a **"Database ready"** message on success.

It is intended to be invoked via ``python3 -m mcpgateway.bootstrap_db`` or
directly with ``python3 mcpgateway/bootstrap_db.py``.

Examples:
    >>> from mcpgateway.bootstrap_db import logging_service, logger
    >>> logging_service is not None
    True
    >>> logger is not None
    True
    >>> hasattr(logger, 'info')
    True
"""

# Standard
import asyncio
from contextlib import contextmanager
from importlib.resources import files
import json
import os
from pathlib import Path
import random
import re
import tempfile
import time
from typing import cast

# Third-Party
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from filelock import FileLock
from sqlalchemy import create_engine, or_, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent, EmailTeam, EmailUser, Gateway, Prompt, Resource, Server, Tool
from mcpgateway.services.logging_service import LoggingService

# Migration lock to prevent concurrent migrations from multiple workers
_MIGRATION_LOCK_PATH = os.path.join(tempfile.gettempdir(), "mcpgateway_migration.lock")
_MIGRATION_LOCK_TIMEOUT = 300  # seconds to wait for lock (5 minutes for slow migrations)

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    """Check whether a table has a specific column.

    Args:
        inspector: SQLAlchemy inspector for the active connection.
        table_name: Table name to inspect.
        column_name: Column name to check.

    Returns:
        True if the column exists, otherwise False.
    """
    try:
        return any(col["name"] == column_name for col in inspector.get_columns(table_name))
    except Exception:
        return False


def _schema_looks_current(inspector) -> bool:
    """Best-effort check for unversioned databases that already match current schema.

    Args:
        inspector: SQLAlchemy inspector for the active connection.

    Returns:
        True when expected columns exist for a recent schema version.
    """
    return (
        _column_exists(inspector, "tools", "display_name")
        and _column_exists(inspector, "gateways", "oauth_config")
        and _column_exists(inspector, "prompts", "custom_name")
        and _column_exists(inspector, "sso_providers", "jwks_uri")
    )


def make_alembic_cfg(database_url: str, *, configure_logger: bool = False) -> Config:
    """Build an Alembic ``Config`` wired to ``database_url`` for this project.

    Centralises two pieces of Alembic-config setup that must be identical
    across every entry-point (``bootstrap_db.main()`` and the schema-at-head
    startup probe in ``mcpgateway.utils.check_schema_at_head``):

      * locating ``alembic.ini`` via ``importlib.resources`` so it works the
        same way inside the Python wheel and inside the container image;
      * doubling ``%`` characters in the URL before handing it to
        ``cfg.set_main_option(...)`` so configparser doesn't choke on
        URL-encoded passwords (e.g., ``%40`` for ``@``).

    Both call sites had this block inlined; reviewer flagged the duplication.
    Keeping the helper public (no leading underscore) so it is intentional
    shared API — anyone refactoring ``bootstrap_db.py`` can see at a glance
    that external code depends on this name.

    Args:
        database_url: SQLAlchemy URL for the target database.
        configure_logger: When True, set ``cfg.attributes["configure_logger"] = True``.
            ``bootstrap_db.main()`` opts in (Alembic command-line UX);
            the startup probe leaves it off (it should not emit Alembic
            INFO logs on every K8s probe tick).

    Returns:
        Configured ``alembic.config.Config`` ready for use with the Alembic
        runtime API or command layer.
    """
    ini_path = files("mcpgateway").joinpath("alembic.ini")
    cfg = Config(str(ini_path))
    if configure_logger:
        cfg.attributes["configure_logger"] = True
    # Escape '%' characters in URL to avoid configparser interpolation errors
    # (e.g., URL-encoded passwords like %40 for '@').
    escaped_url = database_url.replace("%", "%%")
    cfg.set_main_option("sqlalchemy.url", escaped_url)
    return cfg


def alembic_at_head(conn: Connection, cfg: Config) -> bool:
    """Return True when ``alembic_version`` in the DB matches the script directory head(s).

    Used by ``main()`` to skip the migration advisory lock entirely when no
    schema work is needed. This is the fast-path that keeps replicas 2..N
    of a multi-pod deployment from serializing (and potentially hanging)
    on a session-scoped advisory lock that a transaction-pooling connection
    pooler (e.g., PgBouncer in pool_mode=transaction) can orphan across its
    backend handoffs.

    Any error while probing — missing ``alembic_version`` table, connection
    issue, unexpected Alembic state — causes this to return ``False`` so
    the caller falls through to the fully-locked slow path, which handles
    empty/partial/out-of-date databases explicitly.

    Args:
        conn: Active SQLAlchemy connection (not necessarily locked).
        cfg: Alembic Config instance for this project.

    Returns:
        True if the DB schema is at the Alembic script directory's head;
        False on mismatch, empty DB, or any error while probing.
    """
    try:
        script_heads = set(ScriptDirectory.from_config(cfg).get_heads())
        if not script_heads:
            return False
        context = MigrationContext.configure(conn)
        db_heads = set(context.get_current_heads())
        return bool(db_heads) and db_heads == script_heads
    except Exception as exc:  # noqa: BLE001 - intentionally broad; fall through to slow path
        logger.warning("Fast-path head probe failed, falling back to advisory-lock path: %s", exc)
        return False


async def _run_post_migration_bootstrap(conn: Connection) -> None:
    """Run the idempotent post-migration bootstrap steps.

    These steps (team-visibility normalization, admin user, default roles,
    orphaned-resource assignment) are designed to be safe to re-run on
    every startup — each checks for existing state and skips if already
    populated. They must run on replicas that take the fast-path so that a
    prior replica crashing mid-bootstrap doesn't leave downstream state
    unpopulated.

    Args:
        conn: Active SQLAlchemy connection (locked on the slow path,
            unlocked on the fast path). Writes are idempotent either way.
    """
    updated = normalize_team_visibility(conn)
    if updated:
        logger.info(f"Normalized {updated} team record(s) to supported visibility values")

    await bootstrap_admin_user(conn)
    await bootstrap_default_roles(conn)
    await bootstrap_resource_assignments(conn)


@contextmanager
def advisory_lock(conn: Connection):
    """
    Acquire a distributed advisory lock to serialize migrations across multiple instances.

    Behavior depends on the database backend:
    - Postgres: Uses `pg_try_advisory_lock` (non-blocking)
    - SQLite: Fallback to local `FileLock`

    Args:
        conn: Active SQLAlchemy connection

    Yields:
        None

    Raises:
        TimeoutError: If the lock cannot be acquired within the timeout period
    """
    dialect = conn.dialect.name
    # Postgres requires a BIGINT lock ID (arbitrary hash of the string)
    pg_lock_id = 42424242424242

    if dialect == "postgresql":
        logger.info("Attempting to acquire Postgres advisory lock...")

        # Retry parameters
        max_retries = 60  # 60 attempts
        base_delay = 1.0  # Start with 1 second
        max_delay = 10.0  # Cap at 10 seconds

        acquired = False
        for attempt in range(max_retries):
            # Try non-blocking lock
            result = conn.execute(text(f"SELECT pg_try_advisory_lock({pg_lock_id})"))
            acquired = result.scalar()

            if acquired:
                logger.info(f"Acquired Postgres advisory lock on attempt {attempt + 1}")
                break

            # Exponential backoff with jitter
            delay = min(base_delay * (1.5**attempt), max_delay)
            jitter = delay * random.uniform(-0.1, 0.1)  # nosec B311
            sleep_time = delay + jitter

            logger.info(f"Lock held by another instance, retrying in {sleep_time:.1f}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(sleep_time)

        if not acquired:
            raise TimeoutError(f"Failed to acquire advisory lock after {max_retries} attempts")

        try:
            yield
        finally:
            logger.info("Releasing Postgres advisory lock...")
            conn.execute(text(f"SELECT pg_advisory_unlock({pg_lock_id})"))

    else:
        # Fallback for SQLite (single-host/container) or other DBs
        logger.info(f"Using FileLock fallback for {dialect}...")
        file_lock = FileLock(_MIGRATION_LOCK_PATH, timeout=_MIGRATION_LOCK_TIMEOUT)
        with file_lock:
            yield


async def bootstrap_admin_user(conn: Connection) -> None:
    """
    Bootstrap the platform admin user from environment variables.

    Creates the admin user if email authentication is enabled and the user doesn't exist.
    Also creates a personal team for the admin user if auto-creation is enabled.

    Args:
        conn: Active SQLAlchemy connection
    """
    if not settings.email_auth_enabled:
        logger.info("Email authentication disabled - skipping admin user bootstrap")
        return

    try:
        # Import services here to avoid circular imports
        # First-Party
        from mcpgateway.services.email_auth_service import EmailAuthService  # pylint: disable=import-outside-toplevel

        # Use session bound to the locked connection
        with Session(bind=conn) as db:
            auth_service = EmailAuthService(db)

            # Check if admin user already exists
            existing_user = await auth_service.get_user_by_email(settings.platform_admin_email)
            if existing_user:
                logger.info(f"Admin user {SecurityValidator.sanitize_log_message(settings.platform_admin_email)} already exists - skipping creation")
                return

            # Create admin user
            logger.info(f"Creating platform admin user: {SecurityValidator.sanitize_log_message(settings.platform_admin_email)}")
            admin_user = await auth_service.create_platform_admin(
                email=settings.platform_admin_email,
                password=settings.platform_admin_password.get_secret_value(),
                full_name=settings.platform_admin_full_name,
            )

            # Mark admin user as email verified and require password change on first login
            # First-Party
            from mcpgateway.db import utc_now  # pylint: disable=import-outside-toplevel

            admin_user.email_verified_at = utc_now()
            # Respect configuration: only require password change on bootstrap when enabled
            if getattr(settings, "password_change_enforcement_enabled", True) and getattr(settings, "admin_require_password_change_on_bootstrap", True):
                admin_user.password_change_required = True  # Force admin to change default password
            try:
                admin_user.password_changed_at = utc_now()
            except Exception as exc:
                logger.debug("Failed to set admin password_changed_at: %s", exc)
            db.commit()

            # Personal team is automatically created during user creation if enabled
            if settings.auto_create_personal_teams:
                logger.info("Personal team automatically created for admin user")

            db.commit()
            logger.info(f"Platform admin user created successfully: {SecurityValidator.sanitize_log_message(settings.platform_admin_email)}")

    except Exception as e:
        logger.error(f"Failed to bootstrap admin user: {e}")
        # Don't fail the entire bootstrap process if admin user creation fails
        return


async def bootstrap_default_roles(conn: Connection) -> None:
    """Bootstrap default system roles and assign them to admin user.

    Creates essential RBAC roles and assigns administrative privileges
    to the platform admin user.

    Args:
        conn: Active SQLAlchemy connection
    """
    if not settings.email_auth_enabled:
        logger.info("Email authentication disabled - skipping default roles bootstrap")
        return

    try:
        # First-Party
        from mcpgateway.services.email_auth_service import EmailAuthService  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.role_service import RoleService  # pylint: disable=import-outside-toplevel

        # Use session bound to the locked connection
        with Session(bind=conn) as db:
            role_service = RoleService(db)
            auth_service = EmailAuthService(db)

            # Check if admin user exists
            admin_user = await auth_service.get_user_by_email(settings.platform_admin_email)
            if not admin_user:
                logger.info("Admin user not found - skipping role assignment")
                return

            # Default system roles to create
            default_roles = [
                {"name": "platform_admin", "description": "Platform administrator with all permissions", "scope": "global", "permissions": ["*"], "is_system_role": True},  # All permissions
                {
                    "name": "team_admin",
                    "description": "Team administrator with team management permissions",
                    "scope": "team",
                    "permissions": [
                        "admin.dashboard",
                        "admin.overview",
                        "gateways.read",
                        "servers.read",
                        "servers.use",
                        "teams.read",
                        "teams.update",
                        "teams.join",
                        "teams.delete",
                        "teams.manage_members",
                        "tools.read",
                        "tools.execute",
                        "resources.read",
                        "prompts.read",
                        "llm.read",
                        "llm.invoke",
                        "a2a.read",
                        "gateways.create",
                        "servers.create",
                        "tools.create",
                        "resources.create",
                        "prompts.create",
                        "a2a.create",
                        "gateways.update",
                        "servers.update",
                        "tools.update",
                        "resources.update",
                        "prompts.update",
                        "a2a.update",
                        "gateways.delete",
                        "servers.delete",
                        "tools.delete",
                        "resources.delete",
                        "prompts.delete",
                        "a2a.delete",
                        "a2a.invoke",
                        "tokens.create",
                        "tokens.read",
                        "tokens.update",
                        "tokens.revoke",
                        "tools.manage_plugins",
                    ],
                    "is_system_role": True,
                },
                {
                    "name": "developer",
                    "description": "Developer with tool and resource access",
                    "scope": "team",
                    "permissions": [
                        "admin.dashboard",
                        "admin.overview",
                        "gateways.read",
                        "servers.read",
                        "servers.use",
                        "teams.read",
                        "teams.join",
                        "tools.read",
                        "tools.execute",
                        "resources.read",
                        "prompts.read",
                        "llm.read",
                        "llm.invoke",
                        "a2a.read",
                        "gateways.create",
                        "servers.create",
                        "tools.create",
                        "resources.create",
                        "prompts.create",
                        "a2a.create",
                        "gateways.update",
                        "servers.update",
                        "tools.update",
                        "resources.update",
                        "prompts.update",
                        "a2a.update",
                        "gateways.delete",
                        "servers.delete",
                        "tools.delete",
                        "resources.delete",
                        "prompts.delete",
                        "a2a.delete",
                        "a2a.invoke",
                        "tokens.create",
                        "tokens.read",
                        "tokens.update",
                        "tokens.revoke",
                    ],
                    "is_system_role": True,
                },
                {
                    "name": "viewer",
                    "description": "Read access and tool execution within team scope",
                    "scope": "team",
                    "permissions": [
                        "admin.dashboard",
                        "admin.overview",
                        "gateways.read",
                        "servers.read",
                        "servers.use",
                        "teams.read",
                        "teams.join",
                        "tools.read",
                        "tools.execute",
                        "resources.read",
                        "prompts.read",
                        "llm.read",
                        "a2a.read",
                        "tokens.create",
                        "tokens.read",
                        "tokens.update",
                        "tokens.revoke",
                    ],
                    "is_system_role": True,
                },
                {
                    "name": "platform_viewer",
                    "description": "Read-only access to resources and admin UI",
                    "scope": "global",
                    "permissions": [
                        "admin.dashboard",
                        "admin.overview",
                        "gateways.read",
                        "servers.read",
                        "servers.use",
                        "teams.read",
                        "teams.join",
                        "tools.read",
                        "resources.read",
                        "prompts.read",
                        "llm.read",
                        "a2a.read",
                        "tokens.create",
                        "tokens.read",
                        "tokens.update",
                        "tokens.revoke",
                    ],
                    "is_system_role": True,
                },
            ]

            # Logic to add additional default roles from a json file
            if settings.mcpgateway_bootstrap_roles_in_db_enabled:
                try:
                    additional_default_roles_path = Path(settings.mcpgateway_bootstrap_roles_in_db_file)
                    # Try multiple locations for the mcpgateway_bootstrap_roles_in_db_file file
                    if not additional_default_roles_path.is_absolute():
                        # Try current directory first
                        if not additional_default_roles_path.exists():
                            # Try project root (mcpgateway/bootstrap_db.py -> parent.parent = repo root)
                            additional_default_roles_path = Path(__file__).resolve().parent.parent / settings.mcpgateway_bootstrap_roles_in_db_file

                    if not additional_default_roles_path.exists():
                        logger.warning(
                            f"Additional roles file not found. Searched: CWD/{SecurityValidator.sanitize_log_message(settings.mcpgateway_bootstrap_roles_in_db_file)}, {SecurityValidator.sanitize_log_message(str(additional_default_roles_path))}"
                        )
                    else:
                        with open(additional_default_roles_path, "r", encoding="utf-8") as f:
                            additional_default_roles_data = json.load(f)

                        # Validate JSON structure: must be a list of dicts with required keys
                        required_keys = {"name", "scope", "permissions"}
                        if not isinstance(additional_default_roles_data, list):
                            logger.error(f"Additional roles file must contain a JSON array, got {type(additional_default_roles_data).__name__}")
                        else:
                            valid_roles = []
                            for idx, role in enumerate(additional_default_roles_data):
                                if not isinstance(role, dict):
                                    logger.warning(f"Skipping invalid role at index {idx}: expected dict, got {type(role).__name__}")
                                    continue
                                missing_keys = required_keys - set(role.keys())
                                if missing_keys:
                                    role_name = role.get("name", f"<index {idx}>")
                                    logger.warning(f"Skipping role '{SecurityValidator.sanitize_log_message(str(role_name))}': missing required keys {missing_keys}")
                                    continue
                                valid_roles.append(role)

                            if valid_roles:
                                default_roles.extend(valid_roles)
                                logger.info(f"Added {len(valid_roles)} additional roles to default roles in bootstrap db")
                            elif additional_default_roles_data:
                                logger.warning("No valid roles found in additional roles file")
                except Exception as e:
                    logger.error(f"Failed to load mcpgateway_bootstrap_roles_in_db_file: {e}")

            # Create or converge default roles
            created_roles = []
            for role_def in default_roles:
                try:
                    # Check if role already exists
                    existing_role = await role_service.get_role_by_name(str(role_def["name"]), str(role_def["scope"]))
                    if existing_role:
                        # Converge permissions for system roles so schema changes are applied
                        expected_perms = set(cast(list[str], role_def["permissions"]))
                        current_perms = set(existing_role.permissions or [])
                        if existing_role.is_system_role and expected_perms != current_perms:
                            logger.info(f"Updating system role {SecurityValidator.sanitize_log_message(str(role_def['name']))} permissions")
                            existing_role.permissions = sorted(expected_perms)
                            db.commit()
                            db.refresh(existing_role)
                        else:
                            logger.info(f"System role {SecurityValidator.sanitize_log_message(str(role_def['name']))} already exists - skipping")
                        created_roles.append(existing_role)
                        continue

                    # Create the role (description and is_system_role are optional)
                    role = await role_service.create_role(
                        name=str(role_def["name"]),
                        description=str(role_def.get("description", "")),
                        scope=str(role_def["scope"]),
                        permissions=cast(list[str], role_def["permissions"]),
                        created_by=settings.platform_admin_email,
                        is_system_role=bool(role_def.get("is_system_role", False)),
                    )
                    created_roles.append(role)
                    logger.info(f"Created system role: {role.name}")

                except Exception as e:
                    logger.error(f"Failed to create role {SecurityValidator.sanitize_log_message(str(role_def['name']))}: {SecurityValidator.sanitize_log_message(str(e))}")
                    continue

            # Assign platform_admin role to admin user
            platform_admin_role = next((r for r in created_roles if r.name == "platform_admin"), None)
            if not platform_admin_role:
                # Role not in created_roles (creation may have failed) — look up from DB as fallback
                platform_admin_role = await role_service.get_role_by_name("platform_admin", "global")
            if platform_admin_role:
                try:
                    # Check if assignment already exists
                    existing_assignment = await role_service.get_user_role_assignment(user_email=admin_user.email, role_id=platform_admin_role.id, scope="global", scope_id=None)

                    if not existing_assignment or not existing_assignment.is_active:
                        await role_service.assign_role_to_user(user_email=admin_user.email, role_id=platform_admin_role.id, scope="global", scope_id=None, granted_by=admin_user.email)
                        logger.info(f"Assigned platform_admin role to {SecurityValidator.sanitize_log_message(admin_user.email)}")
                    else:
                        logger.info("Admin user already has platform_admin role")

                    # Synchronize is_admin flag with platform_admin role assignment
                    # This ensures consistency when admin is manually demoted in DB but role is re-assigned during bootstrap
                    if not admin_user.is_admin:
                        logger.info(f"Synchronizing is_admin flag for {SecurityValidator.sanitize_log_message(admin_user.email)} (was False, setting to True)")
                        admin_user.is_admin = True
                        db.commit()

                except Exception as e:
                    logger.error(
                        f"Failed to assign platform_admin role to {SecurityValidator.sanitize_log_message(admin_user.email)}: {SecurityValidator.sanitize_log_message(str(e))}. Admin UI routes using allow_admin_bypass=False will return 403."
                    )
            else:
                logger.error(
                    f"platform_admin role not found — could not assign to {SecurityValidator.sanitize_log_message(admin_user.email)}. Admin UI routes using allow_admin_bypass=False will return 403."
                )

            logger.info("Default RBAC roles bootstrap completed successfully")

    except Exception as e:
        logger.error(f"Failed to bootstrap default roles: {e}")
        # Don't fail the entire bootstrap process if role creation fails
        return


def normalize_team_visibility(conn: Connection) -> int:
    """Normalize team visibility values to the supported set {private, public}.

    Any team with an unsupported visibility (e.g., 'team') is set to 'private'.

    Args:
        conn: Active SQLAlchemy connection

    Returns:
        int: Number of teams updated
    """
    try:
        # Use session bound to the locked connection
        with Session(bind=conn) as db:
            # Find teams with invalid visibility
            invalid = db.query(EmailTeam).filter(EmailTeam.visibility.notin_(["private", "public"]))
            count = 0
            for team in invalid.all():
                old = team.visibility
                team.visibility = "private"
                count += 1
                logger.info(f"Normalized team visibility: id={team.id} {old} -> private")
            if count:
                db.commit()
            return count
    except Exception as e:
        logger.error(f"Failed to normalize team visibility: {e}")
        return 0


async def bootstrap_resource_assignments(conn: Connection) -> None:
    """Assign orphaned resources to the platform admin's personal team.

    This ensures existing resources (from pre-multitenancy versions) are
    visible in the new team-based UI by assigning them to the admin's
    personal team with public visibility.

    Args:
        conn: Active SQLAlchemy connection
    """
    if not settings.email_auth_enabled:
        logger.info("Email authentication disabled - skipping resource assignment")
        return

    try:
        # Use session bound to the locked connection
        with Session(bind=conn) as db:
            # Find admin user and their personal team
            admin_user = db.query(EmailUser).filter(EmailUser.email == settings.platform_admin_email, EmailUser.is_admin.is_(True)).first()

            if not admin_user:
                logger.warning("Admin user not found - skipping resource assignment")
                return

            personal_team = admin_user.get_personal_team()
            if not personal_team:
                logger.warning("Admin personal team not found - skipping resource assignment")
                return

            logger.info(f"Assigning orphaned resources to admin team: {SecurityValidator.sanitize_log_message(personal_team.name)}")

            # Resource types to process
            resource_types = [("servers", Server), ("tools", Tool), ("resources", Resource), ("prompts", Prompt), ("gateways", Gateway), ("a2a_agents", A2AAgent)]

            total_assigned = 0

            # Unique field per resource type that participates in the team-scoped unique constraint
            unique_field: dict[str, str] = {
                "servers": "name",
                "tools": "name",
                "resources": "uri",
                "prompts": "name",
                "gateways": "slug",
                "a2a_agents": "slug",
            }

            def _like_safe(v: str) -> str:
                """Escape SQL LIKE wildcard characters for safe use in LIKE patterns.

                Args:
                    v: The string value to escape.

                Returns:
                    The escaped string safe for use in SQL LIKE patterns.
                """
                return v.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")

            for resource_name, resource_model in resource_types:
                try:
                    # Find unassigned resources
                    unassigned = db.query(resource_model).filter((resource_model.team_id.is_(None)) | (resource_model.owner_email.is_(None)) | (resource_model.visibility.is_(None))).all()

                    if not unassigned:
                        continue

                    logger.info(f"Assigning {len(unassigned)} orphaned {resource_name} to admin team")

                    field = unique_field[resource_name]
                    field_col = getattr(resource_model, field)

                    # Collect unique field values from the orphaned batch
                    original_values = {getattr(r, field) for r in unassigned if getattr(r, field) is not None}

                    # One query: fetch all names already taken in the admin team that match any
                    # original value exactly or as a suffixed variant (value-N).
                    # NOTE: This intentionally omits gateway_id from the filter, making it
                    # conservative — for Resource/Prompt models whose uniqueness also depends
                    # on gateway_id, this may produce unnecessary renames but can never miss a
                    # real conflict. That is the correct tradeoff for one-time bootstrap code.
                    existing_taken: set[str] = (
                        {
                            row[0]
                            for row in db.query(field_col).filter(
                                resource_model.team_id == personal_team.id,
                                resource_model.owner_email == admin_user.email,
                                or_(*[cond for v in original_values for cond in (field_col == v, field_col.like(f"{_like_safe(v)}-%", escape="\\"))]),
                            )
                        }
                        if original_values
                        else set()
                    )

                    # Pre-compile suffix regexes keyed by original value
                    suffix_res = {v: re.compile(rf"^{re.escape(v)}-(\d+)$") for v in original_values}

                    # Track names claimed within this batch to catch intra-batch duplicates
                    batch_assigned: set[str] = set()

                    for resource in unassigned:
                        original_value = getattr(resource, field)

                        if original_value is not None:
                            taken = existing_taken | batch_assigned
                            if original_value in taken:
                                # Parse numeric suffixes from taken values to find next free one
                                suffix_re = suffix_res[original_value]
                                used = {int(m.group(1)) for v in taken if (m := suffix_re.match(v))}
                                new_value = f"{original_value}-{(max(used) if used else 1) + 1}"
                                logger.warning(
                                    f"Name conflict for {SecurityValidator.sanitize_log_message(resource_name)} '{SecurityValidator.sanitize_log_message(original_value)}' — renaming to '{SecurityValidator.sanitize_log_message(new_value)}'"
                                )
                                setattr(resource, field, new_value)
                                batch_assigned.add(new_value)
                            else:
                                batch_assigned.add(original_value)

                        resource.team_id = personal_team.id
                        resource.owner_email = admin_user.email
                        resource.visibility = "public"  # Make visible to all users
                        if hasattr(resource, "federation_source") and not resource.federation_source:
                            resource.federation_source = "mcpgateway-0.7.0-migration"

                    db.commit()
                    total_assigned += len(unassigned)

                except Exception as e:
                    logger.error(f"Failed to assign {SecurityValidator.sanitize_log_message(resource_name)}: {SecurityValidator.sanitize_log_message(str(e))}")
                    continue

            if total_assigned > 0:
                logger.info(f"Successfully assigned {total_assigned} orphaned resources to admin team")
            else:
                logger.info("No orphaned resources found - all resources have team assignments")

    except Exception as e:
        logger.error(f"Failed to bootstrap resource assignments: {e}")


async def main() -> None:
    """
    Bootstrap or upgrade the database schema, then log readiness.

    Runs `create_all()` + `alembic stamp head` on an empty DB, otherwise just
    executes `alembic upgrade head`, leaving application data intact.
    Also creates the platform admin user if email authentication is enabled.

    Uses distributed advisory locks (PG) or file locking (SQLite)
    to prevent race conditions when multiple workers start simultaneously.

    Fast-path: when the schema is already at the Alembic head revision (e.g. after
    an init container ran migrations, or on any restart after the first), the advisory
    lock and `alembic upgrade head` are skipped entirely.  Only the idempotent bootstrap
    helpers (admin user, roles, resource assignments) are re-run.

    Args:
        None

    Raises:
        Exception: If migration or bootstrap fails
    """
    engine = create_engine(settings.database_url)
    cfg = make_alembic_cfg(settings.database_url, configure_logger=True)

    # SQLite multi-replica guard: /tmp is per-container, so FileLock provides no
    # cross-container coordination. All replicas run migrations concurrently
    # against the same SQLite file — a silent correctness bug.
    is_sqlite = settings.database_url.startswith("sqlite")
    gateway_replicas = int(os.environ.get("GATEWAY_REPLICAS", "1"))
    if is_sqlite and gateway_replicas > 1:
        logger.warning(
            "SQLite detected with GATEWAY_REPLICAS=%d. The migration file lock at '%s' is stored in "
            "/tmp which is NOT shared across containers — each container holds its own lock file. "
            "All replicas run migrations concurrently with no cross-container coordination. "
            "Use GATEWAY_REPLICAS=1 with SQLite, or switch to PostgreSQL for multi-replica deployments.",
            gateway_replicas,
            _MIGRATION_LOCK_PATH,
        )

    # MCPGATEWAY_SKIP_MIGRATIONS: external tooling (init container, CI pipeline)
    # already ran alembic upgrade head — skip schema migration and run only the
    # idempotent bootstrap helpers. If the schema is NOT at head, the init
    # container failed or the wrong DB was targeted; fail fast so the deployment
    # error is visible.
    if settings.mcpgateway_skip_migrations:
        try:
            with engine.connect() as conn:
                conn.commit()
                if not alembic_at_head(conn, cfg):
                    logger.error("MCPGATEWAY_SKIP_MIGRATIONS=true but schema is not at head — run 'alembic upgrade head' before starting the application")
                    raise RuntimeError("Schema not at head; migrations required before startup")
                logger.info("MCPGATEWAY_SKIP_MIGRATIONS=true — schema already at head, skipping migration")
                await _run_post_migration_bootstrap(conn)
                conn.commit()
        except Exception as e:
            logger.error(f"Bootstrap failed: {e}")
            raise
        finally:
            engine.dispose()
        logger.info("Database ready")
        return

    try:
        # Fast path: if the schema is already at the current Alembic head,
        # skip the migration advisory lock entirely. This is critical for
        # deployments behind a transaction-pooling connection pooler — the
        # session-scoped advisory lock can be orphaned across pgbouncer's
        # backend handoffs, which would otherwise make N-th pod startup
        # spin indefinitely. Replicas 2..N take this branch on normal
        # restarts.
        with engine.connect() as probe_conn:
            probe_conn.commit()
            if alembic_at_head(probe_conn, cfg):
                logger.info("Schema already at Alembic head; skipping migration lock")
                await _run_post_migration_bootstrap(probe_conn)
                probe_conn.commit()
                return

        # Slow path: acquire the migration advisory lock and run schema work.
        with engine.connect() as conn:
            # Commit any open transaction on the connection before locking (though it should be fresh)
            conn.commit()

            with advisory_lock(conn):
                logger.info("Acquired migration lock, checking database schema...")

                # Pass the LOCKED connection to Alembic config
                cfg.attributes["connection"] = conn
                logger.info("Running Alembic migrations to ensure schema is up to date")
                command.upgrade(cfg, "head")

                await _run_post_migration_bootstrap(conn)
                conn.commit()  # Ensure all migration changes are permanently committed

    except Exception as e:
        logger.error(f"Database migration failed: {e}")
        # Allow retry logic or container restart to handle transient issues
        raise
    finally:
        # Dispose the engine to close all connections in the pool
        engine.dispose()
    logger.info("Database ready")


if __name__ == "__main__":
    asyncio.run(main())
