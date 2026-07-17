"""Tests for native async support (:class:`upath.AsyncUPath`).

Covered:

* thread-offload path via ``AsyncFileSystemWrapper`` (memory / local backends),
* the built-in ``_ToThreadFS`` fallback used with older fsspec,
* native async backends (a fake ``AsyncFileSystem``) including real
  concurrency and native ``open_async`` streaming.
"""

from __future__ import annotations

import asyncio

import pytest
from fsspec.asyn import AsyncFileSystem
from fsspec.registry import register_implementation as register_fs

from upath import AsyncUPath
from upath import UPath
from upath.core import UPath as CoreUPath
from upath.registry import register_implementation as register_upath

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def clean_memory():
    """Isolate the process-global in-memory filesystem for each test."""
    from fsspec.implementations.memory import MemoryFileSystem

    store = MemoryFileSystem.store.copy()
    pseudo_dirs = MemoryFileSystem.pseudo_dirs.copy()
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    try:
        yield
    finally:
        MemoryFileSystem.store = store
        MemoryFileSystem.pseudo_dirs = pseudo_dirs


# --- construction / path algebra (shared with sync UPath) -----------------


async def test_async_upath_is_upath_subclass():
    p = AsyncUPath("memory://bucket/a.txt")
    assert isinstance(p, UPath)
    assert type(p).__name__ == "AsyncMemoryPath"
    assert p.protocol == "memory"
    assert p.path == "/bucket/a.txt"


async def test_path_algebra_stays_sync():
    p = AsyncUPath("memory://bucket/dir/a.txt")
    assert p.name == "a.txt"
    assert str(p.parent) == "memory://bucket/dir"
    assert (p.parent / "b.txt").name == "b.txt"
    assert p.suffix == ".txt"
    assert p.with_suffix(".md").name == "a.md"


async def test_with_segments_returns_async():
    p = AsyncUPath("memory://bucket/a.txt")
    child = p.parent / "b.txt"
    assert isinstance(child, AsyncUPath)


# --- round-trip I/O on the wrapper (memory) path --------------------------


async def test_write_read_bytes_and_text(clean_memory):
    p = AsyncUPath("memory://bucket/data/f.txt")
    n = await p.write_bytes(b"hello async")
    assert n == len(b"hello async")
    assert await p.read_bytes() == b"hello async"
    assert await p.read_text() == "hello async"

    m = await p.write_text("second\nline\n")
    assert m == len("second\nline\n")
    assert await p.read_text() == "second\nline\n"


async def test_status_methods(clean_memory):
    p = AsyncUPath("memory://bucket/status/f.txt")
    assert not await p.exists()
    await p.write_bytes(b"x")
    assert await p.exists()
    assert await p.is_file()
    assert not await p.is_dir()
    assert await p.parent.is_dir()

    st = await p.stat()
    assert st.st_size == 1
    info = p.info
    assert await info.is_file()
    assert not await info.is_dir()


async def test_iterdir(clean_memory):
    d = AsyncUPath("memory://bucket/iter")
    await (d / "a.txt").write_bytes(b"a")
    await (d / "b.txt").write_bytes(b"b")
    names = sorted([c.name async for c in d.iterdir()])
    assert names == ["a.txt", "b.txt"]

    with pytest.raises(NotADirectoryError):
        _ = [c async for c in (d / "a.txt").iterdir()]


async def test_glob_and_rglob(clean_memory):
    d = AsyncUPath("memory://bucket/globtest")
    await (d / "a.txt").write_bytes(b"")
    await (d / "sub" / "b.txt").write_bytes(b"")
    top = sorted([c.name async for c in d.glob("*.txt")])
    assert top == ["a.txt"]
    deep = sorted([c.name async for c in d.rglob("*.txt")])
    assert deep == ["a.txt", "b.txt"]


async def test_walk(clean_memory):
    root = AsyncUPath("memory://bucket/walk")
    await (root / "a" / "x.txt").write_bytes(b"")
    await (root / "a" / "b" / "y.txt").write_bytes(b"")
    seen = {}
    async for dirpath, dirnames, filenames in root.walk():
        seen[dirpath.name or dirpath.path] = (sorted(dirnames), sorted(filenames))
    assert seen["walk"] == (["a"], [])
    assert seen["a"] == (["b"], ["x.txt"])
    assert seen["b"] == ([], ["y.txt"])


async def test_mkdir_rmdir_unlink(clean_memory):
    d = AsyncUPath("memory://bucket/mk/deep/dir")
    await d.mkdir(parents=True, exist_ok=True)
    assert await d.is_dir()
    f = d / "f.txt"
    await f.write_bytes(b"data")
    assert await f.exists()

    await f.unlink()
    assert not await f.exists()
    with pytest.raises(FileNotFoundError):
        await f.unlink()
    await f.unlink(missing_ok=True)  # no error

    await AsyncUPath("memory://bucket/mk").rmdir(recursive=True)
    assert not await AsyncUPath("memory://bucket/mk").exists()


