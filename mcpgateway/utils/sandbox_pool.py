# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/sandbox_pool.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

A killable worker pool for untrusted computation.

CPython holds the GIL through a C-level call such as a regex match or a jq run, so an
operation that does not terminate freezes the whole gateway worker. A thread cannot be
cancelled, so the only way to bound such an operation is to run it in a process and kill
that process.

This module owns the pool lifecycle shared by every such sandbox: build, prove the workers
started, gate admission so a timeout means overrun rather than queueing, kill and replace
on overrun, and recover from a broken pool.
"""

# Future
from __future__ import annotations

# Standard
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from concurrent.futures.process import BrokenProcessPool
import logging
import multiprocessing
import os
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

__all__ = ["SandboxBusy", "SandboxError", "SandboxPool", "SandboxTimeout", "SandboxUnavailable"]

# Lower bound on the warm-up wait. A short per-call timeout must not shrink the startup
# budget and turn a boot into a failure.
_WARMUP_MIN_SECONDS = 10.0

# Attribute stamped on each executor with the PID that built it. Ownership has to be
# decidable from the pool object alone: a pool can be replaced while one of its workers
# still runs hostile work, and that worker must stay killable.
_OWNER_PID_ATTR = "_mcpgateway_owner_pid"

# The gate is stamped on the executor, not held on the pool object. A pool can be rebuilt
# while another thread holds a permit; a gate on the instance would then admit against a
# different executor than the one it counted.
_GATE_ATTR = "_mcpgateway_submit_gate"


class SandboxError(Exception):
    """Raised when sandboxed work cannot be run."""


class SandboxTimeout(SandboxError):
    """Raised when sandboxed work exceeds its wall-clock limit.

    Only raised for a submission known to have started immediately, because the admission
    gate guarantees a free worker. This never reflects queueing pressure.
    """


class SandboxBusy(SandboxError):
    """Raised when every worker is already occupied.

    Safe to retry. Never kills the pool, because nothing has overrun.
    """


class SandboxUnavailable(SandboxError):
    """Raised when no sandbox can be built on this platform."""


def _warmup() -> bool:
    """Prove a worker process started and ran code.

    Returns:
        Always True.
    """
    return True


class SandboxPool:
    """A process pool whose workers can be killed and replaced."""

    def __init__(
        self,
        name: str,
        workers_fn: Callable[[], int],
        timeout_fn: Callable[[], float],
        initializer: Optional[Callable[[], None]] = None,
        start_method: str = "fork",
    ) -> None:
        """Configure a sandbox pool.

        Settings arrive as callables so each call reads the live value. Tests monkeypatch
        those settings after import, and a captured value would ignore them.

        Args:
            name: Short label used in log messages.
            workers_fn: Returns the worker count to build with.
            timeout_fn: Returns the wall-clock limit for one submission, in seconds.
            initializer: Optional callable run once inside each worker.
            start_method: Multiprocessing start method established by the Task 1 gate.
        """
        self._name = name
        self._workers_fn = workers_fn
        self._timeout_fn = timeout_fn
        self._initializer = initializer
        self._start_method = start_method
        self._pool: Optional[ProcessPoolExecutor] = None
        self._pool_pid: Optional[int] = None
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        """Report whether this platform supports the configured start method.

        Returns:
            True when the start method exists here.
        """
        return self._start_method in multiprocessing.get_all_start_methods()

    def _current_executor(self) -> Optional[ProcessPoolExecutor]:
        """Return the executor this pool currently holds.

        Returns:
            The executor, or None when the pool is not started.
        """
        return self._pool

    def start(self) -> None:
        """Build the pool and prove its workers start.

        Call from application startup, after any fork the server performs, so each gateway
        worker owns its own pool.

        Raises:
            SandboxUnavailable: If the start method is unsupported here.
            Exception: Whatever the warm-up submission raises when the pool cannot be
                brought up. A pool that will not start is a hard startup failure, because
                the alternative is booting a gateway whose sandbox is absent.
        """
        if not self.is_available():
            raise SandboxUnavailable(f"{self._name}: start method {self._start_method!r} is unavailable")
        with self._lock:
            if self._pool is not None and self._pool_pid == os.getpid():
                return
            pool = self._build()
            try:
                # Force worker creation now, while the process has the fewest threads,
                # rather than mid-request on the first hostile input.
                pool.submit(_warmup).result(timeout=max(_WARMUP_MIN_SECONDS, self._timeout_fn()))
            except Exception:
                pool.shutdown(wait=False, cancel_futures=True)
                raise
            self._pool = pool
            self._pool_pid = os.getpid()
            logger.info("%s sandbox started with %s worker(s)", self._name, self._workers_fn())

    def shutdown(self) -> None:
        """Kill this pool's workers and clear its state."""
        self._discard(None)

    def submit(self, fn: Callable[..., Any], *args: Any) -> Any:
        """Run one call in a worker under the wall-clock limit.

        Args:
            fn: A module-level picklable callable.
            *args: Picklable arguments.

        Returns:
            Whatever the callable returns.

        Raises:
            SandboxBusy: If no worker is free.
            SandboxTimeout: If the call exceeds its limit.
            SandboxError: If the pool cannot run the call.
        """
        pool = self._ensure()
        gate = getattr(pool, _GATE_ATTR, None)
        # Read the budget BEFORE taking a permit. Between acquire() and the try/finally
        # there is no release path, so a raising timeout_fn would leak the permit
        # permanently and brick the pool into returning SandboxBusy forever.
        timeout = self._timeout_fn()
        # ProcessPoolExecutor queues a task the instant every worker is busy, and
        # Future.result(timeout=...) cannot tell "still queued" apart from "running past
        # its budget". Reserving a slot first means a submission only reaches the pool
        # when a worker is free, so a timeout on it is never queueing pressure.
        if gate is None or not gate.acquire(blocking=False):
            raise SandboxBusy(f"{self._name} sandbox has no free worker")
        try:
            try:
                return pool.submit(fn, *args).result(timeout=timeout)
            except FutureTimeoutError as exc:
                logger.warning("%s sandbox exceeded %ss limit; killing worker", self._name, timeout)
                self._discard(pool)
                raise SandboxTimeout(f"{self._name} exceeded the execution time limit") from exc
            except BrokenProcessPool as exc:
                # A worker died without the timeout firing. The executor is permanently
                # broken afterwards, so drop it and let the next call rebuild.
                logger.warning("%s worker pool broke; discarding it so the next call rebuilds", self._name)
                self._discard(pool)
                raise SandboxError(str(exc)) from exc
            except SandboxError:
                raise
            except Exception as exc:  # pylint: disable=broad-except
                raise SandboxError(str(exc)) from exc
        finally:
            gate.release()

    def _build(self) -> ProcessPoolExecutor:
        """Create a worker pool and stamp its ownership and admission gate.

        Returns:
            A new executor.
        """
        workers = self._workers_fn()
        pool = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=multiprocessing.get_context(self._start_method),
            initializer=self._initializer,
        )
        setattr(pool, _OWNER_PID_ATTR, os.getpid())
        setattr(pool, _GATE_ATTR, threading.Semaphore(workers))
        return pool

    def _ensure(self) -> ProcessPoolExecutor:
        """Return a live pool for this process, building one if needed.

        Returns:
            The executor owned by this process.

        Raises:
            SandboxError: If the pool cannot be created.
        """
        with self._lock:
            if self._pool is not None and self._pool_pid == os.getpid():
                return self._pool
            try:
                self._pool = self._build()
                self._pool_pid = os.getpid()
            except Exception as exc:  # pylint: disable=broad-except
                self._pool = None
                self._pool_pid = None
                raise SandboxError(f"{self._name} sandbox unavailable: {exc}") from exc
            return self._pool

    def _owns(self, pool: ProcessPoolExecutor) -> bool:
        """Report whether this process created the pool's workers.

        Args:
            pool: The executor to test.

        Returns:
            True when killing its workers is safe here.
        """
        return getattr(pool, _OWNER_PID_ATTR, None) == os.getpid()

    def _discard(self, pool: Optional[ProcessPoolExecutor]) -> None:
        """Kill a pool's workers and clear state that still names it.

        A pool running hostile work stays killable even after another thread has replaced
        the current pointer, otherwise the runaway worker is orphaned and wedges
        interpreter exit. A pool inherited across a fork is never killed, because its
        Process objects belong to the parent.

        Args:
            pool: The executor to discard, or None for the current one.
        """
        with self._lock:
            target = pool if pool is not None else self._pool
            if target is None:
                return
            if self._owns(target):
                # ProcessPoolExecutor cannot cancel a running task, and the public
                # terminate_workers method is Python 3.14. The private mapping is the only
                # route; a test pins it. shutdown() sets _processes to None to release file
                # descriptors, so an already-shut-down pool must not blow up here.
                for process in list((getattr(target, "_processes", None) or {}).values()):
                    try:
                        process.kill()
                    except Exception:  # pylint: disable=broad-except
                        logger.warning("Failed to kill a %s worker process", self._name, exc_info=True)
                target.shutdown(wait=False, cancel_futures=True)
            # Only stand down the shared state if it still points at the pool just
            # handled; a newer pool built by another thread is left alone.
            if self._pool is target:
                self._pool = None
                self._pool_pid = None
