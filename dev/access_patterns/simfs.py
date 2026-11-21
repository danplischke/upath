"""A fake 'remote' fsspec filesystem that records every backend request.

It subclasses AbstractBufferedFile exactly like s3fs/gcsfs/http/adlfs do, so
fsspec's real cache implementations (readahead, bytes, blockcache, ...) sit
between the reader and the logged requests.  Each logged event corresponds to
one HTTP round trip on a real object store (GET w/ Range, HEAD, or LIST).
"""

from __future__ import annotations

import os
import threading

import fsspec
from fsspec.spec import AbstractBufferedFile
from fsspec.spec import AbstractFileSystem


class Trace:
    def __init__(self):
        self.lock = threading.Lock()
        self.events: list[tuple[str, str, int, int]] = []

    def add(self, kind, path, start, end):
        with self.lock:
            self.events.append((kind, path, start, end))

    def reset(self):
        with self.lock:
            self.events = []


TRACE = Trace()
NET = None  # set to a netsim.Net to add real network delays


def _net(nbytes):
    if NET is not None:
        NET.request(nbytes)


PREFIX = "simremote://"


class SimFile(AbstractBufferedFile):
    def _fetch_range(self, start, end):
        end = min(end, self.size)
        if end <= start:
            return b""
        TRACE.add("get", self.path, start, end)
        _net(end - start)
        with open(self.path, "rb") as f:
            f.seek(start)
            return f.read(end - start)


class SimRemoteFS(AbstractFileSystem):
    protocol = ("simremote",)
    cachable = False  # codespell:ignore cachable

    def __init__(
        self, default_block_size=5 * 2**20, default_cache_type="readahead", **kw
    ):
        super().__init__(**kw)
        self.default_block_size = default_block_size
        self.default_cache_type = default_cache_type

    @classmethod
    def _strip_protocol(cls, path):
        path = fsspec.utils.stringify_path(path)
        path = path.removeprefix(PREFIX)
        return path.rstrip("/") or "/"

    def info(self, path, **kwargs):
        path = self._strip_protocol(path)
        TRACE.add("head", path, 0, 0)
        _net(0)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        if os.path.isdir(path):
            return {"name": path, "size": 0, "type": "directory"}
        return {"name": path, "size": os.path.getsize(path), "type": "file"}

    def ls(self, path, detail=True, **kwargs):
        path = self._strip_protocol(path)
        TRACE.add("list", path, 0, 0)
        _net(0)
        if not os.path.isdir(path):
            raise FileNotFoundError(path)
        out = []
        for name in sorted(os.listdir(path)):
            p = f"{path}/{name}"
            isdir = os.path.isdir(p)
            out.append(
                {
                    "name": p,
                    "size": 0 if isdir else os.path.getsize(p),
                    "type": "directory" if isdir else "file",
                }
            )
        return out if detail else [o["name"] for o in out]

    def cat_file(self, path, start=None, end=None, **kwargs):
        path = self._strip_protocol(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        size = os.path.getsize(path)
        start = 0 if start is None else (max(0, size + start) if start < 0 else start)
        end = size if end is None else (size + end if end < 0 else min(end, size))
        TRACE.add("get", path, start, end)
        _net(end - start)
        with open(path, "rb") as f:
            f.seek(start)
            return f.read(end - start)

    def _open(
        self,
        path,
        mode="rb",
        block_size=None,
        autocommit=True,
        cache_options=None,
        cache_type=None,
        **kwargs,
    ):
        assert mode == "rb"
        return SimFile(
            self,
            path,
            mode,
            block_size=block_size or self.default_block_size,
            cache_type=cache_type or self.default_cache_type,
            cache_options=cache_options,
        )


fsspec.register_implementation("simremote", SimRemoteFS, clobber=True)


from fsspec.asyn import AsyncFileSystem  # noqa: E402


class AsyncSimFS(AsyncFileSystem):
    """Async-native variant (like s3fs/gcsfs) used for zarr's concurrent gets."""

    protocol = ("asim",)
    cachable = False  # codespell:ignore cachable

    async def _info(self, path, **kw):
        TRACE.add("head", path, 0, 0)
        if NET is not None:
            await NET.arequest(0)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        if os.path.isdir(path):
            return {"name": path, "size": 0, "type": "directory"}
        return {"name": path, "size": os.path.getsize(path), "type": "file"}

    async def _cat_file(self, path, start=None, end=None, **kw):
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        size = os.path.getsize(path)
        start = 0 if start is None else (max(0, size + start) if start < 0 else start)
        end = size if end is None else (size + end if end < 0 else min(end, size))
        TRACE.add("get", path, start, end)
        if NET is not None:
            await NET.arequest(end - start)
        with open(path, "rb") as f:
            f.seek(start)
            return f.read(end - start)
