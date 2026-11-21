"""Sweep fsspec cache_type x block_size for file-object workloads.

Cost model (serial reader, which is what h5py/pyarrow-on-a-file-object are):
    T = sum over requests of (RTT + bytes / BW)
"""

import json
import os
import sys
import time

import fsspec.parquet
from simfs import TRACE
from simfs import SimRemoteFS
from workloads import H5AD
from workloads import PARQUET
from workloads import root

DATA = os.path.abspath(sys.argv[1])
R = root(DATA)
K, M = 2**10, 2**20

PROFILES = {
    "LAN/HPC (0.5ms, 400MB/s)": (0.0005, 400e6),
    "cloud VM same-region (20ms, 100MB/s)": (0.020, 100e6),
    "laptop->cloud (40ms, 12MB/s)": (0.040, 12e6),
    "cross-continent (150ms, 25MB/s)": (0.150, 25e6),
}
BLOCKS = [64 * K, 256 * K, 1 * M, 5 * M, 16 * M, 50 * M]
CONFIGS = [("none", None), ("all", None)] + [
    (ct, bs)
    for ct in ["bytes", "readahead", "blockcache", "first", "background"]
    for bs in BLOCKS
]
SHIPPED = {  # what users get today with no options
    "s3fs": ("readahead", 50 * M),
    "gcsfs": ("readahead", 5 * M),
    "adlfs": ("bytes", 50 * M),
    "http": ("bytes", 5 * M),
}


def summarize(events):
    gets = [e - s for k, _, s, e in events if k == "get"]
    meta = sum(k != "get" for k, *_ in events)
    return {"n_get": len(gets), "n_meta": meta, "bytes": sum(gets), "sizes": gets}


def cost(s, rtt, bw):
    return (s["n_get"] + s["n_meta"]) * rtt + s["bytes"] / bw


def run_one(fn, path, okw):
    TRACE.reset()
    fn(path, okw)
    time.sleep(0.02)  # let background prefetch threads finish logging
    s = summarize(TRACE.events)
    del s["sizes"]
    return s


def parquet_parts(name):
    """fsspec.parquet.open_parquet_file: footer-aware prefetch ('parts' cache)."""
    import pyarrow.parquet as pq

    fs = SimRemoteFS()
    path = f"{DATA}/table.parquet"
    cols = {
        "footer only": [],
        "2 of 20 cols": ["f3", "i1"],
        "1 rowgroup, 2 cols": ["f3", "i1"],
        "full read": None,
    }[name]
    rgs = [3] if name == "1 rowgroup, 2 cols" else None

    def fn(_p, _okw):
        with fsspec.parquet.open_parquet_file(
            path, fs=fs, columns=cols, row_groups=rgs, engine="pyarrow"
        ) as f:
            pf = pq.ParquetFile(f)
            if name == "footer only":
                pf.metadata
            elif rgs:
                pf.read_row_group(3, columns=cols)
            else:
                pq.read_table(f, columns=cols)

    return fn


if __name__ == "__main__":
    results = []
    jobs = []
    for fname in ["default.h5ad", "gzip.h5ad"]:
        for wname, fn in H5AD.items():
            jobs.append((f"h5ad[{fname.split('.')[0]}]: {wname}", fn, R / fname))
    for wname, fn in PARQUET.items():
        jobs.append((f"parquet: {wname}", fn, R / "table.parquet"))

    for label, fn, path in jobs:
        for ct, bs in CONFIGS:
            okw = {"cache_type": ct}
            if bs:
                okw["block_size"] = bs
            s = run_one(fn, path, okw)
            results.append({"workload": label, "cache_type": ct, "block_size": bs, **s})
        if label.startswith("parquet"):
            s = run_one(parquet_parts(label.split(": ", 1)[1]), None, {})
            results.append(
                {
                    "workload": label,
                    "cache_type": "fsspec.parquet(parts)",
                    "block_size": None,
                    **s,
                }
            )
        print("done", label, file=sys.stderr)

    with open("results/sweep_small.json", "w") as f:
        json.dump({"results": results, "profiles": PROFILES, "shipped": SHIPPED}, f)
