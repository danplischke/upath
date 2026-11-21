"""Characterize raw application access patterns (cache_type='none')."""

import os
import sys

import numpy as np
from simfs import TRACE
from workloads import H5AD
from workloads import PARQUET
from workloads import ZARR
from workloads import root

DATA = os.path.abspath(sys.argv[1])
R = root(DATA)


def describe(events, fsize=None):
    gets = [(p, s, e) for k, p, s, e in events if k == "get"]
    heads = sum(k == "head" for k, *_ in events)
    lists = sum(k == "list" for k, *_ in events)
    sizes = np.array([e - s for _, s, e in gets]) if gets else np.array([0])
    seq = sum(1 for a, b in zip(gets, gets[1:]) if a[0] == b[0] and b[1] == a[2])
    back = sum(1 for a, b in zip(gets, gets[1:]) if a[0] == b[0] and b[1] < a[1])
    tail = sum(1 for p, s, e in gets if fsize and e >= fsize - 64 * 1024)
    uniq = set()
    for p, s, e in gets:
        uniq.add((p, s, e))
    need = sum(e - s for _, s, e in uniq)
    return {
        "gets": len(gets),
        "heads": heads,
        "lists": lists,
        "p50": int(np.median(sizes)),
        "p90": int(np.percentile(sizes, 90)),
        "max": int(sizes.max()),
        "small": float(np.mean(sizes < 8192)),
        "seq": seq / max(1, len(gets) - 1),
        "back": back / max(1, len(gets) - 1),
        "tail": tail,
        "need": need,
        "cover": (need / fsize) if fsize else None,
    }


def fmt(n):
    for u in ["B", "K", "M", "G"]:
        if n < 1024:
            return f"{n:.0f}{u}"
        n /= 1024
    return f"{n:.0f}T"


hdr = (
    f"{'workload':34s} {'GETs':>6s} {'HEAD':>5s} {'LIST':>4s} {'p50':>6s} {'p90':>6s} "
    f"{'max':>6s} {'<8K':>5s} {'seq':>5s} {'back':>5s} {'needed':>7s} {'cover':>6s}"
)


def row(name, d):
    cov = f"{d['cover'] * 100:5.1f}%" if d["cover"] is not None else "   -  "
    print(
        f"{name:34s} {d['gets']:6d} {d['heads']:5d} {d['lists']:4d} "
        f"{fmt(d['p50']):>6s} {fmt(d['p90']):>6s} {fmt(d['max']):>6s} "
        f"{d['small'] * 100:4.0f}% {d['seq'] * 100:4.0f}% {d['back'] * 100:4.0f}% "
        f"{fmt(d['need']):>7s} {cov}"
    )


if __name__ == "__main__":
    print(hdr)
    for fname in ["default.h5ad", "gzip.h5ad", "paged.h5ad"]:
        p = R / fname
        fsize = os.path.getsize(f"{DATA}/{fname}")
        for name, fn in H5AD.items():
            TRACE.reset()
            fn(p, {"cache_type": "none"})
            row(f"{fname}: {name}", describe(TRACE.events, fsize))
    p = R / "table.parquet"
    fsize = os.path.getsize(f"{DATA}/table.parquet")
    for name, fn in PARQUET.items():
        TRACE.reset()
        fn(p, {"cache_type": "none"})
        row(f"parquet: {name}", describe(TRACE.events, fsize))
    for name, fn in ZARR.items():
        TRACE.reset()
        fn(R)
        row(f"zarr: {name}", describe(TRACE.events))
