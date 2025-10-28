# -*- coding: utf-8 -*-
"""User generator for load testing."""

import hashlib
from datetime import datetime
from typing import Generator, List

from mcpgateway.db import EmailUser

from ..utils.distributions import exponential_decay_temporal
from .base import BaseGenerator


class UserGenerator(BaseGenerator):
    """Generate EmailUser records with realistic data."""

    def get_count(self) -> int:
        """Get total number of users to generate."""
        return self.get_scale_config("users", 100)

    def get_dependencies(self) -> List[str]:
        """No dependencies for users."""
        return []

    def generate(self) -> Generator[EmailUser, None, None]:
        """Generate user records.

        Yields:
            EmailUser instances
        """
        count = self.get_count()
        admin_percent = self.get_scale_config("users_admin_percent", 1)
        active_percent = self.get_scale_config("users_active_percent", 80)

        # Get temporal distribution
        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        timestamps = exponential_decay_temporal(count, start_date, end_date, recent_percent)

        for i in range(count):
            email = f"user{i+1}@{self.email_domain}"
            is_admin = (i < count * admin_percent / 100)
            is_active = (i < count * active_percent / 100)

            user = EmailUser(
                email=email,
                full_name=self.faker.name(),
                password_hash=self._hash_password("password123"),
                is_active=is_active,
                is_admin=is_admin,
                created_at=timestamps[i],
                updated_at=timestamps[i],
                last_login=None,
                failed_login_attempts=0,
                locked_until=None,
            )

            yield user

    def _hash_password(self, password: str) -> str:
        """Hash password (simplified for load testing).

        Args:
            password: Plain text password

        Returns:
            Hashed password
        """
        return hashlib.sha256(password.encode()).hexdigest()
