# -*- coding: utf-8 -*-
"""
Runtime async monitoring with aiomonitor integration.
"""
# Standard
import argparse
import asyncio
from typing import Any, Dict

# Third-Party
import aiomonitor


class AsyncMonitor:
    """Monitor live async operations in mcpgateway."""

    def __init__(self, webui_port: int = 50101, console_port: int = 50102, host: str = "localhost"):
        self.webui_port = webui_port
        self.console_port = console_port
        self.host = host
        self.monitor = None
        self.running = False

    async def start_monitoring(self, console_enabled: bool = True):
        """Start aiomonitor for live async debugging."""

        print(f"👁️  Starting aiomonitor on http://{self.host}:{self.webui_port}")

        # Configure aiomonitor
        self.monitor = aiomonitor.Monitor(
            asyncio.get_event_loop(),
            host=self.host,
            webui_port=self.webui_port,
            console_port=self.console_port,     # TODO: FIX CONSOLE NOT CONNECTING TO PORT
            console_enabled=console_enabled,
            locals={'monitor': self}
        )

        self.monitor.start()
        self.running = True

        if console_enabled:
            print(f"🌐 aiomonitor console available at: http://{self.host}:{self.console_port}")
            print("📊 Available commands: ps, where, cancel, signal, console")
            print("🔍 Use 'ps' to list running tasks")
            print("📍 Use 'where <task_id>' to see task stack trace")

        # Keep monitoring running
        try:
            while self.running:
                await asyncio.sleep(1)

                # Periodic task summary
                tasks = [t for t in asyncio.all_tasks() if not t.done()]
                if len(tasks) % 100 == 0 and len(tasks) > 0:
                    print(f"📈 Current active tasks: {len(tasks)}")

        except KeyboardInterrupt: # TODO: FIX STACK TRACE STILL APPEARING ON CTRL-C
            print("\n🛑 Stopping aiomonitor...")
        finally:
            self.monitor.close()

    def stop_monitoring(self):
        """Stop the monitoring."""
        self.running = False

    async def get_task_summary(self) -> Dict[str, Any]:
        """Get summary of current async tasks."""

        tasks = asyncio.all_tasks()

        summary: Dict[str, Any] = {
            'total_tasks': len(tasks),
            'running_tasks': len([t for t in tasks if not t.done()]),
            'completed_tasks': len([t for t in tasks if t.done()]),
            'cancelled_tasks': len([t for t in tasks if t.cancelled()]),
            'task_details': []
        }

        for task in tasks:
            if not task.done():
                summary['task_details'].append({
                    'name': getattr(task, '_name', 'unnamed'),
                    'state': task._state.name if hasattr(task, '_state') else 'unknown',
                    'coro': str(task._coro) if hasattr(task, '_coro') else 'unknown'
                })

        return summary

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run aiomonitor for live async debugging.")
    parser.add_argument("--host", type=str, default="localhost", help="Host to run aiomonitor on.")
    parser.add_argument("--webui_port", type=int, default=50101, help="Port to run aiomonitor on.")
    parser.add_argument("--console_port", type=int, default=50102, help="Port to run aiomonitor on.")
    parser.add_argument("--console-enabled", action="store_true", help="Enable console for aiomonitor.")

    args = parser.parse_args()

    monitor = AsyncMonitor(webui_port=args.webui_port, console_port=args.console_port, host=args.host)
    asyncio.run(monitor.start_monitoring(console_enabled=args.console_enabled))
