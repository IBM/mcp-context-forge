"""Pytest configuration for automatic benchmark comparison."""

from statistics import mean


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Display benchmark comparison summary after all tests complete."""
    # Check if benchmark plugin is active
    if not hasattr(config, "_benchmarksession"):
        return

    benchmarksession = config._benchmarksession
    if not benchmarksession or not hasattr(benchmarksession, "benchmarks"):
        return

    benchmarks = benchmarksession.benchmarks
    if not benchmarks:
        return

    # Separate Python and Rust benchmarks
    python_benchmarks = [b for b in benchmarks if "python" in b.name.lower()]
    rust_benchmarks = [b for b in benchmarks if "rust" in b.name.lower()]

    if not python_benchmarks or not rust_benchmarks:
        return

    # Calculate aggregate statistics
    python_times = [b.stats.mean for b in python_benchmarks]
    rust_times = [b.stats.mean for b in rust_benchmarks]

    python_mean = mean(python_times)
    python_min = min(python_times)
    python_max = max(python_times)

    rust_mean = mean(rust_times)
    rust_min = min(rust_times)
    rust_max = max(rust_times)

    speedup = python_mean / rust_mean if rust_mean > 0 else 0

    # Display comparison
    tr = terminalreporter
    tr.write_sep("=", "PYTHON vs RUST PERFORMANCE COMPARISON", bold=True, yellow=True)
    tr.write_line("")

    tr.write_line("Python Implementation:", bold=True)
    tr.write_line(f"  Mean:  {python_mean*1e6:>10.2f} μs")
    tr.write_line(f"  Min:   {python_min*1e6:>10.2f} μs")
    tr.write_line(f"  Max:   {python_max*1e6:>10.2f} μs")
    tr.write_line(f"  Tests: {len(python_benchmarks):>10}")
    tr.write_line("")

    tr.write_line("Rust Implementation:", bold=True)
    tr.write_line(f"  Mean:  {rust_mean*1e6:>10.2f} μs")
    tr.write_line(f"  Min:   {rust_min*1e6:>10.2f} μs")
    tr.write_line(f"  Max:   {rust_max*1e6:>10.2f} μs")
    tr.write_line(f"  Tests: {len(rust_benchmarks):>10}")
    tr.write_line("")

    if speedup >= 1:
        tr.write_line(
            f"🚀 Rust is {speedup:.2f}x FASTER than Python", bold=True, green=True
        )
    else:
        tr.write_line(
            f"⚠️  Python is {1/speedup:.2f}x faster than Rust", bold=True, red=True
        )

    tr.write_line("")
    tr.write_sep("=", bold=True, yellow=True)
