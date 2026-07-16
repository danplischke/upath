"""Native async support for universal_pathlib.

This subpackage provides :class:`~upath._async.core.AsyncUPath`, an
``async``/``await`` capable counterpart to :class:`upath.UPath`.

``AsyncUPath`` reuses the entire synchronous path-algebra and construction
machinery of ``UPath`` (parsing, protocol dispatch, chaining, flavours) and
overrides only the filesystem I/O methods to be coroutines / async iterators.

Filesystem operations are dispatched to the underlying fsspec filesystem's
native async implementation when it provides one (``fs.async_impl is True``,
e.g. ``s3``, ``gcs``, ``http``, ``abfs``). For filesystems that only implement
a synchronous interface (e.g. ``memory``, ``file``, ``sftp``, ``ftp``,
``webdav``) the operations are transparently offloaded to a thread via
:func:`asyncio.to_thread` -- either through fsspec's ``AsyncFileSystemWrapper``
when available, or a small built-in fallback for older fsspec versions.
"""

from __future__ import annotations

from upath._async.core import AsyncUPath

__all__ = ["AsyncUPath"]
