# -*- coding: utf-8 -*-
"""API token generator for load testing."""

import random
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Generator, List

from mcpgateway.db import EmailApiToken

from ..utils.distributions import exponential_decay_temporal, normal_distribution
from .base import BaseGenerator


class TokenGenerator(BaseGenerator):
    """Generate EmailApiToken records with realistic distribution."""

    def get_count(self) -> int:
        """Get total number of tokens to generate."""
        user_count = self.get_scale_config("users", 100)
        avg_tokens = self.get_scale_config("tokens_per_user_avg", 5)
        return int(user_count * avg_tokens)

    def get_dependencies(self) -> List[str]:
        """Tokens depend on users."""
        return ["UserGenerator"]

    def generate(self) -> Generator[EmailApiToken, None, None]:
        """Generate API token records.

        Yields:
            EmailApiToken instances
        """
        user_count = self.get_scale_config("users", 100)
        min_tokens = self.get_scale_config("tokens_per_user_min", 1)
        max_tokens = self.get_scale_config("tokens_per_user_max", 10)
        avg_tokens = self.get_scale_config("tokens_per_user_avg", 5)
        active_percent = self.get_scale_config("tokens_active_percent", 90)

        # Get temporal distribution
        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        # Generate tokens per user using normal distribution
        tokens_per_user = normal_distribution(user_count, min_tokens, max_tokens, avg_tokens)
        total_tokens = sum(tokens_per_user)

        timestamps = exponential_decay_temporal(total_tokens, start_date, end_date, recent_percent)

        token_idx = 0

        for user_i in range(user_count):
            user_email = f"user{user_i+1}@{self.email_domain}"
            num_tokens = tokens_per_user[user_i]

            for j in range(num_tokens):
                token_id = str(uuid.uuid4())
                token_value = secrets.token_urlsafe(32)
                is_active = random.random() < (active_percent / 100)

                # Random scopes
                scopes = random.sample(
                    ["tools:read", "tools:write", "resources:read", "resources:write",
                     "prompts:read", "prompts:write", "servers:read", "servers:write"],
                    k=random.randint(1, 4)
                )

                # Token expires in 1-365 days
                expires_days = random.randint(1, 365)
                expires_at = timestamps[token_idx] + timedelta(days=expires_days)

                token = EmailApiToken(
                    id=token_id,
                    name=f"Token {j+1} for {user_email}",
                    description=self.faker.sentence(),
                    user_email=user_email,
                    jti=str(uuid.uuid4()),  # JWT ID
                    token_hash=token_value,  # In production this would be hashed
                    resource_scopes=scopes,
                    is_active=is_active,
                    created_at=timestamps[token_idx],
                    expires_at=expires_at,
                    last_used=None,
                )

                token_idx += 1
                yield token
