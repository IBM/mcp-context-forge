# -*- coding: utf-8 -*-
"""Team populator - creates teams via POST /teams."""

# Standard
import asyncio
import logging
import random
from typing import Any, Dict, List

# Local
from .base import BasePopulator

logger = logging.getLogger(__name__)


class TeamPopulator(BasePopulator):
    """Create teams via REST API and assign members."""

    def get_name(self) -> str:
        return "teams"

    def get_count(self) -> int:
        user_count = self.get_scale_config("users", 100)
        additional = self.get_scale_config("additional_teams_per_user", 5)
        return user_count * additional

    def get_dependencies(self) -> List[str]:
        return ["users"]

    async def populate(self) -> Dict[str, Any]:
        user_count = self.get_scale_config("users", 100)
        additional_per_user = self.get_scale_config("additional_teams_per_user", 5)
        private_percent = self.get_scale_config("teams_private_percent", 60)
        members_min = self.get_scale_config("members_per_team_min", 1)
        members_max = self.get_scale_config("members_per_team_max", 10)

        created = 0
        errors = 0
        team_ids: List[str] = []
        update_count = 0

        async def _create_team(user_i: int, team_j: int):
            nonlocal created, errors, update_count
            email = f"user{user_i + 1}@{self.email_domain}"
            token = self.client.user_tokens.get(email, self.client.admin_token)

            team_name = f"{self.faker.company()}-{user_i + 1}-{team_j + 1}".lower().replace(" ", "-").replace(",", "").replace(".", "")[:60]
            is_private = random.random() < (private_percent / 100)

            try:
                resp = await self.client.post(
                    "/teams/",
                    json={
                        "name": team_name,
                        "description": self.faker.catch_phrase(),
                        "visibility": "private" if is_private else "public",
                    },
                    token=token,
                    expected_status=[200, 201, 409],
                )
                if resp.status_code in (200, 201):
                    created += 1
                    try:
                        data = resp.json()
                        tid = data.get("id")
                        if tid:
                            team_ids.append(tid)
                    except Exception:
                        pass
                elif resp.status_code == 409:
                    created += 1  # Already exists, count as success
                else:
                    errors += 1
            except Exception as exc:
                errors += 1
                logger.debug(f"Failed to create team {team_name}: {exc}")

            update_count += 1
            if self.progress_tracker and update_count % self.progress_update_frequency == 0:
                self.progress_tracker.update(self.get_name(), self.progress_update_frequency)
                self.progress_tracker.refresh()

        # Build all (user_i, team_j) pairs and process in batches
        tasks = [(ui, tj) for ui in range(user_count) for tj in range(additional_per_user)]

        for batch_start in range(0, len(tasks), self.batch_concurrency):
            batch = tasks[batch_start : batch_start + self.batch_concurrency]
            await asyncio.gather(*[_create_team(ui, tj) for ui, tj in batch])

        # Final progress update
        if self.progress_tracker:
            remainder = update_count % self.progress_update_frequency
            if remainder > 0:
                self.progress_tracker.update(self.get_name(), remainder)

        self.existing_data["team_ids"] = team_ids

        # Invite members to teams (subset for performance)
        invite_count = 0
        if team_ids and len(self.client.user_tokens) > 1:
            invite_count = await self._invite_members(team_ids, members_min, members_max)

        return {
            "created": created,
            "errors": errors,
            "ids": team_ids,
            "invitations_sent": invite_count,
        }

    async def _invite_members(self, team_ids: List[str], members_min: int, members_max: int) -> int:
        """Invite random users to a subset of teams."""
        user_emails = self.existing_data.get("user_emails", [])
        if not user_emails or not team_ids:
            return 0

        invite_count = 0
        # Invite to a subset of teams to keep it manageable
        invite_sample_size = min(len(team_ids), self.get_scale_config("users", 100))
        sample_teams = random.sample(team_ids, min(invite_sample_size, len(team_ids)))

        async def _invite_to_team(team_id: str):
            nonlocal invite_count
            num_members = random.randint(members_min, min(members_max, len(user_emails)))
            invitees = random.sample(user_emails, min(num_members, len(user_emails)))

            for invitee_email in invitees:
                try:
                    resp = await self.client.post(
                        f"/teams/{team_id}/invitations",
                        json={"email": invitee_email, "role": "member"},
                        expected_status=[200, 201, 400, 409],  # 400/409 = already member
                    )
                    if resp.status_code in (200, 201):
                        invite_count += 1
                        # Accept invitation
                        try:
                            invite_data = resp.json()
                            invite_token = invite_data.get("token")
                            if invite_token:
                                user_jwt = self.client.user_tokens.get(invitee_email, self.client.admin_token)
                                await self.client.post(
                                    f"/teams/invitations/{invite_token}/accept",
                                    token=user_jwt,
                                    expected_status=[200, 201, 400],
                                )
                        except Exception:
                            pass
                except Exception:
                    pass

        for batch_start in range(0, len(sample_teams), self.batch_concurrency):
            batch = sample_teams[batch_start : batch_start + self.batch_concurrency]
            await asyncio.gather(*[_invite_to_team(tid) for tid in batch])

        return invite_count
