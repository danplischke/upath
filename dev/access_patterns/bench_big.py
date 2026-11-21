"""Real-time simulated-network benchmark of file-object workloads on GB files.

usage: python bench_big.py DATA_DIR PROFILE OUT.jsonl
"""

import json
import math
import os
import sys
import time
import warnings

import anndata as ad
import h5py
import netsim
import numpy as np
import pyarrow.parquet as pq
import simfs
from simfs import TRACE

from upath import UPath
from upath.tuning import HybridBlockCache
from upath.tuning import NetworkProfile
from upath.tuning import fetch_options

warnings.filterwarnings("ignore")
DATA, PROFILE, OUT = os.path.abspath(sys.argv[1]), sys.argv[2], sys.argv[3]
RTT, BWS, BWL = netsim.PROFILES[PROFILE]
BUDGET = float(os.environ.get("BUDGET", 150))
PART = sys.argv[4] if len(sys.argv) > 4 else "all"
FAST = PROFILE in ("LAN/HPC", "cloud same-region")
K, M = 2**10, 2**20
IDX = np.sort(np.random.default_rng(1).choice(1_000_000, 256, replace=False))

SHIPPED = {
    "s3fs default": {"cache_type": "readahead", "block_size": 50 * M},
    "gcsfs default": {"cache_type": "readahead", "block_size": 5 * M},
    "adlfs default": {"cache_type": "bytes", "block_size": 50 * M},
    "http default": {"cache_type": "bytes", "block_size": 5 * M},
}
FIXED = {
    "none": {"cache_type": "none"},
    "blockcache/1M": {"cache_type": "blockcache", "block_size": 1 * M},
    "blockcache/16M": {"cache_type": "blockcache", "block_size": 16 * M},
}


def auto(kind):
    """Rule fixed in advance from the small-file study."""
    if kind == "parquet":
        return {"cache_type": "none"}
    target = 2 * RTT * BWS  # 2x bandwidth-delay product
    b = 1 << math.ceil(math.log2(max(target, 1)))
    return {"cache_type": "blockcache", "block_size": min(max(b, 1 * M), 16 * M)}


def h5(fname, fn, **h5kw):
    def run(okw):
        with (
            UPath(f"simremote://{DATA}/{fname}").open("rb", **okw) as f,
            h5py.File(f, "r", **h5kw) as h,
        ):
            fn(h)

    return run


def pqw(fn):
    def run(okw):
        with UPath(f"simremote://{DATA}/big.parquet").open("rb", **okw) as f:
            fn(f)

    return run


obs_var = lambda h: (ad.io.read_elem(h["obs"]), ad.io.read_elem(h["var"]))  # noqa: E731
rows_slice = lambda h: ad.io.sparse_dataset(h["X"])[500_000:502_000]  # noqa: E731
rows_rand = lambda h: ad.io.sparse_dataset(h["X"])[IDX]  # noqa: E731

# (kind, label, runner, full_read?)
WORKLOADS = [
    ("hdf5", "h5ad: obs+var", h5("big.h5ad", obs_var), False),
    (
        "hdf5",
        "h5ad: obsm X_pca (200MB)",
        h5("big.h5ad", lambda h: ad.io.read_elem(h["obsm/X_pca"])),
        False,
    ),
    ("hdf5", "h5ad: X rows slice 2k", h5("big.h5ad", rows_slice), False),
    ("hdf5", "h5ad: X rows random 256", h5("big.h5ad", rows_rand), False),
    ("hdf5", "h5ad: full load", h5("big.h5ad", lambda h: ad.io.read_elem(h)), True),
    (
        "parquet",
        "parquet: footer only",
        pqw(lambda f: pq.ParquetFile(f).metadata),
        False,
    ),
    (
        "parquet",
        "parquet: 2 of 20 cols",
        pqw(lambda f: pq.read_table(f, columns=["f3", "i1"])),
        False,
    ),
    (
        "parquet",
        "parquet: 1 rowgroup, 2 cols",
        pqw(lambda f: pq.ParquetFile(f).read_row_group(3, columns=["f3", "i1"])),
        False,
    ),
    ("parquet", "parquet: full read", pqw(lambda f: pq.read_table(f)), True),
]
PAGED = [  # writer-side fix: paged HDF5 + reader page buffer; fsspec cache steps aside
    ("paged", "paged h5ad: obs+var", obs_var),
    ("paged", "paged h5ad: X rows slice 2k", rows_slice),
    ("paged", "paged h5ad: X rows random 256", rows_rand),
]


