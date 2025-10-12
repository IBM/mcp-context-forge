# -*- coding: utf-8 -*-
"""Workflow state generators for load testing."""

import random
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Generator, List

from sqlalchemy import text

from mcpgateway.db import (
    EmailTeamInvitation,
    EmailTeamJoinRequest,
    TokenRevocation,
    OAuthToken,
)

from ..utils.distributions import exponential_decay_temporal
from .base import BaseGenerator


class TeamInvitationGenerator(BaseGenerator):
    """Generate team invitation records."""

    def get_count(self) -> int:
        """Get total number of team invitations to generate."""
        team_count = self.get_scale_config("teams_per_user_avg", 6) * self.get_scale_config("users", 100)
        invitations_per_team = self.get_scale_config("invitations_per_team_avg", 2)
        return int(team_count * invitations_per_team)

    def get_dependencies(self) -> List[str]:
        """Depends on teams and users."""
        return ["TeamGenerator", "UserGenerator"]

    def generate(self) -> Generator[EmailTeamInvitation, None, None]:
        """Generate team invitation records.

        Yields:
            EmailTeamInvitation instances
        """
        team_result = self.db.execute(text("SELECT id, created_by FROM email_teams ORDER BY created_at"))
        teams = [(row[0], row[1]) for row in team_result.fetchall()]

        if not teams:
            self.logger.warning("No teams found - cannot generate invitations")
            return

        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))

        # Generate fake email addresses for invitations
        fake_domains = ["example.com", "test.com", self.email_domain]
        roles = ["viewer", "developer", "admin"]

        invitation_rate = self.get_scale_config("invitation_generation_rate", 0.3)  # 30% of teams have invitations
        teams_with_invitations = random.sample(teams, int(len(teams) * invitation_rate))

        for team_id, created_by in teams_with_invitations:
            num_invitations = random.randint(1, 5)

            for _ in range(num_invitations):
                invited_at = start_date + (end_date - start_date) * random.random()
                expires_at = invited_at + timedelta(days=random.choice([7, 14, 30]))

                # 80% active, 20% expired/used
                is_active = random.random() < 0.8

                yield EmailTeamInvitation(
                    id=str(uuid.uuid4()),
                    team_id=team_id,
                    email=f"invited-{random.randint(1, 100000)}@{random.choice(fake_domains)}",
                    role=random.choice(roles),
                    invited_by=created_by,
                    invited_at=invited_at,
                    expires_at=expires_at,
                    token=secrets.token_urlsafe(32),
                    is_active=is_active,
                )


class TeamJoinRequestGenerator(BaseGenerator):
    """Generate team join request records."""

    def get_count(self) -> int:
        """Get total number of join requests to generate."""
        team_count = self.get_scale_config("teams_per_user_avg", 6) * self.get_scale_config("users", 100)
        requests_per_team = self.get_scale_config("join_requests_per_team_avg", 1)
        return int(team_count * requests_per_team)

    def get_dependencies(self) -> List[str]:
        """Depends on teams and users."""
        return ["TeamGenerator", "UserGenerator"]

    def generate(self) -> Generator[EmailTeamJoinRequest, None, None]:
        """Generate team join request records.

        Yields:
            EmailTeamJoinRequest instances
        """
        team_result = self.db.execute(text("SELECT id FROM email_teams ORDER BY created_at"))
        team_ids = [row[0] for row in team_result.fetchall()]

        user_result = self.db.execute(text("SELECT email FROM email_users ORDER BY created_at"))
        user_emails = [row[0] for row in user_result.fetchall()]

        if not team_ids or not user_emails:
            self.logger.warning("No teams or users found - cannot generate join requests")
            return

        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))

        request_rate = self.get_scale_config("join_request_generation_rate", 0.2)  # 20% of teams
        teams_with_requests = random.sample(team_ids, int(len(team_ids) * request_rate))

        statuses = ["pending", "pending", "approved", "rejected"]

        for team_id in teams_with_requests:
            num_requests = random.randint(1, 3)
            selected_users = random.sample(user_emails, min(num_requests, len(user_emails)))

            for user_email in selected_users:
                requested_at = start_date + (end_date - start_date) * random.random()
                expires_at = requested_at + timedelta(days=30)
                status = random.choice(statuses)

                reviewed_at = None
                reviewed_by = None
                if status in ["approved", "rejected"]:
                    reviewed_at = requested_at + timedelta(days=random.randint(1, 7))
                    reviewed_by = random.choice(user_emails)

                yield EmailTeamJoinRequest(
                    id=str(uuid.uuid4()),
                    team_id=team_id,
                    user_email=user_email,
                    message=self.faker.sentence() if random.random() < 0.5 else None,
                    status=status,
                    requested_at=requested_at,
                    expires_at=expires_at,
                    reviewed_at=reviewed_at,
                    reviewed_by=reviewed_by,
                    notes=self.faker.sentence() if reviewed_at and random.random() < 0.3 else None,
                )


