"""Real-time network simulator: every request really sleeps.

A request waits RTT (time to first byte), then transfers at the per-stream
bandwidth, while also reserving time on a shared link of fixed aggregate
capacity. Concurrent requests (background prefetch, zarr's async gets) therefore
overlap latency but compete for the link -- like a real NIC/uplink.
"""

from __future__ import annotations

import asyncio
import threading
import time

PROFILES = {
    # name: (RTT s, per-stream B/s, link B/s)
    "LAN/HPC": (0.0005, 400e6, 1250e6),
    "cloud same-region": (0.020, 100e6, 1250e6),
    "laptop->cloud": (0.040, 12e6, 12e6),
    "cross-continent": (0.150, 25e6, 100e6),
}


class BudgetExceeded(Exception):
    pass


class Net:
    def __init__(self, rtt, bw_stream, bw_link, budget=None):
        self.rtt, self.bw_stream, self.bw_link, self.budget = (
            rtt,
            bw_stream,
            bw_link,
            budget,
        )
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.link_free = 0.0
        self.t0 = time.monotonic()
        self.blown = False

    def _plan(self, nbytes):
        first = time.monotonic() + self.rtt
        with self.lock:
            start = max(first, self.link_free)
            self.link_free = start + nbytes / self.bw_link
            done = max(self.link_free, first + nbytes / self.bw_stream)
        if self.budget and done - self.t0 > self.budget:
            self.blown = True
            raise BudgetExceeded(f"over {self.budget}s budget")
        return done

    def request(self, nbytes):
        done = self._plan(nbytes)
        time.sleep(max(0.0, done - time.monotonic()))

    async def arequest(self, nbytes):
        done = self._plan(nbytes)
        await asyncio.sleep(max(0.0, done - time.monotonic()))
