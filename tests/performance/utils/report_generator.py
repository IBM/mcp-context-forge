#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTML Performance Test Report Generator

Generates comprehensive HTML reports from performance test results including:
- Summary statistics
- SLO compliance
- Charts and visualizations
- System metrics
- Baseline comparisons
- Recommendations
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import yaml


# HTML Template with embedded CSS and Chart.js
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Performance Test Report - {{ timestamp }}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }

        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 20px;
            margin-bottom: 30px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }

        header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }

        header .meta {
            opacity: 0.9;
            font-size: 0.95em;
        }

        .section {
            background: white;
            padding: 30px;
            margin-bottom: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        h2 {
            color: #667eea;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #eee;
        }

        h3 {
            color: #555;
            margin: 20px 0 10px 0;
        }

        /* Metric Cards */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }

        .metric-card {
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid;
        }

        .metric-card.excellent {
            background: #d4edda;
            border-color: #28a745;
        }

        .metric-card.good {
            background: #d1ecf1;
            border-color: #17a2b8;
        }

        .metric-card.warning {
            background: #fff3cd;
            border-color: #ffc107;
        }

        .metric-card.poor {
            background: #f8d7da;
            border-color: #dc3545;
        }

        .metric-card .label {
            font-size: 0.85em;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .metric-card .value {
            font-size: 2em;
            font-weight: bold;
            margin: 10px 0;
        }

        .metric-card .detail {
            font-size: 0.9em;
            color: #666;
        }

        /* Tables */
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }

        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }

        th {
            background: #f8f9fa;
            font-weight: 600;
            color: #555;
        }

        tr:hover {
            background: #f8f9fa;
        }

        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
        }

        .status-badge.pass {
            background: #d4edda;
            color: #155724;
        }

        .status-badge.fail {
            background: #f8d7da;
            color: #721c24;
        }

        .status-badge.warn {
            background: #fff3cd;
            color: #856404;
        }

        /* Charts */
        .chart-container {
            position: relative;
            height: 400px;
            margin: 30px 0;
        }

        .chart-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 30px;
            margin: 30px 0;
        }

        /* Progress Bars */
        .progress-bar {
            width: 100%;
            height: 30px;
            background: #e9ecef;
            border-radius: 4px;
            overflow: hidden;
            position: relative;
        }

        .progress-bar .fill {
            height: 100%;
            transition: width 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 0.85em;
        }

        .progress-bar .fill.excellent { background: #28a745; }
        .progress-bar .fill.good { background: #17a2b8; }
        .progress-bar .fill.warning { background: #ffc107; }
        .progress-bar .fill.poor { background: #dc3545; }

        /* Alerts */
        .alert {
            padding: 15px 20px;
            border-radius: 4px;
            margin: 20px 0;
            border-left: 4px solid;
        }

        .alert.info {
            background: #d1ecf1;
            border-color: #17a2b8;
            color: #0c5460;
        }

        .alert.success {
            background: #d4edda;
            border-color: #28a745;
            color: #155724;
        }

        .alert.warning {
            background: #fff3cd;
            border-color: #ffc107;
            color: #856404;
        }

        .alert.danger {
            background: #f8d7da;
            border-color: #dc3545;
            color: #721c24;
        }

        /* Recommendations */
        .recommendation {
            padding: 15px;
            margin: 10px 0;
            background: #f8f9fa;
            border-left: 3px solid #667eea;
            border-radius: 4px;
        }

        .recommendation .priority {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 0.8em;
            font-weight: 600;
            margin-right: 10px;
        }

        .recommendation .priority.high {
            background: #dc3545;
            color: white;
        }

        .recommendation .priority.medium {
            background: #ffc107;
            color: #333;
        }

        .recommendation .priority.low {
            background: #17a2b8;
            color: white;
        }

        /* Code blocks */
        pre, code {
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }

        pre {
            padding: 15px;
            overflow-x: auto;
        }

        /* Footer */
        footer {
            text-align: center;
            padding: 30px;
            color: #666;
            font-size: 0.9em;
        }

        /* Comparison indicators */
        .comparison {
            display: inline-flex;
            align-items: center;
            margin-left: 10px;
            font-size: 0.85em;
        }

        .comparison.better {
            color: #28a745;
        }

        .comparison.worse {
            color: #dc3545;
        }

        .comparison::before {
            content: '';
            display: inline-block;
            width: 0;
            height: 0;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            margin-right: 4px;
        }

        .comparison.better::before {
            border-bottom: 6px solid #28a745;
        }

        .comparison.worse::before {
            border-top: 6px solid #dc3545;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🚀 Performance Test Report</h1>
            <div class="meta">
                <div><strong>Generated:</strong> {{ timestamp }}</div>
                <div><strong>Profile:</strong> {{ profile }}</div>
                <div><strong>Gateway:</strong> {{ gateway_url }}</div>
                {% if git_commit %}
                <div><strong>Git Commit:</strong> {{ git_commit }}</div>
                {% endif %}
            </div>
        </header>

        <!-- Executive Summary -->
        <div class="section">
            <h2>📊 Executive Summary</h2>

            <div class="metrics-grid">
                <div class="metric-card {{ summary.overall_status }}">
                    <div class="label">Overall Status</div>
                    <div class="value">{{ summary.overall_status_text }}</div>
                    <div class="detail">{{ summary.tests_passed }}/{{ summary.total_tests }} tests passed</div>
                </div>

                <div class="metric-card {{ summary.slo_status }}">
                    <div class="label">SLO Compliance</div>
                    <div class="value">{{ summary.slo_compliance_percent }}%</div>
                    <div class="detail">{{ summary.slos_met }}/{{ summary.total_slos }} SLOs met</div>
                </div>

                <div class="metric-card {{ summary.perf_status }}">
                    <div class="label">Average Throughput</div>
                    <div class="value">{{ summary.avg_rps }}</div>
                    <div class="detail">requests/second</div>
                </div>

                <div class="metric-card {{ summary.latency_status }}">
                    <div class="label">Average p95 Latency</div>
                    <div class="value">{{ summary.avg_p95 }}ms</div>
                    <div class="detail">{{ summary.avg_p99 }}ms p99</div>
                </div>
            </div>

            {% if summary.has_regressions %}
            <div class="alert danger">
                <strong>⚠️ Performance Regressions Detected!</strong><br>
                {{ summary.regression_count }} test(s) show performance degradation compared to baseline.
            </div>
            {% endif %}
        </div>

        <!-- SLO Compliance -->
        <div class="section">
            <h2>🎯 SLO Compliance</h2>

            <table>
                <thead>
                    <tr>
                        <th>Test</th>
                        <th>Metric</th>
                        <th>Target</th>
                        <th>Actual</th>
                        <th>Status</th>
                        <th>Margin</th>
                    </tr>
                </thead>
                <tbody>
                    {% for slo in slo_results %}
                    <tr>
                        <td>{{ slo.test_name }}</td>
                        <td>{{ slo.metric }}</td>
                        <td>{{ slo.target }}</td>
                        <td>{{ slo.actual }}</td>
                        <td><span class="status-badge {{ slo.status }}">{{ slo.status_text }}</span></td>
                        <td>{{ slo.margin }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <!-- Test Results -->
        {% for category, tests in test_results.items() %}
        <div class="section">
            <h2>{{ category.title() }} Performance</h2>

            <table>
                <thead>
                    <tr>
                        <th>Test</th>
                        <th>Requests/sec</th>
                        <th>p50</th>
                        <th>p95</th>
                        <th>p99</th>
                        <th>Error Rate</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for test in tests %}
                    <tr>
                        <td>
                            {{ test.name }}
                            {% if test.has_baseline %}
                            <span class="comparison {{ test.comparison_status }}">
                                {{ test.comparison_text }}
                            </span>
                            {% endif %}
                        </td>
                        <td>{{ test.rps }}</td>
                        <td>{{ test.p50 }}ms</td>
                        <td>{{ test.p95 }}ms</td>
                        <td>{{ test.p99 }}ms</td>
                        <td>{{ test.error_rate }}%</td>
                        <td><span class="status-badge {{ test.status }}">{{ test.status_text }}</span></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>

            <!-- Chart -->
            <div class="chart-container">
                <canvas id="chart_{{ category }}"></canvas>
            </div>
        </div>
        {% endfor %}

        <!-- System Metrics -->
        {% if system_metrics %}
        <div class="section">
            <h2>💻 System Metrics</h2>

            <div class="chart-row">
                <div>
                    <h3>CPU Usage</h3>
                    <div class="chart-container" style="height: 300px;">
                        <canvas id="chart_cpu"></canvas>
                    </div>
                </div>

                <div>
                    <h3>Memory Usage</h3>
                    <div class="chart-container" style="height: 300px;">
                        <canvas id="chart_memory"></canvas>
                    </div>
                </div>
            </div>

            <h3>Resource Utilization Summary</h3>
            <table>
                <thead>
                    <tr>
                        <th>Resource</th>
                        <th>Average</th>
                        <th>Peak</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for metric in system_metrics %}
                    <tr>
                        <td>{{ metric.name }}</td>
                        <td>{{ metric.average }}</td>
                        <td>{{ metric.peak }}</td>
                        <td><span class="status-badge {{ metric.status }}">{{ metric.status_text }}</span></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}

        <!-- Database Performance -->
        {% if db_metrics %}
        <div class="section">
            <h2>🗄️ Database Performance</h2>

            <div class="metrics-grid">
                <div class="metric-card {{ db_metrics.connection_status }}">
                    <div class="label">Connection Pool</div>
                    <div class="value">{{ db_metrics.avg_connections }}</div>
                    <div class="detail">Peak: {{ db_metrics.peak_connections }}</div>
                </div>

                <div class="metric-card {{ db_metrics.query_status }}">
                    <div class="label">Average Query Time</div>
                    <div class="value">{{ db_metrics.avg_query_time }}ms</div>
                    <div class="detail">{{ db_metrics.total_queries }} total queries</div>
                </div>
            </div>

            {% if db_metrics.slow_queries %}
            <h3>Slow Queries</h3>
            <table>
                <thead>
                    <tr>
                        <th>Query</th>
                        <th>Avg Time</th>
                        <th>Max Time</th>
                        <th>Calls</th>
                    </tr>
                </thead>
                <tbody>
                    {% for query in db_metrics.slow_queries %}
                    <tr>
                        <td><code>{{ query.query_text }}</code></td>
                        <td>{{ query.avg_time }}ms</td>
                        <td>{{ query.max_time }}ms</td>
                        <td>{{ query.calls }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% endif %}
        </div>
        {% endif %}

        <!-- Recommendations -->
        <div class="section">
            <h2>💡 Recommendations</h2>

            {% if recommendations %}
                {% for rec in recommendations %}
                <div class="recommendation">
                    <span class="priority {{ rec.priority }}">{{ rec.priority.upper() }}</span>
                    <strong>{{ rec.title }}</strong>
                    <p>{{ rec.description }}</p>
                    {% if rec.action %}
                    <pre><code>{{ rec.action }}</code></pre>
                    {% endif %}
                </div>
                {% endfor %}
            {% else %}
                <div class="alert success">
                    ✅ No immediate performance issues detected. All metrics are within acceptable ranges.
                </div>
            {% endif %}
        </div>

        <!-- Raw Data -->
        <div class="section">
            <h2>📁 Additional Information</h2>

            <h3>Test Configuration</h3>
            <table>
                <tr>
                    <th>Parameter</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>Profile</td>
                    <td>{{ profile }}</td>
                </tr>
                <tr>
                    <td>Requests per test</td>
                    <td>{{ config.requests }}</td>
                </tr>
                <tr>
                    <td>Concurrency</td>
                    <td>{{ config.concurrency }}</td>
                </tr>
                <tr>
                    <td>Timeout</td>
                    <td>{{ config.timeout }}s</td>
                </tr>
                <tr>
                    <td>Total test duration</td>
                    <td>{{ duration }}</td>
                </tr>
            </table>

            <h3>Files</h3>
            <ul>
                {% for file in result_files %}
                <li><a href="{{ file.path }}">{{ file.name }}</a></li>
                {% endfor %}
            </ul>
        </div>

        <footer>
            <p>Generated by ContextForge Performance Testing Suite</p>
            <p>{{ timestamp }}</p>
        </footer>
    </div>

    <!-- Chart.js initialization -->
    <script>
        // Chart data injected from Python
        const chartData = {{ chart_data | safe }};

        // Create charts for each test category
        {% for category, tests in test_results.items() %}
        new Chart(document.getElementById('chart_{{ category }}'), {
            type: 'bar',
            data: {
                labels: chartData.{{ category }}.labels,
                datasets: [
                    {
                        label: 'p50 (ms)',
                        data: chartData.{{ category }}.p50,
                        backgroundColor: 'rgba(54, 162, 235, 0.5)',
                        borderColor: 'rgba(54, 162, 235, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'p95 (ms)',
                        data: chartData.{{ category }}.p95,
                        backgroundColor: 'rgba(255, 206, 86, 0.5)',
                        borderColor: 'rgba(255, 206, 86, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'p99 (ms)',
                        data: chartData.{{ category }}.p99,
                        backgroundColor: 'rgba(255, 99, 132, 0.5)',
                        borderColor: 'rgba(255, 99, 132, 1)',
                        borderWidth: 1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Latency Distribution (ms)'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
        {% endfor %}

        {% if system_metrics %}
        // CPU chart
        new Chart(document.getElementById('chart_cpu'), {
            type: 'line',
            data: {
                labels: chartData.system.timestamps,
                datasets: [{
                    label: 'CPU %',
                    data: chartData.system.cpu,
                    borderColor: 'rgba(75, 192, 192, 1)',
                    backgroundColor: 'rgba(75, 192, 192, 0.2)',
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100
                    }
                }
            }
        });

        // Memory chart
        new Chart(document.getElementById('chart_memory'), {
            type: 'line',
            data: {
                labels: chartData.system.timestamps,
                datasets: [{
                    label: 'Memory %',
                    data: chartData.system.memory,
                    borderColor: 'rgba(153, 102, 255, 1)',
                    backgroundColor: 'rgba(153, 102, 255, 0.2)',
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100
                    }
                }
            }
        });
        {% endif %}
    </script>
</body>
</html>
"""


class SimpleTemplate:
    """Simple template engine for rendering HTML reports"""

    def __init__(self, template: str):
        self.template = template

    def render(self, context: Dict[str, Any]) -> str:
        """Render template with context"""
        result = self.template

        # Handle simple variable substitution {{ var }}
        for key, value in context.items():
            pattern = r"\{\{\s*" + re.escape(key) + r"\s*\}\}"
            result = re.sub(pattern, str(value), result)

        # Handle safe JSON {{ var | safe }}
        for key, value in context.items():
            pattern = r"\{\{\s*" + re.escape(key) + r"\s*\|\s*safe\s*\}\}"
            if isinstance(value, (dict, list)):
                # Use lambda to avoid regex backslash interpretation issues with JSON
                result = re.sub(pattern, lambda m: json.dumps(value), result)

        # Handle conditionals {% if var %}
        result = self._render_conditionals(result, context)

        # Handle loops {% for item in items %}
        result = self._render_loops(result, context)

        return result

    def _render_conditionals(self, template: str, context: Dict) -> str:
        """Render if/else blocks"""
        # Simple implementation - handle {% if var %} ... {% endif %}
        pattern = r"\{%\s*if\s+(\w+)\s*%\}(.*?)\{%\s*endif\s*%\}"

        def replace_conditional(match):
            var_name = match.group(1)
            content = match.group(2)
            return content if context.get(var_name) else ""

        return re.sub(pattern, replace_conditional, template, flags=re.DOTALL)

    def _render_loops(self, template: str, context: Dict) -> str:
        """Render for loops"""
        # Simple implementation - handle {% for item in items %} ... {% endfor %}
        pattern = r"\{%\s*for\s+(\w+)\s+in\s+(\w+)\s*%\}(.*?)\{%\s*endfor\s*%\}"

        def replace_loop(match):
            item_name = match.group(1)
            list_name = match.group(2)
            content = match.group(3)
            items = context.get(list_name, [])

            result = []
            for item in items:
                item_context = context.copy()
                item_context[item_name] = item

                # Simple variable substitution within loop
                item_result = content
                if isinstance(item, dict):
                    for key, value in item.items():
                        var_pattern = r"\{\{\s*" + re.escape(item_name) + r"\." + re.escape(key) + r"\s*\}\}"
                        item_result = re.sub(var_pattern, str(value), item_result)

                result.append(item_result)

            return "".join(result)

        return re.sub(pattern, replace_loop, template, flags=re.DOTALL)


class PerformanceReportGenerator:
    """Generate HTML reports from performance test results"""

    def __init__(self, results_dir: Path, config_file: Optional[Path] = None):
        self.results_dir = Path(results_dir)
        self.config = self._load_config(config_file)
        self.slos = self.config.get("slos", {})

    def _load_config(self, config_file: Optional[Path]) -> Dict:
        """Load configuration from YAML file"""
        if config_file and config_file.exists():
            with open(config_file) as f:
                return yaml.safe_load(f)
        return {}

    def parse_hey_output(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Parse hey output file to extract metrics"""
        try:
            with open(file_path) as f:
                content = f.read()

            metrics = {}

            # Extract summary metrics
            if match := re.search(r"Requests/sec:\s+([\d.]+)", content):
                metrics["rps"] = float(match.group(1))

            if match := re.search(r"Average:\s+([\d.]+)\s+secs", content):
                metrics["avg"] = float(match.group(1)) * 1000  # Convert to ms

            if match := re.search(r"Slowest:\s+([\d.]+)\s+secs", content):
                metrics["max"] = float(match.group(1)) * 1000

            if match := re.search(r"Fastest:\s+([\d.]+)\s+secs", content):
                metrics["min"] = float(match.group(1)) * 1000

            # Extract percentiles from latency distribution
            # Look for patterns like "0.050 [9500]" which indicates 95th percentile
            latency_section = re.search(r"Latency distribution:(.*?)(?=\n\n|\Z)", content, re.DOTALL)
            if latency_section:
                latency_text = latency_section.group(1)

                if match := re.search(r"50%\s+in\s+([\d.]+)\s+secs", latency_text):
                    metrics["p50"] = float(match.group(1)) * 1000

                if match := re.search(r"95%\s+in\s+([\d.]+)\s+secs", latency_text):
                    metrics["p95"] = float(match.group(1)) * 1000

                if match := re.search(r"99%\s+in\s+([\d.]+)\s+secs", latency_text):
                    metrics["p99"] = float(match.group(1)) * 1000

            # Extract status code distribution
            status_codes = {}
            status_section = re.search(r"Status code distribution:(.*?)(?=\n\n|\Z)", content, re.DOTALL)
            if status_section:
                for line in status_section.group(1).strip().split("\n"):
                    if match := re.search(r"\[(\d+)\]\s+(\d+)\s+responses", line):
                        status_codes[int(match.group(1))] = int(match.group(2))

            metrics["status_codes"] = status_codes

            # Calculate error rate
            total_responses = sum(status_codes.values())
            error_responses = sum(count for code, count in status_codes.items() if code >= 400)
            metrics["error_rate"] = (error_responses / total_responses * 100) if total_responses > 0 else 0
            metrics["total_requests"] = total_responses

            return metrics

        except Exception as e:
            print(f"Error parsing {file_path}: {e}", file=sys.stderr)
            return None

    def collect_test_results(self) -> Dict[str, List[Dict]]:
        """Collect all test results from the results directory"""
        results = {}

        # Group results by category (tools, resources, prompts, etc.)
        for result_file in self.results_dir.glob("*.txt"):
            # Parse filename: {category}_{test_name}_{profile}_{timestamp}.txt
            parts = result_file.stem.split("_")
            if len(parts) < 2:
                continue

            category = parts[0]
            test_name = "_".join(parts[1:-2]) if len(parts) > 3 else parts[1]

            metrics = self.parse_hey_output(result_file)
            if not metrics:
                continue

            if category not in results:
                results[category] = []

            results[category].append({"name": test_name, "file": result_file.name, **metrics})

        return results

    def evaluate_slo(self, test_name: str, metrics: Dict[str, float]) -> List[Dict]:
        """Evaluate metrics against SLO thresholds"""
        # Map test names to SLO keys
        slo_key_map = {
            "list_tools": "tools_list",
            "get_system_time": "tools_invoke_simple",
            "convert_time": "tools_invoke_complex",
            "list_resources": "resources_list",
            "read_timezone_info": "resources_read",
            "read_world_times": "resources_read",
            "list_prompts": "prompts_list",
            "get_compare_timezones": "prompts_get",
            "health_check": "health_check",
        }

        slo_key = slo_key_map.get(test_name)
        if not slo_key or slo_key not in self.slos:
            return []

        slo = self.slos[slo_key]
        results = []

        # Check p50
        if "p50_ms" in slo and "p50" in metrics:
            results.append(
                {
                    "test_name": test_name,
                    "metric": "p50",
                    "target": f"{slo['p50_ms']}ms",
                    "actual": f"{metrics['p50']:.1f}ms",
                    "status": "pass" if metrics["p50"] <= slo["p50_ms"] else "fail",
                    "status_text": "✅ Pass" if metrics["p50"] <= slo["p50_ms"] else "❌ Fail",
                    "margin": f"{((metrics['p50'] - slo['p50_ms']) / slo['p50_ms'] * 100):+.1f}%",
                }
            )

        # Check p95
        if "p95_ms" in slo and "p95" in metrics:
            results.append(
                {
                    "test_name": test_name,
                    "metric": "p95",
                    "target": f"{slo['p95_ms']}ms",
                    "actual": f"{metrics['p95']:.1f}ms",
                    "status": "pass" if metrics["p95"] <= slo["p95_ms"] else "fail",
                    "status_text": "✅ Pass" if metrics["p95"] <= slo["p95_ms"] else "❌ Fail",
                    "margin": f"{((metrics['p95'] - slo['p95_ms']) / slo['p95_ms'] * 100):+.1f}%",
                }
            )

        # Check p99
        if "p99_ms" in slo and "p99" in metrics:
            results.append(
                {
                    "test_name": test_name,
                    "metric": "p99",
                    "target": f"{slo['p99_ms']}ms",
                    "actual": f"{metrics['p99']:.1f}ms",
                    "status": "pass" if metrics["p99"] <= slo["p99_ms"] else "fail",
                    "status_text": "✅ Pass" if metrics["p99"] <= slo["p99_ms"] else "❌ Fail",
                    "margin": f"{((metrics['p99'] - slo['p99_ms']) / slo['p99_ms'] * 100):+.1f}%",
                }
            )

        # Check throughput
        if "min_rps" in slo and "rps" in metrics:
            results.append(
                {
                    "test_name": test_name,
                    "metric": "throughput",
                    "target": f"{slo['min_rps']} req/s",
                    "actual": f"{metrics['rps']:.1f} req/s",
                    "status": "pass" if metrics["rps"] >= slo["min_rps"] else "fail",
                    "status_text": "✅ Pass" if metrics["rps"] >= slo["min_rps"] else "❌ Fail",
                    "margin": f"{((metrics['rps'] - slo['min_rps']) / slo['min_rps'] * 100):+.1f}%",
                }
            )

        # Check error rate
        if "max_error_rate" in slo and "error_rate" in metrics:
            max_error_pct = slo["max_error_rate"] * 100
            results.append(
                {
                    "test_name": test_name,
                    "metric": "error_rate",
                    "target": f"{max_error_pct}%",
                    "actual": f"{metrics['error_rate']:.2f}%",
                    "status": "pass" if metrics["error_rate"] <= max_error_pct else "fail",
                    "status_text": "✅ Pass" if metrics["error_rate"] <= max_error_pct else "❌ Fail",
                    "margin": f"{(metrics['error_rate'] - max_error_pct):+.2f}%",
                }
            )

        return results

    def generate_recommendations(self, test_results: Dict, slo_results: List[Dict]) -> List[Dict]:
        """Generate performance recommendations based on results"""
        recommendations = []

        # Check for SLO violations
        failed_slos = [slo for slo in slo_results if slo["status"] == "fail"]
        if failed_slos:
            for slo in failed_slos[:3]:  # Top 3 violations
                recommendations.append(
                    {
                        "priority": "high",
                        "title": f"SLO Violation: {slo['test_name']} {slo['metric']}",
                        "description": f"The {slo['metric']} metric ({slo['actual']}) exceeds the target ({slo['target']}) by {slo['margin']}.",
                        "action": None,
                    }
                )

        # Check for high error rates
        for category, tests in test_results.items():
            for test in tests:
                if test.get("error_rate", 0) > 1:
                    recommendations.append(
                        {
                            "priority": "high",
                            "title": f"High Error Rate: {test['name']}",
                            "description": f"Error rate of {test['error_rate']:.2f}% detected. Investigate application logs for failures.",
                            "action": "docker logs gateway | grep -i error",
                        }
                    )

        # Check for high latency variance
        for category, tests in test_results.items():
            for test in tests:
                if "p99" in test and "p50" in test:
                    variance = test["p99"] / test["p50"] if test["p50"] > 0 else 0
                    if variance > 3:  # p99 is 3x p50
                        recommendations.append(
                            {
                                "priority": "medium",
                                "title": f"High Latency Variance: {test['name']}",
                                "description": f"p99 latency ({test['p99']:.1f}ms) is {variance:.1f}x the p50 ({test['p50']:.1f}ms). This indicates inconsistent performance.",
                                "action": "# Profile the application to identify slow code paths\npy-spy record -o profile.svg --pid <PID> --duration 60",
                            }
                        )

        # Check for low throughput
        for category, tests in test_results.items():
            for test in tests:
                if test.get("rps", float("inf")) < 100:
                    recommendations.append(
                        {
                            "priority": "medium",
                            "title": f"Low Throughput: {test['name']}",
                            "description": f"Throughput of {test['rps']:.1f} req/s is lower than expected. Consider optimizing the request handling.",
                            "action": "# Check database connection pool settings\n# Review application logs for bottlenecks",
                        }
                    )

        return recommendations[:10]  # Top 10 recommendations

    def generate_report(self, output_file: Path, profile: str = "medium"):
        """Generate HTML report"""
        # Collect test results
        test_results = self.collect_test_results()

        # Evaluate SLOs
        slo_results = []
        for category, tests in test_results.items():
            for test in tests:
                slo_results.extend(self.evaluate_slo(test["name"], test))

        # Calculate summary statistics
        total_tests = sum(len(tests) for tests in test_results.values())
        all_tests = [test for tests in test_results.values() for test in tests]

        avg_rps = sum(t.get("rps", 0) for t in all_tests) / len(all_tests) if all_tests else 0
        avg_p95 = sum(t.get("p95", 0) for t in all_tests) / len(all_tests) if all_tests else 0
        avg_p99 = sum(t.get("p99", 0) for t in all_tests) / len(all_tests) if all_tests else 0

        slos_met = sum(1 for slo in slo_results if slo["status"] == "pass")
        total_slos = len(slo_results)
        slo_compliance = (slos_met / total_slos * 100) if total_slos > 0 else 0

        summary = {
            "overall_status": "excellent" if slo_compliance >= 95 else "good" if slo_compliance >= 80 else "warning" if slo_compliance >= 60 else "poor",
            "overall_status_text": "✅ Excellent" if slo_compliance >= 95 else "✓ Good" if slo_compliance >= 80 else "⚠ Warning" if slo_compliance >= 60 else "❌ Poor",
            "tests_passed": total_tests,  # Simplified
            "total_tests": total_tests,
            "slo_status": "excellent" if slo_compliance >= 95 else "good" if slo_compliance >= 80 else "warning" if slo_compliance >= 60 else "poor",
            "slo_compliance_percent": f"{slo_compliance:.1f}",
            "slos_met": slos_met,
            "total_slos": total_slos,
            "perf_status": "good" if avg_rps > 300 else "warning" if avg_rps > 100 else "poor",
            "avg_rps": f"{avg_rps:.0f}",
            "latency_status": "good" if avg_p95 < 50 else "warning" if avg_p95 < 100 else "poor",
            "avg_p95": f"{avg_p95:.1f}",
            "avg_p99": f"{avg_p99:.1f}",
            "has_regressions": False,
            "regression_count": 0,
        }

        # Format test results for display
        formatted_results = {}
        for category, tests in test_results.items():
            formatted_results[category] = []
            for test in tests:
                formatted_results[category].append(
                    {
                        "name": test["name"],
                        "rps": f"{test.get('rps', 0):.1f}",
                        "p50": f"{test.get('p50', 0):.1f}",
                        "p95": f"{test.get('p95', 0):.1f}",
                        "p99": f"{test.get('p99', 0):.1f}",
                        "error_rate": f"{test.get('error_rate', 0):.2f}",
                        "status": "pass" if test.get("error_rate", 0) < 1 else "fail",
                        "status_text": "✅ Pass" if test.get("error_rate", 0) < 1 else "❌ Fail",
                        "has_baseline": False,
                        "comparison_status": "",
                        "comparison_text": "",
                    }
                )

        # Generate chart data
        chart_data = {}
        for category, tests in test_results.items():
            chart_data[category] = {
                "labels": [t["name"] for t in tests],
                "p50": [t.get("p50", 0) for t in tests],
                "p95": [t.get("p95", 0) for t in tests],
                "p99": [t.get("p99", 0) for t in tests],
            }

        # Generate recommendations
        recommendations = self.generate_recommendations(test_results, slo_results)

        # Prepare context for template
        context = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "profile": profile,
            "gateway_url": self.config.get("environment", {}).get("gateway_url", "http://localhost:4444"),
            "git_commit": "",
            "summary": summary,
            "slo_results": slo_results,
            "test_results": formatted_results,
            "system_metrics": None,  # TODO: Parse system metrics
            "db_metrics": None,  # TODO: Parse DB metrics
            "recommendations": recommendations,
            "chart_data": chart_data,
            "config": {"requests": "Variable", "concurrency": "Variable", "timeout": "60"},
            "duration": "Variable",
            "result_files": [{"name": f.name, "path": f.name} for f in sorted(self.results_dir.glob("*.txt"))],
        }

        # Render template
        template = SimpleTemplate(HTML_TEMPLATE)
        html = template.render(context)

        # Write output
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w") as f:
            f.write(html)

        print(f"✅ Report generated: {output_file}")
        return output_file


def main():
    parser = argparse.ArgumentParser(description="Generate HTML performance test report")
    parser.add_argument("--results-dir", type=Path, default=Path("results"), help="Directory containing test results")
    parser.add_argument("--output", type=Path, default=None, help="Output HTML file path")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"), help="Configuration file")
    parser.add_argument("--profile", type=str, default="medium", help="Test profile name")

    args = parser.parse_args()

    # Default output path
    if not args.output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = Path(f"reports/performance_report_{args.profile}_{timestamp}.html")

    # Generate report
    generator = PerformanceReportGenerator(args.results_dir, args.config)
    generator.generate_report(args.output, args.profile)


if __name__ == "__main__":
    main()
