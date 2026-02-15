# -*- coding: utf-8 -*-
"""Token populator - creates API tokens via POST /tokens.

Uses user login JWTs (interactive session tokens) to create API tokens,
since API tokens cannot create new API tokens (security boundary).
"""

# Standard
import asyncio
import logging
import random
from typing import Any, Dict, List

# Local
from .base import BasePopulator

logger = logging.getLogger(__name__)


class TokenPopulator(BasePopulator):
    """Create API tokens via REST API using user login JWTs."""

    def get_name(self) -> str:
        return "tokens"

    def get_count(self) -> int:
        users = self.get_scale_config("users", 100)
        avg = self.get_scale_config("tokens_per_user_avg", 2)
        return int(users * avg)

    def get_dependencies(self) -> List[str]:
        return ["users", "teams"]

    async def populate(self) -> Dict[str, Any]:
        user_count = self.get_scale_config("users", 100)
        min_tokens = self.get_scale_config("tokens_per_user_min", 1)
        max_tokens = self.get_scale_config("tokens_per_user_max", 5)
        team_ids = self.existing_data.get("team_ids", [])

        created = 0
        errors = 0
        skipped = 0
        ids: List[str] = []
        update_count = 0

        async def _create_tokens_for_user(user_i: int):
            nonlocal created, errors, skipped, update_count
            email = f"user{user_i + 1}@{self.email_domain}"
            token = self.client.user_tokens.get(email)

            if not token:
                skipped += 1
                update_count += 1
                if self.progress_tracker and update_count % self.progress_update_frequency == 0:
                    self.progress_tracker.update(self.get_name(), self.progress_update_frequency)
                    self.progress_tracker.refresh()
                return

            num_tokens = random.randint(min_tokens, max_tokens)

            for j in range(num_tokens):
                token_name = f"api-token-{user_i + 1}-{j + 1}"
                payload: Dict[str, Any] = {
                    "name": token_name,
                    "description": f"API token for {email}",
                    "expires_in_days": random.choice([30, 90, 180, 365]),
                }

                # Add tags for token categorization
                if random.random() < 0.5:
                    payload["tags"] = random.sample(["ci-cd", "development", "production", "staging", "monitoring"], k=random.randint(1, 3))

                try:
                    resp = await self.client.post(
                        "/tokens",
                        json=payload,
                        token=token,  # Use login JWT, not API token
                        expected_status=[200, 201, 409],
                    )
                    if resp.status_code in (200, 201):
                        created += 1
                        try:
                            data = resp.json()
                            tid = data.get("id")
                            if tid:
                                ids.append(tid)
                        except Exception:
                            pass
                    elif resp.status_code == 409:
                        created += 1
                    else:
                        errors += 1
                except Exception:
                    errors += 1

                update_count += 1
                if self.progress_tracker and update_count % self.progress_update_frequency == 0:
                    self.progress_tracker.update(self.get_name(), self.progress_update_frequency)
                    self.progress_tracker.refresh()

        for batch_start in range(0, user_count, self.batch_concurrency):
            batch_end = min(batch_start + self.batch_concurrency, user_count)
            await asyncio.gather(*[_create_tokens_for_user(i) for i in range(batch_start, batch_end)])

        if self.progress_tracker:
            remainder = update_count % self.progress_update_frequency
            if remainder > 0:
                self.progress_tracker.update(self.get_name(), remainder)

        self.existing_data["token_ids"] = ids

        if skipped > 0:
            logger.warning(f"Skipped {skipped} users with no login JWT (tokens require interactive session)")

        return {"created": created, "errors": errors, "skipped": skipped, "ids": ids}
