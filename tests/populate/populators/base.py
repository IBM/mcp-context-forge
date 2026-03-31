# -*- coding: utf-8 -*-
"""Base populator class for all REST API entity populators."""

# Standard
from abc import ABC, abstractmethod
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

# Third-Party
from faker import Faker

# Local
from ..api_client import APIClient
from ..utils.progress import MultiProgressTracker
from mcpgateway.db import SessionLocal, utc_now

logger = logging.getLogger(__name__)


class BasePopulator(ABC):
    """Base class for REST API entity populators.

    Each populator creates entities via HTTP POST to the actual gateway
    endpoints, exercising the full write path including validation,
    auth middleware, RBAC, and side effects.
    
    Supports two modes:
    - REST API mode: Full integration testing with validation/RBAC (default)
    - Bulk DB mode: Direct SQLAlchemy inserts for performance (use_bulk_mode=True)
    """

    def __init__(
        self,
        client: APIClient,
        config: Dict[str, Any],
        faker: Faker,
        existing_data: Optional[Dict[str, Any]] = None,
        progress_tracker: Optional[MultiProgressTracker] = None,
        dry_run: bool = False,
        use_bulk_mode: bool = False,
    ):
        self.client = client
        self.config = config
        self.faker = faker
        self.existing_data = existing_data if existing_data is not None else {}
        self.progress_tracker = progress_tracker
        self.dry_run = dry_run
        self.use_bulk_mode = use_bulk_mode
        self.email_domain = config.get("global", {}).get("email_domain", "loadtest.example.com")
        self.batch_concurrency = config.get("concurrency", {}).get("batch_size", 50)
        self.chunk_size = config.get("concurrency", {}).get("chunk_size", 10000)
        self.progress_update_frequency = config.get("global", {}).get("progress_update_frequency", 10)
        self.bulk_batch_size = config.get("concurrency", {}).get("bulk_batch_size", 10000)

        # Results tracking
        self.created_count = 0
        self.error_count = 0
        self.created_ids: List[str] = []

    @abstractmethod
    def get_name(self) -> str:
        """Get the name of this populator (e.g., 'users', 'teams')."""

    @abstractmethod
    def get_count(self) -> int:
        """Get total number of entities to create."""

    @abstractmethod
    def get_dependencies(self) -> List[str]:
        """Get list of populator names this depends on."""

    @abstractmethod
    async def populate(self) -> Dict[str, Any]:
        """Populate entities via REST API.

        Returns:
            Dictionary with 'created', 'errors', 'duration', and 'ids' keys.
        """

    def get_scale_config(self, key: str, default: Any = None) -> Any:
        return self.config.get("scale", {}).get(key, default)

    async def run(self) -> Dict[str, Any]:
        """Run the populator and track progress."""
        name = self.get_name()
        total = self.get_count()

        if self.progress_tracker:
            self.progress_tracker.log(f"Starting [cyan]{name}[/cyan] population ({total:,} entities)...", style="")
            self.progress_tracker.start_task(name)
            self.progress_tracker.refresh()

        start_time = time.time()

        if self.dry_run:
            logger.info(f"[DRY RUN] Would create {total:,} {name} via REST API")
            if self.progress_tracker:
                self.progress_tracker.complete_task(name)
                self.progress_tracker.refresh()
            return {"created": 0, "errors": 0, "duration": 0, "dry_run": True, "planned": total, "ids": []}

        result = await self.populate()

        duration = time.time() - start_time

        if self.progress_tracker:
            self.progress_tracker.complete_task(name)
            self.progress_tracker.refresh()
            rate = result.get("created", 0) / duration if duration > 0 else 0
            errors = result.get("errors", 0)
            err_str = f" ([red]{errors} errors[/red])" if errors else ""
            self.progress_tracker.log(
                f"[green]v[/green] Completed [cyan]{name}[/cyan]: "
                f"[yellow]{result.get('created', 0):,}[/yellow] created in "
                f"[magenta]{duration:.2f}s[/magenta] ([cyan]{rate:,.0f} req/s[/cyan]){err_str}",
                style="",
            )

        result["duration"] = duration
        return result

    async def _batch_create(
        self,
        payloads: List[Dict[str, Any]],
        endpoint: str,
        token: Optional[str] = None,
        id_field: str = "id",
        expected_status: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Create entities in parallel batches.

        Args:
            payloads: List of request payloads
            endpoint: POST endpoint path
            token: Optional JWT token (uses admin if None)
            id_field: Field name containing the entity ID in response
            expected_status: Expected HTTP status codes

        Returns:
            Dictionary with created/errors/ids
        """
        created = 0
        errors = 0
        ids: List[str] = []
        update_count = 0

        async def _create_one(payload: Dict[str, Any]):
            nonlocal created, errors, update_count
            try:
                resp = await self.client.post(endpoint, json=payload, token=token, expected_status=expected_status)
                if resp.status_code in (expected_status or [200, 201]):
                    created += 1
                    try:
                        data = resp.json()
                        if isinstance(data, dict) and id_field in data:
                            ids.append(data[id_field])
                    except Exception:
                        pass
                else:
                    errors += 1
            except Exception as exc:
                errors += 1
                logger.error(f"Failed to create {self.get_name()}: {exc}")

            update_count += 1
            if self.progress_tracker and update_count % self.progress_update_frequency == 0:
                self.progress_tracker.update(self.get_name(), self.progress_update_frequency, errors=0)
                self.progress_tracker.refresh()

        # Process in chunks to avoid overwhelming asyncio.gather with millions of tasks
        # APIClient semaphore still controls actual concurrency
        for i in range(0, len(payloads), self.chunk_size):
            chunk = payloads[i : i + self.chunk_size]
            await asyncio.gather(*[_create_one(p) for p in chunk], return_exceptions=True)


        # Final progress update for remainder
        if self.progress_tracker:
            remainder = update_count % self.progress_update_frequency
            if remainder > 0:
                self.progress_tracker.update(self.get_name(), remainder, errors=errors)

        self.created_count = created
        self.error_count = errors
        self.created_ids = ids

        return {"created": created, "errors": errors, "ids": ids}

    def _bulk_insert_mappings(
        self,
        model_class: Any,
        mappings: List[Dict[str, Any]],
        return_id_field: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Bulk insert records directly into database using SQLAlchemy.

        This bypasses the HTTP API layer for maximum performance, inserting
        records in batches using bulk_insert_mappings(). Use this for large-scale
        data seeding where validation/RBAC checks are not needed.

        Args:
            model_class: SQLAlchemy model class (e.g., EmailUser, EmailTeam)
            mappings: List of dictionaries with column names and values
            return_id_field: Optional field name to extract IDs from mappings

        Returns:
            Dictionary with created/errors/ids counts
        """
        created = 0
        errors = 0
        ids: List[str] = []
        total = len(mappings)

        try:
            with SessionLocal() as session:
                # Process in batches to avoid memory issues
                for i in range(0, total, self.bulk_batch_size):
                    batch = mappings[i : i + self.bulk_batch_size]
                    
                    try:
                        # Use bulk_insert_mappings for maximum performance
                        session.bulk_insert_mappings(model_class, batch)
                        session.commit()
                        
                        batch_created = len(batch)
                        created += batch_created
                        
                        # Extract IDs if requested
                        if return_id_field:
                            ids.extend([m[return_id_field] for m in batch if return_id_field in m])
                        
                        # Update progress
                        if self.progress_tracker:
                            self.progress_tracker.update(self.get_name(), batch_created, errors=0)
                            self.progress_tracker.refresh()
                            
                    except Exception as exc:
                        session.rollback()
                        errors += len(batch)
                        logger.error(f"Bulk insert batch failed for {self.get_name()}: {exc}")

        except Exception as exc:
            logger.error(f"Bulk insert failed for {self.get_name()}: {exc}")
            errors = total

        self.created_count = created
        self.error_count = errors
        self.created_ids = ids

        return {"created": created, "errors": errors, "ids": ids}
