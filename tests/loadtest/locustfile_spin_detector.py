# -*- coding: utf-8 -*-
"""Locust load test for detecting CPU spin loop bug (Issue #2360).

This test uses a spike/drop pattern to stress-test session cleanup:
1. Ramp up to high user count (creates many connections/tasks)
2. Drop to 0 users (triggers cleanup of all sessions)
3. Pause to observe CPU behavior (should return to idle)
4. Repeat multiple cycles

The CPU spin loop bug causes workers to consume 100% CPU each when idle
after clients disconnect, due to orphaned asyncio tasks in anyio's
_deliver_cancellation loop.

See: https://github.com/IBM/mcp-context-forge/issues/2360

Usage:
    make load-test-spin-detector

    # Or directly:
    cd tests/loadtest && locust -f locustfile_spin_detector.py \
        --host=http://localhost:4444 --headless

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import logging
import subprocess
import sys
from datetime import datetime
from typing import Optional

from locust import LoadTestShape, between, events, task
from locust.contrib.fasthttp import FastHttpUser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# Minimal User Class (standalone - no imports from main locustfile)
# =============================================================================
class SpinTestUser(FastHttpUser):
    """Minimal user for spin loop testing - hits simple endpoints."""

    wait_time = between(0.05, 0.2)  # Fast requests for high throughput
    weight = 1

    @task(3)
    def health_check(self):
        """Simple health check - no auth required."""
        self.client.get("/health", name="/health")

    @task(1)
    def root_check(self):
        """Root endpoint check."""
        self.client.get("/", name="/")


# =============================================================================
# ANSI Color Codes
# =============================================================================
class Colors:
    """ANSI color codes for terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    # Background colors
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"

    @classmethod
    def disable(cls) -> None:
        """Disable colors (for non-TTY output)."""
        for attr in dir(cls):
            if not attr.startswith("_") and isinstance(getattr(cls, attr), str):
                setattr(cls, attr, "")


# Disable colors if not a TTY
if not sys.stdout.isatty():
    Colors.disable()


# =============================================================================
# Logging Setup
# =============================================================================
LOG_FILE = f"/tmp/spin_detector_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
_log_file_handle = None


def _init_log_file() -> None:
    """Initialize the log file."""
    global _log_file_handle
    try:
        _log_file_handle = open(LOG_FILE, "w", encoding="utf-8")
        _log_file_handle.write("# CPU Spin Loop Detector Log\n")
        _log_file_handle.write(f"# Started: {datetime.now().isoformat()}\n")
        _log_file_handle.write("# Issue: https://github.com/IBM/mcp-context-forge/issues/2360\n")
        _log_file_handle.write("#" + "=" * 79 + "\n\n")
        _log_file_handle.flush()
    except Exception as e:
        print(f"{Colors.YELLOW}Warning: Could not create log file: {e}{Colors.RESET}")


def _close_log_file() -> None:
    """Close the log file."""
    global _log_file_handle
    if _log_file_handle:
        _log_file_handle.write(f"\n# Finished: {datetime.now().isoformat()}\n")
        _log_file_handle.close()
        _log_file_handle = None


def log(message: str, to_console: bool = True) -> None:
    """Log a message to both console and file.

    Args:
        message: Message to log (may contain ANSI codes for console).
        to_console: Whether to print to console.
    """
    timestamp = datetime.now().strftime("%H:%M:%S")

    if to_console:
        print(message)
        sys.stdout.flush()

    if _log_file_handle:
        # Strip ANSI codes for file
        clean_msg = message
        for attr in dir(Colors):
            if not attr.startswith("_") and isinstance(getattr(Colors, attr), str):
                clean_msg = clean_msg.replace(getattr(Colors, attr), "")
        _log_file_handle.write(f"[{timestamp}] {clean_msg}\n")
        _log_file_handle.flush()