async def test_touch_and_rename(clean_memory):
    f = AsyncUPath("memory://bucket/touch/a.txt")
    await f.touch()
    assert await f.exists()
    target = AsyncUPath("memory://bucket/touch/b.txt")
    returned = await f.rename(target)
    assert isinstance(returned, AsyncUPath)
    assert not await f.exists()
    assert await target.exists()


async def test_open_async_context(clean_memory):
    p = AsyncUPath("memory://bucket/open/f.txt")
    async with await p.open("wb") as f:
        await f.write(b"streamed")
    async with await p.open("rb") as f:
        assert await f.read() == b"streamed"


# --- local filesystem (also wrapper-backed) -------------------------------


async def test_local_roundtrip(tmp_path):
    root = AsyncUPath(str(tmp_path))
    sub = root / "a" / "b"
    await sub.mkdir(parents=True, exist_ok=True)
    f = sub / "x.txt"
    await f.write_text("hi\nthere\n")
    assert await f.read_text() == "hi\nthere\n"
    assert await f.is_file()
    names = [c.name async for c in sub.iterdir()]
    assert names == ["x.txt"]


# --- _ToThreadFS fallback (simulate older fsspec) -------------------------


async def test_to_thread_fallback(clean_memory, monkeypatch):
    import upath._async._fs as fsmod

    monkeypatch.setattr(fsmod, "_HAS_ASYNC_WRAPPER", False)
    p = AsyncUPath("memory://bucket/fallback/f.txt")
    # bypass the property cache so resolution re-runs under the patch
    p2 = AsyncUPath("memory://bucket/fallback/f.txt")
    assert isinstance(p2._async_fs, fsmod._ToThreadFS)
    await p.write_bytes(b"fallback")
    assert await p2.read_bytes() == b"fallback"
    assert await p2.exists()


# --- native async backend: concurrency + native open_async ----------------


class _NativeAsyncFS(AsyncFileSystem):
    """A minimal native async filesystem with an artificial per-op delay."""

    protocol = "nativeasync"
    root_marker = ""
    store: dict[str, bytes] = {}
    delay = 0.15

    async def _cat_file(self, path, start=None, end=None, **kwargs):
        await asyncio.sleep(self.delay)
        return self.store[path]

    async def _pipe_file(self, path, value, **kwargs):
        self.store[path] = bytes(value)

    async def _info(self, path, **kwargs):
        if path not in self.store:
            raise FileNotFoundError(path)
        return {"name": path, "size": len(self.store[path]), "type": "file"}

    async def open_async(self, path, mode="rb", **kwargs):
        return _NativeAsyncFile(self, path, mode)


class _NativeAsyncFile:
    def __init__(self, fs, path, mode):
        self.fs = fs
        self.path = path
        self.mode = mode
        self._buf = bytearray()

    async def read(self, size=-1):
        return self.fs.store[self.path]

    async def write(self, data):
        self._buf += bytes(data)
        return len(data)

    async def close(self):
        if "w" in self.mode or "a" in self.mode:
            self.fs.store[self.path] = bytes(self._buf)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()


@pytest.fixture()
def native_async_backend():
    from fsspec.registry import _registry as _fsspec_registry

    from upath._async.core import _async_class_cache
    from upath.registry import _registry as _upath_registry
    from upath.registry import get_upath_class

    _NativeAsyncFS.store = {}
    register_fs("nativeasync", _NativeAsyncFS, clobber=True)

    class NativeAsyncPath(CoreUPath):
        __slots__ = ()

    register_upath("nativeasync", NativeAsyncPath, clobber=True)
    get_upath_class.cache_clear()
    try:
        yield
    finally:
        # avoid polluting the global registries for other tests
        _fsspec_registry.pop("nativeasync", None)
        _upath_registry._m.maps[0].pop("nativeasync", None)
        _async_class_cache.pop(NativeAsyncPath, None)
        get_upath_class.cache_clear()


async def test_native_async_is_used(native_async_backend):
    p = AsyncUPath("nativeasync://f.txt")
    assert p._async_fs.async_impl is True
    assert p._async_fs.asynchronous is True


async def test_native_async_concurrency(native_async_backend):
    paths = [AsyncUPath(f"nativeasync://f{i}.txt") for i in range(5)]
    for p in paths:
        await p.write_bytes(b"x" * 4)

    loop = asyncio.get_event_loop()
    start = loop.time()
    results = await asyncio.gather(*[p.read_bytes() for p in paths])
    elapsed = loop.time() - start

    assert all(r == b"x" * 4 for r in results)
    # 5 concurrent 0.15s reads should overlap: well under the 0.75s serial time
    assert elapsed < 0.5


async def test_native_open_async(native_async_backend):
    p = AsyncUPath("nativeasync://stream.txt")
    async with await p.open("wb") as f:
        await f.write(b"native-stream")
    async with await p.open("rb") as f:
        assert await f.read() == b"native-stream"
