# -*- coding: utf-8 -*-
"""Migration test runner for comprehensive database migration testing.

This module orchestrates migration testing scenarios across different
MCP Gateway versions with detailed logging and validation.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .container_manager import ContainerManager

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    """Result of a migration test operation."""
    success: bool
    version_from: str
    version_to: str
    execution_time: float
    schema_before: str
    schema_after: str
    data_integrity_check: bool
    migration_direction: str  # "upgrade" or "downgrade"
    alembic_output: str = ""
    error_message: Optional[str] = None
    records_before: Dict[str, int] = field(default_factory=dict)
    records_after: Dict[str, int] = field(default_factory=dict)
    performance_metrics: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert result to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "version_from": self.version_from,
            "version_to": self.version_to,
            "execution_time": self.execution_time,
            "data_integrity_check": self.data_integrity_check,
            "migration_direction": self.migration_direction,
            "error_message": self.error_message,
            "records_before": self.records_before,
            "records_after": self.records_after,
            "performance_metrics": self.performance_metrics,
            "alembic_output_length": len(self.alembic_output),
            "schema_before_length": len(self.schema_before),
            "schema_after_length": len(self.schema_after)
        }


class MigrationTestRunner:
    """Orchestrates comprehensive migration testing scenarios.
    
    Provides methods for testing:
    - Forward migrations (version upgrades)
    - Reverse migrations (version downgrades) 
    - Skip-version migrations (jumping multiple versions)
    - Data integrity validation across migrations
    - Performance benchmarking
    """
    
    def __init__(self, container_manager: ContainerManager):
        """Initialize migration test runner.
        
        Args:
            container_manager: Container management instance
        """
        self.container_manager = container_manager
        self.results: List[MigrationResult] = []
        
        logger.info("🚀 Initialized MigrationTestRunner")
    
    def test_forward_migration(self, from_version: str, to_version: str, 
                              test_data: Optional[Dict] = None) -> MigrationResult:
        """Test upgrade migration between versions.
        
        Args:
            from_version: Source version
            to_version: Target version
            test_data: Optional test data to seed before migration
            
        Returns:
            Migration test result
        """
        logger.info(f"🔄 Testing FORWARD migration: {from_version} → {to_version}")
        return self._run_migration_test(
            from_version, to_version, "upgrade", test_data
        )
    
    def test_reverse_migration(self, from_version: str, to_version: str,
                              test_data: Optional[Dict] = None) -> MigrationResult:
        """Test downgrade migration between versions.
        
        Args:
            from_version: Source version (higher version)
            to_version: Target version (lower version)  
            test_data: Optional test data to seed before migration
            
        Returns:
            Migration test result
        """
        logger.info(f"🔙 Testing REVERSE migration: {from_version} → {to_version}")
        return self._run_migration_test(
            from_version, to_version, "downgrade", test_data
        )
    
    def test_skip_version_migration(self, from_version: str, to_version: str,
                                   test_data: Optional[Dict] = None) -> MigrationResult:
        """Test migration skipping intermediate versions.
        
        Args:
            from_version: Source version
            to_version: Target version (multiple versions away)
            test_data: Optional test data to seed before migration
            
        Returns:
            Migration test result
        """
        logger.info(f"⏭️ Testing SKIP-VERSION migration: {from_version} → {to_version}")
        return self._run_migration_test(
            from_version, to_version, "skip_upgrade", test_data
        )
    
    def _run_migration_test(self, from_version: str, to_version: str, 
                           direction: str, test_data: Optional[Dict] = None) -> MigrationResult:
        """Run a complete migration test scenario.
        
        Args:
            from_version: Source version
            to_version: Target version
            direction: Migration direction ("upgrade", "downgrade", "skip_upgrade")
            test_data: Optional test data to seed
            
        Returns:
            Complete migration test result
        """
        start_time = time.time()
        container_id = None
        
        try:
            # Phase 1: Setup source version container
            logger.info(f"📦 Phase 1: Setting up source container ({from_version})")
            container_id = self.container_manager.start_sqlite_container(from_version)
            
            # Phase 2: Initialize database schema for source version  
            logger.info(f"🔧 Phase 2: Initializing database schema for {from_version}")
            alembic_init_output = self.container_manager.exec_alembic_command(
                container_id, "upgrade head"
            )
            logger.info(f"✅ Database initialized for {from_version}")
            
            # Phase 3: Seed test data if provided
            records_before = {}
            if test_data:
                logger.info(f"🌱 Phase 3: Seeding test data")
                self._seed_test_data(container_id, test_data)
                records_before = self._count_records(container_id)
                logger.info(f"📊 Record counts before migration: {records_before}")
            else:
                logger.info(f"ℹ️ Phase 3: No test data to seed")
            
            # Phase 4: Capture pre-migration state
            logger.info(f"📋 Phase 4: Capturing pre-migration state")
            schema_before = self.container_manager.get_database_schema(container_id, "sqlite")
            logger.info(f"✅ Pre-migration schema captured ({len(schema_before)} chars)")
            
            # Phase 5: Stop container and switch to target version
            logger.info(f"🔄 Phase 5: Switching to target version ({to_version})")
            self.container_manager.cleanup_container(container_id)
            container_id = self.container_manager.start_sqlite_container(to_version)
            
            # Phase 6: Run migration
            logger.info(f"🚀 Phase 6: Executing migration ({direction})")
            migration_output = self._execute_migration(container_id, direction, from_version, to_version)
            logger.info(f"✅ Migration completed successfully")
            
            # Phase 7: Capture post-migration state
            logger.info(f"📋 Phase 7: Capturing post-migration state")
            schema_after = self.container_manager.get_database_schema(container_id, "sqlite")
            records_after = self._count_records(container_id) if test_data else {}
            logger.info(f"📊 Record counts after migration: {records_after}")
            
            # Phase 8: Validate data integrity
            logger.info(f"🔍 Phase 8: Validating data integrity")
            data_integrity = self._validate_data_integrity(
                container_id, records_before, records_after
            )
            
            # Phase 9: Calculate performance metrics
            execution_time = time.time() - start_time
            performance_metrics = self._calculate_performance_metrics(
                container_id, execution_time, len(schema_before), len(schema_after)
            )
            
            logger.info(f"✅ Migration test completed successfully in {execution_time:.2f}s")
            
            result = MigrationResult(
                success=True,
                version_from=from_version,
                version_to=to_version,
                execution_time=execution_time,
                schema_before=schema_before,
                schema_after=schema_after,
                data_integrity_check=data_integrity,
                migration_direction=direction,
                alembic_output=migration_output,
                records_before=records_before,
                records_after=records_after,
                performance_metrics=performance_metrics
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"❌ Migration test failed after {execution_time:.2f}s: {str(e)}")
            
            # Try to capture error details
            error_details = str(e)
            if container_id:
                try:
                    logs = self.container_manager.get_container_logs(container_id)
                    error_details += f"\n\nContainer logs:\n{logs}"
                except:
                    pass
            
            result = MigrationResult(
                success=False,
                version_from=from_version,
                version_to=to_version,
                execution_time=execution_time,
                schema_before="",
                schema_after="",
                data_integrity_check=False,
                migration_direction=direction,
                error_message=error_details,
                records_before=records_before if 'records_before' in locals() else {},
                records_after={},
                performance_metrics={}
            )
            
        finally:
            # Cleanup
            if container_id:
                self.container_manager.cleanup_container(container_id)
        
        self.results.append(result)
        return result
    
    def _execute_migration(self, container_id: str, direction: str, 
                          from_version: str, to_version: str) -> str:
        """Execute the appropriate migration command.
        
        Args:
            container_id: Target container ID
            direction: Migration direction
            from_version: Source version
            to_version: Target version
            
        Returns:
            Alembic command output
        """
        if direction in ["upgrade", "skip_upgrade"]:
            command = "upgrade head"
            logger.info(f"⬆️ Running upgrade migration to latest schema")
        elif direction == "downgrade":
            # Find the target revision for downgrade
            # For now, we'll use a simple approach - in production this would
            # need more sophisticated revision mapping
            command = f"downgrade -1"  # Downgrade by one revision
            logger.info(f"⬇️ Running downgrade migration")
        else:
            raise ValueError(f"Unknown migration direction: {direction}")
        
        logger.info(f"🔧 Executing: alembic {command}")
        output = self.container_manager.exec_alembic_command(container_id, command)
        
        if "ERROR" in output or "FAILED" in output:
            logger.error(f"❌ Migration command failed")
            logger.error(f"📤 Alembic output: {output}")
            raise RuntimeError(f"Alembic migration failed: {output}")
        
        logger.info(f"✅ Migration command completed successfully")
        return output
    
    def _seed_test_data(self, container_id: str, test_data: Dict) -> None:
        """Seed test data into the container database.
        
        Args:
            container_id: Target container ID
            test_data: Dictionary containing test data
        """
        logger.info(f"🌱 Seeding test data: {len(test_data.get('tools', []))} tools, "
                   f"{len(test_data.get('servers', []))} servers, "
                   f"{len(test_data.get('gateways', []))} gateways")
        
        # Create temporary data file
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f, indent=2)
            temp_file = f.name
        
        try:
            self.container_manager.seed_test_data(container_id, temp_file)
            logger.info(f"✅ Test data seeded successfully")
        finally:
            os.unlink(temp_file)
    
    def _count_records(self, container_id: str) -> Dict[str, int]:
        """Count records in all major tables.
        
        Args:
            container_id: Target container ID
            
        Returns:
            Dictionary mapping table names to record counts
        """
        logger.debug(f"📊 Counting records in database tables")
        
        # SQL to count records in major tables
        count_sql = '''
import sqlite3
conn = sqlite3.connect("/app/data/mcp-alembic-migration-test.db")
cursor = conn.cursor()

tables = ["tools", "servers", "gateways", "resources", "prompts", "a2a_agents"]
counts = {}

for table in tables:
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        counts[table] = cursor.fetchone()[0]
    except Exception:
        counts[table] = 0

conn.close()
print(",".join([f"{k}:{v}" for k, v in counts.items()]))
'''
        
        # Write and execute counting script
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(count_sql)
            script_path = f.name
        
        try:
            self.container_manager._copy_to_container(container_id, script_path, "/app/count_records.py")
            
            result = self.container_manager._run_command([
                self.container_manager.runtime, "exec", container_id,
                "python", "/app/count_records.py"
            ], capture_output=True)
            
            # Parse output like "tools:5,servers:3,gateways:2"
            counts = {}
            if result.stdout.strip():
                for pair in result.stdout.strip().split(","):
                    if ":" in pair:
                        table, count = pair.split(":", 1)
                        counts[table] = int(count)
            
            logger.debug(f"📊 Record counts: {counts}")
            return counts
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to count records: {e}")
            return {}
        finally:
            os.unlink(script_path)
    
    def _validate_data_integrity(self, container_id: str, 
                               records_before: Dict[str, int], 
                               records_after: Dict[str, int]) -> bool:
        """Validate data integrity after migration.
        
        Args:
            container_id: Container ID
            records_before: Record counts before migration
            records_after: Record counts after migration
            
        Returns:
            True if data integrity is maintained
        """
        logger.info(f"🔍 Validating data integrity")
        
        if not records_before:
            logger.info(f"ℹ️ No baseline data to compare - integrity check passed")
            return True
        
        integrity_ok = True
        
        for table, count_before in records_before.items():
            count_after = records_after.get(table, 0)
            
            if count_after < count_before:
                logger.error(f"❌ Data loss detected in {table}: {count_before} → {count_after}")
                integrity_ok = False
            elif count_after > count_before:
                logger.info(f"ℹ️ Records added to {table}: {count_before} → {count_after}")
            else:
                logger.info(f"✅ {table} records preserved: {count_before}")
        
        # Additional integrity checks
        try:
            # Check for foreign key violations
            fk_check_sql = '''
import sqlite3
conn = sqlite3.connect("/app/data/mcp-alembic-migration-test.db")
cursor = conn.cursor()
cursor.execute("PRAGMA foreign_key_check")
violations = cursor.fetchall()
conn.close()
print(f"FK_VIOLATIONS:{len(violations)}")
'''
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(fk_check_sql)
                script_path = f.name
            
            try:
                self.container_manager._copy_to_container(container_id, script_path, "/app/fk_check.py")
                result = self.container_manager._run_command([
                    self.container_manager.runtime, "exec", container_id,
                    "python", "/app/fk_check.py"
                ], capture_output=True)
                
                if "FK_VIOLATIONS:0" in result.stdout:
                    logger.info(f"✅ No foreign key violations detected")
                else:
                    logger.warning(f"⚠️ Foreign key violations detected: {result.stdout}")
                    integrity_ok = False
                    
            finally:
                os.unlink(script_path)
                
        except Exception as e:
            logger.warning(f"⚠️ Could not check foreign key integrity: {e}")
        
        if integrity_ok:
            logger.info(f"✅ Data integrity validation passed")
        else:
            logger.error(f"❌ Data integrity validation failed")
        
        return integrity_ok
    
    def _calculate_performance_metrics(self, container_id: str, execution_time: float,
                                     schema_before_size: int, schema_after_size: int) -> Dict[str, float]:
        """Calculate performance metrics for the migration.
        
        Args:
            container_id: Container ID
            execution_time: Total execution time in seconds
            schema_before_size: Size of schema before migration
            schema_after_size: Size of schema after migration
            
        Returns:
            Dictionary of performance metrics
        """
        logger.debug(f"📊 Calculating performance metrics")
        
        metrics = {
            "execution_time_seconds": execution_time,
            "schema_size_before": schema_before_size,
            "schema_size_after": schema_after_size,
            "schema_size_delta": schema_after_size - schema_before_size
        }
        
        # Try to get container resource usage
        try:
            stats_result = self.container_manager._run_command([
                self.container_manager.runtime, "stats", "--no-stream", "--format", 
                "table {{.CPUPerc}},{{.MemUsage}}", container_id
            ], capture_output=True, check=False)
            
            if stats_result.returncode == 0 and stats_result.stdout:
                lines = stats_result.stdout.strip().split('\n')
                if len(lines) > 1:  # Skip header
                    stats_line = lines[1]
                    if ',' in stats_line:
                        cpu_str, mem_str = stats_line.split(',', 1)
                        # Parse CPU percentage
                        if '%' in cpu_str:
                            try:
                                metrics["cpu_percent"] = float(cpu_str.replace('%', '').strip())
                            except:
                                pass
                        # Parse memory usage
                        if '/' in mem_str:
                            try:
                                mem_used = mem_str.split('/')[0].strip()
                                # Convert various units to MB
                                if 'GiB' in mem_used:
                                    metrics["memory_mb"] = float(mem_used.replace('GiB', '').strip()) * 1024
                                elif 'MiB' in mem_used:
                                    metrics["memory_mb"] = float(mem_used.replace('MiB', '').strip())
                                elif 'MB' in mem_used:
                                    metrics["memory_mb"] = float(mem_used.replace('MB', '').strip())
                            except:
                                pass
        
        except Exception as e:
            logger.debug(f"Could not get container stats: {e}")
        
        # Calculate derived metrics
        if execution_time > 0:
            metrics["operations_per_second"] = 1.0 / execution_time
        
        logger.debug(f"📊 Performance metrics: {metrics}")
        return metrics
    
    def run_full_migration_matrix(self, include_reverse: bool = True, 
                                 include_skip: bool = True) -> Dict[str, List[MigrationResult]]:
        """Run complete migration test matrix.
        
        Args:
            include_reverse: Whether to include reverse migration tests
            include_skip: Whether to include skip-version migration tests
            
        Returns:
            Dictionary of test results organized by category
        """
        logger.info(f"🚀 Starting full migration test matrix")
        logger.info(f"📋 Settings: reverse={include_reverse}, skip={include_skip}")
        
        versions = self.container_manager.AVAILABLE_VERSIONS
        logger.info(f"🔢 Testing with versions: {versions}")
        
        results = {
            "forward_migrations": [],
            "reverse_migrations": [],
            "skip_migrations": []
        }
        
        # Generate test data for all scenarios
        test_data = self._generate_test_data()
        
        # Forward migrations (sequential version upgrades)
        logger.info(f"⬆️ Testing forward migrations")
        for i in range(len(versions) - 1):
            from_ver, to_ver = versions[i], versions[i + 1]
            logger.info(f"🔄 Testing {from_ver} → {to_ver}")
            
            try:
                result = self.test_forward_migration(from_ver, to_ver, test_data)
                results["forward_migrations"].append(result)
                
                if result.success:
                    logger.info(f"✅ {from_ver} → {to_ver} PASSED ({result.execution_time:.2f}s)")
                else:
                    logger.error(f"❌ {from_ver} → {to_ver} FAILED: {result.error_message}")
                    
            except Exception as e:
                logger.error(f"❌ {from_ver} → {to_ver} EXCEPTION: {e}")
        
        # Reverse migrations (sequential version downgrades)
        if include_reverse:
            logger.info(f"⬇️ Testing reverse migrations")
            for i in range(len(versions) - 1, 0, -1):
                from_ver, to_ver = versions[i], versions[i - 1]
                logger.info(f"🔄 Testing {from_ver} → {to_ver}")
                
                try:
                    result = self.test_reverse_migration(from_ver, to_ver, test_data)
                    results["reverse_migrations"].append(result)
                    
                    if result.success:
                        logger.info(f"✅ {from_ver} → {to_ver} PASSED ({result.execution_time:.2f}s)")
                    else:
                        logger.error(f"❌ {from_ver} → {to_ver} FAILED: {result.error_message}")
                        
                except Exception as e:
                    logger.error(f"❌ {from_ver} → {to_ver} EXCEPTION: {e}")
        
        # Skip version migrations
        if include_skip:
            logger.info(f"⏭️ Testing skip-version migrations")
            skip_pairs = [
                ("0.2.0", "0.4.0"),  # Skip 0.3.0
                ("0.3.0", "0.6.0"),  # Skip 0.4.0, 0.5.0
                ("0.4.0", "latest"), # Skip 0.5.0, 0.6.0
                ("0.2.0", "latest")  # Skip all intermediate versions
            ]
            
            for from_ver, to_ver in skip_pairs:
                if from_ver in versions and to_ver in versions:
                    logger.info(f"🔄 Testing {from_ver} ⏭️ {to_ver}")
                    
                    try:
                        result = self.test_skip_version_migration(from_ver, to_ver, test_data)
                        results["skip_migrations"].append(result)
                        
                        if result.success:
                            logger.info(f"✅ {from_ver} ⏭️ {to_ver} PASSED ({result.execution_time:.2f}s)")
                        else:
                            logger.error(f"❌ {from_ver} ⏭️ {to_ver} FAILED: {result.error_message}")
                            
                    except Exception as e:
                        logger.error(f"❌ {from_ver} ⏭️ {to_ver} EXCEPTION: {e}")
        
        # Summary
        total_tests = (len(results["forward_migrations"]) + 
                      len(results["reverse_migrations"]) + 
                      len(results["skip_migrations"]))
        
        successful_tests = sum(1 for result_list in results.values() 
                              for result in result_list if result.success)
        
        logger.info(f"📊 Migration matrix completed:")
        logger.info(f"   Total tests: {total_tests}")
        logger.info(f"   Successful: {successful_tests}")
        logger.info(f"   Failed: {total_tests - successful_tests}")
        logger.info(f"   Success rate: {successful_tests/total_tests*100:.1f}%")
        
        return results
    
    def _generate_test_data(self) -> Dict:
        """Generate realistic test data for migration testing.
        
        Returns:
            Dictionary containing test data for seeding
        """
        logger.info(f"🎲 Generating test data for migration scenarios")
        
        test_data = {
            "tools": [
                {
                    "name": "migration_test_tool_1",
                    "description": "Test tool for migration validation",
                    "schema": {"type": "object", "properties": {"param": {"type": "string"}}},
                    "annotations": {"category": "test", "priority": "high"}
                },
                {
                    "name": "migration_test_tool_2", 
                    "description": "Another test tool with complex schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "items": {"type": "array", "items": {"type": "string"}},
                            "config": {"type": "object", "additionalProperties": True}
                        }
                    },
                    "annotations": {"category": "test", "version": "1.0"}
                }
            ],
            "servers": [
                {
                    "name": "migration_test_server",
                    "description": "Test server for migration validation", 
                    "transport": "sse",
                    "annotations": {"environment": "test"}
                }
            ],
            "gateways": [
                {
                    "name": "migration_test_gateway",
                    "base_url": "http://test-gateway.example.com",
                    "description": "Test gateway for federation testing",
                    "annotations": {"region": "test", "type": "migration"}
                }
            ]
        }
        
        logger.info(f"✅ Generated test data: {len(test_data['tools'])} tools, "
                   f"{len(test_data['servers'])} servers, {len(test_data['gateways'])} gateways")
        
        return test_data
    
    def save_results_to_file(self, output_file: str) -> None:
        """Save all test results to a JSON file.
        
        Args:
            output_file: Path to output file
        """
        logger.info(f"💾 Saving {len(self.results)} test results to {output_file}")
        
        results_data = {
            "metadata": {
                "total_tests": len(self.results),
                "successful_tests": sum(1 for r in self.results if r.success),
                "timestamp": time.time(),
                "container_runtime": self.container_manager.runtime
            },
            "results": [result.to_dict() for result in self.results]
        }
        
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        logger.info(f"✅ Results saved to {output_file}")