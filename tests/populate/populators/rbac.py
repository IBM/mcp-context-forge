# -*- coding: utf-8 -*-
"""RBAC populator - creates custom roles and assigns roles to users."""

# Standard
import logging
import random
from typing import Any, Dict, List

# Local
from .base import BasePopulator

logger = logging.getLogger(__name__)

# Custom roles to create (beyond built-in platform_admin, team_admin, developer, viewer)
CUSTOM_ROLES = [
    {
        "name": "loadtest_operator",
        "description": "Load test operator with read/execute access",
        "scope": "global",
        "permissions": ["tools.read", "tools.execute", "resources.read", "prompts.read"],
    },
    {
        "name": "loadtest_analyst",
        "description": "Load test analyst with read-only access",
        "scope": "global",
        "permissions": ["tools.read", "resources.read", "prompts.read", "servers.read"],
    },
    {
        "name": "loadtest_deployer",
        "description": "Load test deployer with server management access",
        "scope": "team",
        "permissions": ["servers.read", "servers.create", "servers.update", "gateways.read", "gateways.create"],
    },
]

# Built-in roles available for assignment
ASSIGNABLE_ROLES = ["developer", "viewer", "team_admin"]


class RBACPopulator(BasePopulator):
    """Create custom RBAC roles and assign roles to users."""

    def get_name(self) -> str:
        return "rbac"

    def get_count(self) -> int:
        # Custom roles + role assignments (one per user)
        user_count = self.get_scale_config("users", 100)
        return len(CUSTOM_ROLES) + user_count

    def get_dependencies(self) -> List[str]:
        return ["users", "teams"]

    async def populate(self) -> Dict[str, Any]:
        roles_created = 0
        roles_errors = 0
        assigns_created = 0
        assigns_errors = 0

        # Step 1: Create custom roles (admin-only) and collect role IDs
        # Maps role name -> {"id": ..., "scope": ...}
        role_info_map: Dict[str, Dict[str, str]] = {}

        for role_def in CUSTOM_ROLES:
            try:
                resp = await self.client.post(
                    "/rbac/roles",
                    json=role_def,
                    expected_status=[200, 201, 409],
                )
                if resp.status_code in (200, 201):
                    roles_created += 1
                    try:
                        data = resp.json()
                        if isinstance(data, dict) and "id" in data:
                            role_info_map[role_def["name"]] = {"id": data["id"], "scope": data.get("scope", role_def.get("scope", "global"))}
                    except Exception:
                        pass
                elif resp.status_code == 409:
                    roles_created += 1
                else:
                    roles_errors += 1
            except Exception as exc:
                roles_errors += 1
                logger.debug(f"Failed to create role {role_def['name']}: {exc}")

            if self.progress_tracker:
                self.progress_tracker.update(self.get_name(), 1)

        # Fetch all roles to build complete role map (includes built-in roles)
        try:
            resp = await self.client.get("/rbac/roles", expected_status=[200])
            if resp.status_code == 200:
                roles_data = resp.json()
                role_list = roles_data if isinstance(roles_data, list) else roles_data.get("items", [])
                for r in role_list:
                    if isinstance(r, dict) and "name" in r and "id" in r:
                        role_info_map[r["name"]] = {"id": r["id"], "scope": r.get("scope", "global")}
        except Exception as exc:
            logger.debug(f"Failed to fetch roles list: {exc}")

        # Step 2: Assign roles to users
        user_emails = self.existing_data.get("user_emails", [])
        team_ids = self.existing_data.get("team_ids", [])
        all_role_names = ASSIGNABLE_ROLES + [r["name"] for r in CUSTOM_ROLES]
        # Filter to roles we have info for
        assignable = [name for name in all_role_names if name in role_info_map]
        if not assignable:
            logger.warning("No role IDs available for assignment, skipping")
            return {"created": roles_created, "errors": roles_errors, "roles_created": roles_created, "role_assignments": 0, "ids": []}

        if not user_emails:
            logger.warning("No user emails available for role assignment")
            return {"created": roles_created, "errors": roles_errors, "roles_created": roles_created, "role_assignments": 0, "ids": []}

        payloads = []
        for email in user_emails:
            role_name = random.choice(assignable)
            role_info = role_info_map[role_name]
            role_id = role_info["id"]
            role_scope = role_info["scope"]

            # Match assignment scope to role scope
            if role_scope == "team" and team_ids:
                scope = "team"
                scope_id = random.choice(team_ids)
            elif role_scope == "team" and not team_ids:
                # Team-scoped role but no teams available - pick a global role instead
                global_roles = [n for n in assignable if role_info_map[n]["scope"] == "global"]
                if global_roles:
                    role_name = random.choice(global_roles)
                    role_info = role_info_map[role_name]
                    role_id = role_info["id"]
                    scope = "global"
                    scope_id = None
                else:
                    continue
            else:
                scope = "global"
                scope_id = None

            payloads.append((email, {"role_id": role_id, "scope": scope, "scope_id": scope_id}))

        update_count = 0

        async def _assign_role(email: str, payload: Dict[str, Any]):
            nonlocal assigns_created, assigns_errors, update_count
            try:
                resp = await self.client.post(
                    f"/rbac/users/{email}/roles",
                    json=payload,
                    expected_status=[200, 201, 400, 409],
                )
                if resp.status_code in (200, 201, 409):
                    assigns_created += 1
                else:
                    assigns_errors += 1
            except Exception:
                assigns_errors += 1

            update_count += 1
            if self.progress_tracker and update_count % self.progress_update_frequency == 0:
                self.progress_tracker.update(self.get_name(), self.progress_update_frequency)
                self.progress_tracker.refresh()

        # Standard
        import asyncio

        for batch_start in range(0, len(payloads), self.batch_concurrency):
            batch = payloads[batch_start : batch_start + self.batch_concurrency]
            await asyncio.gather(*[_assign_role(email, payload) for email, payload in batch])

        # Final progress update
        if self.progress_tracker:
            remainder = update_count % self.progress_update_frequency
            if remainder > 0:
                self.progress_tracker.update(self.get_name(), remainder)

        return {
            "created": roles_created + assigns_created,
            "errors": roles_errors + assigns_errors,
            "roles_created": roles_created,
            "role_assignments": assigns_created,
            "ids": list(role_info_map.keys()),
        }