# =============================================================================
# Docker Stats
# =============================================================================
def get_docker_stats() -> tuple[str, list[tuple[str, float]]]:
    """Get docker stats for gateway containers.

    Returns:
        Tuple of (formatted output string, list of (container_name, cpu_percent)).
    """
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format",
             "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            gateway_lines = []
            cpu_values = []

            for line in lines:
                if "gateway" in line.lower():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        name = parts[0]
                        cpu_str = parts[1].replace("%", "")
                        try:
                            cpu = float(cpu_str)
                            cpu_values.append((name, cpu))
                        except ValueError:
                            cpu = 0.0
                        gateway_lines.append(line)

            if gateway_lines:
                header = f"{'CONTAINER':<40} {'CPU %':>10} {'MEMORY':>20}"
                formatted = header + "\n" + "-" * 72 + "\n"
                for line in gateway_lines:
                    parts = line.split("\t")
                    if len(parts) >= 3:
                        formatted += f"{parts[0]:<40} {parts[1]:>10} {parts[2]:>20}\n"
                return formatted, cpu_values
            return "(no gateway containers found)", []
        return f"(docker stats failed: {result.stderr})", []
    except subprocess.TimeoutExpired:
        return "(docker stats timed out)", []
    except FileNotFoundError:
        return "(docker not found)", []
    except Exception as e:
        return f"(error: {e})", []


def format_cpu_status(cpu_values: list[tuple[str, float]]) -> str:
    """Format CPU status with color-coded health indicator.

    Args:
        cpu_values: List of (container_name, cpu_percent) tuples.

    Returns:
        Formatted status string with colors.
    """
    if not cpu_values:
        return f"{Colors.YELLOW}[?] No CPU data{Colors.RESET}"

    max_cpu = max(cpu for _, cpu in cpu_values)
    total_cpu = sum(cpu for _, cpu in cpu_values)

    if max_cpu < 10:
        icon = f"{Colors.GREEN}{Colors.BOLD}[PASS]{Colors.RESET}"
        status = f"{Colors.GREEN}CPU idle - cleanup working correctly{Colors.RESET}"
    elif max_cpu < 50:
        icon = f"{Colors.YELLOW}{Colors.BOLD}[WARN]{Colors.RESET}"
        status = f"{Colors.YELLOW}CPU moderate - may be processing{Colors.RESET}"
    else:
        icon = f"{Colors.RED}{Colors.BOLD}[FAIL]{Colors.RESET}"
        status = f"{Colors.RED}CPU HIGH - possible spin loop!{Colors.RESET}"

    return f"{icon} Total: {total_cpu:.1f}% | Max: {max_cpu:.1f}% - {status}"


# =============================================================================
# Pretty Printing
# =============================================================================
def print_box(title: str, content: str, color: str = Colors.CYAN, width: int = 80) -> None:
    """Print a colored box with title and content.

    Args:
        title: Box title.
        content: Box content.
        color: Color for the border.
        width: Box width.
    """
    top = f"{color}{'=' * width}{Colors.RESET}"
    log(top)
    log(f"{color}{Colors.BOLD}{title.center(width)}{Colors.RESET}")
    log(f"{color}{'=' * width}{Colors.RESET}")
    if content:
        for line in content.split("\n"):
            log(line)


def print_section(title: str, color: str = Colors.BLUE) -> None:
    """Print a section header.

    Args:
        title: Section title.
        color: Color for the header.
    """
    log(f"\n{color}{Colors.BOLD}{title}{Colors.RESET}")
    log(f"{color}{'-' * len(title)}{Colors.RESET}")


