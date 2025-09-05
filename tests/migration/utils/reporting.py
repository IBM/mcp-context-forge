# -*- coding: utf-8 -*-
"""Migration test reporting and HTML dashboard utilities.

This module provides comprehensive reporting capabilities for migration tests
including HTML dashboards, JSON reports, and performance visualizations.
"""

# Standard
from dataclasses import asdict
from datetime import datetime
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MigrationReportGenerator:
    """Generates comprehensive migration test reports and dashboards.

    Provides capabilities for:
    - HTML dashboard generation
    - JSON report export
    - Performance visualization
    - Test result aggregation
    - Historical comparison
    """

    def __init__(self, output_dir: str = "tests/migration/reports"):
        """Initialize report generator.

        Args:
            output_dir: Directory to save reports
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"📊 Initialized MigrationReportGenerator: {self.output_dir}")

    def generate_html_dashboard(self, test_results: List[Dict],
                               metadata: Dict[str, Any] = None) -> Path:
        """Generate comprehensive HTML dashboard for migration test results.

        Args:
            test_results: List of migration test results
            metadata: Additional metadata for the report

        Returns:
            Path to generated HTML report
        """
        logger.info(f"📊 Generating HTML dashboard with {len(test_results)} test results")

        # Prepare report data
        report_data = self._prepare_dashboard_data(test_results, metadata)

        # Generate HTML content
        html_content = self._generate_dashboard_html(report_data)

        # Save HTML report
        html_file = self.output_dir / "migration_dashboard.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"✅ HTML dashboard generated: {html_file}")
        return html_file

    def _prepare_dashboard_data(self, test_results: List[Dict],
                               metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Prepare data for dashboard generation."""

        # Calculate summary statistics
        total_tests = len(test_results)
        successful_tests = sum(1 for result in test_results if result.get('success', False))
        failed_tests = total_tests - successful_tests

        # Performance statistics
        execution_times = [r.get('execution_time', 0) for r in test_results if r.get('execution_time')]
        avg_execution_time = sum(execution_times) / len(execution_times) if execution_times else 0
        max_execution_time = max(execution_times) if execution_times else 0
        min_execution_time = min(execution_times) if execution_times else 0

        # Version analysis
        version_pairs = {}
        for result in test_results:
            version_key = f"{result.get('version_from', 'unknown')} → {result.get('version_to', 'unknown')}"
            if version_key not in version_pairs:
                version_pairs[version_key] = {'total': 0, 'successful': 0, 'avg_time': 0}

            version_pairs[version_key]['total'] += 1
            if result.get('success', False):
                version_pairs[version_key]['successful'] += 1

        # Calculate success rates for each version pair
        for pair_data in version_pairs.values():
            pair_data['success_rate'] = (pair_data['successful'] / pair_data['total']) * 100

        return {
            'metadata': metadata or {},
            'summary': {
                'total_tests': total_tests,
                'successful_tests': successful_tests,
                'failed_tests': failed_tests,
                'success_rate': (successful_tests / total_tests * 100) if total_tests > 0 else 0,
                'avg_execution_time': avg_execution_time,
                'max_execution_time': max_execution_time,
                'min_execution_time': min_execution_time
            },
            'version_analysis': version_pairs,
            'test_results': test_results,
            'generation_time': datetime.now().isoformat(),
            'total_execution_time': sum(execution_times)
        }

    def _generate_dashboard_html(self, report_data: Dict[str, Any]) -> str:
        """Generate HTML dashboard content."""

        html_template = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Gateway Migration Test Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: #f8fafc;
            color: #334155;
            line-height: 1.6;
        }

        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 2rem 0;
            text-align: center;
        }

        .header h1 {
            font-size: 2.5rem;
            margin-bottom: 0.5rem;
        }

        .header p {
            font-size: 1.1rem;
            opacity: 0.9;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        .stat-card {
            background: white;
            padding: 1.5rem;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
            text-align: center;
        }

        .stat-number {
            font-size: 2.5rem;
            font-weight: bold;
            margin-bottom: 0.5rem;
        }

        .stat-number.success { color: #10b981; }
        .stat-number.error { color: #ef4444; }
        .stat-number.info { color: #3b82f6; }
        .stat-number.warning { color: #f59e0b; }

        .stat-label {
            font-size: 0.9rem;
            color: #64748b;
            text-transform: uppercase;
            font-weight: 500;
            letter-spacing: 0.05em;
        }

        .section {
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
        }

        .section h2 {
            font-size: 1.5rem;
            margin-bottom: 1rem;
            color: #1e293b;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 0.5rem;
        }

        .version-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 1rem;
        }

        .version-card {
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 1rem;
        }

        .version-title {
            font-weight: 600;
            margin-bottom: 0.5rem;
            font-family: 'Courier New', monospace;
            background: #f1f5f9;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            display: inline-block;
        }

        .success-bar {
            width: 100%;
            height: 8px;
            background-color: #fee2e2;
            border-radius: 4px;
            margin: 0.5rem 0;
            overflow: hidden;
        }

        .success-fill {
            height: 100%;
            background-color: #10b981;
            transition: width 0.3s ease;
        }

        .test-results-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }

        .test-results-table th,
        .test-results-table td {
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }

        .test-results-table th {
            background-color: #f8fafc;
            font-weight: 600;
            color: #475569;
        }

        .status-badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.875rem;
            font-weight: 500;
        }

        .status-success {
            background-color: #dcfce7;
            color: #166534;
        }

        .status-error {
            background-color: #fee2e2;
            color: #991b1b;
        }

        .performance-chart {
            margin: 1rem 0;
            padding: 1rem;
            background: #f8fafc;
            border-radius: 8px;
        }

        .chart-bar {
            display: flex;
            align-items: center;
            margin: 0.5rem 0;
        }

        .chart-label {
            min-width: 120px;
            font-size: 0.875rem;
            color: #64748b;
        }

        .chart-value {
            flex: 1;
            height: 20px;
            background: linear-gradient(90deg, #3b82f6, #1d4ed8);
            border-radius: 4px;
            margin: 0 1rem;
            position: relative;
        }

        .chart-number {
            font-size: 0.875rem;
            font-weight: 500;
            min-width: 60px;
        }

        .footer {
            text-align: center;
            padding: 2rem;
            color: #64748b;
            border-top: 1px solid #e2e8f0;
        }

        .expandable {
            cursor: pointer;
        }

        .expandable-content {
            display: none;
            margin-top: 1rem;
            padding: 1rem;
            background: #f8fafc;
            border-radius: 8px;
        }

        .expandable.expanded .expandable-content {
            display: block;
        }

        .error-details {
            background: #fef2f2;
            border: 1px solid #fecaca;
            padding: 1rem;
            border-radius: 8px;
            margin-top: 0.5rem;
            font-family: 'Courier New', monospace;
            font-size: 0.875rem;
            color: #991b1b;
            white-space: pre-wrap;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔄 MCP Gateway Migration Test Dashboard</h1>
        <p>Comprehensive Database Migration Testing Results</p>
        <p style="font-size: 0.9rem; opacity: 0.8;">Generated: {generation_time}</p>
    </div>

    <div class="container">
        <!-- Summary Statistics -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-number info">{total_tests}</div>
                <div class="stat-label">Total Tests</div>
            </div>
            <div class="stat-card">
                <div class="stat-number success">{successful_tests}</div>
                <div class="stat-label">Successful</div>
            </div>
            <div class="stat-card">
                <div class="stat-number error">{failed_tests}</div>
                <div class="stat-label">Failed</div>
            </div>
            <div class="stat-card">
                <div class="stat-number warning">{success_rate:.1f}%</div>
                <div class="stat-label">Success Rate</div>
            </div>
        </div>

        <!-- Performance Summary -->
        <div class="section">
            <h2>📊 Performance Summary</h2>
            <div class="performance-chart">
                <div class="chart-bar">
                    <div class="chart-label">Avg Execution:</div>
                    <div class="chart-value" style="width: {avg_time_width}%"></div>
                    <div class="chart-number">{avg_execution_time:.2f}s</div>
                </div>
                <div class="chart-bar">
                    <div class="chart-label">Max Execution:</div>
                    <div class="chart-value" style="width: {max_time_width}%"></div>
                    <div class="chart-number">{max_execution_time:.2f}s</div>
                </div>
                <div class="chart-bar">
                    <div class="chart-label">Min Execution:</div>
                    <div class="chart-value" style="width: {min_time_width}%"></div>
                    <div class="chart-number">{min_execution_time:.2f}s</div>
                </div>
                <div class="chart-bar">
                    <div class="chart-label">Total Runtime:</div>
                    <div class="chart-value" style="width: 100%"></div>
                    <div class="chart-number">{total_execution_time:.1f}s</div>
                </div>
            </div>
        </div>

        <!-- Version Analysis -->
        <div class="section">
            <h2>🔄 Version Migration Analysis</h2>
            <div class="version-grid">
                {version_cards}
            </div>
        </div>

        <!-- Detailed Test Results -->
        <div class="section">
            <h2>📋 Detailed Test Results</h2>
            <table class="test-results-table">
                <thead>
                    <tr>
                        <th>Migration Path</th>
                        <th>Status</th>
                        <th>Duration</th>
                        <th>Direction</th>
                        <th>Records</th>
                        <th>Details</th>
                    </tr>
                </thead>
                <tbody>
                    {test_result_rows}
                </tbody>
            </table>
        </div>
    </div>

    <div class="footer">
        <p>MCP Gateway Migration Test Suite | Generated with comprehensive validation and performance monitoring</p>
    </div>

    <script>
        // Add interactivity for expandable sections
        document.querySelectorAll('.expandable').forEach(element => {
            element.addEventListener('click', () => {
                element.classList.toggle('expanded');
            });
        });

        // Performance chart animations
        document.addEventListener('DOMContentLoaded', () => {
            const chartValues = document.querySelectorAll('.chart-value');
            chartValues.forEach((bar, index) => {
                setTimeout(() => {
                    bar.style.opacity = '1';
                    bar.style.transform = 'scaleX(1)';
                }, index * 200);
            });
        });
    </script>
</body>
</html>
'''

        # Prepare template variables
        summary = report_data['summary']

        # Calculate chart widths (relative to max time)
        max_time = summary['max_execution_time'] if summary['max_execution_time'] > 0 else 1
        avg_time_width = (summary['avg_execution_time'] / max_time) * 100
        max_time_width = 100
        min_time_width = (summary['min_execution_time'] / max_time) * 100 if summary['min_execution_time'] > 0 else 5

        # Generate version cards
        version_cards = []
        for version_pair, stats in report_data['version_analysis'].items():
            success_rate = stats['success_rate']
            version_card = f'''
            <div class="version-card">
                <div class="version-title">{version_pair}</div>
                <div>Tests: {stats['total']} | Success: {stats['successful']}</div>
                <div class="success-bar">
                    <div class="success-fill" style="width: {success_rate}%"></div>
                </div>
                <div style="font-size: 0.875rem; color: #64748b;">
                    Success Rate: {success_rate:.1f}%
                </div>
            </div>
            '''
            version_cards.append(version_card)

        # Generate test result rows
        test_result_rows = []
        for result in report_data['test_results']:
            status_class = 'status-success' if result.get('success', False) else 'status-error'
            status_text = '✅ Success' if result.get('success', False) else '❌ Failed'

            migration_path = f"{result.get('version_from', 'unknown')} → {result.get('version_to', 'unknown')}"
            duration = f"{result.get('execution_time', 0):.2f}s"
            direction = result.get('migration_direction', 'unknown').title()

            # Calculate total records
            records_after = result.get('records_after', {})
            total_records = sum(records_after.values()) if isinstance(records_after, dict) else 0

            error_details = ""
            if not result.get('success', False) and result.get('error_message'):
                error_details = f'''
                <div class="expandable">
                    <div style="color: #ef4444; cursor: pointer;">View Error ⤵</div>
                    <div class="expandable-content">
                        <div class="error-details">{result['error_message'][:500]}{'...' if len(result.get('error_message', '')) > 500 else ''}</div>
                    </div>
                </div>
                '''

            row = f'''
            <tr>
                <td><code>{migration_path}</code></td>
                <td><span class="status-badge {status_class}">{status_text}</span></td>
                <td>{duration}</td>
                <td>{direction}</td>
                <td>{total_records:,}</td>
                <td>{error_details if error_details else '—'}</td>
            </tr>
            '''
            test_result_rows.append(row)

        # Format the HTML template
        formatted_html = html_template.format(
            generation_time=report_data['generation_time'],
            total_tests=summary['total_tests'],
            successful_tests=summary['successful_tests'],
            failed_tests=summary['failed_tests'],
            success_rate=summary['success_rate'],
            avg_execution_time=summary['avg_execution_time'],
            max_execution_time=summary['max_execution_time'],
            min_execution_time=summary['min_execution_time'],
            total_execution_time=report_data['total_execution_time'],
            avg_time_width=avg_time_width,
            max_time_width=max_time_width,
            min_time_width=min_time_width,
            version_cards=''.join(version_cards),
            test_result_rows=''.join(test_result_rows)
        )

        return formatted_html

    def generate_json_report(self, test_results: List[Dict],
                           metadata: Dict[str, Any] = None) -> Path:
        """Generate JSON report for programmatic consumption.

        Args:
            test_results: List of migration test results
            metadata: Additional metadata

        Returns:
            Path to generated JSON report
        """
        logger.info(f"📋 Generating JSON report with {len(test_results)} test results")

        report_data = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'generator': 'MigrationReportGenerator',
                'version': '1.0.0',
                **(metadata or {})
            },
            'summary': self._calculate_summary_stats(test_results),
            'test_results': test_results,
            'version_analysis': self._analyze_version_performance(test_results),
            'performance_metrics': self._calculate_performance_metrics(test_results)
        }

        json_file = self.output_dir / "migration_test_results.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, default=str)

        logger.info(f"✅ JSON report generated: {json_file}")
        return json_file

    def _calculate_summary_stats(self, test_results: List[Dict]) -> Dict[str, Any]:
        """Calculate summary statistics from test results."""
        total_tests = len(test_results)
        successful_tests = sum(1 for result in test_results if result.get('success', False))

        execution_times = [r.get('execution_time', 0) for r in test_results if r.get('execution_time')]

        return {
            'total_tests': total_tests,
            'successful_tests': successful_tests,
            'failed_tests': total_tests - successful_tests,
            'success_rate': (successful_tests / total_tests * 100) if total_tests > 0 else 0,
            'execution_time_stats': {
                'avg': sum(execution_times) / len(execution_times) if execution_times else 0,
                'min': min(execution_times) if execution_times else 0,
                'max': max(execution_times) if execution_times else 0,
                'total': sum(execution_times)
            }
        }

    def _analyze_version_performance(self, test_results: List[Dict]) -> Dict[str, Any]:
        """Analyze performance by version pairs."""
        version_stats = {}

        for result in test_results:
            version_key = f"{result.get('version_from', 'unknown')}_to_{result.get('version_to', 'unknown')}"

            if version_key not in version_stats:
                version_stats[version_key] = {
                    'test_count': 0,
                    'success_count': 0,
                    'execution_times': [],
                    'directions': []
                }

            stats = version_stats[version_key]
            stats['test_count'] += 1

            if result.get('success', False):
                stats['success_count'] += 1

            if result.get('execution_time'):
                stats['execution_times'].append(result['execution_time'])

            if result.get('migration_direction'):
                stats['directions'].append(result['migration_direction'])

        # Calculate derived metrics
        for version_key, stats in version_stats.items():
            stats['success_rate'] = (stats['success_count'] / stats['test_count'] * 100) if stats['test_count'] > 0 else 0

            if stats['execution_times']:
                stats['avg_execution_time'] = sum(stats['execution_times']) / len(stats['execution_times'])
                stats['min_execution_time'] = min(stats['execution_times'])
                stats['max_execution_time'] = max(stats['execution_times'])
            else:
                stats['avg_execution_time'] = 0
                stats['min_execution_time'] = 0
                stats['max_execution_time'] = 0

        return version_stats

    def _calculate_performance_metrics(self, test_results: List[Dict]) -> Dict[str, Any]:
        """Calculate performance metrics from test results."""

        # Extract performance data
        execution_times = []
        memory_usage = []
        processing_rates = []

        for result in test_results:
            if result.get('execution_time'):
                execution_times.append(result['execution_time'])

            if result.get('performance_metrics', {}).get('memory_mb'):
                memory_usage.append(result['performance_metrics']['memory_mb'])

            # Calculate processing rate if data available
            records_after = result.get('records_after', {})
            exec_time = result.get('execution_time', 0)
            if isinstance(records_after, dict) and exec_time > 0:
                total_records = sum(records_after.values())
                if total_records > 0:
                    processing_rates.append(total_records / exec_time)

        metrics = {}

        if execution_times:
            metrics['execution_time'] = {
                'avg': sum(execution_times) / len(execution_times),
                'min': min(execution_times),
                'max': max(execution_times),
                'median': sorted(execution_times)[len(execution_times) // 2]
            }

        if memory_usage:
            metrics['memory_usage'] = {
                'avg_mb': sum(memory_usage) / len(memory_usage),
                'min_mb': min(memory_usage),
                'max_mb': max(memory_usage)
            }

        if processing_rates:
            metrics['processing_rate'] = {
                'avg_records_per_sec': sum(processing_rates) / len(processing_rates),
                'min_records_per_sec': min(processing_rates),
                'max_records_per_sec': max(processing_rates)
            }

        return metrics

    def generate_performance_comparison(self, current_results: List[Dict],
                                      historical_results: List[Dict] = None) -> Path:
        """Generate performance comparison report.

        Args:
            current_results: Current test results
            historical_results: Historical test results for comparison

        Returns:
            Path to generated comparison report
        """
        logger.info(f"📈 Generating performance comparison report")

        current_metrics = self._calculate_performance_metrics(current_results)
        historical_metrics = self._calculate_performance_metrics(historical_results) if historical_results else None

        comparison_data = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'current_test_count': len(current_results),
                'historical_test_count': len(historical_results) if historical_results else 0
            },
            'current_metrics': current_metrics,
            'historical_metrics': historical_metrics,
            'performance_changes': self._calculate_performance_changes(current_metrics, historical_metrics),
            'recommendations': self._generate_performance_recommendations(current_metrics, historical_metrics)
        }

        comparison_file = self.output_dir / "performance_comparison.json"
        with open(comparison_file, 'w', encoding='utf-8') as f:
            json.dump(comparison_data, f, indent=2, default=str)

        logger.info(f"✅ Performance comparison report generated: {comparison_file}")
        return comparison_file

    def _calculate_performance_changes(self, current: Dict[str, Any],
                                     historical: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate performance changes between current and historical results."""
        if not historical:
            return {"note": "No historical data available for comparison"}

        changes = {}

        # Compare execution times
        if 'execution_time' in current and 'execution_time' in historical:
            current_avg = current['execution_time']['avg']
            historical_avg = historical['execution_time']['avg']

            if historical_avg > 0:
                change_percent = ((current_avg - historical_avg) / historical_avg) * 100
                changes['execution_time_change'] = {
                    'current_avg': current_avg,
                    'historical_avg': historical_avg,
                    'change_percent': change_percent,
                    'improvement': change_percent < 0
                }

        # Compare memory usage
        if 'memory_usage' in current and 'memory_usage' in historical:
            current_avg = current['memory_usage']['avg_mb']
            historical_avg = historical['memory_usage']['avg_mb']

            if historical_avg > 0:
                change_percent = ((current_avg - historical_avg) / historical_avg) * 100
                changes['memory_usage_change'] = {
                    'current_avg_mb': current_avg,
                    'historical_avg_mb': historical_avg,
                    'change_percent': change_percent,
                    'improvement': change_percent < 0
                }

        # Compare processing rates
        if 'processing_rate' in current and 'processing_rate' in historical:
            current_avg = current['processing_rate']['avg_records_per_sec']
            historical_avg = historical['processing_rate']['avg_records_per_sec']

            if historical_avg > 0:
                change_percent = ((current_avg - historical_avg) / historical_avg) * 100
                changes['processing_rate_change'] = {
                    'current_avg_rps': current_avg,
                    'historical_avg_rps': historical_avg,
                    'change_percent': change_percent,
                    'improvement': change_percent > 0  # Higher rate is better
                }

        return changes

    def _generate_performance_recommendations(self, current: Dict[str, Any],
                                           historical: Dict[str, Any]) -> List[str]:
        """Generate performance recommendations based on results."""
        recommendations = []

        # Execution time recommendations
        if 'execution_time' in current:
            avg_time = current['execution_time']['avg']
            max_time = current['execution_time']['max']

            if avg_time > 60:
                recommendations.append("Average execution time is over 1 minute. Consider optimizing migration scripts.")

            if max_time > 300:
                recommendations.append("Maximum execution time exceeds 5 minutes. Investigate slow migrations.")

            if current['execution_time']['max'] > current['execution_time']['avg'] * 3:
                recommendations.append("High variance in execution times detected. Check for performance outliers.")

        # Memory usage recommendations
        if 'memory_usage' in current:
            avg_memory = current['memory_usage']['avg_mb']
            max_memory = current['memory_usage']['max_mb']

            if avg_memory > 512:
                recommendations.append("Average memory usage is high (>512MB). Consider memory optimization.")

            if max_memory > 1024:
                recommendations.append("Peak memory usage exceeds 1GB. Monitor for memory leaks.")

        # Processing rate recommendations
        if 'processing_rate' in current:
            avg_rate = current['processing_rate']['avg_records_per_sec']

            if avg_rate < 10:
                recommendations.append("Low processing rate detected (<10 records/sec). Review migration efficiency.")

        # Historical comparison recommendations
        if historical:
            changes = self._calculate_performance_changes(current, historical)

            if 'execution_time_change' in changes:
                change = changes['execution_time_change']
                if not change['improvement'] and abs(change['change_percent']) > 20:
                    recommendations.append(f"Execution time regression of {change['change_percent']:.1f}% detected.")

            if 'memory_usage_change' in changes:
                change = changes['memory_usage_change']
                if not change['improvement'] and abs(change['change_percent']) > 30:
                    recommendations.append(f"Memory usage increased by {change['change_percent']:.1f}%.")

        if not recommendations:
            recommendations.append("Performance metrics look good. No specific recommendations at this time.")

        return recommendations

    def save_test_results(self, test_results: List[Dict], filename: str = None) -> Path:
        """Save test results to JSON file for future analysis.

        Args:
            test_results: List of test results to save
            filename: Optional filename (defaults to timestamped file)

        Returns:
            Path to saved results file
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"migration_results_{timestamp}.json"

        results_file = self.output_dir / filename

        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'test_count': len(test_results),
                'results': test_results
            }, f, indent=2, default=str)

        logger.info(f"💾 Test results saved: {results_file}")
        return results_file


def main():
    """Command-line interface for report generation."""
    # Standard
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Generate migration test reports")
    parser.add_argument("--results", required=True, help="Path to test results JSON file")
    parser.add_argument("--output", default="tests/migration/reports", help="Output directory")
    parser.add_argument("--format", choices=["html", "json", "both"], default="both", help="Report format")
    parser.add_argument("--historical", help="Path to historical results for comparison")

    args = parser.parse_args()

    # Load test results
    try:
        with open(args.results, 'r') as f:
            data = json.load(f)
            test_results = data.get('results', data)  # Handle different formats
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading test results: {e}")
        sys.exit(1)

    # Initialize report generator
    reporter = MigrationReportGenerator(args.output)

    # Generate reports
    if args.format in ["html", "both"]:
        html_report = reporter.generate_html_dashboard(test_results)
        print(f"HTML report generated: {html_report}")

    if args.format in ["json", "both"]:
        json_report = reporter.generate_json_report(test_results)
        print(f"JSON report generated: {json_report}")

    # Generate comparison if historical data provided
    if args.historical:
        try:
            with open(args.historical, 'r') as f:
                historical_data = json.load(f)
                historical_results = historical_data.get('results', historical_data)

            comparison_report = reporter.generate_performance_comparison(test_results, historical_results)
            print(f"Performance comparison generated: {comparison_report}")

        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load historical data: {e}")


if __name__ == "__main__":
    main()