def measure(run, okw, net):
    simfs.NET = net
    TRACE.reset()
    if net:
        net.reset()
    t0, c0 = time.perf_counter(), time.process_time()
    err = None
    try:
        run(okw)
    except Exception as e:  # budget blowups surface as h5py/pyarrow errors
        err = repr(e)[:120]
    wall, cpu = time.perf_counter() - t0, time.process_time() - c0
    time.sleep(0.05)
    ev = list(TRACE.events)
    gets = [e - s for k, _, s, e in ev if k == "get"]
    meta = sum(k != "get" for k, *_ in ev)
    timeout = bool(net and net.blown)
    return {
        "wall": None if timeout else wall,
        "cpu": cpu,
        "timeout": timeout,
        "error": None if timeout else err,
        "n_get": len(gets),
        "n_meta": meta,
        "bytes": sum(gets),
        "model": (len(gets) + meta) * RTT + sum(gets) / BWS,
    }


def main():
    net = netsim.Net(RTT, BWS, BWL, budget=BUDGET)
    out = open(OUT, "w")

    def emit(rec):
        out.write(json.dumps(rec) + "\n")
        out.flush()
        st = "TIMEOUT" if rec["timeout"] else f"{rec['wall']:7.2f}s"
        print(
            f"[{PROFILE}] {rec['workload']:32s} {rec['config']:16s} {st} "
            f"gets={rec['n_get']:5d} MB={rec['bytes'] / 1e6:8.1f}",
            flush=True,
        )

    for kind, label, run, full in WORKLOADS:
        if full and not FAST:
            continue
        if (
            PART in ("h5ad", "hybrid")
            and kind != "hdf5"
            or PART == "rest"
            and kind == "hdf5"
        ):
            continue
        if PART == "hybrid":
            a = fetch_options("scattered", network=NetworkProfile(RTT, BWS))
            hyb = {
                f"hybrid/{b // M}M": {
                    "cache_type": HybridBlockCache.name,
                    "block_size": b,
                }
                for b in sorted({1 * M, 16 * M, a["block_size"]})
            }
            for cname, okw in hyb.items():
                rec = measure(run, dict(okw), net)
                emit(
                    {
                        "profile": PROFILE,
                        "workload": label,
                        "config": cname,
                        "okw": okw,
                        "is_auto": False,
                        "is_hybrid_auto": okw["block_size"] == a["block_size"],
                        **rec,
                    }
                )
            continue
        base = measure(run, {"cache_type": "none"}, None)
        emit(
            {
                "profile": PROFILE,
                "workload": label,
                "config": "LOCAL (no network)",
                **base,
            }
        )
        configs = {**SHIPPED, **FIXED}
        a = auto(kind)
        if a not in configs.values():
            configs["auto"] = a
        if full:
            configs["all"] = {"cache_type": "all"}
        for cname, okw in configs.items():
            rec = measure(run, dict(okw), net)
            emit(
                {
                    "profile": PROFILE,
                    "workload": label,
                    "config": cname,
                    "okw": okw,
                    "is_auto": okw == a,
                    **rec,
                }
            )
    for _kind, label, fn in PAGED if PART not in ("h5ad", "hybrid") else []:
        for cname, pbs in {
            "none, page_buf 16M": 16 * M,
            "none, page_buf 64M": 64 * M,
        }.items():
            okw = {"cache_type": "none"}
            rec = measure(h5("big_paged.h5ad", fn, page_buf_size=pbs), okw, net)
            emit(
                {
                    "profile": PROFILE,
                    "workload": label,
                    "config": cname,
                    "okw": okw,
                    "is_auto": False,
                    **rec,
                }
            )


if __name__ == "__main__":
    main()