class TokenRevocationGenerator(BaseGenerator):
    """Generate token revocation records."""

    def get_count(self) -> int:
        """Get total number of revoked tokens to generate."""
        token_count = self.get_scale_config("users", 100) * self.get_scale_config("tokens_per_user_avg", 3)
        revocation_rate = self.get_scale_config("token_revocation_rate", 0.05)  # 5% revoked
        return int(token_count * revocation_rate)

    def get_dependencies(self) -> List[str]:
        """Depends on tokens."""
        return ["TokenGenerator"]

    def generate(self) -> Generator[TokenRevocation, None, None]:
        """Generate token revocation records.

        Yields:
            TokenRevocation instances
        """
        token_result = self.db.execute(text("SELECT jti, user_email, created_at FROM email_api_tokens ORDER BY created_at"))
        tokens = [(row[0], row[1], datetime.fromisoformat(row[2]) if isinstance(row[2], str) else row[2]) for row in token_result.fetchall()]

        if not tokens:
            self.logger.warning("No tokens found - cannot generate revocations")
            return

        user_result = self.db.execute(text("SELECT email FROM email_users ORDER BY created_at"))
        user_emails = [row[0] for row in user_result.fetchall()]

        revocation_rate = self.get_scale_config("token_revocation_rate", 0.05)
        tokens_to_revoke = random.sample(tokens, int(len(tokens) * revocation_rate))

        for jti, user_email, created_at in tokens_to_revoke:
            # Revoked some time after creation
            revoked_at = created_at + timedelta(days=random.randint(1, 90))

            yield TokenRevocation(
                jti=jti,
                revoked_at=revoked_at,
                revoked_by=user_email,  # Usually self-revoked
                reason=random.choice([
                    "User requested",
                    "Security policy",
                    "Token compromised",
                    "Administrative action",
                    None,
                ]),
            )


class OAuthTokenGenerator(BaseGenerator):
    """Generate OAuth token records for gateway authentication."""

    def get_count(self) -> int:
        """Get total number of OAuth tokens to generate."""
        gateway_count = self.get_scale_config("gateways", 100)
        user_count = self.get_scale_config("users", 100)
        # Not all users have OAuth tokens for all gateways
        oauth_rate = self.get_scale_config("oauth_token_rate", 0.1)  # 10% of user-gateway combinations
        return int(gateway_count * user_count * oauth_rate)

    def get_dependencies(self) -> List[str]:
        """Depends on gateways and users."""
        return ["GatewayGenerator", "UserGenerator"]

    def generate(self) -> Generator[OAuthToken, None, None]:
        """Generate OAuth token records.

        Yields:
            OAuthToken instances
        """
        gateway_result = self.db.execute(text("SELECT id FROM gateways ORDER BY created_at"))
        gateway_ids = [row[0] for row in gateway_result.fetchall()]

        user_result = self.db.execute(text("SELECT email FROM email_users ORDER BY created_at"))
        user_emails = [row[0] for row in user_result.fetchall()]

        if not gateway_ids or not user_emails:
            self.logger.warning("No gateways or users found - cannot generate OAuth tokens")
            return

        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))

        oauth_rate = self.get_scale_config("oauth_token_rate", 0.1)

        # Generate random gateway-user pairs
        num_tokens = int(len(gateway_ids) * len(user_emails) * oauth_rate)
        generated_pairs = set()

        for _ in range(num_tokens):
            gateway_id = random.choice(gateway_ids)
            user_email = random.choice(user_emails)
            pair = (gateway_id, user_email)

            if pair in generated_pairs:
                continue

            generated_pairs.add(pair)

            created_at = start_date + (end_date - start_date) * random.random()
            updated_at = created_at + timedelta(days=random.randint(0, 30))
            expires_at = created_at + timedelta(days=random.choice([30, 60, 90, 365]))

            yield OAuthToken(
                id=str(uuid.uuid4()),
                gateway_id=gateway_id,
                user_id=user_email,  # Column is user_id but references email
                app_user_email=user_email,
                access_token=f"ya29.{secrets.token_urlsafe(64)}",
                refresh_token=f"1//{secrets.token_urlsafe(32)}" if random.random() < 0.8 else None,
                token_type="Bearer",
                expires_at=expires_at,
                scopes=["read", "write"] if random.random() < 0.5 else ["read"],
                created_at=created_at,
                updated_at=updated_at,
            )
