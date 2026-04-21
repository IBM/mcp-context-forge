import os
import ssl
import time
import asyncio
import traceback
import sys


def ctask():
    try:
        return asyncio.current_task()
    except RuntimeError:
        return "-n-"


class SSLValidator:
    count = 0
    tm = 0
    _original_create = ssl.create_default_context

    @classmethod
    def patched_create(cls, *args, **kwargs):
        t = time.perf_counter()
        r = cls._original_create(*args, **kwargs)
        cls.count += 1
        cls.tm += time.perf_counter() - t
        sys.stderr.write(f"PID {os.getpid()} task: {ctask()} SSL Context Created {cls.tm/cls.count}")
        traceback.print_stack(file=sys.stderr, limit=15)
        sys.stderr.flush()
        return r


ssl.create_default_context = SSLValidator.patched_create
