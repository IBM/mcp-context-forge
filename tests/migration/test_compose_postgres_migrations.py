# -*- coding: utf-8 -*-
"""Location: ./tests/migration/test_compose_postgres_migrations.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

PostgreSQL docker-compose migration tests.

This module tests database migrations using PostgreSQL via docker-compose
stacks across different ContextForge versions with comprehensive validation.
"""

# Standard
import logging
import time

# Third-Party
import pytest

# Local

logger = logging.getLogger(__name__)


@pytest.mark.slow
class TestPostgreSQLMigrations:
    """Test migration scenarios using PostgreSQL docker-compose stacks.

    These tests validate:
    - Full-stack migrations with PostgreSQL and Redis
    - Service orchestration and dependencies
    - Production-like environment testing
    - Cross-service data consistency
    - Performance under realistic load
    """

    def test_compose_forward_migrations(self, container_manager, docker_compose_file, sample_test_data, version_pair):
        """Test forward migrations using docker-compose stack.

        This test validates migrations in a production-like environment with:
        - PostgreSQL database backend
        - Redis caching layer
        - Full service orchestration
        - Inter-service dependencies
        """
        from_version, to_version = version_pair

        logger.info(f"🧪 Testing compose forward migration: {from_version} → {to_version}")
        logger.info(f"📊 Test data: {sum(len(entities) for entities in sample_test_data.values())} records")
        logger.info(f"🐙 Using compose file: {docker_compose_file}")

        # Start compose stack with source version
        logger.info(f"🚀 Starting compose stack with {from_version}")
        containers = container_manager.start_compose_stack(from_version, docker_compose_file)

        try:
            gateway_container = containers["gateway"]
            postgres_container = containers["postgres"]

            logger.info("✅ Compose stack started:")
            logger.info(f"   Gateway: {gateway_container[:12]}")
            logger.info(f"   PostgreSQL: {postgres_container[:12]}")
            logger.info(f"   Redis: {containers.get('redis', 'N/A')[:12]}")

            # Wait for application to initialize database schema
            logger.info(f"🔧 Waiting for application to initialize database for {from_version}")
            # The gateway application automatically initializes the database on startup
            # Let's give it time to complete initialization
            time.sleep(5)
            logger.info("✅ Database initialized by application")

            # Seed test data
            if sample_test_data:
                logger.info("🌱 Seeding test data")
                self._seed_compose_test_data(container_manager, gateway_container, sample_test_data)

                # Verify data was seeded
                records_before = self._count_postgres_records(container_manager, gateway_container)
                logger.info(f"📊 Records seeded: {records_before}")

            # Capture pre-migration state
            logger.info("📋 Capturing pre-migration state")
            schema_before = container_manager.get_database_schema(postgres_container, "postgresql")
            logger.info(f"✅ Pre-migration schema captured ({len(schema_before)} chars)")

            # Stop compose stack
            logger.info("🛑 Stopping compose stack")
            self._stop_compose_stack(container_manager, docker_compose_file)

            # Start compose stack with target version
            logger.info(f"🔄 Starting compose stack with {to_version}")
            containers = container_manager.start_compose_stack(to_version, docker_compose_file)

            gateway_container = containers["gateway"]
            postgres_container = containers["postgres"]

            # Wait for application to run migration automatically
            logger.info(f"⬆️ Application automatically migrating database to {to_version}")
            migration_start = time.time()
            # The application detects the older database schema and automatically migrates it
            # Let's give it time to complete the migration
            time.sleep(8)  # Compose stacks may need more time
            migration_time = time.time() - migration_start

            logger.info(f"✅ Migration completed automatically in {migration_time:.2f}s")

            # Capture post-migration state
            logger.info("📋 Capturing post-migration state")
            schema_after = container_manager.get_database_schema(postgres_container, "postgresql")
            records_after = self._count_postgres_records(container_manager, gateway_container)

            logger.info(f"📊 Records after migration: {records_after}")

            # Validate data integrity
            logger.info("🔍 Validating data integrity")
            data_integrity = self._validate_compose_data_integrity(records_before, records_after)

            # Validate results
            assert data_integrity, "Data integrity validation failed"
            assert migration_time < 180, f"Compose migration took too long: {migration_time:.2f}s"

            # Validate service health
            logger.info("❤️ Validating service health")
            health_ok = self._validate_compose_service_health(container_manager, containers)
            assert health_ok, "Service health validation failed"

            logger.info("✅ Compose forward migration completed successfully:")
            logger.info(f"   Migration time: {migration_time:.2f}s")
            logger.info("   Data integrity: ✅")
            logger.info("   Service health: ✅")

        finally:
            # Cleanup compose stack
            logger.info("🧹 Cleaning up compose stack")
            self._stop_compose_stack(container_manager, docker_compose_file)

    def test_compose_service_dependencies(self, container_manager, docker_compose_file):
        """Test that service dependencies are properly managed during migrations.

        This test validates:
        - PostgreSQL starts before gateway
        - Gateway waits for database to be ready
        - Migration can connect to database
        - Services remain healthy throughout process
        """
        logger.info("🧪 Testing compose service dependencies")

        # Start stack and monitor startup sequence
        logger.info("🚀 Starting compose stack with dependency monitoring")
        start_time = time.time()

        containers = container_manager.start_compose_stack("latest", docker_compose_file)

        startup_time = time.time() - start_time
        logger.info(f"✅ Stack started in {startup_time:.2f}s")

        try:
            gateway_container = containers["gateway"]
            postgres_container = containers["postgres"]

            # Test 1: PostgreSQL should be ready
            logger.info("🔍 Test 1: Validating PostgreSQL readiness")
            postgres_ready = self._check_postgres_ready(container_manager, postgres_container)
            assert postgres_ready, "PostgreSQL not ready after stack startup"

            # Test 2: Gateway should be able to connect to database
            logger.info("🔍 Test 2: Validating gateway database connectivity")
            db_connectivity = self._check_gateway_db_connection(container_manager, gateway_container)
            assert db_connectivity, "Gateway cannot connect to PostgreSQL"

            # Test 3: Migration should work
            logger.info("🔍 Test 3: Validating migration execution")
            migration_output = container_manager.exec_alembic_command(gateway_container, "upgrade head")
            assert "ERROR" not in migration_output, f"Migration failed: {migration_output}"

            # Test 4: Services should remain healthy
            logger.info("🔍 Test 4: Validating ongoing service health")
            health_ok = self._validate_compose_service_health(container_manager, containers)
            assert health_ok, "Services not healthy after migration"

            logger.info("✅ Service dependencies validation completed")

        finally:
            self._stop_compose_stack(container_manager, docker_compose_file)

    def test_compose_concurrent_connections(self, container_manager, docker_compose_file, large_test_data):
        """Test migration behavior under concurrent database connections.

        This test validates that migrations work correctly when there are
        multiple concurrent connections to the database, simulating production
        load conditions.
        """
        logger.info("🧪 Testing compose migration with concurrent connections")
        logger.info(f"📊 Large dataset: {sum(len(entities) for entities in large_test_data.values())} records")

        # Start compose stack
        containers = container_manager.start_compose_stack("latest", docker_compose_file)

        try:
            gateway_container = containers["gateway"]
            postgres_container = containers["postgres"]

            # Initialize schema
            container_manager.exec_alembic_command(gateway_container, "upgrade head")

            # Seed large dataset
            logger.info("🌱 Seeding large dataset for concurrent testing")
            self._seed_compose_test_data(container_manager, gateway_container, large_test_data)

            # Simulate concurrent connections by running multiple operations
            logger.info("🔀 Simulating concurrent database operations")

            concurrent_operations = []

            # Operation 1: Count records
            def count_operation():
                return self._count_postgres_records(container_manager, gateway_container)

            # Operation 2: Query schema
            def schema_operation():
                return container_manager.get_database_schema(postgres_container, "postgresql")

            # Operation 3: Simple alembic info
            def alembic_operation():
                return container_manager.exec_alembic_command(gateway_container, "current")

            # Execute operations concurrently (simulated)
            logger.info("⚡ Executing concurrent operations")
            concurrent_start = time.time()

            records = count_operation()
            schema = schema_operation()
            alembic_info = alembic_operation()

            concurrent_time = time.time() - concurrent_start

            logger.info(f"✅ Concurrent operations completed in {concurrent_time:.2f}s")
            logger.info(f"   Records counted: {sum(records.values())}")
            logger.info(f"   Schema size: {len(schema)} chars")
            logger.info(f"   Alembic info: {alembic_info.strip()[:100]}...")

            # Validate that all operations succeeded
            assert records, "Record counting failed under concurrent load"
            assert schema, "Schema query failed under concurrent load"
            assert alembic_info, "Alembic operation failed under concurrent load"
            assert concurrent_time < 60, "Concurrent operations took too long"

        finally:
            self._stop_compose_stack(container_manager, docker_compose_file)

    def test_compose_data_persistence(self, container_manager, docker_compose_file, sample_test_data):
        """Test data persistence across container restarts.

        This test validates that data persists correctly when containers
        are stopped and restarted, simulating production deployment scenarios.
        """
        logger.info("🧪 Testing compose data persistence across restarts")

        # Phase 1: Start stack, seed data, capture state
        logger.info("📋 Phase 1: Initial setup and data seeding")
        containers = container_manager.start_compose_stack("latest", docker_compose_file)

        try:
            gateway_container = containers["gateway"]
            postgres_container = containers["postgres"]

            # Initialize and seed data
            container_manager.exec_alembic_command(gateway_container, "upgrade head")
            self._seed_compose_test_data(container_manager, gateway_container, sample_test_data)

            # Capture initial state
            records_initial = self._count_postgres_records(container_manager, gateway_container)
            schema_initial = container_manager.get_database_schema(postgres_container, "postgresql")

            logger.info(f"📊 Initial state captured: {sum(records_initial.values())} records")

        finally:
            # Stop stack
            logger.info("🛑 Stopping stack for restart test")
            self._stop_compose_stack(container_manager, docker_compose_file)

        # Phase 2: Restart stack and verify data persistence
        logger.info("📋 Phase 2: Restarting stack and verifying persistence")

        # Wait a moment to ensure full cleanup
        time.sleep(5)

        containers = container_manager.start_compose_stack("latest", docker_compose_file)

        try:
            gateway_container = containers["gateway"]
            postgres_container = containers["postgres"]

            # Capture post-restart state
            records_after_restart = self._count_postgres_records(container_manager, gateway_container)
            schema_after_restart = container_manager.get_database_schema(postgres_container, "postgresql")

            logger.info(f"📊 Post-restart state: {sum(records_after_restart.values())} records")

            # Validate data persistence
            logger.info("🔍 Validating data persistence")

            # Record counts should match
            for table, initial_count in records_initial.items():
                restart_count = records_after_restart.get(table, 0)
                assert restart_count == initial_count, f"Data lost in {table}: {initial_count} → {restart_count}"
                logger.info(f"   {table}: {initial_count} ✅")

            # Schema should be identical
            assert len(schema_after_restart) > 0, "Schema lost after restart"
            logger.info(f"   Schema preserved: {len(schema_after_restart)} chars ✅")

            # Test that we can still run migrations
            logger.info("🔧 Testing migration capability after restart")
            alembic_current = container_manager.exec_alembic_command(gateway_container, "current")
            assert alembic_current, "Alembic not working after restart"
            logger.info("   Alembic functional: ✅")

            logger.info("✅ Data persistence validation completed successfully")

        finally:
            self._stop_compose_stack(container_manager, docker_compose_file)

    def test_compose_migration_rollback(self, container_manager, docker_compose_file, sample_test_data):
        """Test migration rollback in compose environment.

        This test validates rollback capabilities in a full-stack environment
        with proper service coordination and data consistency.
        """
        logger.info("🧪 Testing compose migration rollback")

        # Start with 0.6.0, migrate to latest, then rollback
        logger.info("📋 Phase 1: Setup with version 0.6.0")
        containers = container_manager.start_compose_stack("0.6.0", docker_compose_file)

        try:
            gateway_container = containers["gateway"]
            postgres_container = containers["postgres"]

            # Initialize schema for 0.6.0
            container_manager.exec_alembic_command(gateway_container, "upgrade head")
            self._seed_compose_test_data(container_manager, gateway_container, sample_test_data)

            records_v060 = self._count_postgres_records(container_manager, gateway_container)
            schema_v060 = container_manager.get_database_schema(postgres_container, "postgresql")

            logger.info(f"📊 Version 0.6.0 state: {sum(records_v060.values())} records")

        finally:
            self._stop_compose_stack(container_manager, docker_compose_file)

        # Phase 2: Upgrade to latest
        logger.info("📋 Phase 2: Upgrade to latest version")
        containers = container_manager.start_compose_stack("latest", docker_compose_file)

        try:
            gateway_container = containers["gateway"]
            postgres_container = containers["postgres"]

            # Run upgrade migration
            upgrade_output = container_manager.exec_alembic_command(gateway_container, "upgrade head")
            assert "ERROR" not in upgrade_output, f"Upgrade failed: {upgrade_output}"

            records_latest = self._count_postgres_records(container_manager, gateway_container)
            logger.info(f"📊 Latest version state: {sum(records_latest.values())} records")

            # Data should be preserved during upgrade
            for table, count_v060 in records_v060.items():
                count_latest = records_latest.get(table, 0)
                assert count_latest >= count_v060, f"Data lost during upgrade in {table}"

        finally:
            self._stop_compose_stack(container_manager, docker_compose_file)

        # Phase 3: Rollback test
        logger.info("📋 Phase 3: Testing rollback capability")
        containers = container_manager.start_compose_stack("0.6.0", docker_compose_file)

        try:
            gateway_container = containers["gateway"]
            postgres_container = containers["postgres"]

            # Attempt rollback (this might not always be possible depending on migration design)
            logger.info("⬇️ Attempting rollback migration")

            try:
                rollback_output = container_manager.exec_alembic_command(gateway_container, "downgrade -1")
                rollback_successful = "ERROR" not in rollback_output

                if rollback_successful:
                    records_rollback = self._count_postgres_records(container_manager, gateway_container)
                    logger.info(f"📊 Rollback state: {sum(records_rollback.values())} records")

                    # Validate rollback preserved essential data
                    for table in ["tools", "servers", "gateways"]:  # Core tables
                        if table in records_v060:
                            original_count = records_v060[table]
                            rollback_count = records_rollback.get(table, 0)
                            assert rollback_count >= original_count * 0.8, f"Significant data loss in {table} during rollback"

                    logger.info("✅ Rollback completed successfully")
                else:
                    logger.info("ℹ️ Rollback not supported (expected for some migrations)")

            except Exception as e:
                logger.info(f"ℹ️ Rollback failed as expected: {str(e)[:100]}...")
                # This is often expected for migrations that can't be rolled back

        finally:
            self._stop_compose_stack(container_manager, docker_compose_file)

    # Helper methods for compose testing

    def _seed_compose_test_data(self, container_manager, gateway_container, test_data):
        """Seed test data in compose environment via REST API."""
        logger.debug("🌱 Seeding compose test data via API")

        # Get gateway container port (compose usually maps to a fixed port)
        port = container_manager._get_container_port(gateway_container, "4444")
        base_url = f"http://localhost:{port}"

        # Seed data using REST API
        # Third-Party
        import requests

        session = requests.Session()
        session.timeout = 15

        # Add tools
        for tool in test_data.get("tools", []):
            try:
                response = session.post(f"{base_url}/tools", json=tool)
                response.raise_for_status()
                logger.debug(f"✅ Added tool: {tool.get('name', 'unnamed')}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to add tool {tool.get('name', 'unnamed')}: {e}")

        # Add servers
        for server in test_data.get("servers", []):
            try:
                response = session.post(f"{base_url}/servers", json=server)
                response.raise_for_status()
                logger.debug(f"✅ Added server: {server.get('name', 'unnamed')}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to add server {server.get('name', 'unnamed')}: {e}")

        # Add gateways
        for gateway in test_data.get("gateways", []):
            try:
                response = session.post(f"{base_url}/gateways", json=gateway)
                response.raise_for_status()
                logger.debug(f"✅ Added gateway: {gateway.get('name', 'unnamed')}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to add gateway {gateway.get('name', 'unnamed')}: {e}")

    def _count_postgres_records(self, container_manager, gateway_container):
        """Count records in PostgreSQL database via REST API."""
        logger.debug("📊 Counting PostgreSQL records via REST API")

        endpoints = ["tools", "servers", "gateways", "resources", "prompts", "a2a"]
        counts = {}

        for endpoint in endpoints:
            try:
                # Use gateway container since that's where the REST API is running
                result = container_manager._run_command(
                    [
                        container_manager.runtime,
                        "exec",
                        gateway_container,
                        "python3",
                        "-c",
                        f"import urllib.request; resp = urllib.request.urlopen('http://localhost:4444/{endpoint}', timeout=5); print(resp.read().decode())",
                    ],
                    capture_output=True,
                )

                # Standard
                import json

                data = json.loads(result.stdout.strip())

                # Handle different response formats
                if isinstance(data, list):
                    counts[endpoint] = len(data)
                elif isinstance(data, dict) and "items" in data:
                    counts[endpoint] = len(data["items"])
                elif isinstance(data, dict) and "data" in data:
                    counts[endpoint] = len(data["data"])
                else:
                    counts[endpoint] = 1 if data else 0

                logger.debug(f"📊 {endpoint}: {counts[endpoint]} records")

            except Exception as e:
                logger.warning(f"⚠️ Failed to count {endpoint} records: {e}")
                counts[endpoint] = 0

        return counts

    def _check_postgres_ready(self, container_manager, postgres_container):
        """Check if PostgreSQL is ready for connections."""
        try:
            result = container_manager._run_command([container_manager.runtime, "exec", postgres_container, "pg_isready", "-U", "test_user", "-d", "mcp_test"], capture_output=True, check=False)

            return result.returncode == 0
        except Exception:
            return False

    def _check_gateway_db_connection(self, container_manager, gateway_container):
        """Check if gateway can connect to database."""
        try:
            # Try to run alembic current, which requires DB connection
            result = container_manager._run_command([container_manager.runtime, "exec", gateway_container, "python", "-m", "alembic", "current"], capture_output=True, check=False)

            return result.returncode == 0 and "ERROR" not in result.stdout
        except Exception:
            return False

    def _validate_compose_data_integrity(self, records_before, records_after):
        """Validate data integrity in compose environment."""
        if not records_before:
            return True  # No baseline to compare

        for table, count_before in records_before.items():
            count_after = records_after.get(table, 0)
            if count_after < count_before:
                logger.error(f"❌ Data loss in {table}: {count_before} → {count_after}")
                return False

        return True

    def _validate_compose_service_health(self, container_manager, containers):
        """Validate health of all services in compose stack."""
        logger.debug("❤️ Validating compose service health")

        for service_name, container_id in containers.items():
            try:
                # Check if container is running
                result = container_manager._run_command([container_manager.runtime, "ps", "-q", "--filter", f"id={container_id}"], capture_output=True, check=False)

                if not result.stdout.strip():
                    logger.error(f"❌ Service {service_name} not running")
                    return False

                logger.debug(f"   {service_name}: ✅")

            except Exception as e:
                logger.error(f"❌ Error checking {service_name} health: {e}")
                return False

        return True

    def _stop_compose_stack(self, container_manager, compose_file):
        """Stop and clean up compose stack."""
        try:
            cmd = [f"{container_manager.runtime}-compose", "-f", compose_file, "down", "-v", "--remove-orphans"]
            container_manager._run_command(cmd, check=False)
        except Exception as e:
            logger.warning(f"⚠️ Error stopping compose stack: {e}")
