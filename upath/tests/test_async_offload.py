"""Tests for the async thread-offload seam (``upath._async._offload``)."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from upath import AsyncUPath
from upath._async import _fs as fsmod
from upath._async import _offload


class _FakeStatefulFS:
    """A sync fs with a single non-thread-safe connection.

    ``op`` asserts it is never entered concurrently -- exactly the invariant a
    per-connection single-worker executor must guarantee.
    """

    protocol = "ftp"  # a STATEFUL protocol
    cachable = False

    def __init__(self):
        self._active = 0
        self.max_concurrent = 0
        self.lock = threading.Lock()

    def op(self, n):
        with self.lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        time.sleep(0.01)
        with self.lock:
            self._active -= 1
        return n


# --- executor policy -------------------------------------------------------


def test_stateful_detection():
    assert _offload._is_stateful(_FakeStatefulFS()) is True

    class _Mem:
        protocol = "memory"

    assert _offload._is_stateful(_Mem()) is False


def test_stateful_gets_single_worker_executor_cached_by_instance():
    fs1, fs2 = _FakeStatefulFS(), _FakeStatefulFS()
    e1, e1b, e2 = (
        _offload.executor_for(fs1),
        _offload.executor_for(fs1),
        _offload.executor_for(fs2),
    )
    assert e1 is e1b  # same connection -> same executor
    assert e1 is not e2  # different connection -> different executor
    assert e1._max_workers == 1


def test_stateless_uses_shared_bounded_pool():
    class _Mem:
        protocol = "memory"

    assert _offload.executor_for(_Mem()) is _offload._get_shared_executor()


def test_max_workers_env(monkeypatch):
    monkeypatch.setenv("UPATH_ASYNC_MAX_THREADS", "3")
    assert _offload._max_workers() == 3
    monkeypatch.setenv("UPATH_ASYNC_MAX_THREADS", "not-an-int")
    assert _offload._max_workers() >= 1  # falls back to default


# --- serialization (the correctness win) -----------------------------------


async def test_stateful_ops_never_overlap():
    fs = _FakeStatefulFS()
    executor = _offload.executor_for(fs)
    # fan out many concurrent offloaded calls onto the connection's executor
    await asyncio.gather(
        *(_offload.run_in_thread(fs.op, i, executor=executor) for i in range(20))
    )
    assert fs.max_concurrent == 1  # never ran two ops at once


async def test_resolve_async_fs_serializes_stateful(monkeypatch):
    # even when the fsspec wrapper is available, stateful backends use _ToThreadFS
    fs = _FakeStatefulFS()
    afs = fsmod.resolve_async_fs(fs)
    assert isinstance(afs, fsmod._ToThreadFS)
    assert afs._executor._max_workers == 1


# --- override hook (runtime portability seam) ------------------------------


async def test_run_in_thread_is_the_single_seam(clean_memory, monkeypatch):
    calls = []
    real = _offload.run_in_thread

    async def spy(func, /, *args, **kwargs):
        calls.append(getattr(func, "__name__", type(func).__name__))
        return await real(func, *args, **kwargs)

    # patch at both the definition site and the import sites
    monkeypatch.setattr(_offload, "run_in_thread", spy)
    monkeypatch.setattr(fsmod, "run_in_thread", spy)
    import upath._async.core as coremod

    monkeypatch.setattr(coremod, "run_in_thread", spy)

    p = AsyncUPath("memory://offload/f.txt")
    await p.write_bytes(b"data")
    assert await p.read_bytes() == b"data"
    async with await p.open("rb") as f:
        await f.read()

    assert calls, "offloads did not route through run_in_thread"


@pytest.fixture()
def clean_memory():
    from fsspec.implementations.memory import MemoryFileSystem

    store = MemoryFileSystem.store.copy()
    MemoryFileSystem.store.clear()
    try:
        yield
    finally:
        MemoryFileSystem.store = store
