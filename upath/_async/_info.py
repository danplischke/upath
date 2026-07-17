"""Async path-info for :class:`AsyncUPath`, mirroring :mod:`upath._info`."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from upath._async.core import AsyncUPath

__all__ = ["AsyncUPathInfo"]


class AsyncUPathInfo:
    """Async counterpart of :class:`upath._info.UPathInfo`.

    The status-check methods are coroutines so they can be awaited::

        info = path.info
        if await info.is_dir():
            ...
    """

    def __init__(self, path: AsyncUPath) -> None:
        self._path = path.path
        self._fs = path._async_fs

    async def exists(self, *, follow_symlinks: bool = True) -> bool:
        return await self._fs._exists(self._path)

    async def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        return await self._fs._isdir(self._path)

    async def is_file(self, *, follow_symlinks: bool = True) -> bool:
        return await self._fs._isfile(self._path)

    async def is_symlink(self) -> bool:
        return False
