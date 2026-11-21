"""Real-time simulated-network benchmark for zarr on GB arrays.

usage: python zarr_big.py DATA_DIR OUT.jsonl
"""

import json
import math
import os
import sys
import time
import warnings

import anndata as ad
import netsim
import numpy as np
import simfs
import zarr
from simfs import TRACE
from simfs import AsyncSimFS
from zarr.storage import FsspecStore

warnings.filterwarnings("ignore")
DATA, OUT = os.path.abspath(sys.argv[1]), sys.argv[2]
M = 2**20
BUDGET = 150.0
IDX = np.sort(np.random.default_rng(1).choice(1_000_000, 256, replace=False))

ARRAYS = (
    {  # name: (dir, object size fetched for a region read, object size for full read)
        "256KiB chunks (4096 objects)": ("z_c256k.zarr", 256 * 1024, 256 * 1024),
        "4MiB chunks (256 objects)": ("z_c4m.zarr", 4 * M, 4 * M),
        "64MiB shards / 256KiB inner": ("z_shard64m.zarr", 256 * 1024, 64 * M),
    }
)


def c_star(rtt, bws, bwl, obj):
    return math.ceil(bwl * (rtt + obj / bws) / obj)


def store(path):
    return FsspecStore(
        fs=AsyncSimFS(asynchronous=True), path=f"{DATA}/{path}", read_only=True
    )


def measure(fn, net, conc):
    zarr.config.set({"async.concurrency": conc})
    simfs.NET = net
    TRACE.reset()
    net.reset()
    t0, c0 = time.perf_counter(), time.process_time()
    err = None
    try:
        fn()
    except Exception as e:
        err = repr(e)[:120]
    wall, cpu = time.perf_counter() - t0, time.process_time() - c0
    gets = [e - s for k, _, s, e in TRACE.events if k == "get"]
    return {
        "wall": None if net.blown else wall,
        "cpu": cpu,
        "timeout": net.blown,
        "error": None if net.blown else err,
        "n_get": len(gets),
        "bytes": sum(gets),
    }


def main():
    out = open(OUT, "w")

    def emit(rec):
        out.write(json.dumps(rec) + "\n")
        out.flush()
        st = "TIMEOUT" if rec["timeout"] else f"{rec['wall']:7.2f}s"
        print(
            f"[{rec['profile']}] {rec['workload']:44s} C={rec['concurrency']:4d} {st} "
            f"gets={rec['n_get']:5d} MB={rec['bytes'] / 1e6:8.1f} "
            f"{rec.get('error') or ''}",
            flush=True,
        )

    g = zarr.open_group(f"{DATA}/big_adata.zarr", mode="r")
    print(
        "anndata zarr X/data chunks:",
        g["X/data"].chunks,
        g["X/data"].dtype,
        "| X/indptr chunks:",
        g["X/indptr"].chunks,
        flush=True,
    )

    for pname, (rtt, bws, bwl) in netsim.PROFILES.items():
        net = netsim.Net(rtt, bws, bwl, budget=BUDGET)
        for aname, (path, obj_region, obj_full) in ARRAYS.items():
            for wname, sel, obj in [
                ("2048x2048 region (16MiB)", np.s_[1000:3048, 1000:3048], obj_region),
                ("full read (1GiB)", np.s_[:, :], obj_full),
            ]:
                if wname.startswith("full") and pname == "laptop->cloud":
                    continue  # >= 90s per run at 12MB/s regardless of config
                cs = c_star(rtt, bws, bwl, obj)
                for conc in sorted({10, cs, 64}):
                    rec = measure(
                        lambda path=path, sel=sel: zarr.open_array(
                            store(path), mode="r"
                        )[sel],
                        net,
                        conc,
                    )
                    emit(
                        {
                            "profile": pname,
                            "workload": f"{aname}: {wname}",
                            "concurrency": conc,
                            "c_star": cs,
                            **rec,
                        }
                    )
        for wname, fn in {
            "anndata-zarr: obs+var": lambda: (
                (gg := zarr.open_group(store("big_adata.zarr"), mode="r")),
                ad.io.read_elem(gg["obs"]),
                ad.io.read_elem(gg["var"]),
            ),
            "anndata-zarr: X rows slice 2k": lambda: ad.io.sparse_dataset(
                zarr.open_group(store("big_adata.zarr"), mode="r")["X"]
            )[500_000:502_000],
            "anndata-zarr: X rows random 256": lambda: ad.io.sparse_dataset(
                zarr.open_group(store("big_adata.zarr"), mode="r")["X"]
            )[IDX],
        }.items():
            for conc in [10, 64]:
                rec = measure(fn, net, conc)
                emit(
                    {
                        "profile": pname,
                        "workload": wname,
                        "concurrency": conc,
                        "c_star": None,
                        **rec,
                    }
                )


if __name__ == "__main__":
    main()
