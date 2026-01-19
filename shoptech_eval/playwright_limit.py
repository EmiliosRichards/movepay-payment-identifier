from __future__ import annotations

import contextlib
import os
import threading


def _max_concurrency_from_env() -> int:
    raw = (os.environ.get("SHOPTECH_PLAYWRIGHT_MAX_CONCURRENCY") or "").strip()
    if not raw:
        return 1
    try:
        v = int(raw)
        return max(1, v)
    except Exception:
        return 1


_PW_SEMAPHORE = threading.Semaphore(_max_concurrency_from_env())


@contextlib.contextmanager
def playwright_slot():
    """
    Global concurrency limiter for Playwright usage.

    This prevents multiple worker threads from spawning too many Chromium instances at once.
    Control via env:
      SHOPTECH_PLAYWRIGHT_MAX_CONCURRENCY (default 1)
    """
    with _PW_SEMAPHORE:
        yield

