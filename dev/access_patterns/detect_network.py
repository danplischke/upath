"""Validate upath.tuning's network detection over the real-time simulated network.

Opens a sequence of files twice: with detection (estimates start empty, so
the first open uses DEFAULT_NETWORK), and with DEFAULT_NETWORK pinned (fixed
4 MiB blocks). Records the estimate after each open next to the true profile.

usage: python detect_network.py DATA_DIR PROFILE OUT.jsonl
"""

import json
import os
import sys
import time
import warnings

import anndata as ad
import h5py
import netsim
import pyarrow.parquet as pq
import simfs

from upath import UPath
from upath import tuning

warnings.filterwarnings("ignore")
DATA, PROFILE, OUT = os.path.abspath(sys.argv[1]), sys.argv[2], sys.argv[3]
RTT, BWS, BWL = netsim.PROFILES[PROFILE]


def h5(fn):
    def run(f):
        with h5py.File(f, "r") as h:
            fn(h)

    return run


SEQUENCE = [
    (
        "h5ad: obs+var",
        "big.h5ad",
        h5(lambda h: (ad.io.read_elem(h["obs"]), ad.io.read_elem(h["var"]))),
    ),
    (
        "h5ad: X rows slice 2k",
        "big.h5ad",
        h5(lambda h: ad.io.sparse_dataset(h["X"])[500_000:502_000]),
    ),
    (
        "parquet: 1 rowgroup, 2 cols",
        "big.parquet",
        lambda f: pq.ParquetFile(f).read_row_group(3, columns=["f3", "i1"]),
    ),
    (
        "h5ad: X rows slice 2k (other rows)",
        "big.h5ad",
        h5(lambda h: ad.io.sparse_dataset(h["X"])[700_000:702_000]),
    ),
    (
        "h5ad: obs+var (again)",
        "big.h5ad",
        h5(lambda h: (ad.io.read_elem(h["obs"]), ad.io.read_elem(h["var"]))),
    ),
]


def main():
    simfs.NET = net = netsim.Net(RTT, BWS, BWL)
    out = open(OUT, "w")
    for mode in ["detect", "fixed 4 MiB"]:
        tuning._ESTIMATOR.clear()
        tuning.set_default_network(None if mode == "detect" else tuning.DEFAULT_NETWORK)
        for i, (label, fname, fn) in enumerate(SEQUENCE):
            p = UPath(f"simremote://{DATA}/{fname}")
            simfs.TRACE.reset()
            net.reset()
            t0 = time.perf_counter()
            with p.open("rb", access="auto") as f:
                cache, block = f.cache.name, f.blocksize
                fn(f)
            wall = time.perf_counter() - t0
            est = tuning.estimate_network(p)
            gets = [e - s for k, _, s, e in simfs.TRACE.events if k == "get"]
            rec = {
                "profile": PROFILE,
                "mode": mode,
                "step": i,
                "workload": label,
                "cache": cache,
                "block": block if cache == "upath-hybrid" else None,
                "wall": wall,
                "n_get": len(gets),
                "bytes": sum(gets),
                "est_rtt": est and est.rtt,
                "est_bw": est and est.bandwidth,
                "true_rtt": RTT,
                "true_bw": BWS,
            }
            out.write(json.dumps(rec) + "\n")
            out.flush()
            e = (
                f"rtt={est.rtt * 1e3:6.2f}ms bw={est.bandwidth / 1e6:6.1f}MB/s"
                if est
                else "-"
            )
            blk = f"{block // 2**20}MiB" if rec["block"] else cache
            print(
                f"[{PROFILE}] {mode:11s} {i} {label:34s} {blk:10s} "
                f"{wall:7.2f}s  estimate: {e}",
                flush=True,
            )


if __name__ == "__main__":
    main()
