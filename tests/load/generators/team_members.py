# -*- coding: utf-8 -*-
"""Team member generator for load testing."""

import random
import uuid
from datetime import datetime
from typing import Generator, List

from mcpgateway.db import EmailTeamMember

from ..utils.distributions import exponential_decay_temporal, power_law_distribution
from .base import BaseGenerator


class TeamMemberGenerator(BaseGenerator):
    """Generate EmailTeamMember records with realistic team size distribution."""

    def get_count(self) -> int:
        """Get estimated number of team members."""
        # This is approximate - actual count depends on distribution
        user_count = self.get_scale_config("users", 100)
        team_count = self.get_scale_config("users", 100) * (
            self.get_scale_config("personal_teams_per_user", 1) +
            self.get_scale_config("additional_teams_per_user", 10)
        )
        avg_members = (self.get_scale_config("members_per_team_min", 1) +
                       self.get_scale_config("members_per_team_max", 100)) / 2
        return int(team_count * avg_members)

    def get_dependencies(self) -> List[str]:
        """Team members depend on users and teams."""
        return ["UserGenerator", "TeamGenerator"]

    def generate(self) -> Generator[EmailTeamMember, None, None]:
        """Generate team member records.

        Yields:
            EmailTeamMember instances
        """
        from sqlalchemy import text

        user_count = self.get_scale_config("users", 100)
        personal_teams_per_user = self.get_scale_config("personal_teams_per_user", 1)
        additional_teams_per_user = self.get_scale_config("additional_teams_per_user", 10)

        min_members = self.get_scale_config("members_per_team_min", 1)
        max_members = self.get_scale_config("members_per_team_max", 100)
        distribution = self.get_scale_config("members_per_team_distribution", "power_law")

        # Get temporal distribution
        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        total_teams = user_count * (personal_teams_per_user + additional_teams_per_user)

        # Fetch actual team IDs from database
        result = self.db.execute(
            text("SELECT id, created_by FROM email_teams WHERE created_by LIKE :domain ORDER BY created_at"),
            {"domain": f"%{self.email_domain}"}
        )
        teams = [(row[0], row[1]) for row in result.fetchall()]

        if len(teams) != total_teams:
            self.logger.warning(f"Expected {total_teams} teams, found {len(teams)}")

        # Generate team sizes using power law distribution
        if distribution == "power_law":
            team_sizes = power_law_distribution(len(teams), min_members, max_members)
        else:
            team_sizes = [random.randint(min_members, max_members) for _ in range(len(teams))]

        # Calculate total members needed
        total_members = sum(team_sizes)
        timestamps = exponential_decay_temporal(total_members, start_date, end_date, recent_percent)

        member_idx = 0
        team_idx = 0

        # Generate members for each team
        for team_id, team_owner in teams:
            if team_idx >= len(team_sizes):
                break

            team_size = team_sizes[team_idx]
            team_idx += 1

            # Track members added to this team to avoid duplicates
            team_members_set = set()

            # Owner membership
            member_id = str(uuid.uuid4())
            member = EmailTeamMember(
                id=member_id,
                team_id=team_id,
                user_email=team_owner,
                role="owner",
                joined_at=timestamps[member_idx] if member_idx < len(timestamps) else end_date,
                is_active=True,
            )
            team_members_set.add(team_owner)
            member_idx += 1
            yield member

            # Additional members for this team
            attempts = 0
            max_attempts = user_count * 2  # Prevent infinite loop
            while len(team_members_set) < min(team_size, user_count) and attempts < max_attempts:
                if member_idx >= len(timestamps):
                    break

                attempts += 1

                # Random user from pool
                random_user_idx = random.randint(0, user_count - 1)
                random_user_email = f"user{random_user_idx+1}@{self.email_domain}"

                # Skip if already in team
                if random_user_email in team_members_set:
                    continue

                team_members_set.add(random_user_email)
                member_id = str(uuid.uuid4())
                member = EmailTeamMember(
                    id=member_id,
                    team_id=team_id,
                    user_email=random_user_email,
                    role=random.choice(["member", "admin"]),
                    joined_at=timestamps[member_idx],
                    is_active=True,
                )
                member_idx += 1
                yield member
