"""Async filesystem resolution and helpers for :class:`AsyncUPath`.

This module bridges upath to fsspec's async layer:

* :func:`resolve_async_fs` returns an ``fsspec.asyn.AsyncFileSystem`` for a
  given (sync) fsspec filesystem class + storage options, preferring the
  backend's native async implementation and falling back to a thread-offloading
  wrapper for sync-only backends.
* :class:`_ToThreadFS` is a minimal ``AsyncFileSystem``-like shim used when
  fsspec is too old to provide ``AsyncFileSystemWrapper`` (fsspec < ~2024.12).
* :class:`_AsyncFileWrapper` adapts a synchronous fsspec file object to the
  async file protocol (``await f.read()`` / ``async with``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from upath._async._offload import _is_stateful
from upath._async._offload import executor_for
from upath._async._offload import run_in_thread

if TYPE_CHECKING:
    from concurrent.futures import ThreadPoolExecutor

    from fsspec import AbstractFileSystem
    from fsspec.asyn import AsyncFileSystem

__all__ = [
    "resolve_async_fs",
    "has_working_open_async",
]


# fsspec's AsyncFileSystemWrapper landed around the 2024.12 release. upath's
# floor is fsspec >=2024.5.0, so its availability must be feature-detected.
try:
    from fsspec.implementations.asyn_wrapper import (
        AsyncFileSystemWrapper as _AsyncFileSystemWrapper,
    )  # noqa: F401

    _HAS_ASYNC_WRAPPER = True
except ImportError:  # pragma: no cover - depends on installed fsspec version
    _AsyncFileSystemWrapper = None  # type: ignore[assignment,misc]
    _HAS_ASYNC_WRAPPER = False


# The subset of async coroutines AsyncUPath relies on. The _ToThreadFS fallback
# only needs to provide these; native async filesystems provide the full set.
_OFFLOADED_METHODS = frozenset(
    {
        "_cat_file",
        "_pipe_file",
        "_ls",
        "_info",
        "_isdir",
        "_isfile",
        "_exists",
        "_rm",
        "_rm_file",
        "_mkdir",
        "_makedirs",
        "_cp_file",
        "_copy",
        "_get_file",
        "_put_file",
        "_glob",
        "_find",
        "_mv",
    }
)


def _is_native_async(fs_cls: type[AbstractFileSystem]) -> bool:
    """Whether an fsspec filesystem class ships its own async implementation."""
    return bool(getattr(fs_cls, "async_impl", False))


def resolve_async_fs(sync_fs: AbstractFileSystem) -> AsyncFileSystem:
    """Return an async filesystem for the given (chain-aware) sync instance.

    ``sync_fs`` is the filesystem resolved by ``UPath.fs``, which already
    handles chained URLs (e.g. ``simplecache::memory://``) correctly.

    * If it is natively async, build an ``asynchronous=True`` instance with the
      same storage options so its coroutines can be awaited directly on the
      running loop. fsspec's global instance cache is skipped: a cached instance
      binds its client/session (aiobotocore/aiohttp) to the loop it was first
      used on, which breaks when the same path is later awaited on a different
      loop. AsyncUPath caches the resolved instance per path via
      ``_async_fs_cached``.
    * Otherwise wrap the synchronous instance so all operations are offloaded to
      a thread pool (via fsspec's ``AsyncFileSystemWrapper`` when available, or
      the built-in :class:`_ToThreadFS` fallback).
    """
    if _is_native_async(type(sync_fs)):
        return type(sync_fs)(  # type: ignore[return-value]
            asynchronous=True,
            skip_instance_cache=True,
            **sync_fs.storage_options,
        )
    # Stateful, connection-based backends (ftp/sftp/smb) must serialize their
    # offloaded work onto a single per-connection thread; fsspec's
    # AsyncFileSystemWrapper offloads onto the shared default pool and cannot
    # guarantee that, so use our _ToThreadFS (which routes through executor_for).
    if _HAS_ASYNC_WRAPPER and not _is_stateful(sync_fs):
        return _AsyncFileSystemWrapper(sync_fs, asynchronous=True)
    return _ToThreadFS(sync_fs)  # type: ignore[return-value]


def has_working_open_async(fs: AsyncFileSystem) -> bool:
    """Whether ``fs.open_async`` is expected to return a usable async file.

    fsspec's base ``open_async`` and ``AsyncFileSystemWrapper.open_async`` both
    raise ``NotImplementedError``; only backends that override it with a real
    implementation are usable for native async streaming.
    """
    if not getattr(fs, "async_impl", False):
        return False
    if _HAS_ASYNC_WRAPPER and isinstance(fs, _AsyncFileSystemWrapper):
        return False
    if isinstance(fs, _ToThreadFS):
        return False
    from fsspec.asyn import AsyncFileSystem

    # unoverridden base method -> no native async file handles
    return type(fs).open_async is not AsyncFileSystem.open_async


class _ToThreadFS:
    """Minimal async filesystem shim wrapping a synchronous fsspec filesystem.

    Used as a fallback when ``AsyncFileSystemWrapper`` is unavailable in the
    installed fsspec version, and for stateful (connection-based) backends that
    must serialize onto a single worker thread. Each supported coroutine offloads
    the corresponding synchronous call via :func:`upath._async._offload.run_in_thread`
    on the filesystem's assigned executor.
    """

    async_impl = True

    def __init__(self, sync_fs: AbstractFileSystem) -> None:
        self.sync_fs = sync_fs
        self.asynchronous = True
        self._executor = executor_for(sync_fs)

    def __getattr__(self, item: str) -> Any:
        # expose async `_name` coroutines that offload the sync `name` method,
        # and pass through everything else (protocol, sep, storage_options, ...)
        if item in _OFFLOADED_METHODS:
            sync_name = item[1:]  # strip leading underscore
            sync_call = getattr(self.sync_fs, sync_name)
            executor = self.__dict__["_executor"]

            async def _offloaded(*args: Any, **kwargs: Any) -> Any:
                return await run_in_thread(
                    sync_call, *args, executor=executor, **kwargs
                )

            return _offloaded
        return getattr(self.sync_fs, item)

    async def open_async(self, path: str, mode: str = "rb", **kwargs: Any) -> Any:
        raise NotImplementedError

    @property
    def loop(self) -> Any:  # pragma: no cover - not used in offload mode
        return getattr(self.sync_fs, "loop", None)


class _AsyncFileWrapper:
    """Adapt a synchronous fsspec file object to the async file protocol.

    Read/write/seek/close are offloaded to threads. The ``executor`` is the one
    belonging to the owning filesystem, so a connection-based backend's file I/O
    serializes with its metadata calls on the same worker thread. Supports async
    context manager usage: ``async with await path.open("rb") as f: await f.read()``.
    """

    def __init__(self, file: Any, executor: ThreadPoolExecutor | None = None) -> None:
        self._file = file
        self._executor = executor

    async def read(self, size: int = -1) -> Any:
        return await run_in_thread(self._file.read, size, executor=self._executor)

    async def write(self, data: Any) -> Any:
        return await run_in_thread(self._file.write, data, executor=self._executor)

    async def seek(self, offset: int, whence: int = 0) -> Any:
        return await run_in_thread(
            self._file.seek, offset, whence, executor=self._executor
        )

    async def tell(self) -> int:
        return await run_in_thread(self._file.tell, executor=self._executor)

    async def flush(self) -> None:
        await run_in_thread(self._file.flush, executor=self._executor)

    async def close(self) -> None:
        await run_in_thread(self._file.close, executor=self._executor)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._file, item)

    async def __aenter__(self) -> _AsyncFileWrapper:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
