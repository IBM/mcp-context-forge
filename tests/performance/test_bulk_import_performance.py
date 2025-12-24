# -*- coding: utf-8 -*-
"""
Performance tests for bulk import operations.

This module contains comprehensive performance tests for bulk import operations
across all entity types: Resources, Tools, and Prompts.

Tests measure:
- Execution time
- Throughput (entities/second)
- Memory usage
- Success rates
- Comparison between single and bulk operations
"""

import gc
import logging
import time
import tracemalloc
from dataclasses import dataclass
from typing import Any, Dict, List

import pytest
from sqlalchemy.orm import Session

from mcpgateway.services.import_service import ImportService, ConflictStrategy

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Container for performance metrics."""
    execution_time: float
    throughput: float
    memory_used: float
    success_count: int
    total_count: int

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        return (self.success_count / self.total_count * 100) if self.total_count > 0 else 0.0


class BulkImportPerformanceTester:
    """Performance testing utilities for bulk import operations."""

    def __init__(self, db: Session, import_service: ImportService):
        self.db = db
        self.import_service = import_service

    def _generate_resources(self, count: int) -> List[Dict[str, Any]]:
        """Generate test resource data."""
        return [
            {
                "uri": f"test://resource-{i}",
                "name": f"Test Resource {i}",
                "content": f"Test content for resource {i}",
                "description": f"Performance test resource {i}",
                "mime_type": "text/plain"
            }
            for i in range(count)
        ]

    def _generate_tools(self, count: int) -> List[Dict[str, Any]]:
        """Generate test tool data."""
        return [
            {
                "name": f"test_tool_{i}",
                "url": f"http://example.com/tool/{i}",
                "description": f"Performance test tool {i}",
                "integration_type": "REST",
                "request_type": "GET",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "param1": {"type": "string"},
                        "param2": {"type": "integer"}
                    }
                }
            }
            for i in range(count)
        ]

    def _generate_prompts(self, count: int) -> List[Dict[str, Any]]:
        """Generate test prompt data."""
        return [
            {
                "name": f"test_prompt_{i}",
                "description": f"Performance test prompt {i}",
                "template": f"This is test prompt {i} with {{{{variable}}}}"
            }
            for i in range(count)
        ]

    async def benchmark_resources_import(
        self,
        resources: List[Dict[str, Any]],
        imported_by: str = "perf_test"
    ) -> PerformanceMetrics:
        """Benchmark resource import performance."""
        # Prepare configuration
        config_data = {
            "version": "1.0",
            "exported_at": "2025-01-01T00:00:00Z",
            "entities": {
                "resources": resources
            }
        }

        # Force garbage collection before measurement
        gc.collect()

        # Start memory tracking
        tracemalloc.start()
        start_memory = tracemalloc.get_traced_memory()[0]

        # Measure execution time
        start_time = time.perf_counter()

        result = await self.import_service.import_configuration(
            db=self.db,
            import_data=config_data,
            imported_by=imported_by,
            conflict_strategy=ConflictStrategy.SKIP
        )

        end_time = time.perf_counter()

        # Measure memory usage
        current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        execution_time = end_time - start_time
        memory_used = (current_memory - start_memory) / 1024 / 1024  # Convert to MB

        # Calculate success count
        success_count = result.processed_entities
        total_count = len(resources)
        throughput = total_count / execution_time if execution_time > 0 else 0

        return PerformanceMetrics(
            execution_time=execution_time,
            throughput=throughput,
            memory_used=memory_used,
            success_count=success_count,
            total_count=total_count
        )

    async def benchmark_resources_import_single(
        self,
        resources: List[Dict[str, Any]],
        imported_by: str = "perf_test"
    ) -> PerformanceMetrics:
        """Benchmark resource import performance using single imports."""
        gc.collect()
        tracemalloc.start()
        start_memory = tracemalloc.get_traced_memory()[0]

        start_time = time.perf_counter()
        success_count = 0

        # Import each resource individually
        for resource in resources:
            config_data = {
                "version": "1.0",
                "exported_at": "2025-01-01T00:00:00Z",
                "entities": {"resources": [resource]}
            }
            result = await self.import_service.import_configuration(
                db=self.db,
                import_data=config_data,
                imported_by=imported_by,
                conflict_strategy=ConflictStrategy.SKIP
            )
            success_count += result.processed_entities

        end_time = time.perf_counter()

        current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        execution_time = end_time - start_time
        memory_used = (current_memory - start_memory) / 1024 / 1024
        total_count = len(resources)
        throughput = total_count / execution_time if execution_time > 0 else 0

        return PerformanceMetrics(
            execution_time=execution_time,
            throughput=throughput,
            memory_used=memory_used,
            success_count=success_count,
            total_count=total_count
        )

    async def benchmark_tools_import(
        self,
        tools: List[Dict[str, Any]],
        imported_by: str = "perf_test"
    ) -> PerformanceMetrics:
        """Benchmark tool import performance."""
        config_data = {
            "version": "1.0",
            "exported_at": "2025-01-01T00:00:00Z",
            "entities": {
                "tools": tools
            }
        }

        gc.collect()
        tracemalloc.start()
        start_memory = tracemalloc.get_traced_memory()[0]

        start_time = time.perf_counter()
        result = await self.import_service.import_configuration(
            db=self.db,
            import_data=config_data,
            imported_by=imported_by,
            conflict_strategy=ConflictStrategy.SKIP
        )
        end_time = time.perf_counter()

        current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        execution_time = end_time - start_time
        memory_used = (current_memory - start_memory) / 1024 / 1024

        success_count = result.processed_entities
        total_count = len(tools)
        throughput = total_count / execution_time if execution_time > 0 else 0

        return PerformanceMetrics(
            execution_time=execution_time,
            throughput=throughput,
            memory_used=memory_used,
            success_count=success_count,
            total_count=total_count
        )

    async def benchmark_prompts_import(
        self,
        prompts: List[Dict[str, Any]],
        imported_by: str = "perf_test"
    ) -> PerformanceMetrics:
        """Benchmark prompt import performance."""
        config_data = {
            "version": "1.0",
            "exported_at": "2025-01-01T00:00:00Z",
            "entities": {
                "prompts": prompts
            }
        }

        gc.collect()
        tracemalloc.start()
        start_memory = tracemalloc.get_traced_memory()[0]

        start_time = time.perf_counter()
        result = await self.import_service.import_configuration(
            db=self.db,
            import_data=config_data,
            imported_by=imported_by,
            conflict_strategy=ConflictStrategy.SKIP
        )
        end_time = time.perf_counter()

        current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        execution_time = end_time - start_time
        memory_used = (current_memory - start_memory) / 1024 / 1024

        success_count = result.processed_entities
        total_count = len(prompts)
        throughput = total_count / execution_time if execution_time > 0 else 0

        return PerformanceMetrics(
            execution_time=execution_time,
            throughput=throughput,
            memory_used=memory_used,
            success_count=success_count,
            total_count=total_count
        )

    async def benchmark_mixed_import(
        self,
        tools: List[Dict[str, Any]],
        prompts: List[Dict[str, Any]],
        imported_by: str = "perf_test"
    ) -> PerformanceMetrics:
        """Benchmark mixed entity import performance."""
        config_data = {
            "version": "1.0",
            "exported_at": "2025-01-01T00:00:00Z",
            "entities": {
                "tools": tools,
                "prompts": prompts
            }
        }

        gc.collect()
        tracemalloc.start()
        start_memory = tracemalloc.get_traced_memory()[0]

        start_time = time.perf_counter()
        result = await self.import_service.import_configuration(
            db=self.db,
            import_data=config_data,
            imported_by=imported_by,
            conflict_strategy=ConflictStrategy.SKIP
        )
        end_time = time.perf_counter()

        current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        execution_time = end_time - start_time
        memory_used = (current_memory - start_memory) / 1024 / 1024

        success_count = result.processed_entities
        total_count = len(tools) + len(prompts)
        throughput = total_count / execution_time if execution_time > 0 else 0

        return PerformanceMetrics(
            execution_time=execution_time,
            throughput=throughput,
            memory_used=memory_used,
            success_count=success_count,
            total_count=total_count
        )

    async def benchmark_tools_import_single(
        self,
        tools: List[Dict[str, Any]],
        imported_by: str = "perf_test"
    ) -> PerformanceMetrics:
        """Benchmark tool import performance using single imports."""
        gc.collect()
        tracemalloc.start()
        start_memory = tracemalloc.get_traced_memory()[0]

        start_time = time.perf_counter()
        success_count = 0

        # Import each tool individually
        for tool in tools:
            config_data = {
                "version": "1.0",
                "exported_at": "2025-01-01T00:00:00Z",
                "entities": {"tools": [tool]}
            }
            result = await self.import_service.import_configuration(
                db=self.db,
                import_data=config_data,
                imported_by=imported_by,
                conflict_strategy=ConflictStrategy.SKIP
            )
            success_count += result.processed_entities

        end_time = time.perf_counter()

        current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        execution_time = end_time - start_time
        memory_used = (current_memory - start_memory) / 1024 / 1024
        total_count = len(tools)
        throughput = total_count / execution_time if execution_time > 0 else 0

        return PerformanceMetrics(
            execution_time=execution_time,
            throughput=throughput,
            memory_used=memory_used,
            success_count=success_count,
            total_count=total_count
        )

    async def benchmark_prompts_import_single(
        self,
        prompts: List[Dict[str, Any]],
        imported_by: str = "perf_test"
    ) -> PerformanceMetrics:
        """Benchmark prompt import performance using single imports."""
        gc.collect()
        tracemalloc.start()
        start_memory = tracemalloc.get_traced_memory()[0]

        start_time = time.perf_counter()
        success_count = 0

        # Import each prompt individually
        for prompt in prompts:
            config_data = {
                "version": "1.0",
                "exported_at": "2025-01-01T00:00:00Z",
                "entities": {"prompts": [prompt]}
            }
            result = await self.import_service.import_configuration(
                db=self.db,
                import_data=config_data,
                imported_by=imported_by,
                conflict_strategy=ConflictStrategy.SKIP
            )
            success_count += result.processed_entities

        end_time = time.perf_counter()

        current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        execution_time = end_time - start_time
        memory_used = (current_memory - start_memory) / 1024 / 1024
        total_count = len(prompts)
        throughput = total_count / execution_time if execution_time > 0 else 0

        return PerformanceMetrics(
            execution_time=execution_time,
            throughput=throughput,
            memory_used=memory_used,
            success_count=success_count,
            total_count=total_count
        )


@pytest.fixture
def perf_tester(test_db, test_engine):
    """Create performance tester instance."""
    # Ensure all tables exist, including audit_trails
    from mcpgateway.db import Base
    Base.metadata.create_all(bind=test_engine)

    return BulkImportPerformanceTester(test_db, ImportService())


@pytest.mark.asyncio
@pytest.mark.performance
class TestResourceBulkImportPerformance:
    """Performance tests for resource bulk import operations."""

    async def test_small_batch_resources(self, perf_tester: BulkImportPerformanceTester):
        """Test performance with small batch (100 resources)."""
        resources = perf_tester._generate_resources(100)
        metrics = await perf_tester.benchmark_resources_import(resources)

        logger.info(f"Small Batch (100 resources):")
        logger.info(f"  Execution Time: {metrics.execution_time:.3f}s")
        logger.info(f"  Throughput: {metrics.throughput:.1f} resources/s")
        logger.info(f"  Memory Used: {metrics.memory_used:.2f} MB")
        logger.info(f"  Success Rate: {metrics.success_rate:.1f}%")

        assert metrics.success_count == 100
        assert metrics.throughput > 0

    async def test_medium_batch_resources(self, perf_tester: BulkImportPerformanceTester):
        """Test performance with medium batch (1000 resources)."""
        resources = perf_tester._generate_resources(1000)
        metrics = await perf_tester.benchmark_resources_import(resources)

        logger.info(f"Medium Batch (1000 resources):")
        logger.info(f"  Execution Time: {metrics.execution_time:.3f}s")
        logger.info(f"  Throughput: {metrics.throughput:.1f} resources/s")
        logger.info(f"  Memory Used: {metrics.memory_used:.2f} MB")
        logger.info(f"  Success Rate: {metrics.success_rate:.1f}%")

        assert metrics.success_count == 1000
        assert metrics.throughput > 0

    async def test_large_batch_resources(self, perf_tester: BulkImportPerformanceTester):
        """Test performance with large batch (5000 resources)."""
        resources = perf_tester._generate_resources(5000)
        metrics = await perf_tester.benchmark_resources_import(resources)

        logger.info(f"Large Batch (5000 resources):")
        logger.info(f"  Execution Time: {metrics.execution_time:.3f}s")
        logger.info(f"  Throughput: {metrics.throughput:.1f} resources/s")
        logger.info(f"  Memory Used: {metrics.memory_used:.2f} MB")
        logger.info(f"  Success Rate: {metrics.success_rate:.1f}%")

        assert metrics.success_count == 5000
        assert metrics.throughput > 0


@pytest.mark.asyncio
@pytest.mark.performance
class TestToolBulkImportPerformance:
    """Performance tests for tool bulk import operations."""

    async def test_small_batch_tools(self, perf_tester: BulkImportPerformanceTester):
        """Test performance with small batch (100 tools)."""
        tools = perf_tester._generate_tools(100)
        metrics = await perf_tester.benchmark_tools_import(tools)

        logger.info(f"Small Batch (100 tools):")
        logger.info(f"  Execution Time: {metrics.execution_time:.3f}s")
        logger.info(f"  Throughput: {metrics.throughput:.1f} tools/s")
        logger.info(f"  Memory Used: {metrics.memory_used:.2f} MB")
        logger.info(f"  Success Rate: {metrics.success_rate:.1f}%")

        assert metrics.success_count == 100
        assert metrics.throughput > 0

    async def test_medium_batch_tools(self, perf_tester: BulkImportPerformanceTester):
        """Test performance with medium batch (500 tools)."""
        tools = perf_tester._generate_tools(500)
        metrics = await perf_tester.benchmark_tools_import(tools)

        logger.info(f"Medium Batch (500 tools):")
        logger.info(f"  Execution Time: {metrics.execution_time:.3f}s")
        logger.info(f"  Throughput: {metrics.throughput:.1f} tools/s")
        logger.info(f"  Memory Used: {metrics.memory_used:.2f} MB")
        logger.info(f"  Success Rate: {metrics.success_rate:.1f}%")

        assert metrics.success_count == 500
        assert metrics.throughput > 0

    async def test_large_batch_tools(self, perf_tester: BulkImportPerformanceTester):
        """Test performance with large batch (1000 tools)."""
        tools = perf_tester._generate_tools(1000)
        metrics = await perf_tester.benchmark_tools_import(tools)

        logger.info(f"Large Batch (1000 tools):")
        logger.info(f"  Execution Time: {metrics.execution_time:.3f}s")
        logger.info(f"  Throughput: {metrics.throughput:.1f} tools/s")
        logger.info(f"  Memory Used: {metrics.memory_used:.2f} MB")
        logger.info(f"  Success Rate: {metrics.success_rate:.1f}%")

        assert metrics.success_count == 1000
        assert metrics.throughput > 0


@pytest.mark.asyncio
@pytest.mark.performance
class TestPromptBulkImportPerformance:
    """Performance tests for prompt bulk import operations."""

    async def test_small_batch_prompts(self, perf_tester: BulkImportPerformanceTester):
        """Test performance with small batch (100 prompts)."""
        prompts = perf_tester._generate_prompts(100)
        metrics = await perf_tester.benchmark_prompts_import(prompts)

        logger.info(f"Small Batch (100 prompts):")
        logger.info(f"  Execution Time: {metrics.execution_time:.3f}s")
        logger.info(f"  Throughput: {metrics.throughput:.1f} prompts/s")
        logger.info(f"  Memory Used: {metrics.memory_used:.2f} MB")
        logger.info(f"  Success Rate: {metrics.success_rate:.1f}%")

        assert metrics.success_count == 100
        assert metrics.throughput > 0

    async def test_medium_batch_prompts(self, perf_tester: BulkImportPerformanceTester):
        """Test performance with medium batch (500 prompts)."""
        prompts = perf_tester._generate_prompts(500)
        metrics = await perf_tester.benchmark_prompts_import(prompts)

        logger.info(f"Medium Batch (500 prompts):")
        logger.info(f"  Execution Time: {metrics.execution_time:.3f}s")
        logger.info(f"  Throughput: {metrics.throughput:.1f} prompts/s")
        logger.info(f"  Memory Used: {metrics.memory_used:.2f} MB")
        logger.info(f"  Success Rate: {metrics.success_rate:.1f}%")

        assert metrics.success_count == 500
        assert metrics.throughput > 0

    async def test_large_batch_prompts(self, perf_tester: BulkImportPerformanceTester):
        """Test performance with large batch (1000 prompts)."""
        prompts = perf_tester._generate_prompts(1000)
        metrics = await perf_tester.benchmark_prompts_import(prompts)

        logger.info(f"Large Batch (1000 prompts):")
        logger.info(f"  Execution Time: {metrics.execution_time:.3f}s")
        logger.info(f"  Throughput: {metrics.throughput:.1f} prompts/s")
        logger.info(f"  Memory Used: {metrics.memory_used:.2f} MB")
        logger.info(f"  Success Rate: {metrics.success_rate:.1f}%")

        assert metrics.success_count == 1000
        assert metrics.throughput > 0


@pytest.mark.asyncio
@pytest.mark.performance
class TestMixedBulkImportPerformance:
    """Performance tests for mixed entity bulk import operations."""

    async def test_mixed_small_batch(self, perf_tester: BulkImportPerformanceTester):
        """Test performance with small mixed batch (50 tools + 50 prompts)."""
        tools = perf_tester._generate_tools(50)
        prompts = perf_tester._generate_prompts(50)
        metrics = await perf_tester.benchmark_mixed_import(tools, prompts)

        logger.info(f"Mixed Small Batch (50 tools + 50 prompts):")
        logger.info(f"  Execution Time: {metrics.execution_time:.3f}s")
        logger.info(f"  Throughput: {metrics.throughput:.1f} entities/s")
        logger.info(f"  Memory Used: {metrics.memory_used:.2f} MB")
        logger.info(f"  Success Rate: {metrics.success_rate:.1f}%")

        assert metrics.success_count == 100
        assert metrics.throughput > 0

    async def test_mixed_medium_batch(self, perf_tester: BulkImportPerformanceTester):
        """Test performance with medium mixed batch (100 tools + 100 prompts)."""
        tools = perf_tester._generate_tools(100)
        prompts = perf_tester._generate_prompts(100)
        metrics = await perf_tester.benchmark_mixed_import(tools, prompts)

        logger.info(f"Mixed Medium Batch (100 tools + 100 prompts):")
        logger.info(f"  Execution Time: {metrics.execution_time:.3f}s")
        logger.info(f"  Throughput: {metrics.throughput:.1f} entities/s")
        logger.info(f"  Memory Used: {metrics.memory_used:.2f} MB")
        logger.info(f"  Success Rate: {metrics.success_rate:.1f}%")

        assert metrics.success_count == 200
        assert metrics.throughput > 0

    async def test_mixed_large_batch(self, perf_tester: BulkImportPerformanceTester):
        """Test performance with large mixed batch (500 tools + 500 prompts)."""
        tools = perf_tester._generate_tools(500)
        prompts = perf_tester._generate_prompts(500)
        metrics = await perf_tester.benchmark_mixed_import(tools, prompts)

        logger.info(f"Mixed Large Batch (500 tools + 500 prompts):")
        logger.info(f"  Execution Time: {metrics.execution_time:.3f}s")
        logger.info(f"  Throughput: {metrics.throughput:.1f} entities/s")
        logger.info(f"  Memory Used: {metrics.memory_used:.2f} MB")
        logger.info(f"  Success Rate: {metrics.success_rate:.1f}%")

        assert metrics.success_count == 1000


@pytest.mark.asyncio
@pytest.mark.performance
class TestResourcesImportComparison:
    """Comparison tests for single vs bulk resource imports to measure speedup."""

    async def test_resources_single_vs_bulk_comparison(self, perf_tester: BulkImportPerformanceTester):
        """Compare single vs bulk import performance for resources (100 resources)."""
        resources = perf_tester._generate_resources(100)

        # Test single import
        logger.info("Testing single resource imports...")
        single_metrics = await perf_tester.benchmark_resources_import_single(resources)

        # Test bulk import
        logger.info("Testing bulk resource imports...")
        bulk_metrics = await perf_tester.benchmark_resources_import(resources)

        # Calculate speedup
        speedup = single_metrics.execution_time / bulk_metrics.execution_time if bulk_metrics.execution_time > 0 else 0
        throughput_improvement = ((bulk_metrics.throughput - single_metrics.throughput) / single_metrics.throughput * 100) if single_metrics.throughput > 0 else 0

        logger.info(f"\n{'='*70}")
        logger.info(f"Resources Import Performance Comparison (100 resources)")
        logger.info(f"{'='*70}")
        logger.info(f"Single Import:")
        logger.info(f"  Execution Time: {single_metrics.execution_time:.3f}s")
        logger.info(f"  Throughput:     {single_metrics.throughput:.1f} resources/s")
        logger.info(f"  Memory Used:    {single_metrics.memory_used:.2f} MB")
        logger.info(f"")
        logger.info(f"Bulk Import:")
        logger.info(f"  Execution Time: {bulk_metrics.execution_time:.3f}s")
        logger.info(f"  Throughput:     {bulk_metrics.throughput:.1f} resources/s")
        logger.info(f"  Memory Used:    {bulk_metrics.memory_used:.2f} MB")
        logger.info(f"")
        logger.info(f"Performance Improvement:")
        logger.info(f"  Speedup:        {speedup:.2f}x")
        logger.info(f"  Throughput:     +{throughput_improvement:.1f}%")
        logger.info(f"{'='*70}")


    async def test_resources_single_vs_bulk_comparison_1k(self, perf_tester: BulkImportPerformanceTester):
        """Compare single vs bulk import performance for resources (1000 resources)."""
        resources = perf_tester._generate_resources(1000)

        # Test single import
        logger.info("Testing single resource imports (1000 resources)...")
        single_metrics = await perf_tester.benchmark_resources_import_single(resources)

        # Test bulk import
        logger.info("Testing bulk resource imports (1000 resources)...")
        bulk_metrics = await perf_tester.benchmark_resources_import(resources)

        # Calculate speedup
        speedup = single_metrics.execution_time / bulk_metrics.execution_time if bulk_metrics.execution_time > 0 else 0
        throughput_improvement = ((bulk_metrics.throughput - single_metrics.throughput) / single_metrics.throughput * 100) if single_metrics.throughput > 0 else 0

        logger.info(f"\n{'='*70}")
        logger.info(f"Resources Import Performance Comparison (1000 resources)")
        logger.info(f"{'='*70}")
        logger.info(f"Single Import:")
        logger.info(f"  Execution Time: {single_metrics.execution_time:.3f}s")
        logger.info(f"  Throughput:     {single_metrics.throughput:.1f} resources/s")
        logger.info(f"  Memory Used:    {single_metrics.memory_used:.2f} MB")
        logger.info(f"")
        logger.info(f"Bulk Import:")
        logger.info(f"  Execution Time: {bulk_metrics.execution_time:.3f}s")
        logger.info(f"  Throughput:     {bulk_metrics.throughput:.1f} resources/s")
        logger.info(f"  Memory Used:    {bulk_metrics.memory_used:.2f} MB")
        logger.info(f"")
        logger.info(f"Performance Improvement:")
        logger.info(f"  Speedup:        {speedup:.2f}x")
        logger.info(f"  Throughput:     +{throughput_improvement:.1f}%")
        logger.info(f"{'='*70}")

        assert bulk_metrics.throughput > single_metrics.throughput, "Bulk should be faster than single"
        assert speedup > 1.0, f"Expected speedup > 1.0x, got {speedup:.2f}x"
        assert bulk_metrics.throughput > single_metrics.throughput, "Bulk should be faster than single"
        assert speedup > 1.0, f"Expected speedup > 1.0x, got {speedup:.2f}x"



@pytest.mark.asyncio
@pytest.mark.performance
class TestToolsImportComparison:
    """Comparison tests for single vs bulk tool imports to measure speedup."""

    async def test_tools_single_vs_bulk_comparison(self, perf_tester: BulkImportPerformanceTester):
        """Compare single vs bulk import performance for tools (100 tools)."""
        tools = perf_tester._generate_tools(100)

        # Test single import
        logger.info("Testing single tool imports...")
        single_metrics = await perf_tester.benchmark_tools_import_single(tools)

        # Test bulk import
        logger.info("Testing bulk tool imports...")
        bulk_metrics = await perf_tester.benchmark_tools_import(tools)

        # Calculate speedup
        speedup = single_metrics.execution_time / bulk_metrics.execution_time if bulk_metrics.execution_time > 0 else 0
        throughput_improvement = ((bulk_metrics.throughput - single_metrics.throughput) / single_metrics.throughput * 100) if single_metrics.throughput > 0 else 0

        logger.info(f"\n{'='*70}")
        logger.info(f"Tools Import Performance Comparison (100 tools)")
        logger.info(f"{'='*70}")
        logger.info(f"Single Import:")
        logger.info(f"  Execution Time: {single_metrics.execution_time:.3f}s")
        logger.info(f"  Throughput:     {single_metrics.throughput:.1f} tools/s")
        logger.info(f"  Memory Used:    {single_metrics.memory_used:.2f} MB")
        logger.info(f"")
        logger.info(f"Bulk Import:")
        logger.info(f"  Execution Time: {bulk_metrics.execution_time:.3f}s")
        logger.info(f"  Throughput:     {bulk_metrics.throughput:.1f} tools/s")
        logger.info(f"  Memory Used:    {bulk_metrics.memory_used:.2f} MB")
        logger.info(f"")
        logger.info(f"Performance Improvement:")
        logger.info(f"  Speedup:        {speedup:.2f}x")
        logger.info(f"  Throughput:     +{throughput_improvement:.1f}%")
        logger.info(f"{'='*70}")

        assert bulk_metrics.throughput > single_metrics.throughput, "Bulk should be faster than single"
        assert speedup > 1.0, f"Expected speedup > 1.0x, got {speedup:.2f}x"

    async def test_tools_single_vs_bulk_comparison_1k(self, perf_tester: BulkImportPerformanceTester):
        """Compare single vs bulk import performance for tools (1000 tools)."""
        tools = perf_tester._generate_tools(1000)

        # Test single import
        logger.info("Testing single tool imports (1000 tools)...")
        single_metrics = await perf_tester.benchmark_tools_import_single(tools)

        # Test bulk import
        logger.info("Testing bulk tool imports (1000 tools)...")
        bulk_metrics = await perf_tester.benchmark_tools_import(tools)

        # Calculate speedup
        speedup = single_metrics.execution_time / bulk_metrics.execution_time if bulk_metrics.execution_time > 0 else 0
        throughput_improvement = ((bulk_metrics.throughput - single_metrics.throughput) / single_metrics.throughput * 100) if single_metrics.throughput > 0 else 0

        logger.info(f"\n{'='*70}")
        logger.info(f"Tools Import Performance Comparison (1000 tools)")
        logger.info(f"{'='*70}")
        logger.info(f"Single Import:")
        logger.info(f"  Execution Time: {single_metrics.execution_time:.3f}s")
        logger.info(f"  Throughput:     {single_metrics.throughput:.1f} tools/s")
        logger.info(f"  Memory Used:    {single_metrics.memory_used:.2f} MB")
        logger.info(f"")
        logger.info(f"Bulk Import:")
        logger.info(f"  Execution Time: {bulk_metrics.execution_time:.3f}s")
        logger.info(f"  Throughput:     {bulk_metrics.throughput:.1f} tools/s")
        logger.info(f"  Memory Used:    {bulk_metrics.memory_used:.2f} MB")
        logger.info(f"")
        logger.info(f"Performance Improvement:")
        logger.info(f"  Speedup:        {speedup:.2f}x")
        logger.info(f"  Throughput:     +{throughput_improvement:.1f}%")
        logger.info(f"{'='*70}")

        assert bulk_metrics.throughput > single_metrics.throughput, "Bulk should be faster than single"
        assert speedup > 1.0, f"Expected speedup > 1.0x, got {speedup:.2f}x"


@pytest.mark.asyncio
@pytest.mark.performance
class TestPromptsImportComparison:
    """Comparison tests for single vs bulk prompt imports to measure speedup."""

    async def test_prompts_single_vs_bulk_comparison(self, perf_tester: BulkImportPerformanceTester):
        """Compare single vs bulk import performance for prompts (100 prompts)."""
        prompts = perf_tester._generate_prompts(100)

        # Test single import
        logger.info("Testing single prompt imports...")
        single_metrics = await perf_tester.benchmark_prompts_import_single(prompts)

        # Test bulk import
        logger.info("Testing bulk prompt imports...")
        bulk_metrics = await perf_tester.benchmark_prompts_import(prompts)

        # Calculate speedup
        speedup = single_metrics.execution_time / bulk_metrics.execution_time if bulk_metrics.execution_time > 0 else 0
        throughput_improvement = ((bulk_metrics.throughput - single_metrics.throughput) / single_metrics.throughput * 100) if single_metrics.throughput > 0 else 0

        logger.info(f"\n{'='*70}")
        logger.info(f"Prompts Import Performance Comparison (100 prompts)")
        logger.info(f"{'='*70}")
        logger.info(f"Single Import:")
        logger.info(f"  Execution Time: {single_metrics.execution_time:.3f}s")
        logger.info(f"  Throughput:     {single_metrics.throughput:.1f} prompts/s")
        logger.info(f"  Memory Used:    {single_metrics.memory_used:.2f} MB")
        logger.info(f"")
        logger.info(f"Bulk Import:")
        logger.info(f"  Execution Time: {bulk_metrics.execution_time:.3f}s")
        logger.info(f"  Throughput:     {bulk_metrics.throughput:.1f} prompts/s")
        logger.info(f"  Memory Used:    {bulk_metrics.memory_used:.2f} MB")
        logger.info(f"")
        logger.info(f"Performance Improvement:")
        logger.info(f"  Speedup:        {speedup:.2f}x")
        logger.info(f"  Throughput:     +{throughput_improvement:.1f}%")
        logger.info(f"{'='*70}")

        assert bulk_metrics.throughput > single_metrics.throughput, "Bulk should be faster than single"
        assert speedup > 1.0, f"Expected speedup > 1.0x, got {speedup:.2f}x"



    async def test_prompts_single_vs_bulk_comparison_1k(self, perf_tester: BulkImportPerformanceTester):
        """Compare single vs bulk import performance for prompts (1000 prompts)."""
        prompts = perf_tester._generate_prompts(1000)

        # Test single import
        logger.info("Testing single prompt imports (1000 prompts)...")
        single_metrics = await perf_tester.benchmark_prompts_import_single(prompts)

        # Test bulk import
        logger.info("Testing bulk prompt imports (1000 prompts)...")
        bulk_metrics = await perf_tester.benchmark_prompts_import(prompts)

        # Calculate speedup
        speedup = single_metrics.execution_time / bulk_metrics.execution_time if bulk_metrics.execution_time > 0 else 0
        throughput_improvement = ((bulk_metrics.throughput - single_metrics.throughput) / single_metrics.throughput * 100) if single_metrics.throughput > 0 else 0

        logger.info(f"\n{'='*70}")
        logger.info(f"Prompts Import Performance Comparison (1000 prompts)")
        logger.info(f"{'='*70}")
        logger.info(f"Single Import:")
        logger.info(f"  Execution Time: {single_metrics.execution_time:.3f}s")
        logger.info(f"  Throughput:     {single_metrics.throughput:.1f} prompts/s")
        logger.info(f"  Memory Used:    {single_metrics.memory_used:.2f} MB")
        logger.info(f"")
        logger.info(f"Bulk Import:")
        logger.info(f"  Execution Time: {bulk_metrics.execution_time:.3f}s")
        logger.info(f"  Throughput:     {bulk_metrics.throughput:.1f} prompts/s")
        logger.info(f"  Memory Used:    {bulk_metrics.memory_used:.2f} MB")
        logger.info(f"")
        logger.info(f"Performance Improvement:")
        logger.info(f"  Speedup:        {speedup:.2f}x")
        logger.info(f"  Throughput:     +{throughput_improvement:.1f}%")
        logger.info(f"{'='*70}")

        assert bulk_metrics.throughput > single_metrics.throughput, "Bulk should be faster than single"
        assert speedup > 1.0, f"Expected speedup > 1.0x, got {speedup:.2f}x"
