"""Zarr: chunk GETs are whole objects -> concurrency, not block size, is the knob.

Async (s3fs/gcsfs-like) fake FS with real sleeps: each GET waits RTT, then
transfers at min(per-stream BW, share of a link with aggregate capacity).
"""

import asyncio
import math
import os
import sys
import time

import zarr
from fsspec.asyn import AsyncFileSystem
from zarr.storage import FsspecStore

DATA = os.path.abspath(sys.argv[1])
NET = {}


class AsyncSimFS(AsyncFileSystem):
    protocol = ("asim",)
    cachable = False  # codespell:ignore cachable

    def __init__(self, **kw):
        super().__init__(**kw)
        self.n = 0
        self.link_free = 0.0

    async def _delay(self, nbytes):
        rtt, bws, bwl = NET["p"]
        loop = asyncio.get_running_loop()
        first_byte = loop.time() + rtt
        start = max(first_byte, self.link_free)
        self.link_free = start + nbytes / bwl
        done = max(self.link_free, first_byte + nbytes / bws)
        await asyncio.sleep(done - loop.time())

    async def _info(self, path, **kw):
        await self._delay(0)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        return {"name": path, "size": os.path.getsize(path), "type": "file"}

    async def _cat_file(self, path, start=None, end=None, **kw):
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        size = os.path.getsize(path)
        start = 0 if start is None else (max(0, size + start) if start < 0 else start)
        end = size if end is None else (size + end if end < 0 else min(end, size))
        self.n += 1
        await self._delay(end - start)
        with open(path, "rb") as f:
            f.seek(start)
            return f.read(end - start)


PROFILES = {
    "cloud VM (20ms, 100MB/s/stream, 10Gbit link)": (0.020, 100e6, 1250e6),
    "laptop (40ms, 12MB/s, 100Mbit link)": (0.040, 12e6, 12e6),
}
CASES = {
    "chunked 256 KiB chunks, full read": ("chunked.zarr", 256 * 1024),
    "sharded 16 MiB shards, full read": ("sharded.zarr", 16 * 2**20),
}

for pname, prof in PROFILES.items():
    NET["p"] = prof
    rtt, bws, bwl = prof
    print(f"\n### {pname}")
    for cname, (store, obj) in CASES.items():
        # in-flight requests needed to fill the link: Little's law on request time
        c_star = math.ceil(bwl * (rtt + obj / bws) / obj)
        print(f"{cname}: C* = ceil(BW_link*(RTT+obj/BW_stream)/obj) = {c_star}")
        for c in [1, 4, 10, 32, 64]:
            zarr.config.set({"async.concurrency": c})
            fs = AsyncSimFS(asynchronous=True)
            arr = zarr.open_array(
                FsspecStore(fs=fs, path=f"{DATA}/{store}", read_only=True), mode="r"
            )
            t0 = time.perf_counter()
            arr[:]
            dt = time.perf_counter() - t0
            print(
                f"  concurrency={c:3d}: {dt:6.2f}s  ({fs.n} GETs, {64 / dt:6.1f} MiB/s)"
            )
