# -*- coding: utf-8 -*-
"""User populator - creates users via POST /auth/email/admin/users and logs them in."""

# Standard
import asyncio
import logging
from typing import Any, Dict, List

# Local
from .base import BasePopulator

logger = logging.getLogger(__name__)

DEFAULT_PASSWORD = "LoadTest1234!"


class UserPopulator(BasePopulator):
    """Create users via admin endpoint and obtain login JWTs."""

    def get_name(self) -> str:
        return "users"

    def get_count(self) -> int:
        return self.get_scale_config("users", 100)

    def get_dependencies(self) -> List[str]:
        return []

    async def populate(self) -> Dict[str, Any]:
        count = self.get_count()
        admin_percent = self.get_scale_config("users_admin_percent", 5)
        admin_count = max(1, int(count * admin_percent / 100))

        created = 0
        errors = 0
        login_errors = 0
        update_count = 0

        async def _create_and_login(i: int):
            nonlocal created, errors, login_errors, update_count
            email = f"user{i + 1}@{self.email_domain}"
            is_admin = i < admin_count
            full_name = self.faker.name()

            # Create user via admin endpoint
            try:
                resp = await self.client.post(
                    "/auth/email/admin/users",
                    json={
                        "email": email,
                        "password": DEFAULT_PASSWORD,
                        "full_name": full_name,
                        "is_admin": is_admin,
                    },
                    expected_status=[200, 201, 409],  # 409 = already exists
                )
                if resp.status_code in (200, 201, 409):
                    created += 1
                else:
                    errors += 1
                    logger.debug(f"Failed to create user {email}: {resp.status_code} {resp.text[:200]}")
                    update_count += 1
                    if self.progress_tracker and update_count % self.progress_update_frequency == 0:
                        self.progress_tracker.update(self.get_name(), self.progress_update_frequency)
                        self.progress_tracker.refresh()
                    return
            except Exception as exc:
                errors += 1
                logger.debug(f"Failed to create user {email}: {exc}")
                update_count += 1
                if self.progress_tracker and update_count % self.progress_update_frequency == 0:
                    self.progress_tracker.update(self.get_name(), self.progress_update_frequency)
                    self.progress_tracker.refresh()
                return

            # Login to obtain user-scoped JWT
            try:
                login_resp = await self.client.post(
                    "/auth/email/login",
                    json={"email": email, "password": DEFAULT_PASSWORD},
                    expected_status=[200],
                )
                if login_resp.status_code == 200:
                    data = login_resp.json()
                    token = data.get("access_token") or data.get("token")
                    if token:
                        self.client.user_tokens[email] = token
                else:
                    login_errors += 1
            except Exception:
                login_errors += 1

            update_count += 1
            if self.progress_tracker and update_count % self.progress_update_frequency == 0:
                self.progress_tracker.update(self.get_name(), self.progress_update_frequency)
                self.progress_tracker.refresh()

        # Process in batches
        for batch_start in range(0, count, self.batch_concurrency):
            batch_end = min(batch_start + self.batch_concurrency, count)
            await asyncio.gather(*[_create_and_login(i) for i in range(batch_start, batch_end)])

        # Final progress update
        if self.progress_tracker:
            remainder = update_count % self.progress_update_frequency
            if remainder > 0:
                self.progress_tracker.update(self.get_name(), remainder)

        if login_errors > 0:
            logger.warning(f"Login failures: {login_errors}/{created} users could not log in")

        # Store user emails in existing_data for downstream populators
        emails = [f"user{i + 1}@{self.email_domain}" for i in range(count)]
        self.existing_data["user_emails"] = emails
        self.existing_data["admin_emails"] = emails[:admin_count]

        return {
            "created": created,
            "errors": errors,
            "login_errors": login_errors,
            "tokens_obtained": len(self.client.user_tokens),
            "ids": emails,
        }
