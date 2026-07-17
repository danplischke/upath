"""Thread-offload seam for :class:`AsyncUPath`.

For backends that fsspec has no native async driver for, ``AsyncUPath`` offloads
blocking filesystem calls to a thread. This module is the *single place* that
does so, giving one point to control:

* **which executor** runs the blocking call -- a dedicated, bounded pool rather
  than the event loop's shared default ``ThreadPoolExecutor``; and
* **thread-safety for stateful backends** -- connection-based filesystems (ftp,
  sftp, smb) hold a single, non-thread-safe connection per instance, so *all*
  their offloaded work (metadata calls and file-handle I/O alike) must run on a
  single, per-connection worker thread. Running two ops concurrently on one such
  connection can corrupt the protocol stream.

Runtime note: ``AsyncUPath`` targets asyncio (fsspec's native async layer is
asyncio-only). :func:`run_in_thread` is the override point -- reassign
``upath._async._offload.run_in_thread`` to route offloads through another
runtime's thread helper (e.g. ``anyio.to_thread.run_sync``) without touching any
call site.
"""

from __future__ import annotations

import asyncio
import os
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem

__all__ = [
    "run_in_thread",
    "executor_for",
    "STATEFUL_PROTOCOLS",
]


# Protocols backed by a single, non-thread-safe connection per filesystem
# instance. fsspec exposes no "thread-safe" flag, so this is an explicit,
# extensible list. Offloaded work for these is serialized onto one worker.
STATEFUL_PROTOCOLS: frozenset[str] = frozenset({"ftp", "sftp", "ssh", "smb"})


def _max_workers() -> int:
    """Worker count for the shared (stateless) offload pool."""
    raw = os.environ.get("UPATH_ASYNC_MAX_THREADS")
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    # mirror asyncio's default default-executor sizing
    return min(32, (os.cpu_count() or 1) + 4)


def _op_timeout() -> float | None:
    """Default per-offload timeout in seconds, from ``UPATH_ASYNC_OP_TIMEOUT``."""
    raw = os.environ.get("UPATH_ASYNC_OP_TIMEOUT")
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return None


_shared_executor: ThreadPoolExecutor | None = None
# guards lazy creation of the shared pool and of the per-connection executors so
# concurrent first-use from multiple threads can't leak duplicate pools
_executor_lock = threading.Lock()
# per-filesystem single-worker executors, keyed weakly by fs instance so they
# are cleaned up when the filesystem is garbage collected
_stateful_executors: weakref.WeakKeyDictionary[Any, ThreadPoolExecutor] = (
    weakref.WeakKeyDictionary()
)


def _get_shared_executor() -> ThreadPoolExecutor:
    global _shared_executor
    if _shared_executor is None:
        with _executor_lock:
            if _shared_executor is None:
                _shared_executor = ThreadPoolExecutor(
                    max_workers=_max_workers(),
                    thread_name_prefix="upath-async",
                )
    return _shared_executor


def _protocol_of(fs: AbstractFileSystem) -> tuple[str, ...]:
    protocol = getattr(fs, "protocol", ())
    if isinstance(protocol, str):
        return (protocol,)
    try:
        return tuple(protocol)
    except TypeError:  # pragma: no cover - defensive
        return ()


def _is_stateful(fs: AbstractFileSystem) -> bool:
    return any(p in STATEFUL_PROTOCOLS for p in _protocol_of(fs))


def executor_for(fs: AbstractFileSystem | None) -> ThreadPoolExecutor:
    """Return the executor that should run ``fs``'s offloaded blocking calls.

    Stateless filesystems share one bounded pool. Stateful (connection-based)
    filesystems each get a dedicated single-worker executor, cached by instance,
    so their operations serialize on one thread.
    """
    if fs is not None and _is_stateful(fs):
        with _executor_lock:
            try:
                executor = _stateful_executors.get(fs)
            except TypeError:  # fs not weak-referenceable
                executor = None
            if executor is None:
                executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="upath-async-conn",
                )
                try:
                    _stateful_executors[fs] = executor
                except TypeError:  # pragma: no cover - fs not weak-referenceable
                    pass
            return executor
    return _get_shared_executor()


async def run_in_thread(
    func: Callable[..., Any],
    /,
    *args: Any,
    executor: ThreadPoolExecutor | None = None,
    **kwargs: Any,
) -> Any:
    """Run a blocking callable in a thread and await its result.

    This is the single offload primitive used across the async layer, and the
    supported override point for alternate runtimes. ``executor`` selects the
    pool (see :func:`executor_for`); ``None`` uses the shared stateless pool.

    If the ``UPATH_ASYNC_OP_TIMEOUT`` environment variable is set (seconds),
    every offloaded call is bounded by it and raises :class:`TimeoutError` on
    expiry. Note that Python cannot force-kill a worker thread: on timeout -- or
    if the awaiting task is cancelled -- control returns to the caller, but the
    blocking call keeps running to completion in the background. For a
    single-worker (stateful) executor that worker stays busy until it finishes,
    so prefer a per-connection timeout on the backend where one is available.

    The timeout is read from the environment (not a parameter) so it can never
    shadow a ``timeout`` keyword that a backend method itself accepts via
    ``**kwargs`` (e.g. ``fs.mv(..., timeout=...)``).
    """
    loop = asyncio.get_running_loop()
    pool = executor if executor is not None else _get_shared_executor()
    if kwargs:
        from functools import partial

        future = loop.run_in_executor(pool, partial(func, *args, **kwargs))
    else:
        future = loop.run_in_executor(pool, func, *args)
    timeout = _op_timeout()
    if timeout is None:
        return await future
    return await asyncio.wait_for(future, timeout)
