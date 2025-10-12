# -*- coding: utf-8 -*-
"""Team generator for load testing."""

import random
import uuid
from datetime import datetime
from typing import Generator, List

from mcpgateway.db import EmailTeam

from ..utils.distributions import exponential_decay_temporal
from .base import BaseGenerator


class TeamGenerator(BaseGenerator):
    """Generate EmailTeam records with realistic data."""

    def get_count(self) -> int:
        """Get total number of teams to generate."""
        user_count = self.get_scale_config("users", 100)
        personal_teams = self.get_scale_config("personal_teams_per_user", 1)
        additional_teams = self.get_scale_config("additional_teams_per_user", 10)
        return user_count * (personal_teams + additional_teams)

    def get_dependencies(self) -> List[str]:
        """Teams depend on users."""
        return ["UserGenerator"]

    def generate(self) -> Generator[EmailTeam, None, None]:
        """Generate team records.

        Yields:
            EmailTeam instances
        """
        user_count = self.get_scale_config("users", 100)
        personal_teams_per_user = self.get_scale_config("personal_teams_per_user", 1)
        additional_teams_per_user = self.get_scale_config("additional_teams_per_user", 10)
        private_percent = self.get_scale_config("teams_private_percent", 60)

        # Get temporal distribution
        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        total_teams = self.get_count()
        timestamps = exponential_decay_temporal(total_teams, start_date, end_date, recent_percent)

        team_idx = 0

        # Generate teams for each user
        for user_i in range(user_count):
            user_email = f"user{user_i+1}@{self.email_domain}"

            # Personal team(s)
            for _ in range(personal_teams_per_user):
                team_id = str(uuid.uuid4())
                slug = f"personal-user{user_i+1}"
                team = EmailTeam(
                    id=team_id,
                    name=f"personal-user{user_i+1}",
                    slug=slug,
                    description=f"Personal team for {user_email}",
                    created_by=user_email,
                    visibility="private",
                    is_personal=True,
                    is_active=True,
                    created_at=timestamps[team_idx],
                    updated_at=timestamps[team_idx],
                )
                team_idx += 1
                yield team

            # Additional teams
            for j in range(additional_teams_per_user):
                team_id = str(uuid.uuid4())
                is_private = random.random() < (private_percent / 100)
                name = f"{self.faker.company()}-{user_i+1}-{j+1}".lower().replace(" ", "-")
                slug = f"{name}-{team_id[:8]}"  # Add UUID prefix to ensure uniqueness

                team = EmailTeam(
                    id=team_id,
                    name=name,
                    slug=slug,
                    description=self.faker.catch_phrase(),
                    created_by=user_email,
                    visibility="private" if is_private else "public",
                    is_personal=False,
                    is_active=True,
                    created_at=timestamps[team_idx],
                    updated_at=timestamps[team_idx],
                )
                team_idx += 1
                yield team