# =============================================================================
# Load Shape
# =============================================================================
class SpinDetectorShape(LoadTestShape):
    """Load shape with spike/drop pattern for detecting CPU spin loops.

    Pattern:
    - Ramp up to target users over ramp_time
    - Sustain load for sustain_time
    - Drop to 0 users
    - Pause for pause_time (monitor CPU - should return to idle)
    - Repeat for multiple cycles

    If CPU stays high during pause phases, the spin loop bug is present.
    """

    # Configuration for each cycle: (target_users, ramp_time, sustain_time, pause_time)
    cycles = [
        (2000, 30, 20, 30),   # Cycle 1: 2000 users
        (3000, 30, 20, 30),   # Cycle 2: 3000 users
        (4000, 30, 20, 30),   # Cycle 3: 4000 users (peak)
        (2000, 20, 10, 20),   # Cycle 4: Quick cycle
        (4000, 30, 20, 30),   # Cycle 5: Final peak
    ]

    spawn_rate = 200

    def __init__(self):
        """Initialize the load shape."""
        super().__init__()
        self._current_cycle = 0
        self._cycle_start_time = 0
        self._last_phase = None
        self._pause_stats: list[tuple[int, float]] = []  # (cycle, max_cpu) during pauses
        self._banner_printed = False

    def tick(self) -> Optional[tuple[int, float]]:
        """Calculate the current target user count and spawn rate."""
        # Print banner on first tick (before any phase output)
        if not self._banner_printed:
            self._banner_printed = True
            self._print_banner()

        run_time = self.get_run_time()

        if self._current_cycle >= len(self.cycles):
            if self._last_phase != "complete":
                self._log_phase_change("complete", 0, 0)
            return None

        target_users, ramp_time, sustain_time, pause_time = self.cycles[self._current_cycle]
        cycle_duration = ramp_time + sustain_time + pause_time

        if self._cycle_start_time == 0:
            self._cycle_start_time = run_time

        cycle_time = run_time - self._cycle_start_time

        if cycle_time < ramp_time:
            phase = "ramp"
            progress = cycle_time / ramp_time
            users = max(1, int(target_users * progress))  # At least 1 user during ramp
        elif cycle_time < ramp_time + sustain_time:
            phase = "sustain"
            users = target_users
        elif cycle_time < cycle_duration:
            phase = "pause"
            users = 0
        else:
            self._current_cycle += 1
            self._cycle_start_time = run_time
            self._last_phase = None
            return self.tick()

        if phase != self._last_phase:
            self._log_phase_change(phase, users, target_users)
            self._last_phase = phase

        return (users, self.spawn_rate)

    def _print_banner(self) -> None:
        """Print initial banner and instructions."""
        _init_log_file()

        log("")
        print_box(
            "CPU SPIN LOOP DETECTOR",
            f"Issue #2360 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            Colors.CYAN
        )

        log(f"""
{Colors.BOLD}PURPOSE:{Colors.RESET}
  Detect CPU spin loop bug caused by orphaned asyncio tasks.

{Colors.BOLD}TEST PATTERN:{Colors.RESET}
  1. {Colors.GREEN}Ramp up{Colors.RESET} to high user count (creates sessions)
  2. {Colors.CYAN}Sustain{Colors.RESET} load for observation
  3. {Colors.MAGENTA}Drop{Colors.RESET} to 0 users (triggers cleanup)
  4. {Colors.YELLOW}Pause{Colors.RESET} to monitor CPU (should return to idle)
  5. Repeat for 5 cycles

{Colors.BOLD}EXPECTED:{Colors.RESET}
  {Colors.GREEN}PASS:{Colors.RESET} CPU <10% during pause | {Colors.RED}FAIL:{Colors.RESET} CPU >100% during pause

{Colors.DIM}Log: {LOG_FILE}{Colors.RESET}
""")

        print_section("Initial Docker Stats")
        stats_output, cpu_values = get_docker_stats()
        log(stats_output)
        log(f"\n{format_cpu_status(cpu_values)}\n")

    def _log_phase_change(self, phase: str, current_users: int, target_users: int) -> None:
        """Log phase transitions with docker stats."""
        cycle_num = self._current_cycle + 1
        total_cycles = len(self.cycles)

        stats_output, cpu_values = get_docker_stats()
        cpu_status = format_cpu_status(cpu_values)

        if phase == "ramp":
            print_box(
                f"CYCLE {cycle_num}/{total_cycles}: RAMPING UP",
                f"Target: {target_users} users | Spawn rate: {self.spawn_rate}/s",
                Colors.BLUE
            )
        elif phase == "sustain":
            print_box(
                f"CYCLE {cycle_num}/{total_cycles}: SUSTAINING LOAD",
                f"Holding at {target_users} users",
                Colors.CYAN
            )
        elif phase == "pause":
            print_box(
                f"CYCLE {cycle_num}/{total_cycles}: PAUSE - MONITORING CPU",
                "",
                Colors.MAGENTA
            )
            log("")
            log(f"  {Colors.YELLOW}{Colors.BOLD}>>> ALL USERS DISCONNECTED <<<{Colors.RESET}")
            log(f"  {Colors.YELLOW}>>> CPU should drop to <10% if cleanup is working <<<{Colors.RESET}")
            log("")

            # Record max CPU for this pause
            if cpu_values:
                max_cpu = max(cpu for _, cpu in cpu_values)
                self._pause_stats.append((cycle_num, max_cpu))

        elif phase == "complete":
            self._print_final_report()
            return

        # Print docker stats
        print_section("Docker Stats")
        log(stats_output)
        log(f"\n{cpu_status}\n")

    def _print_final_report(self) -> None:
        """Print final summary report."""
        stats_output, cpu_values = get_docker_stats()

        log("")
        print_box(
            "TEST COMPLETE",
            "",
            Colors.GREEN if all(cpu < 10 for _, cpu in cpu_values) else Colors.RED
        )

        # Summary table
        print_section("Pause Phase CPU Summary", Colors.MAGENTA)
        log(f"{'Cycle':<10} {'Max CPU %':<15} {'Status':<20}")
        log("-" * 45)

        all_passed = True
        for cycle_num, max_cpu in self._pause_stats:
            if max_cpu < 10:
                status = f"{Colors.GREEN}PASS{Colors.RESET}"
            elif max_cpu < 50:
                status = f"{Colors.YELLOW}WARN{Colors.RESET}"
                all_passed = False
            else:
                status = f"{Colors.RED}FAIL{Colors.RESET}"
                all_passed = False
            log(f"{cycle_num:<10} {max_cpu:<15.1f} {status}")

        # Final stats
        print_section("Final Docker Stats")
        log(stats_output)
        log(f"\n{format_cpu_status(cpu_values)}")

        # Verdict
        log("")
        if all_passed and cpu_values and all(cpu < 10 for _, cpu in cpu_values):
            log(f"{Colors.GREEN}{Colors.BOLD}")
            log("  +------------------------------------------+")
            log("  |              TEST PASSED                 |")
            log("  |   CPU returned to idle after cleanup     |")
            log("  +------------------------------------------+")
            log(f"{Colors.RESET}")
        else:
            log(f"{Colors.RED}{Colors.BOLD}")
            log("  +------------------------------------------+")
            log("  |              TEST FAILED                 |")
            log("  |   CPU spin loop may still be present     |")
            log("  +------------------------------------------+")
            log(f"{Colors.RESET}")
            log(f"\n{Colors.YELLOW}See: todo/how-to-analyze.md for debugging steps{Colors.RESET}")

        log(f"\n{Colors.DIM}Issue: https://github.com/IBM/mcp-context-forge/issues/2360{Colors.RESET}")
        log(f"{Colors.DIM}Log file: {LOG_FILE}{Colors.RESET}\n")


# =============================================================================
# Event Handlers
# =============================================================================
@events.test_stop.add_listener
def on_test_stop(environment, **_kwargs):
    """Clean up on test stop."""
    _close_log_file()
    log(f"\n{Colors.DIM}Log saved to: {LOG_FILE}{Colors.RESET}\n")
