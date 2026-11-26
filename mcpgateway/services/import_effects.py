# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/import_effects.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Registry side effects that must wait for configuration import commit.
"""

# Standard
from collections.abc import Callable
from contextvars import ContextVar
from functools import partial
from inspect import isawaitable
from typing import Any

pending_import_effects: ContextVar[list[Callable[[], Any]] | None] = ContextVar("pending_import_effects", default=None)


async def after_import_commit(callback: Callable[..., Any], /, *args: Any, **kwargs: Any) -> None:
    """Run an asynchronous registry effect now or queue it for import commit.

    Args:
        callback: Registry effect to run.
        args: Effect positional arguments.
        kwargs: Effect keyword arguments.
    """
    pending = pending_import_effects.get()
    if pending is None:
        result = callback(*args, **kwargs)
        if isawaitable(result):
            await result
    else:
        pending.append(partial(callback, *args, **kwargs))


def after_import_commit_sync(callback: Callable[..., Any], /, *args: Any, **kwargs: Any) -> None:
    """Run a synchronous registry effect now or queue it for import commit.

    Args:
        callback: Registry effect to run.
        args: Effect positional arguments.
        kwargs: Effect keyword arguments.
    """
    pending = pending_import_effects.get()
    if pending is None:
        callback(*args, **kwargs)
    else:
        pending.append(partial(callback, *args, **kwargs))
