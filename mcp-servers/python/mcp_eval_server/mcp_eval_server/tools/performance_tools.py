# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp_eval_server/mcp_eval_server/tools/performance_tools.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP tools for performance monitoring and evaluation.
"""

# Standard
import asyncio
import statistics
import time
from typing import Any, Callable, Dict, List, Optional

# Third-Party
import psutil

# Local
from .judge_tools import JudgeTools


class PerformanceTools:
    """Tools for performance monitoring and evaluation."""

    def __init__(self, judge_tools: Optional[JudgeTools] = None):
        """Initialize performance tools.

        Args:
            judge_tools: Judge tools instance for LLM evaluations
        """
        self.judge_tools = judge_tools or JudgeTools()
        self._baseline_memory = psutil.virtual_memory().used

    async def measure_response_latency(
        self,
        test_inputs: List[str],
        target_function: Optional[Callable] = None,
        warmup_runs: int = 2,
        measurement_runs: int = 10,
        timeout_seconds: float = 30.0,
    ) -> Dict[str, Any]:
        """Track generation speed and response times.

        Args:
            test_inputs: List of inputs to test latency for
            target_function: Function to measure (if None, simulates responses)
            warmup_runs: Number of warmup runs before measurement
            measurement_runs: Number of measured runs per input
            timeout_seconds: Maximum time to wait for response

        Returns:
            Response latency analysis
        """
        if target_function is None:
            target_function = self._simulate_response_generation

        latency_results = []

        for test_input in test_inputs:
            input_latencies = []

            # Warmup runs
            for _ in range(warmup_runs):
                try:
                    await asyncio.wait_for(target_function(test_input), timeout=timeout_seconds)
                except asyncio.TimeoutError:
                    continue

            # Measurement runs
            for _run in range(measurement_runs):
                start_time = time.perf_counter()
                try:
                    await asyncio.wait_for(target_function(test_input), timeout=timeout_seconds)
                    end_time = time.perf_counter()
                    latency = end_time - start_time
                    input_latencies.append(latency)
                except asyncio.TimeoutError:
                    input_latencies.append(timeout_seconds)  # Mark as timeout
                except Exception:
                    input_latencies.append(float("inf"))  # Mark as error

            # Calculate statistics for this input
            valid_latencies = [latency for latency in input_latencies if latency != float("inf") and latency < timeout_seconds]

            if valid_latencies:
                latency_stats = {
                    "input": test_input[:100],  # Truncate for display
                    "mean_latency": statistics.mean(valid_latencies),
                    "median_latency": statistics.median(valid_latencies),
                    "std_latency": statistics.stdev(valid_latencies) if len(valid_latencies) > 1 else 0.0,
                    "min_latency": min(valid_latencies),
                    "max_latency": max(valid_latencies),
                    "p95_latency": self._calculate_percentile(valid_latencies, 95),
                    "p99_latency": self._calculate_percentile(valid_latencies, 99),
                    "success_rate": len(valid_latencies) / measurement_runs,
                    "timeout_rate": sum(1 for latency in input_latencies if latency >= timeout_seconds) / measurement_runs,
                }
            else:
                latency_stats = {
                    "input": test_input[:100],
                    "mean_latency": float("inf"),
                    "success_rate": 0.0,
                    "timeout_rate": 1.0,
                }

            latency_results.append(latency_stats)

        # Aggregate statistics
        all_latencies = []
        for result in latency_results:
            if result["success_rate"] > 0:
                all_latencies.append(result["mean_latency"])

        if all_latencies:
            aggregate_stats = {
                "overall_mean_latency": statistics.mean(all_latencies),
                "overall_median_latency": statistics.median(all_latencies),
                "overall_std_latency": statistics.stdev(all_latencies) if len(all_latencies) > 1 else 0.0,
                "overall_p95_latency": self._calculate_percentile(all_latencies, 95),
                "overall_p99_latency": self._calculate_percentile(all_latencies, 99),
            }
        else:
            aggregate_stats = {"overall_mean_latency": float("inf")}

        return {
            "aggregate_stats": aggregate_stats,
            "input_results": latency_results,
            "analysis": {
                "total_inputs_tested": len(test_inputs),
                "measurement_runs_per_input": measurement_runs,
                "timeout_threshold": timeout_seconds,
                "fastest_input": min(latency_results, key=lambda x: x.get("mean_latency", float("inf")))["input"][:50] if all_latencies else None,
                "slowest_input": max(latency_results, key=lambda x: x.get("mean_latency", 0))["input"][:50] if all_latencies else None,
            },
            "recommendations": self._generate_latency_recommendations(aggregate_stats, latency_results),
        }

    async def assess_computational_efficiency(
        self,
        test_workloads: List[Dict[str, Any]],
        resource_monitoring_interval: float = 0.1,
        efficiency_metrics: List[str] = None,
    ) -> Dict[str, Any]:
        """Measure resource usage and computational efficiency.

        Args:
            test_workloads: List of workloads to test efficiency for
            resource_monitoring_interval: How often to sample resource usage (seconds)
            efficiency_metrics: Specific efficiency metrics to track

        Returns:
            Computational efficiency analysis
        """
        if efficiency_metrics is None:
            efficiency_metrics = ["cpu_usage", "memory_usage", "cpu_per_token", "memory_per_token"]

        # Baseline resource measurements
        baseline_cpu = psutil.cpu_percent(interval=0.1)
        baseline_memory = psutil.virtual_memory().used

        efficiency_results = []

        for workload in test_workloads:
            efficiency_result = await self._measure_workload_efficiency(workload, baseline_cpu, baseline_memory, resource_monitoring_interval)
            efficiency_results.append(efficiency_result)

        # Aggregate efficiency metrics
        metric_aggregates = {}
        for metric in efficiency_metrics:
            metric_values = []
            for result in efficiency_results:
                if metric in result["efficiency_metrics"]:
                    metric_values.append(result["efficiency_metrics"][metric])

            if metric_values:
                metric_aggregates[metric] = {
                    "mean": statistics.mean(metric_values),
                    "std": statistics.stdev(metric_values) if len(metric_values) > 1 else 0.0,
                    "min": min(metric_values),
                    "max": max(metric_values),
                    "p95": self._calculate_percentile(metric_values, 95),
                }

        # Calculate overall efficiency score
        efficiency_scores = []
        for result in efficiency_results:
            workload_efficiency = 1.0 - min(1.0, result["resource_usage"]["peak_cpu"] / 100.0 + result["resource_usage"]["peak_memory_mb"] / 1000.0)
            efficiency_scores.append(max(0.0, workload_efficiency))

        overall_efficiency = statistics.mean(efficiency_scores) if efficiency_scores else 0.0

        return {
            "overall_efficiency": overall_efficiency,
            "metric_aggregates": metric_aggregates,
            "efficiency_results": efficiency_results,
            "baseline_resources": {
                "cpu_percent": baseline_cpu,
                "memory_mb": baseline_memory / (1024 * 1024),
            },
            "analysis": {
                "workloads_tested": len(test_workloads),
                "efficiency_metrics": efficiency_metrics,
                "monitoring_interval": resource_monitoring_interval,
                "most_efficient_workload": min(efficiency_results, key=lambda x: x["resource_usage"]["peak_cpu"])["workload"]["name"] if efficiency_results else None,
                "least_efficient_workload": max(efficiency_results, key=lambda x: x["resource_usage"]["peak_cpu"])["workload"]["name"] if efficiency_results else None,
            },
            "recommendations": self._generate_efficiency_recommendations(overall_efficiency, metric_aggregates),
        }

    async def evaluate_throughput_scaling(
        self,
        test_request: str,
        concurrency_levels: List[int] = None,
        requests_per_level: int = 20,
        target_function: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """Test concurrent request handling and scaling behavior.

        Args:
            test_request: Request to use for throughput testing
            concurrency_levels: List of concurrent request counts to test
            requests_per_level: Number of requests to send at each concurrency level
            target_function: Function to test (if None, simulates responses)

        Returns:
            Throughput scaling analysis
        """
        if concurrency_levels is None:
            concurrency_levels = [1, 2, 5, 10, 20]

        if target_function is None:
            target_function = self._simulate_response_generation

        scaling_results = []

        for concurrency in concurrency_levels:
            scaling_result = await self._test_concurrency_level(test_request, concurrency, requests_per_level, target_function)
            scaling_results.append(scaling_result)

        # Analyze scaling characteristics
        scaling_analysis = self._analyze_scaling_behavior(scaling_results)

        # Calculate throughput metrics
        max_throughput = max(r["throughput_rps"] for r in scaling_results)
        optimal_concurrency = max(scaling_results, key=lambda x: x["throughput_rps"])["concurrency"]

        # Detect throughput bottlenecks
        bottlenecks = self._detect_throughput_bottlenecks(scaling_results)

        return {
            "max_throughput": max_throughput,
            "optimal_concurrency": optimal_concurrency,
            "scaling_results": scaling_results,
            "scaling_analysis": scaling_analysis,
            "bottlenecks": bottlenecks,
            "analysis": {
                "concurrency_levels_tested": concurrency_levels,
                "requests_per_level": requests_per_level,
                "scaling_efficiency": scaling_analysis["scaling_efficiency"],
                "throughput_peak": max_throughput,
                "degradation_point": scaling_analysis["degradation_point"],
            },
            "recommendations": self._generate_throughput_recommendations(scaling_analysis, bottlenecks),
        }

    async def monitor_memory_usage(
        self,
        monitoring_duration: float = 60.0,
        sampling_interval: float = 1.0,
        workload_function: Optional[Callable] = None,
        memory_threshold_mb: float = 1000.0,
    ) -> Dict[str, Any]:
        """Track memory consumption patterns during execution.

        Args:
            monitoring_duration: How long to monitor (seconds)
            sampling_interval: How often to sample memory (seconds)
            workload_function: Function to run during monitoring
            memory_threshold_mb: Memory usage threshold for alerts

        Returns:
            Memory usage monitoring results
        """
        memory_samples = []
        start_time = time.time()

        # Start workload if provided
        workload_task = None
        if workload_function:
            workload_task = asyncio.create_task(workload_function())

        try:
            # Monitor memory usage
            while (time.time() - start_time) < monitoring_duration:
                memory_info = psutil.virtual_memory()
                process = psutil.Process()
                process_memory = process.memory_info()

                sample = {
                    "timestamp": time.time() - start_time,
                    "system_memory_mb": memory_info.used / (1024 * 1024),
                    "system_memory_percent": memory_info.percent,
                    "process_memory_mb": process_memory.rss / (1024 * 1024),
                    "process_memory_vms_mb": process_memory.vms / (1024 * 1024),
                }
                memory_samples.append(sample)

                await asyncio.sleep(sampling_interval)

        finally:
            if workload_task and not workload_task.done():
                workload_task.cancel()
                try:
                    await workload_task
                except asyncio.CancelledError:
                    pass

        # Analyze memory patterns
        memory_analysis = self._analyze_memory_patterns(memory_samples, memory_threshold_mb)

        # Detect memory issues
        memory_issues = self._detect_memory_issues(memory_samples, memory_threshold_mb)

        # Calculate memory efficiency metrics
        if memory_samples:
            system_memory_values = [s["system_memory_mb"] for s in memory_samples]
            process_memory_values = [s["process_memory_mb"] for s in memory_samples]

            memory_metrics = {
                "peak_system_memory": max(system_memory_values),
                "avg_system_memory": statistics.mean(system_memory_values),
                "peak_process_memory": max(process_memory_values),
                "avg_process_memory": statistics.mean(process_memory_values),
                "memory_growth_rate": self._calculate_memory_growth_rate(memory_samples),
                "memory_stability": self._calculate_memory_stability(process_memory_values),
            }
        else:
            memory_metrics = {}

        return {
            "memory_metrics": memory_metrics,
            "memory_samples": memory_samples,
            "memory_analysis": memory_analysis,
            "memory_issues": memory_issues,
            "analysis": {
                "monitoring_duration": monitoring_duration,
                "sampling_interval": sampling_interval,
                "total_samples": len(memory_samples),
                "memory_threshold": memory_threshold_mb,
                "baseline_memory": self._baseline_memory / (1024 * 1024),
            },
            "recommendations": self._generate_memory_recommendations(memory_metrics, memory_issues),
        }

    # Helper methods for performance monitoring

    async def _simulate_response_generation(self, input_text: str) -> str:
        """Simulate response generation for testing.

        Args:
            input_text: Input text to simulate processing for

        Returns:
            Simulated response string
        """
        # Simulate processing time based on input length
        processing_time = len(input_text) * 0.001 + 0.05  # Base time + length factor
        await asyncio.sleep(processing_time)
        return f"Simulated response for: {input_text[:50]}..."

    def _calculate_percentile(self, values: List[float], percentile: int) -> float:
        """Calculate percentile of values.

        Args:
            values: List of numerical values
            percentile: Percentile to calculate (0-100)

        Returns:
            Percentile value
        """
        if not values:
            return 0.0

        sorted_values = sorted(values)
        index = int((percentile / 100.0) * len(sorted_values))
        index = min(index, len(sorted_values) - 1)
        return sorted_values[index]

    async def _measure_workload_efficiency(self, workload: Dict[str, Any], baseline_cpu: float, _baseline_memory: int, _interval: float) -> Dict[str, Any]:
        """Measure efficiency for a specific workload.

        Args:
            workload: Workload configuration to measure
            baseline_cpu: Baseline CPU usage percentage
            _baseline_memory: Baseline memory usage in bytes
            _interval: Monitoring interval in seconds

        Returns:
            Dictionary containing workload efficiency metrics
        """
        _ = workload.get("name", "unnamed")  # Workload name for potential future use
        workload_input = workload.get("input", "test input")

        # Monitor resources during workload execution
        start_time = time.time()
        start_memory = psutil.virtual_memory().used

        # Simulate workload execution
        await self._simulate_response_generation(workload_input)

        end_time = time.time()
        end_memory = psutil.virtual_memory().used

        execution_time = end_time - start_time
        memory_delta = (end_memory - start_memory) / (1024 * 1024)  # MB

        # Calculate efficiency metrics
        efficiency_metrics = {
            "cpu_usage": psutil.cpu_percent() - baseline_cpu,
            "memory_usage": memory_delta,
            "cpu_per_token": (psutil.cpu_percent() - baseline_cpu) / max(1, len(workload_input.split())),
            "memory_per_token": memory_delta / max(1, len(workload_input.split())),
        }

        resource_usage = {
            "execution_time": execution_time,
            "peak_cpu": psutil.cpu_percent(),
            "peak_memory_mb": end_memory / (1024 * 1024),
            "memory_delta_mb": memory_delta,
        }

        return {
            "workload": workload,
            "efficiency_metrics": efficiency_metrics,
            "resource_usage": resource_usage,
        }

    async def _test_concurrency_level(self, request: str, concurrency: int, total_requests: int, target_function: Callable) -> Dict[str, Any]:
        """Test throughput at a specific concurrency level.

        Args:
            request: Request string to test with
            concurrency: Number of concurrent requests
            total_requests: Total number of requests to send
            target_function: Function to test concurrency for

        Returns:
            Dictionary containing concurrency test results
        """
        start_time = time.time()

        # Create tasks for concurrent execution
        tasks = []
        for _ in range(total_requests):
            task = asyncio.create_task(target_function(request))
            tasks.append(task)

        # Execute with controlled concurrency
        semaphore = asyncio.Semaphore(concurrency)

        async def controlled_execution(task):
            async with semaphore:
                return await task

        # Wait for all tasks to complete
        try:
            results = await asyncio.gather(*[controlled_execution(task) for task in tasks], return_exceptions=True)
            end_time = time.time()

            # Analyze results
            successful_requests = sum(1 for r in results if not isinstance(r, Exception))
            failed_requests = total_requests - successful_requests
            total_time = end_time - start_time

            throughput_rps = successful_requests / total_time if total_time > 0 else 0.0
            success_rate = successful_requests / total_requests

        except Exception:
            end_time = time.time()
            total_time = end_time - start_time
            successful_requests = 0
            failed_requests = total_requests
            throughput_rps = 0.0
            success_rate = 0.0

        return {
            "concurrency": concurrency,
            "total_requests": total_requests,
            "successful_requests": successful_requests,
            "failed_requests": failed_requests,
            "total_time": total_time,
            "throughput_rps": throughput_rps,
            "success_rate": success_rate,
            "avg_response_time": total_time / max(1, successful_requests),
        }

    def _analyze_scaling_behavior(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze scaling behavior from throughput test results.

        Args:
            results: List of throughput test results

        Returns:
            Dictionary containing scaling behavior analysis
        """
        if not results:
            return {"scaling_efficiency": 0.0, "degradation_point": None}

        # Calculate scaling efficiency
        throughputs = [r["throughput_rps"] for r in results]
        concurrencies = [r["concurrency"] for r in results]

        # Find peak throughput
        peak_throughput = max(throughputs)
        peak_concurrency = results[throughputs.index(peak_throughput)]["concurrency"]

        # Calculate scaling efficiency (how linear is the scaling)
        if len(results) >= 2:
            # Linear scaling would mean throughput increases proportionally with concurrency
            ideal_scaling = [(throughputs[0] * c / concurrencies[0]) for c in concurrencies]
            actual_vs_ideal = [actual / ideal for actual, ideal in zip(throughputs, ideal_scaling)]
            scaling_efficiency = statistics.mean(actual_vs_ideal)
        else:
            scaling_efficiency = 1.0

        # Find degradation point (where throughput starts decreasing)
        degradation_point = None
        for i in range(1, len(results)):
            if results[i]["throughput_rps"] < results[i - 1]["throughput_rps"] * 0.95:
                degradation_point = results[i]["concurrency"]
                break

        return {
            "scaling_efficiency": min(1.0, scaling_efficiency),
            "peak_throughput": peak_throughput,
            "peak_concurrency": peak_concurrency,
            "degradation_point": degradation_point,
            "throughput_curve": list(zip(concurrencies, throughputs)),
        }

    def _detect_throughput_bottlenecks(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect throughput bottlenecks from scaling results.

        Args:
            results: List of scaling test results

        Returns:
            List of detected bottlenecks with details
        """
        bottlenecks = []

        for i, result in enumerate(results):
            # Check for high failure rates
            if result["success_rate"] < 0.9:
                bottlenecks.append(
                    {
                        "type": "high_failure_rate",
                        "concurrency": result["concurrency"],
                        "success_rate": result["success_rate"],
                        "severity": "high" if result["success_rate"] < 0.5 else "medium",
                    }
                )

            # Check for throughput plateaus
            if i > 0:
                prev_throughput = results[i - 1]["throughput_rps"]
                curr_throughput = result["throughput_rps"]
                if prev_throughput > 0 and curr_throughput / prev_throughput < 1.1:
                    bottlenecks.append(
                        {
                            "type": "throughput_plateau",
                            "concurrency": result["concurrency"],
                            "throughput_ratio": curr_throughput / prev_throughput,
                            "severity": "medium",
                        }
                    )

        return bottlenecks

    def _analyze_memory_patterns(self, samples: List[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
        """Analyze memory usage patterns.

        Args:
            samples: List of memory usage samples
            threshold: Memory threshold for analysis

        Returns:
            Dictionary containing memory pattern analysis
        """
        if not samples:
            return {}

        process_memory = [s["process_memory_mb"] for s in samples]
        # system_memory = [s["system_memory_mb"] for s in samples]  # Unused but may be needed later

        # Detect memory trends
        memory_trend = "stable"
        if len(process_memory) >= 3:
            early_avg = statistics.mean(process_memory[: len(process_memory) // 3])
            late_avg = statistics.mean(process_memory[-len(process_memory) // 3 :])

            if late_avg > early_avg * 1.2:
                memory_trend = "increasing"
            elif late_avg < early_avg * 0.8:
                memory_trend = "decreasing"

        # Calculate memory efficiency
        peak_memory = max(process_memory)
        avg_memory = statistics.mean(process_memory)
        memory_efficiency = avg_memory / peak_memory if peak_memory > 0 else 1.0

        return {
            "memory_trend": memory_trend,
            "memory_efficiency": memory_efficiency,
            "peak_memory": peak_memory,
            "avg_memory": avg_memory,
            "memory_variance": statistics.variance(process_memory) if len(process_memory) > 1 else 0.0,
            "threshold_exceeded": any(m > threshold for m in process_memory),
        }

    def _detect_memory_issues(self, samples: List[Dict[str, Any]], threshold: float) -> List[Dict[str, Any]]:
        """Detect memory-related issues.

        Args:
            samples: List of memory usage samples
            threshold: Memory threshold for issue detection

        Returns:
            List of detected memory issues
        """
        issues = []

        if not samples:
            return issues

        process_memory = [s["process_memory_mb"] for s in samples]

        # Check for memory leaks
        if len(process_memory) >= 5:
            early_memory = statistics.mean(process_memory[:2])
            late_memory = statistics.mean(process_memory[-2:])

            if late_memory > early_memory * 1.5:
                issues.append(
                    {
                        "type": "potential_memory_leak",
                        "severity": "high",
                        "growth_factor": late_memory / early_memory,
                    }
                )

        # Check for memory spikes
        peak_memory = max(process_memory)
        avg_memory = statistics.mean(process_memory)

        if peak_memory > avg_memory * 2:
            issues.append(
                {
                    "type": "memory_spike",
                    "severity": "medium",
                    "peak_memory": peak_memory,
                    "spike_ratio": peak_memory / avg_memory,
                }
            )

        # Check threshold violations
        violations = [s for s in samples if s["process_memory_mb"] > threshold]
        if violations:
            issues.append(
                {
                    "type": "threshold_violation",
                    "severity": "high",
                    "violation_count": len(violations),
                    "max_violation": max(v["process_memory_mb"] for v in violations),
                }
            )

        return issues

    def _calculate_memory_growth_rate(self, samples: List[Dict[str, Any]]) -> float:
        """Calculate memory growth rate over time.

        Args:
            samples: List of memory usage samples with timestamps

        Returns:
            Memory growth rate in MB per second
        """
        if len(samples) < 2:
            return 0.0

        process_memory = [s["process_memory_mb"] for s in samples]
        timestamps = [s["timestamp"] for s in samples]

        # Simple linear regression for growth rate
        n = len(samples)
        sum_x = sum(timestamps)
        sum_y = sum(process_memory)
        sum_xy = sum(t * m for t, m in zip(timestamps, process_memory))
        sum_x2 = sum(t * t for t in timestamps)

        if n * sum_x2 - sum_x * sum_x != 0:
            slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
            return slope  # MB per second
        return 0.0

    def _calculate_memory_stability(self, memory_values: List[float]) -> float:
        """Calculate memory usage stability.

        Args:
            memory_values: List of memory usage values

        Returns:
            Memory stability score (0-1)
        """
        if len(memory_values) < 2:
            return 1.0

        # Calculate coefficient of variation
        mean_memory = statistics.mean(memory_values)
        std_memory = statistics.stdev(memory_values)

        if mean_memory > 0:
            cv = std_memory / mean_memory
            stability = max(0.0, 1.0 - cv)  # Higher CV = lower stability
        else:
            stability = 1.0

        return stability

    # Recommendation generation methods

    def _generate_latency_recommendations(self, stats: Dict, results: List) -> List[str]:
        """Generate recommendations for improving latency.

        Args:
            stats: Aggregate latency statistics
            results: List of latency test results

        Returns:
            List of recommendation strings
        """
        recommendations = []

        if stats.get("overall_mean_latency", 0) > 2.0:
            recommendations.append("Optimize response generation for better latency")

        high_variance_inputs = [r for r in results if r.get("std_latency", 0) > r.get("mean_latency", 0) * 0.5]
        if high_variance_inputs:
            recommendations.append("Address high latency variance for consistent performance")

        timeout_inputs = [r for r in results if r.get("timeout_rate", 0) > 0.1]
        if timeout_inputs:
            recommendations.append("Investigate and fix timeout issues")

        return recommendations

    def _generate_efficiency_recommendations(self, efficiency: float, metrics: Dict) -> List[str]:
        """Generate recommendations for improving computational efficiency.

        Args:
            efficiency: Overall efficiency score
            metrics: Efficiency metrics by type

        Returns:
            List of recommendation strings
        """
        recommendations = []

        if efficiency < 0.7:
            recommendations.append("Optimize computational efficiency")

        high_cpu_metrics = [metric for metric, data in metrics.items() if "cpu" in metric and data.get("mean", 0) > 50]
        if high_cpu_metrics:
            recommendations.append("Reduce CPU usage for better efficiency")

        high_memory_metrics = [metric for metric, data in metrics.items() if "memory" in metric and data.get("mean", 0) > 500]
        if high_memory_metrics:
            recommendations.append("Optimize memory usage")

        return recommendations

    def _generate_throughput_recommendations(self, analysis: Dict, bottlenecks: List) -> List[str]:
        """Generate recommendations for improving throughput.

        Args:
            analysis: Throughput scaling analysis
            bottlenecks: List of detected bottlenecks

        Returns:
            List of recommendation strings
        """
        recommendations = []

        if analysis.get("scaling_efficiency", 1.0) < 0.7:
            recommendations.append("Improve scaling efficiency for better throughput")

        if analysis.get("degradation_point"):
            recommendations.append(f"Investigate performance degradation above {analysis['degradation_point']} concurrent requests")

        bottleneck_types = [b["type"] for b in bottlenecks]
        if "high_failure_rate" in bottleneck_types:
            recommendations.append("Address high failure rates at increased concurrency")

        return recommendations

    def _generate_memory_recommendations(self, metrics: Dict, issues: List) -> List[str]:
        """Generate recommendations for memory optimization.

        Args:
            metrics: Memory usage metrics
            issues: List of detected memory issues

        Returns:
            List of recommendation strings
        """
        recommendations = []

        if metrics.get("memory_stability", 1.0) < 0.8:
            recommendations.append("Improve memory usage stability")

        if metrics.get("memory_growth_rate", 0) > 1.0:  # More than 1MB/second growth
            recommendations.append("Investigate potential memory leaks")

        issue_types = [i["type"] for i in issues]
        if "threshold_violation" in issue_types:
            recommendations.append("Reduce memory usage to stay within limits")

        if "memory_spike" in issue_types:
            recommendations.append("Optimize memory allocation to prevent spikes")

        return recommendations

    # Additional placeholder methods for complex operations
    async def _compare_cross_lingual_texts(self, _text1: str, _text2: str, _lang1: str, _lang2: str, metrics: List[str], _judge_model: str) -> Dict[str, Any]:
        """Compare texts across languages.

        Args:
            _text1: First text to compare
            _text2: Second text to compare
            _lang1: Language of first text
            _lang2: Language of second text
            metrics: Comparison metrics to evaluate
            _judge_model: Judge model for assessment

        Returns:
            Dictionary containing cross-lingual comparison results
        """
        consistency_scores = {metric: 0.8 for metric in metrics}  # Placeholder
        return {"consistency_scores": consistency_scores}

    async def _compare_translation_pair(self, _text1: str, _text2: str, _lang1: str, _lang2: str, metrics: List[str], _judge_model: str) -> Dict[str, Any]:
        """Compare pair of translations.

        Args:
            _text1: First translation text
            _text2: Second translation text
            _lang1: Language of first text
            _lang2: Language of second text
            metrics: Comparison metrics to evaluate
            _judge_model: Judge model for assessment

        Returns:
            Dictionary containing translation pair comparison
        """
        consistency_scores = {metric: 0.75 for metric in metrics}  # Placeholder
        return {"consistency_scores": consistency_scores}

    async def _assess_cultural_dimension(self, _text: str, _culture: str, _dimension: str, _judge_model: str) -> float:
        """Assess cultural adaptation dimension.

        Args:
            _text: Text to assess
            _culture: Target culture
            _dimension: Cultural dimension to evaluate
            _judge_model: Judge model for assessment

        Returns:
            Cultural adaptation score for the dimension
        """
        return 0.7  # Placeholder

    async def _compare_cultural_adaptation(self, _text: str, _reference: str, _culture: str, _judge_model: str) -> Dict[str, Any]:
        """Compare cultural adaptation with reference.

        Args:
            _text: Text to assess
            _reference: Reference text for comparison
            _culture: Target culture
            _judge_model: Judge model for assessment

        Returns:
            Dictionary containing cultural adaptation comparison
        """
        return {"comparison_score": 0.8}  # Placeholder

    async def _llm_assess_language_mixing(self, _text: str, _expected_lang: str, _judge_model: str) -> Dict[str, Any]:
        """LLM assessment of language mixing.

        Args:
            _text: Text to assess
            _expected_lang: Expected primary language
            _judge_model: Judge model for assessment

        Returns:
            Dictionary containing language mixing assessment
        """
        return {"appropriateness": 0.7}  # Placeholder
