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
``webdav``) the operations are transparently offloaded to a thread pool (see
:mod:`upath._async._offload`); connection-based backends serialize onto a single
per-connection worker thread.
"""

from __future__ import annotations

from upath._async.core import AsyncUPath

__all__ = ["AsyncUPath"]
