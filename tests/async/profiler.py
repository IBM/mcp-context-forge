# -*- coding: utf-8 -*-
"""Location: ./tests/async/profiler.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive async performance profiler for mcpgateway.
"""

# Standard
import argparse
import asyncio
import cProfile
import json
from pathlib import Path
import pstats
import time
from typing import Any, Dict, List, Union

# Third-Party
import aiohttp
import websockets


class AsyncProfiler:
    """Profile async operations in mcpgateway."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.profiles = {}

    def _generate_combined_profile(self, scenarios: List[str]) -> None:
        """
        Generate a combined profile for the given scenarios.
        Args:
            scenarios (List[str]): A list of scenario names.
        """
        combined_profile_path = self.output_dir / "combined_profile.prof"
        print(f"Generating combined profile at {combined_profile_path}")

        stats = pstats.Stats()

        for scenario in scenarios:
            profile_path = self.output_dir / f"{scenario}_profile.prof"
            stats.add(str(profile_path))

        stats.dump_stats(str(combined_profile_path))

    def _generate_summary_report(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a summary report from the profiling results.
        Args:
            results (Dict[str, Any]): The profiling results.
        """
        # Implementation of the summary report generation
        print("Generating summary report with results:", results)
        return {"results": results}

    async def profile_all_scenarios(self, scenarios: List[str], duration: int) -> Dict[str, Any]:
        """Profile all specified async scenarios."""

        results: Dict[str, Union[Dict[str, Any], float]] = {"scenarios": {}, "summary": {}, "timestamp": time.time()}

        # Ensure 'scenarios' and 'summary' keys are dictionaries
        results["scenarios"] = {}
        results["summary"] = {}

        for scenario in scenarios:
            print(f"📊 Profiling scenario: {scenario}")

            profile_path = self.output_dir / f"{scenario}_profile.prof"
            profile_result = await self._profile_scenario(scenario, duration, profile_path)

            results["scenarios"][scenario] = profile_result

        # Generate combined profile
        self._generate_combined_profile(scenarios)

        # Generate summary report
        results["summary"] = self._generate_summary_report(results["scenarios"])

        return results

    async def _profile_scenario(self, scenario: str, duration: int, output_path: Path) -> Dict[str, Any]:
        """Profile a specific async scenario."""

        scenario_methods = {
            "websocket": self._profile_websocket_operations,
            "database": self._profile_database_operations,
            "mcp_calls": self._profile_mcp_operations,
            "concurrent_requests": self._profile_concurrent_requests,
        }

        if scenario not in scenario_methods:
            raise ValueError(f"Unknown scenario: {scenario}")

        # Run profiling
        profiler = cProfile.Profile()
        profiler.enable()

        start_time = time.time()
        scenario_result = await scenario_methods[scenario](duration)
        end_time = time.time()

        profiler.disable()
        profiler.dump_stats(str(output_path))

        # Analyze profile
        stats = pstats.Stats(str(output_path))
        stats.sort_stats("cumulative")

        return {
            "scenario": scenario,
            "duration": end_time - start_time,
            "profile_file": str(output_path),
            "total_calls": stats.total_calls,
            "total_time": stats.total_tt,
            "top_functions": self._extract_top_functions(stats),
            "async_metrics": scenario_result,
        }

    async def _profile_concurrent_requests(self, duration: int) -> Dict[str, Any]:
        """Profile concurrent HTTP requests."""

        metrics: Dict[str, float] = {"requests_made": 0, "avg_response_time": 0, "successful_requests": 0, "failed_requests": 0}

        async def make_request():
            try:
                async with aiohttp.ClientSession() as session:
                    start_time = time.time()

                    async with session.get("http://localhost:4444/ws") as response:
                        await response.text()

                    response_time = time.time() - start_time
                    metrics["requests_made"] += 1
                    metrics["successful_requests"] += 1
                    metrics["avg_response_time"] = (metrics["avg_response_time"] * (metrics["requests_made"] - 1) + response_time) / metrics["requests_made"]

            except Exception:
                metrics["failed_requests"] += 1

        # Run concurrent requests
        tasks: List[Any] = []
        end_time = time.time() + duration

        while time.time() < end_time:
            if len(tasks) < 10:  # Max 10 concurrent requests
                task = asyncio.create_task(make_request())
                tasks.append(task)

            # Clean up completed tasks
            tasks = [t for t in tasks if not t.done()]
            await asyncio.sleep(0.1)

        # Wait for remaining tasks
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return metrics

    async def _profile_websocket_operations(self, duration: int) -> Dict[str, Any]:
        """Profile WebSocket connection and message handling."""

        metrics: Dict[str, float] = {"connections_established": 0, "messages_sent": 0, "messages_received": 0, "connection_errors": 0, "avg_latency": 0}

        async def websocket_client():
            try:
                async with websockets.connect("ws://localhost:4444/ws") as websocket:
                    metrics["connections_established"] += 1

                    # Send test messages
                    for i in range(10):
                        message = json.dumps({"type": "ping", "data": f"test_{i}"})
                        start_time = time.time()

                        await websocket.send(message)
                        metrics["messages_sent"] += 1

                        _response = await websocket.recv()  # noqa: F841
                        metrics["messages_received"] += 1

                        latency = time.time() - start_time
                        metrics["avg_latency"] = (metrics["avg_latency"] * i + latency) / (i + 1)

                        await asyncio.sleep(0.1)

            except Exception:
                metrics["connection_errors"] += 1

        # Run concurrent WebSocket clients
        tasks: List[Any] = []
        end_time = time.time() + duration

        while time.time() < end_time:
            if len(tasks) < 10:  # Max 10 concurrent connections
                task = asyncio.create_task(websocket_client())
                tasks.append(task)

            # Clean up completed tasks
            tasks = [t for t in tasks if not t.done()]
            await asyncio.sleep(0.1)

        # Wait for remaining tasks
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return metrics

    async def _profile_database_operations(self, duration: int) -> Dict[str, Any]:
        """Profile database query performance."""

        metrics: Dict[str, float] = {"queries_executed": 0, "avg_query_time": 0, "connection_time": 0, "errors": 0}

        # Simulate database operations
        async def database_operations():
            try:
                # Simulate async database queries
                query_start = time.time()

                # Mock database query (replace with actual database calls)
                await asyncio.sleep(0.01)  # Simulate 10ms query

                query_time = time.time() - query_start
                metrics["queries_executed"] += 1
                metrics["avg_query_time"] = (metrics["avg_query_time"] * (metrics["queries_executed"] - 1) + query_time) / metrics["queries_executed"]

            except Exception:
                metrics["errors"] += 1

        # Run database operations for specified duration
        end_time = time.time() + duration

        while time.time() < end_time:
            await database_operations()
            await asyncio.sleep(0.001)  # Small delay between operations

        return metrics

    async def _profile_mcp_operations(self, duration: int) -> Dict[str, Any]:
        """Profile MCP server communication."""

        metrics: Dict[str, float] = {"rpc_calls": 0, "avg_rpc_time": 0, "successful_calls": 0, "failed_calls": 0}

        async def mcp_rpc_call():
            try:
                async with aiohttp.ClientSession() as session:
                    payload = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}

                    start_time = time.time()

                    async with session.post("http://localhost:4444/rpc", json=payload, timeout=aiohttp.ClientTimeout(total=5)) as response:
                        await response.json()

                    rpc_time = time.time() - start_time
                    metrics["rpc_calls"] += 1
                    metrics["successful_calls"] += 1
                    metrics["avg_rpc_time"] = (metrics["avg_rpc_time"] * (metrics["rpc_calls"] - 1) + rpc_time) / metrics["rpc_calls"]

            except Exception:
                metrics["failed_calls"] += 1

        # Run MCP operations
        end_time = time.time() + duration

        while time.time() < end_time:
            await mcp_rpc_call()
            await asyncio.sleep(0.1)

        return metrics

    def _extract_top_functions(self, stats: pstats.Stats) -> List[Dict[str, Union[str, float, int]]]:
        """
        Extract the top functions from the profiling stats.
        Args:
            stats (pstats.Stats): The profiling statistics.
        Returns:
            List[Dict[str, Union[str, float, int]]]: A list of dictionaries containing the top functions.
        """
        top_functions: List[Dict[str, Any]] = []
        for func_stat in stats.fcn_list[:10]:  # Get top 10 functions
            top_functions.append({"function_name": func_stat[2], "call_count": stats.stats[func_stat][0], "total_time": stats.stats[func_stat][2], "cumulative_time": stats.stats[func_stat][3]})
        return top_functions


# Main entry point for the script
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Async performance profiler for mcpgateway.")
    parser.add_argument("--scenarios", type=str, required=True, help="Comma-separated list of scenarios to profile.")
    parser.add_argument("--output", type=str, required=True, help="Output directory for profile files.")
    parser.add_argument("--duration", type=int, default=60, help="Duration to run each scenario (in seconds).")

    args = parser.parse_args()

    scenarios = args.scenarios.split(",")
    output_dir = args.output
    duration = args.duration

    profiler = AsyncProfiler(output_dir)

    asyncio.run(profiler.profile_all_scenarios(scenarios, duration))
