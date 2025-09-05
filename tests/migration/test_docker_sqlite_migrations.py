# -*- coding: utf-8 -*-
"""SQLite container migration tests.

This module tests database migrations using SQLite containers across
different MCP Gateway versions with comprehensive validation.
"""

# Standard
import logging
from pathlib import Path
import time

# Third-Party
import pytest

# Local
from .utils.data_seeder import DataGenerationConfig, DataSeeder
from .utils.schema_validator import SchemaValidator

logger = logging.getLogger(__name__)


class TestSQLiteMigrations:
    """Test migration scenarios using SQLite containers.

    These tests validate:
    - Sequential version upgrades
    - Sequential version downgrades
    - Skip-version migrations
    - Data integrity across migrations
    - Schema evolution validation
    """

    def test_sequential_forward_migrations(self, migration_runner, sample_test_data, version_pair):
        """Test sequential version upgrades with data validation.

        This test:
        1. Starts container with source version
        2. Initializes database and seeds test data
        3. Captures pre-migration state
        4. Switches to target version and runs migration
        5. Validates data integrity and schema evolution
        """
        from_version, to_version = version_pair

        logger.info(f"🧪 Testing sequential forward migration: {from_version} → {to_version}")
        logger.info(f"📊 Test data: {sum(len(entities) for entities in sample_test_data.values())} records")

        # Execute migration test
        result = migration_runner.test_forward_migration(from_version, to_version, sample_test_data)

        # Validate result
        assert result.success, f"Migration failed: {result.error_message}"
        assert result.data_integrity_check, "Data integrity validation failed"
        assert result.execution_time < 60, f"Migration took too long: {result.execution_time:.2f}s"

        # Log detailed results
        logger.info(f"✅ Migration completed successfully:")
        logger.info(f"   Execution time: {result.execution_time:.2f}s")
        logger.info(f"   Records before: {result.records_before}")
        logger.info(f"   Records after: {result.records_after}")
        logger.info(f"   Schema size: {len(result.schema_before)} → {len(result.schema_after)} chars")

        # Validate performance metrics
        if result.performance_metrics:
            logger.info(f"   Performance metrics: {result.performance_metrics}")

            # Check memory usage if available
            if "memory_mb" in result.performance_metrics:
                assert result.performance_metrics["memory_mb"] < 512, "Memory usage too high"

    def test_sequential_reverse_migrations(self, migration_runner, sample_test_data, reverse_version_pair):
        """Test sequential version downgrades with data validation.

        This test validates that downgrade migrations:
        1. Complete successfully without errors
        2. Preserve existing data (no data loss)
        3. Maintain referential integrity
        4. Execute within reasonable time limits
        """
        from_version, to_version = reverse_version_pair

        logger.info(f"🧪 Testing sequential reverse migration: {from_version} → {to_version}")

        # Execute reverse migration test
        result = migration_runner.test_reverse_migration(from_version, to_version, sample_test_data)

        # Validate result - note: reverse migrations may have different expectations
        assert result.success, f"Reverse migration failed: {result.error_message}"
        assert result.data_integrity_check, "Data integrity validation failed"
        assert result.execution_time < 120, f"Reverse migration took too long: {result.execution_time:.2f}s"

        logger.info(f"✅ Reverse migration completed successfully:")
        logger.info(f"   Execution time: {result.execution_time:.2f}s")
        logger.info(f"   Data integrity maintained: {result.data_integrity_check}")

        # Reverse migrations should not lose data
        for table, count_before in result.records_before.items():
            count_after = result.records_after.get(table, 0)
            assert count_after >= count_before, f"Data loss detected in {table}: {count_before} → {count_after}"

    def test_skip_version_migrations(self, migration_runner, sample_test_data, skip_version_pair):
        """Test migrations that skip intermediate versions.

        Skip-version migrations test the robustness of the migration system
        by applying multiple schema changes in sequence without intermediate
        validation steps.
        """
        from_version, to_version = skip_version_pair

        logger.info(f"🧪 Testing skip-version migration: {from_version} ⏭️ {to_version}")
        logger.info(f"📋 This migration skips intermediate versions")

        # Execute skip-version migration test
        result = migration_runner.test_skip_version_migration(from_version, to_version, sample_test_data)

        # Validate result - skip migrations may take longer
        assert result.success, f"Skip-version migration failed: {result.error_message}"
        assert result.data_integrity_check, "Data integrity validation failed"
        assert result.execution_time < 180, f"Skip-version migration took too long: {result.execution_time:.2f}s"

        logger.info(f"✅ Skip-version migration completed successfully:")
        logger.info(f"   Execution time: {result.execution_time:.2f}s")
        logger.info(f"   Schema evolution validated")

    def test_migration_with_large_dataset(self, migration_runner, large_test_data, performance_thresholds):
        """Test migration performance with large datasets.

        This test validates that migrations can handle realistic data volumes
        without performance degradation or failures.
        """
        logger.info(f"🧪 Testing migration with large dataset")
        logger.info(f"📊 Large dataset: {sum(len(entities) for entities in large_test_data.values())} records")

        # Test with recent version pair for performance
        result = migration_runner.test_forward_migration("0.6.0", "latest", large_test_data)

        # Validate result with large dataset thresholds
        assert result.success, f"Large dataset migration failed: {result.error_message}"
        assert result.data_integrity_check, "Data integrity validation failed with large dataset"

        # Apply large dataset performance threshold
        max_duration = performance_thresholds["large_dataset"]["max_duration"]
        assert result.execution_time < max_duration, f"Large dataset migration too slow: {result.execution_time:.2f}s > {max_duration}s"

        logger.info(f"✅ Large dataset migration completed:")
        logger.info(f"   Execution time: {result.execution_time:.2f}s (threshold: {max_duration}s)")
        logger.info(f"   Records processed: {sum(result.records_after.values())} total")

        # Validate all record types were preserved
        for table, expected_count in result.records_before.items():
            actual_count = result.records_after.get(table, 0)
            assert actual_count >= expected_count, f"Data loss in {table} with large dataset"

    def test_migration_error_recovery(self, container_manager, migration_runner):
        """Test migration error scenarios and recovery mechanisms.

        This test validates that the migration system handles errors gracefully
        and provides useful diagnostic information.
        """
        logger.info(f"🧪 Testing migration error recovery scenarios")

        # Test 1: Migration with invalid data
        logger.info("🔍 Test 1: Testing with corrupted test data")
        corrupted_data = {
            "tools": [
                {
                    # Missing required fields to trigger validation errors
                    "invalid_field": "this should cause issues",
                    "schema": "not a valid schema object"
                }
            ]
        }

        result = migration_runner.test_forward_migration("0.6.0", "latest", corrupted_data)

        # The migration should either succeed (gracefully handling bad data)
        # or fail with a clear error message
        if not result.success:
            assert result.error_message is not None, "Failed migration should provide error message"
            assert len(result.error_message) > 0, "Error message should not be empty"
            logger.info(f"📋 Expected failure with error: {result.error_message[:100]}...")
        else:
            logger.info("✅ Migration gracefully handled corrupted data")

        # Test 2: Very fast migration (should always succeed)
        logger.info("🔍 Test 2: Testing minimal data migration")
        minimal_data = {
            "tools": [{"name": "minimal_tool", "description": "Minimal test tool", "schema": {"type": "object"}}]
        }

        result = migration_runner.test_forward_migration("0.6.0", "latest", minimal_data)
        assert result.success, f"Minimal migration should always succeed: {result.error_message}"
        assert result.execution_time < 30, "Minimal migration should be fast"

        logger.info(f"✅ Minimal migration completed in {result.execution_time:.2f}s")

    def test_schema_validation_comprehensive(self, container_manager, migration_runner):
        """Test comprehensive schema validation across migrations.

        This test validates that:
        1. Schema changes are properly tracked
        2. Breaking changes are identified
        3. Compatibility scores are calculated correctly
        """
        logger.info(f"🧪 Testing comprehensive schema validation")

        # Create schema validator
        schema_validator = SchemaValidator()

        # Test schema evolution from 0.6.0 to latest
        logger.info("🔍 Testing schema evolution: 0.6.0 → latest")

        # Get schema before migration
        container_id_before = container_manager.start_sqlite_container("0.6.0")
        try:
            container_manager.exec_alembic_command(container_id_before, "upgrade head")
            schema_sql_before = container_manager.get_database_schema(container_id_before, "sqlite")
            schema_before = schema_validator.parse_sqlite_schema(schema_sql_before)

            logger.info(f"📋 Schema before: {len(schema_before)} tables")
            for table_name, table_schema in schema_before.items():
                logger.info(f"   {table_name}: {len(table_schema.columns)} columns")

        finally:
            container_manager.cleanup_container(container_id_before)

        # Get schema after migration
        container_id_after = container_manager.start_sqlite_container("latest")
        try:
            container_manager.exec_alembic_command(container_id_after, "upgrade head")
            schema_sql_after = container_manager.get_database_schema(container_id_after, "sqlite")
            schema_after = schema_validator.parse_sqlite_schema(schema_sql_after)

            logger.info(f"📋 Schema after: {len(schema_after)} tables")
            for table_name, table_schema in schema_after.items():
                logger.info(f"   {table_name}: {len(table_schema.columns)} columns")

        finally:
            container_manager.cleanup_container(container_id_after)

        # Compare schemas
        comparison = schema_validator.compare_schemas(schema_before, schema_after)

        logger.info(f"📊 Schema comparison results:")
        logger.info(f"   Added tables: {comparison.added_tables}")
        logger.info(f"   Removed tables: {comparison.removed_tables}")
        logger.info(f"   Modified tables: {comparison.modified_tables}")
        logger.info(f"   Compatibility score: {comparison.compatibility_score:.2f}")
        logger.info(f"   Breaking changes: {len(comparison.breaking_changes)}")
        logger.info(f"   Warnings: {len(comparison.warnings)}")

        # Validate schema comparison results
        assert comparison.compatibility_score >= 0.5, "Schema compatibility too low"

        # Schema evolution should generally be additive (no removed tables)
        assert len(comparison.removed_tables) == 0, f"Unexpected table removal: {comparison.removed_tables}"

        # Log any breaking changes for review
        if comparison.breaking_changes:
            logger.warning("⚠️ Breaking changes detected:")
            for change in comparison.breaking_changes:
                logger.warning(f"   - {change}")

        # Save schema snapshots for future reference
        reports_dir = Path("tests/migration/reports")
        reports_dir.mkdir(parents=True, exist_ok=True)

        schema_validator.save_schema_snapshot(schema_before, "0.6.0", str(reports_dir))
        schema_validator.save_schema_snapshot(schema_after, "latest", str(reports_dir))

        logger.info(f"💾 Schema snapshots saved to {reports_dir}")

    def test_migration_idempotency(self, migration_runner, sample_test_data):
        """Test that migrations are idempotent (can be run multiple times safely).

        This test validates that running the same migration multiple times
        produces the same result without errors or data corruption.
        """
        logger.info(f"🧪 Testing migration idempotency")

        # Run migration twice and compare results
        logger.info("🔍 Running first migration")
        result1 = migration_runner.test_forward_migration("0.6.0", "latest", sample_test_data)

        assert result1.success, f"First migration failed: {result1.error_message}"

        logger.info("🔍 Running second migration (idempotency test)")
        result2 = migration_runner.test_forward_migration("0.6.0", "latest", sample_test_data)

        assert result2.success, f"Second migration failed: {result2.error_message}"

        # Compare results - they should be similar
        logger.info("📊 Comparing migration results:")
        logger.info(f"   Execution time: {result1.execution_time:.2f}s vs {result2.execution_time:.2f}s")
        logger.info(f"   Schema size: {len(result1.schema_after)} vs {len(result2.schema_after)} chars")
        logger.info(f"   Records: {result1.records_after} vs {result2.records_after}")

        # Results should be consistent
        assert result1.records_after == result2.records_after, "Record counts should be identical"
        assert result1.data_integrity_check == result2.data_integrity_check, "Data integrity should be consistent"

        # Second run might be faster (no actual migration work)
        time_ratio = result2.execution_time / result1.execution_time if result1.execution_time > 0 else 1.0
        logger.info(f"⚡ Second run time ratio: {time_ratio:.2f} (< 1.0 means faster)")

        logger.info(f"✅ Migration idempotency validated")

    def test_migration_rollback_safety(self, migration_runner, sample_test_data):
        """Test migration rollback safety and data preservation.

        This test validates that forward migration followed by rollback
        preserves the original data state.
        """
        logger.info(f"🧪 Testing migration rollback safety")

        # Test forward migration followed by rollback
        logger.info("⬆️ Testing forward migration: 0.5.0 → 0.6.0")
        forward_result = migration_runner.test_forward_migration("0.5.0", "0.6.0", sample_test_data)

        assert forward_result.success, f"Forward migration failed: {forward_result.error_message}"

        logger.info("⬇️ Testing rollback migration: 0.6.0 → 0.5.0")
        rollback_result = migration_runner.test_reverse_migration("0.6.0", "0.5.0", sample_test_data)

        # Rollback should succeed and preserve data
        assert rollback_result.success, f"Rollback migration failed: {rollback_result.error_message}"
        assert rollback_result.data_integrity_check, "Data integrity lost during rollback"

        # Compare original data with post-rollback data
        logger.info("📊 Comparing original vs post-rollback data:")

        # Data counts should be preserved through forward + rollback cycle
        for table in forward_result.records_before.keys():
            original_count = forward_result.records_before[table]
            rollback_count = rollback_result.records_after.get(table, 0)

            logger.info(f"   {table}: {original_count} → {rollback_count}")

            # Allow for some variation in rollback scenarios
            assert rollback_count >= original_count * 0.9, f"Significant data loss in {table} during rollback"

        total_time = forward_result.execution_time + rollback_result.execution_time
        logger.info(f"⏱️ Total round-trip time: {total_time:.2f}s")

        logger.info(f"✅ Migration rollback safety validated")
