# Async support

`universal_pathlib` ships an `async`/`await` capable path class,
[`AsyncUPath`][upath.AsyncUPath], alongside the synchronous
[`UPath`][upath.UPath].

`AsyncUPath` is constructed exactly like `UPath` and shares all of its
path-algebra (`/`, `.name`, `.parent`, `.parts`, `.with_suffix`, …). Only the
filesystem I/O methods differ: they are coroutines and async iterators.

```python
import asyncio
from upath import AsyncUPath


async def main():
    p = AsyncUPath("s3://my-bucket/data/file.txt", anon=True)

    # path algebra is synchronous, just like UPath
    print(p.name, p.parent)

    # I/O is awaited
    await p.write_bytes(b"hello")
    data = await p.read_bytes()
    text = await p.read_text()

    if await p.exists() and await p.is_file():
        stat = await p.stat()
        print(stat.st_size)

    # iterdir / glob / walk are async iterators
    async for child in p.parent.iterdir():
        print(child)

    # open() returns an async file object / async context manager
    async with await p.open("rb") as f:
        chunk = await f.read()


asyncio.run(main())
```

## How it works

`AsyncUPath` dispatches to the underlying fsspec filesystem's **native async
implementation** whenever the backend provides one (`fs.async_impl is True`,
e.g. `s3`, `gcs`, `http`, `abfs`, `hf`). In that case operations are awaited
directly on the running event loop, so concurrent calls truly overlap:

```python
# these downloads run concurrently, not one after another
results = await asyncio.gather(*(p.read_bytes() for p in paths))
```

For backends that only implement a **synchronous** interface (e.g. `memory`,
`file`, `sftp`, `ftp`, `webdav`, `smb`), the operations are transparently
offloaded to a thread. The API is identical either way; only the degree of real
concurrency differs.

The async filesystem instance is available on `AsyncUPath` via the
`_async_fs` attribute, and the synchronous fsspec filesystem remains available
via `.fs` for fsspec-specific functionality.

## Runtime and thread-offload

`AsyncUPath` targets **asyncio**. This matches fsspec: its native async
filesystems (s3fs/aiobotocore, gcsfs/http/aiohttp) are asyncio-only, so cloud
backends cannot run under trio regardless of upath.

Thread offloads for sync-only backends are centralized in `upath._async._offload`:

- **Bounded pool.** Blocking calls run on a dedicated `ThreadPoolExecutor` rather
  than the event loop's shared default executor. Size it with the
  `UPATH_ASYNC_MAX_THREADS` environment variable (default `min(32, cpu+4)`).
- **Operation timeout.** Set `UPATH_ASYNC_OP_TIMEOUT` (seconds) to bound each
  offloaded call; on timeout the awaiting coroutine raises `TimeoutError`. Python
  cannot force-kill a worker thread, so the blocking call still runs to
  completion in the background — the timeout returns control to the caller, it
  does not abort the backend operation. This applies only to thread-offloaded
  (sync) backends; wrap native cloud calls in `asyncio.timeout()` yourself.
- **Connection safety.** Connection-based backends (`ftp`, `sftp`, `ssh`, `smb`)
  hold a single, non-thread-safe connection per filesystem instance, so *all* of
  their offloaded work — metadata calls and file-handle reads/writes alike — is
  serialized onto one dedicated worker thread per connection. Stateless backends
  share the bounded pool.
- **Override point.** `upath._async._offload.run_in_thread` is the single offload
  primitive. Reassign it (e.g. to `anyio.to_thread.run_sync`) to route offloads
  through another runtime's thread helper without touching any call site — note
  that only the sync-backend paths become runtime-portable; native cloud backends
  remain asyncio-bound.

## Supported operations

Coroutines: `read_bytes`, `read_text`, `write_bytes`, `write_text`, `open`,
`stat`, `lstat`, `samefile`, `exists`, `is_dir`, `is_file`, `mkdir`, `rmdir`,
`unlink`, `touch`, `rename`, `replace`, `copy`, `copy_into`, `move`,
`move_into`.

Async iterators: `iterdir`, `glob`, `rglob`, `walk`.

The `.info` property returns an async info object whose `exists`, `is_dir`,
`is_file`, and `is_symlink` checks are coroutines.

Arguments that fsspec backends cannot honor — `follow_symlinks=False`,
`glob`/`rglob`'s `case_sensitive` and `recurse_symlinks`, `open`'s `buffering`,
and the `mode` of `mkdir`/`touch` — are accepted for `pathlib` signature
compatibility but emit a `UserWarning` when set to a non-default value instead
of silently doing nothing.

## Resource cleanup

Each `AsyncUPath` lazily resolves and caches its async filesystem. Native async
backends are created with `skip_instance_cache=True`, so the path holds the only
strong reference to the underlying client/session. In long-running programs,
call `await path.aclose()` — or use the path as an async context manager — to
drop that reference once you are done, letting the client/session be collected
instead of living for the lifetime of the path object:

```python
async with AsyncUPath("s3://my-bucket/key", anon=True) as p:
    data = await p.read_bytes()
# the resolved async filesystem is released here
```

`aclose()` is safe to call repeatedly; the next I/O call transparently
re-resolves the filesystem.
