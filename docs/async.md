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
offloaded to a thread via [`asyncio.to_thread`][asyncio.to_thread] — using
fsspec's `AsyncFileSystemWrapper` when available, or a small built-in fallback
for older fsspec versions. The API is identical either way; only the degree of
real concurrency differs.

The async filesystem instance is available on `AsyncUPath` via the
`_async_fs` attribute, and the synchronous fsspec filesystem remains available
via `.fs` for fsspec-specific functionality.

## Supported operations

Coroutines: `read_bytes`, `read_text`, `write_bytes`, `write_text`, `open`,
`stat`, `lstat`, `exists`, `is_dir`, `is_file`, `mkdir`, `rmdir`, `unlink`,
`touch`, `rename`, `replace`.

Async iterators: `iterdir`, `glob`, `rglob`, `walk`.

The `.info` property returns an async info object whose `exists`, `is_dir`,
`is_file`, and `is_symlink` checks are coroutines.
